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
"""This module contains a network retry loop implementation.
Its specifically tailored to handling the Telegram API and its errors.

.. versionadded:: 21.11

Hint:
    It was originally part of the `Updater` class, but as part of #4657 it was extracted into its
    own module to be used by other parts of the library.

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

import asyncio
import contextlib
from collections.abc import Callable, Coroutine

from telegram._utils.logging import get_logger
from telegram.error import InvalidToken, RetryAfter, TelegramError, TimedOut

_LOGGER = get_logger(__name__)


async def network_retry_loop(
    *,
    action_cb: Callable[..., Coroutine],
    on_err_cb: Callable[[TelegramError], None] | None = None,
    description: str,
    interval: float,
    stop_event: asyncio.Event | None = None,
    is_running: Callable[[], bool] | None = None,
    max_retries: int,
    repeat_on_success: bool = False,
) -> None:
    """Perform a loop calling `action_cb`, retrying after network errors.

    Stop condition for loop in case of ``max_retries < 0``:
        * `is_running()` evaluates :obj:`False`
        * `stop_event` is set.
        * calling `action_cb` succeeds and `repeat_on_success` is :obj:`False`.

    Additional stop condition for loop in case of `max_retries >= 0``:
        * a call to `action_cb` succeeds
        * or `max_retries` is reached.

    Args:
        action_cb (:term:`coroutine function`): Network oriented callback function to call.
        on_err_cb (:obj:`callable`): Optional. Callback to call when TelegramError is caught.
            Receives the exception object as a parameter.

            Hint:
                Only required if you want to handle the error in a special way. Logging about
                the error is already handled by the loop.

            Important:
                Must not raise exceptions! If it does, the loop will be aborted.
        description (:obj:`str`): Description text to use for logs and exception raised.
        interval (:obj:`float` | :obj:`int`): Interval to sleep between each call to
            `action_cb`.
        stop_event (:class:`asyncio.Event` | :obj:`None`): Event to wait on for stopping the
            loop. Setting the event will make the loop exit even if `action_cb` is currently
            running. Defaults to :obj:`None`.
        is_running (:obj:`callable`): Function to check if the loop should continue running.
            Must return a boolean value. Defaults to `lambda: True`.
        max_retries (:obj:`int`): Maximum number of retries before stopping the loop.

            * < 0: Retry indefinitely.
            * 0: No retries.
            * > 0: Number of retries.

        repeat_on_success (:obj:`bool`): Whether to repeat the action after a successful call.
            Defaults to :obj:`False`.

    Raises:
        ValueError: When passing `repeat_on_success=True` and `max_retries >= 0`. This case is
            currently not supported.

    """
    pass
