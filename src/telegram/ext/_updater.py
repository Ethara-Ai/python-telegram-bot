#!/usr/bin/env python
#
# A library that provides a Python interface to the Telegram Bot API
# Copyright (C) 2015-2026
# Leandro Toledo de Souza <devs@python-telegram-bot.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser Public License for more details.
#
# You should have received a copy of the GNU Lesser Public License
# along with this program.  If not, see [http://www.gnu.org/licenses/].
"""This module contains the class Updater, which tries to make creating Telegram bots intuitive."""

import asyncio
import contextlib
import datetime as dtm
import ssl
from collections.abc import Callable, Coroutine, Sequence
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, TypeVar

from telegram._utils.defaultvalue import DEFAULT_80, DEFAULT_IP, DefaultValue
from telegram._utils.logging import get_logger
from telegram._utils.repr import build_repr_with_selected_attrs
from telegram._utils.types import DVType, TimePeriod
from telegram.error import TelegramError
from telegram.ext._utils.networkloop import network_retry_loop

try:
    from telegram.ext._utils.webhookhandler import WebhookAppClass, WebhookServer

    WEBHOOKS_AVAILABLE = True
except ImportError:
    WEBHOOKS_AVAILABLE = False

if TYPE_CHECKING:
    from socket import socket

    from telegram import Bot


_UpdaterType = TypeVar("_UpdaterType", bound="Updater")  # pylint: disable=invalid-name
_LOGGER = get_logger(__name__)


