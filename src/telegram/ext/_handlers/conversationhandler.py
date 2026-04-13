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
"""This module contains the ConversationHandler."""

import asyncio
import datetime as dtm
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Generic, NoReturn, cast

from telegram import Update
from telegram._utils.defaultvalue import DEFAULT_TRUE, DefaultValue
from telegram._utils.logging import get_logger
from telegram._utils.repr import build_repr_with_selected_attrs
from telegram._utils.types import DVType
from telegram._utils.warnings import warn
from telegram.ext._application import ApplicationHandlerStop
from telegram.ext._extbot import ExtBot
from telegram.ext._handlers.basehandler import BaseHandler
from telegram.ext._handlers.callbackqueryhandler import CallbackQueryHandler
from telegram.ext._handlers.choseninlineresulthandler import ChosenInlineResultHandler
from telegram.ext._handlers.inlinequeryhandler import InlineQueryHandler
from telegram.ext._handlers.stringcommandhandler import StringCommandHandler
from telegram.ext._handlers.stringregexhandler import StringRegexHandler
from telegram.ext._handlers.typehandler import TypeHandler
from telegram.ext._utils.trackingdict import TrackingDict
from telegram.ext._utils.types import CCT, ConversationDict, ConversationKey

if TYPE_CHECKING:
    from telegram.ext import Application, Job, JobQueue
_CheckUpdateType = tuple[object, ConversationKey, BaseHandler[Update, CCT, object], object]

_LOGGER = get_logger(__name__, class_name="ConversationHandler")


@dataclass
class _ConversationTimeoutContext(Generic[CCT]):
    """Used as a datastore for conversation timeouts. Passed in the
    :paramref:`JobQueue.run_once.data` parameter. See :meth:`_trigger_timeout`.
    """

    __slots__ = ("application", "callback_context", "conversation_key", "update")

    conversation_key: ConversationKey
    update: Update
    application: "Application[Any, CCT, Any, Any, Any, JobQueue]"
    callback_context: CCT


@dataclass
class PendingState:
    """Thin wrapper around :class:`asyncio.Task` to handle block=False handlers. Note that this is
    a public class of this module, since :meth:`Application.update_persistence` needs to access it.
    It's still hidden from users, since this module itself is private.
    """

    __slots__ = ("old_state", "task")

    task: asyncio.Task
    old_state: object

    def done(self) -> bool:
        return self.task.done()

    def resolve(self) -> object:
        """Returns the new state of the :class:`ConversationHandler` if available. If there was an
        exception during the task execution, then return the old state. If both the new and old
        state are :obj:`None`, return `CH.END`. If only the new state is :obj:`None`, return the
        old state.

        Raises:
            :exc:`RuntimeError`: If the current task has not yet finished.
        """
        if not self.task.done():
            raise RuntimeError("New state is not yet available")

        exc = self.task.exception()
        if exc:
            _LOGGER.exception(
                "Task function raised exception. Falling back to old state %s",
                self.old_state,
            )
            return self.old_state

        res = self.task.result()
        if res is None and self.old_state is None:
            res = ConversationHandler.END
        elif res is None:
            # returning None from a callback means that we want to stay in the old state
            return self.old_state

        return res