class Updater(contextlib.AbstractAsyncContextManager["Updater"]):
    """This class fetches updates for the bot either via long polling or by starting a webhook
    server. Received updates are enqueued into the :attr:`update_queue` and may be fetched from
    there to handle them appropriately.

    Instances of this class can be used as asyncio context managers, where

    .. code:: python

        async with updater:
            # code

    is roughly equivalent to

    .. code:: python

        try:
            await updater.initialize()
            # code
        finally:
            await updater.shutdown()

    .. seealso:: :meth:`__aenter__` and :meth:`__aexit__`.

    .. seealso:: :wiki:`Architecture Overview <Architecture>`,
        :wiki:`Builder Pattern <Builder-Pattern>`

    .. versionchanged:: 20.0

        * Removed argument and attribute ``user_sig_handler``
        * The only arguments and attributes are now :attr:`bot` and :attr:`update_queue` as now
          the sole purpose of this class is to fetch updates. The entry point to a PTB application
          is now :class:`telegram.ext.Application`.

    Args:
        bot (:class:`telegram.Bot`): The bot used with this Updater.
        update_queue (:class:`asyncio.Queue`): Queue for the updates.

    Attributes:
        bot (:class:`telegram.Bot`): The bot used with this Updater.
        update_queue (:class:`asyncio.Queue`): Queue for the updates.

    """

    __slots__ = (
        "__lock",
        "__polling_cleanup_cb",
        "__polling_task",
        "__polling_task_stop_event",
        "_httpd",
        "_initialized",
        "_last_update_id",
        "_running",
        "bot",
        "update_queue",
    )

    def __init__(
        self,
        bot: "Bot",
        update_queue: "asyncio.Queue[object]",
    ):
        self.bot: Bot = bot
        self.update_queue: asyncio.Queue[object] = update_queue

        self._last_update_id = 0
        self._running = False
        self._initialized = False
        self._httpd: WebhookServer | None = None
        self.__lock = asyncio.Lock()
        self.__polling_task: asyncio.Task | None = None
        self.__polling_task_stop_event: asyncio.Event = asyncio.Event()
        self.__polling_cleanup_cb: Callable[[], Coroutine[Any, Any, None]] | None = None

    async def __aenter__(self: _UpdaterType) -> _UpdaterType:
        """
        |async_context_manager| :meth:`initializes <initialize>` the Updater.

        Returns:
            The initialized Updater instance.

        Raises:
            :exc:`Exception`: If an exception is raised during initialization, :meth:`shutdown`
                is called in this case.
        """
        try:
            await self.initialize()
        except Exception:
            await self.shutdown()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """|async_context_manager| :meth:`shuts down <shutdown>` the Updater."""
        # Make sure not to return `True` so that exceptions are not suppressed
        # https://docs.python.org/3/reference/datamodel.html?#object.__aexit__
        await self.shutdown()

    def __repr__(self) -> str:
        """Give a string representation of the updater in the form ``Updater[bot=...]``.

        As this class doesn't implement :meth:`object.__str__`, the default implementation
        will be used, which is equivalent to :meth:`__repr__`.

        Returns:
            :obj:`str`
        """
        return build_repr_with_selected_attrs(self, bot=self.bot)


    async def initialize(self) -> None:
        """Initializes the Updater & the associated :attr:`bot` by calling
        :meth:`telegram.Bot.initialize`.

        .. seealso::
            :meth:`shutdown`
        """
        pass

    async def shutdown(self) -> None:
        """
        Shutdown the Updater & the associated :attr:`bot` by calling :meth:`telegram.Bot.shutdown`.

        .. seealso::
            :meth:`initialize`

        Raises:
            :exc:`RuntimeError`: If the updater is still running.
        """
        if self.running:
            raise RuntimeError("This Updater is still running!")

        if not self._initialized:
            _LOGGER.debug("This Updater is already shut down. Returning.")
            return

        await self.bot.shutdown()
        self._initialized = False
        _LOGGER.debug("Shut down of Updater complete")

    async def start_polling(
        self,
        poll_interval: float = 0.0,
        timeout: TimePeriod = dtm.timedelta(seconds=10),
        bootstrap_retries: int = 0,
        allowed_updates: Sequence[str] | None = None,
        drop_pending_updates: bool | None = None,
        error_callback: Callable[[TelegramError], None] | None = None,
    ) -> "asyncio.Queue[object]":
        """Starts polling updates from Telegram.

        .. versionchanged:: 20.0
            Removed the ``clean`` argument in favor of :paramref:`drop_pending_updates`.

        .. versionchanged:: 22.0
            Removed the deprecated arguments ``read_timeout``, ``write_timeout``,
            ``connect_timeout``, and ``pool_timeout`` in favor of setting the timeouts via
            the corresponding methods of :class:`telegram.ext.ApplicationBuilder`. or
            by specifying the timeout via :paramref:`telegram.Bot.get_updates_request`.

        Args:
            poll_interval (:obj:`float`, optional): Time to wait between polling updates from
                Telegram in seconds. Default is ``0.0``.
            timeout (:obj:`int` | :class:`datetime.timedelta`, optional): Passed to
                :paramref:`telegram.Bot.get_updates.timeout`. Defaults to
                ``timedelta(seconds=10)``.

                .. versionchanged:: v22.2
                    |time-period-input|
            bootstrap_retries (:obj:`int`, optional): Whether the bootstrapping phase of
                will retry on failures on the Telegram server.

                * < 0 - retry indefinitely
                *   0 - no retries (default)
                * > 0 - retry up to X times

                .. versionchanged:: 21.11
                    The default value will be changed to from ``-1`` to ``0``. Indefinite retries
                    during bootstrapping are not recommended.
            allowed_updates (Sequence[:obj:`str`], optional): Passed to
                :meth:`telegram.Bot.get_updates`.

                .. versionchanged:: 21.9
                    Accepts any :class:`collections.abc.Sequence` as input instead of just a list
            drop_pending_updates (:obj:`bool`, optional): Whether to clean any pending updates on
                Telegram servers before actually starting to poll. Default is :obj:`False`.

                .. versionadded :: 13.4
            error_callback (Callable[[:exc:`telegram.error.TelegramError`], :obj:`None`], \
                optional): Callback to handle :exc:`telegram.error.TelegramError` s that occur
                while calling :meth:`telegram.Bot.get_updates` during polling. Defaults to
                :obj:`None`, in which case errors will be logged. Callback signature::

                    def callback(error: telegram.error.TelegramError)

                Note:
                    The :paramref:`error_callback` must *not* be a :term:`coroutine function`! If
                    asynchronous behavior of the callback is wanted, please schedule a task from
                    within the callback.

        Returns:
            :class:`asyncio.Queue`: The update queue that can be filled from the main thread.

        Raises:
            :exc:`RuntimeError`: If the updater is already running or was not initialized.

        """
        pass


    async def start_webhook(
        self,
        listen: DVType[str] = DEFAULT_IP,
        port: DVType[int] = DEFAULT_80,
        url_path: str = "",
        cert: str | Path | None = None,
        key: str | Path | None = None,
        bootstrap_retries: int = 0,
        webhook_url: str | None = None,
        allowed_updates: Sequence[str] | None = None,
        drop_pending_updates: bool | None = None,
        ip_address: str | None = None,
        max_connections: int = 40,
        secret_token: str | None = None,
        unix: "str | Path | socket | None" = None,
    ) -> "asyncio.Queue[object]":
        """
        Starts a small http server to listen for updates via webhook. If :paramref:`cert`
        and :paramref:`key` are not provided, the webhook will be started directly on
        ``http://listen:port/url_path``, so SSL can be handled by another
        application. Else, the webhook will be started on
        ``https://listen:port/url_path``. Also calls :meth:`telegram.Bot.set_webhook` as required.

        Important:
            If you want to use this method, you must install PTB with the optional requirement
            ``webhooks``, i.e.

            .. code-block:: bash

               pip install "python-telegram-bot[webhooks]"

        .. seealso:: :wiki:`Webhooks`

        .. versionchanged:: 13.4
            :meth:`start_webhook` now *always* calls :meth:`telegram.Bot.set_webhook`, so pass
            ``webhook_url`` instead of calling ``updater.bot.set_webhook(webhook_url)`` manually.
        .. versionchanged:: 20.0

            * Removed the ``clean`` argument in favor of :paramref:`drop_pending_updates` and
              removed the deprecated argument ``force_event_loop``.

        Args:
            listen (:obj:`str`, optional): IP-Address to listen on. Defaults to
                `127.0.0.1 <https://en.wikipedia.org/wiki/Localhost>`_.
            port (:obj:`int`, optional): Port the bot should be listening on. Must be one of
                :attr:`telegram.constants.SUPPORTED_WEBHOOK_PORTS` unless the bot is running
                behind a proxy. Defaults to ``80``.
            url_path (:obj:`str`, optional): Path inside url (http(s)://listen:port/<url_path>).
                Defaults to ``''``.
            cert (:class:`pathlib.Path` | :obj:`str`, optional): Path to the SSL certificate file.
            key (:class:`pathlib.Path` | :obj:`str`, optional): Path to the SSL key file.
            drop_pending_updates (:obj:`bool`, optional): Whether to clean any pending updates on
                Telegram servers before actually starting to poll. Default is :obj:`False`.

                .. versionadded :: 13.4
            bootstrap_retries (:obj:`int`, optional): Whether the bootstrapping phase of
                will retry on failures on the Telegram server.

                * < 0 - retry indefinitely
                *   0 - no retries (default)
                * > 0 - retry up to X times
            webhook_url (:obj:`str`, optional): Explicitly specify the webhook url. Useful behind
                NAT, reverse proxy, etc. Default is derived from :paramref:`listen`,
                :paramref:`port`, :paramref:`url_path`, :paramref:`cert`, and :paramref:`key`.
            ip_address (:obj:`str`, optional): Passed to :meth:`telegram.Bot.set_webhook`.
                Defaults to :obj:`None`.

                .. versionadded :: 13.4
            allowed_updates (Sequence[:obj:`str`], optional): Passed to
                :meth:`telegram.Bot.set_webhook`. Defaults to :obj:`None`.

                .. versionchanged:: 21.9
                    Accepts any :class:`collections.abc.Sequence` as input instead of just a list
            max_connections (:obj:`int`, optional): Passed to
                :meth:`telegram.Bot.set_webhook`. Defaults to ``40``.

                .. versionadded:: 13.6
            secret_token (:obj:`str`, optional): Passed to :meth:`telegram.Bot.set_webhook`.
                Defaults to :obj:`None`.

                When added, the web server started by this call will expect the token to be set in
                the ``X-Telegram-Bot-Api-Secret-Token`` header of an incoming request and will
                raise a :class:`http.HTTPStatus.FORBIDDEN <http.HTTPStatus>` error if either the
                header isn't set or it is set to a wrong token.

                .. versionadded:: 20.0
            unix (:class:`pathlib.Path` | :obj:`str` | :class:`socket.socket`, optional): Can be
                either:

                * the path to the unix socket file as :class:`pathlib.Path` or :obj:`str`. This
                  will be passed to `tornado.netutil.bind_unix_socket <https://www.tornadoweb.org/
                  en/stable/netutil.html#tornado.netutil.bind_unix_socket>`_ to create the socket.
                  If the Path does not exist, the file will be created.

                * or the socket itself. This option allows you to e.g. restrict the permissions of
                  the socket for improved security. Note that you need to pass the correct family,
                  type and socket options yourself.

                Caution:
                    This parameter is a replacement for the default TCP bind. Therefore, it is
                    mutually exclusive with :paramref:`listen` and :paramref:`port`. When using
                    this param, you must also run a reverse proxy to the unix socket and set the
                    appropriate :paramref:`webhook_url`.

                .. versionadded:: 20.8
                .. versionchanged:: 21.1
                    Added support to pass a socket instance itself.
        Returns:
            :class:`queue.Queue`: The update queue that can be filled from the main thread.

        Raises:
            :exc:`RuntimeError`: If the updater is already running or was not initialized.
        """
        pass



    async def _bootstrap(
        self,
        max_retries: int,
        webhook_url: str | None,
        allowed_updates: Sequence[str] | None,
        drop_pending_updates: bool | None = None,
        cert: bytes | None = None,
        bootstrap_interval: float = 1,
        ip_address: str | None = None,
        max_connections: int = 40,
        secret_token: str | None = None,
    ) -> None:
        """Prepares the setup for fetching updates: delete or set the webhook and drop pending
        updates if appropriate. If there are unsuccessful attempts, this will retry as specified by
        :paramref:`max_retries`.
        """
        pass

    async def stop(self) -> None:
        """Stops the polling/webhook.

        .. seealso::
            :meth:`start_polling`, :meth:`start_webhook`

        Raises:
            :exc:`RuntimeError`: If the updater is not running.
        """
        async with self.__lock:
            if not self.running:
                raise RuntimeError("This Updater is not running!")

            _LOGGER.debug("Stopping Updater")

            self._running = False

            await self._stop_httpd()
            await self._stop_polling()

            _LOGGER.debug("Updater.stop() is complete")

    async def _stop_httpd(self) -> None:
        """Stops the Webhook server by calling ``WebhookServer.shutdown()``"""
        if self._httpd:
            _LOGGER.debug("Waiting for current webhook connection to be closed.")
            await self._httpd.shutdown()
            self._httpd = None

    async def _stop_polling(self) -> None:
        """Stops the polling task by awaiting it."""
        if self.__polling_task:
            _LOGGER.debug("Waiting background polling task to finish up.")
            self.__polling_task_stop_event.set()

            with contextlib.suppress(asyncio.CancelledError):
                await self.__polling_task
                # It only fails in rare edge-cases, e.g. when `stop()` is called directly
                # after start_polling(), but lets better be safe than sorry ...

            self.__polling_task = None
            self.__polling_task_stop_event.clear()

            if self.__polling_cleanup_cb:
                await self.__polling_cleanup_cb()
                self.__polling_cleanup_cb = None
            else:
                _LOGGER.warning(
                    "No polling cleanup callback defined. The last fetched updates may be "
                    "fetched again on the next polling start."
                )