class ConversationHandler(BaseHandler[Update, CCT, object]):
    """
    A handler to hold a conversation with a single or multiple users through Telegram updates by
    managing three collections of other handlers.

    Warning:
        :class:`ConversationHandler` heavily relies on incoming updates being processed one by one.
        When using this handler, :attr:`telegram.ext.ApplicationBuilder.concurrent_updates` should
        be set to :obj:`False`.

    Note:
        :class:`ConversationHandler` will only accept updates that are (subclass-)instances of
        :class:`telegram.Update`. This is, because depending on the :attr:`per_user` and
        :attr:`per_chat`, :class:`ConversationHandler` relies on
        :attr:`telegram.Update.effective_user` and/or :attr:`telegram.Update.effective_chat` in
        order to determine which conversation an update should belong to. For
        :attr:`per_message=True <per_message>`, :class:`ConversationHandler` uses
        :attr:`update.callback_query.message.message_id <telegram.Message.message_id>` when
        :attr:`per_chat=True <per_chat>` and
        :attr:`update.callback_query.inline_message_id <.CallbackQuery.inline_message_id>` when
        :attr:`per_chat=False <per_chat>`. For a more detailed explanation, please see our `FAQ`_.

        Finally, :class:`ConversationHandler`, does *not* handle (edited) channel posts.

    .. _`FAQ`: https://github.com/python-telegram-bot/python-telegram-bot/wiki\
        /Frequently-Asked-Questions#what-do-the-per_-settings-in-conversation handler-do

    The first collection, a :obj:`list` named :attr:`entry_points`, is used to initiate the
    conversation, for example with a :class:`telegram.ext.CommandHandler` or
    :class:`telegram.ext.MessageHandler`.

    The second collection, a :obj:`dict` named :attr:`states`, contains the different conversation
    steps and one or more associated handlers that should be used if the user sends a message when
    the conversation with them is currently in that state. Here you can also define a state for
    :attr:`TIMEOUT` to define the behavior when :attr:`conversation_timeout` is exceeded, and a
    state for :attr:`WAITING` to define behavior when a new update is received while the previous
    :attr:`block=False <block>` handler is not finished.

    The third collection, a :obj:`list` named :attr:`fallbacks`, is used if the user is currently
    in a conversation but the state has either no associated handler or the handler that is
    associated to the state is inappropriate for the update, for example if the update contains a
    command, but a regular text message is expected. You could use this for a ``/cancel`` command
    or to let the user know their message was not recognized.

    To change the state of conversation, the callback function of a handler must return the new
    state after responding to the user. If it does not return anything (returning :obj:`None` by
    default), the state will not change. If an entry point callback function returns :obj:`None`,
    the conversation ends immediately after the execution of this callback function.
    To end the conversation, the callback function must return :attr:`END` or ``-1``. To
    handle the conversation timeout, use handler :attr:`TIMEOUT` or ``-2``.
    Finally, :class:`telegram.ext.ApplicationHandlerStop` can be used in conversations as described
    in its documentation.

    Note:
        In each of the described collections of handlers, a handler may in turn be a
        :class:`ConversationHandler`. In that case, the child :class:`ConversationHandler` should
        have the attribute :attr:`map_to_parent` which allows returning to the parent conversation
        at specified states within the child conversation.

        Note that the keys in :attr:`map_to_parent` must not appear as keys in :attr:`states`
        attribute or else the latter will be ignored. You may map :attr:`END` to one of the parents
        states to continue the parent conversation after the child conversation has ended or even
        map a state to :attr:`END` to end the *parent* conversation from within the child
        conversation. For an example on nested :class:`ConversationHandler` s, see
        :any:`examples.nestedconversationbot`.

    Examples:
        * :any:`Conversation Bot <examples.conversationbot>`
        * :any:`Conversation Bot 2 <examples.conversationbot2>`
        * :any:`Nested Conversation Bot <examples.nestedconversationbot>`
        * :any:`Persistent Conversation Bot <examples.persistentconversationbot>`

    Args:
        entry_points (list[:class:`telegram.ext.BaseHandler`]): A list of :obj:`BaseHandler`
            objects that
            can trigger the start of the conversation. The first handler whose :meth:`check_update`
            method returns :obj:`True` will be used. If all return :obj:`False`, the update is not
            handled.
        states (dict[:obj:`object`, list[:class:`telegram.ext.BaseHandler`]]): A :obj:`dict` that
            defines the different states of conversation a user can be in and one or more
            associated :obj:`BaseHandler` objects that should be used in that state. The first
            handler whose :meth:`check_update` method returns :obj:`True` will be used.
        fallbacks (list[:class:`telegram.ext.BaseHandler`]): A list of handlers that might be used
            if the user is in a conversation, but every handler for their current state returned
            :obj:`False` on :meth:`check_update`. The first handler which :meth:`check_update`
            method returns :obj:`True` will be used. If all return :obj:`False`, the update is not
            handled.
        allow_reentry (:obj:`bool`, optional): If set to :obj:`True`, a user that is currently in a
            conversation can restart the conversation by triggering one of the entry points.
            Default is :obj:`False`.
        per_chat (:obj:`bool`, optional): If the conversation key should contain the Chat's ID.
            Default is :obj:`True`.
        per_user (:obj:`bool`, optional): If the conversation key should contain the User's ID.
            Default is :obj:`True`.
        per_message (:obj:`bool`, optional): If the conversation key should contain the Message's
            ID. Default is :obj:`False`.
        conversation_timeout (:obj:`float` | :obj:`datetime.timedelta`, optional): When this
            handler is inactive more than this timeout (in seconds), it will be automatically
            ended. If this value is ``0`` or :obj:`None` (default), there will be no timeout. The
            last received update and the corresponding :class:`context <.CallbackContext>` will be
            handled by *ALL* the handler's whose :meth:`check_update` method returns :obj:`True`
            that are in the state :attr:`ConversationHandler.TIMEOUT`.

            Caution:
                * This feature relies on the :attr:`telegram.ext.Application.job_queue` being set
                  and hence requires that the dependencies that :class:`telegram.ext.JobQueue`
                  relies on are installed.
                * Using :paramref:`conversation_timeout` with nested conversations is currently
                  not supported. You can still try to use it, but it will likely behave
                  differently from what you expect.

        name (:obj:`str`, optional): The name for this conversation handler. Required for
            persistence.
        persistent (:obj:`bool`, optional): If the conversation's dict for this handler should be
            saved. :paramref:`name` is required and persistence has to be set in
            :attr:`Application <.Application.persistence>`.

            .. versionchanged:: 20.0
                Was previously named as ``persistence``.
        map_to_parent (dict[:obj:`object`, :obj:`object`], optional): A :obj:`dict` that can be
            used to instruct a child conversation handler to transition into a mapped state on
            its parent conversation handler in place of a specified nested state.
        block (:obj:`bool`, optional): Pass :obj:`False` or :obj:`True` to set a default value for
            the :attr:`BaseHandler.block` setting of all handlers (in :attr:`entry_points`,
            :attr:`states` and :attr:`fallbacks`). The resolution order for checking if a handler
            should be run non-blocking is:

            1. :attr:`telegram.ext.BaseHandler.block` (if set)
            2. the value passed to this parameter (if any)
            3. :attr:`telegram.ext.Defaults.block` (if defaults are used)

            .. seealso:: :wiki:`Concurrency`

            .. versionchanged:: 20.0
                No longer overrides the handlers settings. Resolution order was changed.

    Raises:
        :exc:`ValueError`: If :paramref:`persistent` is used but :paramref:`name` was not set, or
            when :attr:`per_message`, :attr:`per_chat`, :attr:`per_user` are all :obj:`False`.

    Attributes:
        block (:obj:`bool`): Determines whether the callback will run in a blocking way. Always
            :obj:`True` since conversation handlers handle any non-blocking callbacks internally.

    """

    __slots__ = (
        "_allow_reentry",
        "_block",
        "_child_conversations",
        "_conversation_timeout",
        "_conversations",
        "_entry_points",
        "_fallbacks",
        "_map_to_parent",
        "_name",
        "_per_chat",
        "_per_message",
        "_per_user",
        "_persistent",
        "_states",
        "_timeout_jobs_lock",
        "timeout_jobs",
    )

    END: Final[int] = -1
    """:obj:`int`: Used as a constant to return when a conversation is ended."""
    TIMEOUT: Final[int] = -2
    """:obj:`int`: Used as a constant to handle state when a conversation is timed out
    (exceeded :attr:`conversation_timeout`).
    """
    WAITING: Final[int] = -3
    """:obj:`int`: Used as a constant to handle state when a conversation is still waiting on the
    previous :attr:`block=False <block>` handler to finish."""

    # pylint: disable=super-init-not-called
    def __init__(
        self: "ConversationHandler[CCT]",
        entry_points: list[BaseHandler[Update, CCT, object]],
        states: dict[object, list[BaseHandler[Update, CCT, object]]],
        fallbacks: list[BaseHandler[Update, CCT, object]],
        allow_reentry: bool = False,
        per_chat: bool = True,
        per_user: bool = True,
        per_message: bool = False,
        conversation_timeout: float | dtm.timedelta | None = None,
        name: str | None = None,
        persistent: bool = False,
        map_to_parent: dict[object, object] | None = None,
        block: DVType[bool] = DEFAULT_TRUE,
    ):
        # these imports need to be here because of circular import error otherwise
        from telegram.ext import (  # pylint: disable=import-outside-toplevel  # noqa: PLC0415
            PollAnswerHandler,
            PollHandler,
            PreCheckoutQueryHandler,
            ShippingQueryHandler,
        )

        # self.block is what the Application checks and we want it to always run CH in a blocking
        # way so that CH can take care of any non-blocking logic internally
        self.block: DVType[bool] = True
        # Store the actual setting in a protected variable instead
        self._block: DVType[bool] = block

        self._entry_points: list[BaseHandler[Update, CCT, object]] = entry_points
        self._states: dict[object, list[BaseHandler[Update, CCT, object]]] = states
        self._fallbacks: list[BaseHandler[Update, CCT, object]] = fallbacks

        self._allow_reentry: bool = allow_reentry
        self._per_user: bool = per_user
        self._per_chat: bool = per_chat
        self._per_message: bool = per_message
        self._conversation_timeout: float | dtm.timedelta | None = conversation_timeout
        self._name: str | None = name
        self._map_to_parent: dict[object, object] | None = map_to_parent

        # if conversation_timeout is used, this dict is used to schedule a job which runs when the
        # conv has timed out.
        self.timeout_jobs: dict[ConversationKey, Job[Any]] = {}
        self._timeout_jobs_lock = asyncio.Lock()
        self._conversations: ConversationDict = {}
        self._child_conversations: set[ConversationHandler] = set()

        if persistent and not self.name:
            raise ValueError("Conversations can't be persistent when handler is unnamed.")
        self._persistent: bool = persistent

        if not any((self.per_user, self.per_chat, self.per_message)):
            raise ValueError("'per_user', 'per_chat' and 'per_message' can't all be 'False'")

        if self.per_message and not self.per_chat:
            warn(
                "If 'per_message=True' is used, 'per_chat=True' should also be used, "
                "since message IDs are not globally unique.",
                stacklevel=2,
            )

        all_handlers: list[BaseHandler[Update, CCT, object]] = []
        all_handlers.extend(entry_points)
        all_handlers.extend(fallbacks)

        for state_handlers in states.values():
            all_handlers.extend(state_handlers)

        self._child_conversations.update(
            handler for handler in all_handlers if isinstance(handler, ConversationHandler)
        )

        # this link will be added to all warnings tied to per_* setting
        per_faq_link = (
            " Read this FAQ entry to learn more about the per_* settings: "
            "https://github.com/python-telegram-bot/python-telegram-bot/wiki"
            "/Frequently-Asked-Questions#what-do-the-per_-settings-in-conversationhandler-do."
        )

        # this loop is going to warn the user about handlers which can work unexpectedly
        # in conversations
        for handler in all_handlers:
            if isinstance(handler, StringCommandHandler | StringRegexHandler):
                warn(
                    "The `ConversationHandler` only handles updates of type `telegram.Update`. "
                    f"{handler.__class__.__name__} handles updates of type `str`.",
                    stacklevel=2,
                )
            elif isinstance(handler, TypeHandler) and not issubclass(handler.type, Update):
                warn(
                    "The `ConversationHandler` only handles updates of type `telegram.Update`."
                    f" The TypeHandler is set to handle {handler.type.__name__}.",
                    stacklevel=2,
                )
            elif isinstance(handler, PollHandler):
                warn(
                    "PollHandler will never trigger in a conversation since it has no information "
                    "about the chat or the user who voted in it. Do you mean the "
                    "`PollAnswerHandler`?",
                    stacklevel=2,
                )

            elif self.per_chat and (
                isinstance(
                    handler,
                    ShippingQueryHandler
                    | InlineQueryHandler
                    | ChosenInlineResultHandler
                    | PreCheckoutQueryHandler
                    | PollAnswerHandler,
                )
            ):
                warn(
                    f"Updates handled by {handler.__class__.__name__} only have information about "
                    "the user, so this handler won't ever be triggered if `per_chat=True`."
                    f"{per_faq_link}",
                    stacklevel=2,
                )

            elif self.per_message and not isinstance(handler, CallbackQueryHandler):
                warn(
                    "If 'per_message=True', all entry points, state handlers, and fallbacks"
                    " must be 'CallbackQueryHandler', since no other handlers "
                    f"have a message context.{per_faq_link}",
                    stacklevel=2,
                )
            elif not self.per_message and isinstance(handler, CallbackQueryHandler):
                warn(
                    "If 'per_message=False', 'CallbackQueryHandler' will not be "
                    f"tracked for every message.{per_faq_link}",
                    stacklevel=2,
                )

            if self.conversation_timeout and isinstance(handler, self.__class__):
                warn(
                    "Using `conversation_timeout` with nested conversations is currently not "
                    "supported. You can still try to use it, but it will likely behave "
                    "differently from what you expect.",
                    stacklevel=2,
                )

    def __repr__(self) -> str:
        """Give a string representation of the ConversationHandler in the form
        ``ConversationHandler[name=..., states={...}]``.

        If there are more than 3 states, only the first 3 states are listed.

        As this class doesn't implement :meth:`object.__str__`, the default implementation
        will be used, which is equivalent to :meth:`__repr__`.

        Returns:
            :obj:`str`
        """
        truncation_threshold = 3
        states = dict(list(self.states.items())[:truncation_threshold])
        states_string = str(states)
        if len(self.states) > truncation_threshold:
            states_string = states_string[:-1] + ", ...}"

        return build_repr_with_selected_attrs(
            self,
            name=self.name,
            states=states_string,
        )

    @property
    def entry_points(self) -> list[BaseHandler[Update, CCT, object]]:
        """list[:class:`telegram.ext.BaseHandler`]: A list of :obj:`BaseHandler` objects that can
        trigger the start of the conversation.
        """
        pass

    @entry_points.setter
    def entry_points(self, _: object) -> NoReturn:
        raise AttributeError(
            "You can not assign a new value to entry_points after initialization."
        )

    @property
    def states(self) -> dict[object, list[BaseHandler[Update, CCT, object]]]:
        """dict[:obj:`object`, list[:class:`telegram.ext.BaseHandler`]]: A :obj:`dict` that
        defines the different states of conversation a user can be in and one or more
        associated :obj:`BaseHandler` objects that should be used in that state.
        """
        pass

    @states.setter
    def states(self, _: object) -> NoReturn:
        raise AttributeError("You can not assign a new value to states after initialization.")

    @property
    def fallbacks(self) -> list[BaseHandler[Update, CCT, object]]:
        """list[:class:`telegram.ext.BaseHandler`]: A list of handlers that might be used if
        the user is in a conversation, but every handler for their current state returned
        :obj:`False` on :meth:`check_update`.
        """
        pass

    @fallbacks.setter
    def fallbacks(self, _: object) -> NoReturn:
        raise AttributeError("You can not assign a new value to fallbacks after initialization.")

    @property
    def allow_reentry(self) -> bool:
        """:obj:`bool`: Determines if a user can restart a conversation with an entry point."""
        pass

    @allow_reentry.setter
    def allow_reentry(self, _: object) -> NoReturn:
        raise AttributeError(
            "You can not assign a new value to allow_reentry after initialization."
        )

    @property
    def per_user(self) -> bool:
        """:obj:`bool`: If the conversation key should contain the User's ID."""
        pass

    @per_user.setter
    def per_user(self, _: object) -> NoReturn:
        raise AttributeError("You can not assign a new value to per_user after initialization.")

    @property
    def per_chat(self) -> bool:
        """:obj:`bool`: If the conversation key should contain the Chat's ID."""
        pass

    @per_chat.setter
    def per_chat(self, _: object) -> NoReturn:
        raise AttributeError("You can not assign a new value to per_chat after initialization.")

    @property
    def per_message(self) -> bool:
        """:obj:`bool`: If the conversation key should contain the message's ID."""
        pass

    @per_message.setter
    def per_message(self, _: object) -> NoReturn:
        raise AttributeError("You can not assign a new value to per_message after initialization.")

    @property
    def conversation_timeout(
        self,
    ) -> float | dtm.timedelta | None:
        """:obj:`float` | :obj:`datetime.timedelta`: Optional. When this
        handler is inactive more than this timeout (in seconds), it will be automatically
        ended.
        """
        pass

    @conversation_timeout.setter
    def conversation_timeout(self, _: object) -> NoReturn:
        raise AttributeError(
            "You can not assign a new value to conversation_timeout after initialization."
        )

    @property
    def name(self) -> str | None:
        """:obj:`str`: Optional. The name for this :class:`ConversationHandler`."""
        pass

    @name.setter
    def name(self, _: object) -> NoReturn:
        raise AttributeError("You can not assign a new value to name after initialization.")

    @property
    def persistent(self) -> bool:
        """:obj:`bool`: Optional. If the conversations dict for this handler should be
        saved. :attr:`name` is required and persistence has to be set in
        :attr:`Application <.Application.persistence>`.
        """
        pass

    @persistent.setter
    def persistent(self, _: object) -> NoReturn:
        raise AttributeError("You can not assign a new value to persistent after initialization.")

    @property
    def map_to_parent(self) -> dict[object, object] | None:
        """dict[:obj:`object`, :obj:`object`]: Optional. A :obj:`dict` that can be
        used to instruct a nested :class:`ConversationHandler` to transition into a mapped state on
        its parent :class:`ConversationHandler` in place of a specified nested state.
        """
        pass

    @map_to_parent.setter
    def map_to_parent(self, _: object) -> NoReturn:
        raise AttributeError(
            "You can not assign a new value to map_to_parent after initialization."
        )

    async def _initialize_persistence(
        self, application: "Application"
    ) -> dict[str, TrackingDict[ConversationKey, object]]:
        """Initializes the persistence for this handler and its child conversations.
        While this method is marked as protected, we expect it to be called by the
        Application/parent conversations. It's just protected to hide it from users.

        Args:
            application (:class:`telegram.ext.Application`): The application.

        Returns:
            A dict {conversation.name -> TrackingDict}, which contains all dict of this
            conversation and possible child conversations.

        """
        pass

    def _get_key(self, update: Update) -> ConversationKey:
        """Builds the conversation key associated with the update."""
        pass


    def _schedule_job(
        self,
        new_state: object,
        application: "Application[Any, CCT, Any, Any, Any, JobQueue]",
        update: Update,
        context: CCT,
        conversation_key: ConversationKey,
    ) -> None:
        """Schedules a job which executes :meth:`_trigger_timeout` upon conversation timeout."""
        pass

    # pylint: disable=too-many-return-statements
    def check_update(self, update: object) -> _CheckUpdateType[CCT] | None:
        """
        Determines whether an update should be handled by this conversation handler, and if so in
        which state the conversation currently is.

        Args:
            update (:class:`telegram.Update` | :obj:`object`): Incoming update.

        Returns:
            :obj:`bool`

        """
        pass

    async def handle_update(  # type: ignore[override]
        self,
        update: Update,
        application: "Application[Any, CCT, Any, Any, Any, Any]",
        check_result: _CheckUpdateType[CCT],
        context: CCT,
    ) -> object | None:
        """Send the update to the callback for the current state and BaseHandler

        Args:
            check_result: The result from :meth:`check_update`. For this handler it's a tuple of
                the conversation state, key, handler, and the handler's check result.
            update (:class:`telegram.Update`): Incoming telegram update.
            application (:class:`telegram.ext.Application`): Application that originated the
                update.
            context (:class:`telegram.ext.CallbackContext`): The context as provided by
                the application.

        """
        pass


    async def _trigger_timeout(self, context: CCT) -> None:
        """This is run whenever a conversation has timed out. Also makes sure that all handlers
        which are in the :attr:`TIMEOUT` state and whose :meth:`BaseHandler.check_update` returns
        :obj:`True` is handled.
        """
        pass
