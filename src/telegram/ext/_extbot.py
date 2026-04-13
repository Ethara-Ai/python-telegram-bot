#!/usr/bin/env python
# pylint: disable=too-many-arguments
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
"""This module contains an object that represents a Telegram Bot with convenience extensions."""

import datetime as dtm
from collections.abc import Callable, Sequence
from copy import copy
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    TypeVar,
    cast,
    no_type_check,
    overload,
)
from uuid import uuid4

from telegram import (
    AcceptedGiftTypes,
    Animation,
    Audio,
    Bot,
    BotCommand,
    BotCommandScope,
    BotDescription,
    BotName,
    BotShortDescription,
    BusinessConnection,
    CallbackQuery,
    ChatAdministratorRights,
    ChatFullInfo,
    ChatInviteLink,
    ChatMember,
    ChatPermissions,
    ChatPhoto,
    Document,
    File,
    ForumTopic,
    GameHighScore,
    Gifts,
    InlineKeyboardMarkup,
    InlineQueryResultsButton,
    InputChecklist,
    InputMedia,
    InputPaidMedia,
    InputPollOption,
    InputProfilePhoto,
    LinkPreviewOptions,
    MaskPosition,
    MenuButton,
    Message,
    MessageId,
    OwnedGifts,
    PhotoSize,
    Poll,
    PreparedInlineMessage,
    ReactionType,
    ReplyParameters,
    SentWebAppMessage,
    StarAmount,
    StarTransactions,
    Sticker,
    StickerSet,
    Story,
    TelegramObject,
    Update,
    User,
    UserChatBoosts,
    UserProfileAudios,
    UserProfilePhotos,
    Video,
    VideoNote,
    Voice,
    WebhookInfo,
)
from telegram._utils.datetime import to_timestamp
from telegram._utils.defaultvalue import DEFAULT_NONE, DefaultValue
from telegram._utils.logging import get_logger
from telegram._utils.repr import build_repr_with_selected_attrs
from telegram._utils.types import (
    BaseUrl,
    CorrectOptionID,
    FileInput,
    JSONDict,
    ODVInput,
    ReplyMarkup,
    TimePeriod,
)
from telegram.ext._callbackdatacache import CallbackDataCache
from telegram.ext._utils.types import RLARGS
from telegram.request import BaseRequest
from telegram.warnings import PTBUserWarning

if TYPE_CHECKING:
    from telegram import (
        Contact,
        Gift,
        InlineQueryResult,
        InputMediaAudio,
        InputMediaDocument,
        InputMediaPhoto,
        InputMediaVideo,
        InputSticker,
        InputStoryContent,
        LabeledPrice,
        Location,
        MessageEntity,
        PassportElementError,
        ShippingOption,
        StoryArea,
        SuggestedPostParameters,
        Venue,
    )
    from telegram.ext import BaseRateLimiter, Defaults

HandledTypes = TypeVar("HandledTypes", bound=Message | CallbackQuery | ChatFullInfo)
KT = TypeVar("KT", bound=ReplyMarkup)


class ExtBot(Bot, Generic[RLARGS]):
    """This object represents a Telegram Bot with convenience extensions.

    Warning:
        Not to be confused with :class:`telegram.Bot`.

    For the documentation of the arguments, methods and attributes, please see
    :class:`telegram.Bot`.

    All API methods of this class have an additional keyword argument ``rate_limit_args``.
    This can be used to pass additional information to the rate limiter, specifically to
    :paramref:`telegram.ext.BaseRateLimiter.process_request.rate_limit_args`.

    This class is a :class:`~typing.Generic` class and accepts one type variable that specifies
    the generic type of the :attr:`rate_limiter` used by the bot. Use :obj:`None` if no rate
    limiter is used.

    Warning:
        * The keyword argument ``rate_limit_args`` can `not` be used, if :attr:`rate_limiter`
          is :obj:`None`.
        * The method :meth:`~telegram.Bot.get_updates` is the only method that does not have the
          additional argument, as this method will never be rate limited.

    Examples:
        :any:`Arbitrary Callback Data Bot <examples.arbitrarycallbackdatabot>`

    .. seealso:: :wiki:`Arbitrary callback_data <Arbitrary-callback_data>`

    .. versionadded:: 13.6

    .. versionchanged:: 20.0
        Removed the attribute ``arbitrary_callback_data``. You can instead use
        :attr:`bot.callback_data_cache.maxsize <telegram.ext.CallbackDataCache.maxsize>` to
        access the size of the cache.

    .. versionchanged:: 20.5
        Removed deprecated methods ``set_sticker_set_thumb`` and ``setStickerSetThumb``.

    Args:
        defaults (:class:`telegram.ext.Defaults`, optional): An object containing default values to
            be used if not set explicitly in the bot methods.
        arbitrary_callback_data (:obj:`bool` | :obj:`int`, optional): Whether to
            allow arbitrary objects as callback data for :class:`telegram.InlineKeyboardButton`.
            Pass an integer to specify the maximum number of objects cached in memory.
            Defaults to :obj:`False`.

            .. seealso:: :wiki:`Arbitrary callback_data <Arbitrary-callback_data>`
        rate_limiter (:class:`telegram.ext.BaseRateLimiter`, optional): A rate limiter to use for
            limiting the number of requests made by the bot per time interval.

            .. versionadded:: 20.0

    """

    __slots__ = ("_callback_data_cache", "_defaults", "_rate_limiter")

    _LOGGER = get_logger(__name__, class_name="ExtBot")

    # using object() would be a tiny bit safer, but a string plays better with the typing setup
    __RL_KEY = uuid4().hex

    @overload
    def __init__(
        self: "ExtBot[None]",
        token: str,
        base_url: BaseUrl = "https://api.telegram.org/bot",
        base_file_url: BaseUrl = "https://api.telegram.org/file/bot",
        request: BaseRequest | None = None,
        get_updates_request: BaseRequest | None = None,
        private_key: bytes | None = None,
        private_key_password: bytes | None = None,
        defaults: "Defaults | None" = None,
        arbitrary_callback_data: bool | int = False,
        local_mode: bool = False,
    ): ...

    @overload
    def __init__(
        self: "ExtBot[RLARGS]",
        token: str,
        base_url: BaseUrl = "https://api.telegram.org/bot",
        base_file_url: BaseUrl = "https://api.telegram.org/file/bot",
        request: BaseRequest | None = None,
        get_updates_request: BaseRequest | None = None,
        private_key: bytes | None = None,
        private_key_password: bytes | None = None,
        defaults: "Defaults | None" = None,
        arbitrary_callback_data: bool | int = False,
        local_mode: bool = False,
        rate_limiter: "BaseRateLimiter[RLARGS] | None" = None,
    ): ...

    def __init__(
        self,
        token: str,
        base_url: BaseUrl = "https://api.telegram.org/bot",
        base_file_url: BaseUrl = "https://api.telegram.org/file/bot",
        request: BaseRequest | None = None,
        get_updates_request: BaseRequest | None = None,
        private_key: bytes | None = None,
        private_key_password: bytes | None = None,
        defaults: "Defaults | None" = None,
        arbitrary_callback_data: bool | int = False,
        local_mode: bool = False,
        rate_limiter: "BaseRateLimiter[RLARGS] | None" = None,
    ):
        super().__init__(
            token=token,
            base_url=base_url,
            base_file_url=base_file_url,
            request=request,
            get_updates_request=get_updates_request,
            private_key=private_key,
            private_key_password=private_key_password,
            local_mode=local_mode,
        )
        with self._unfrozen():
            self._defaults: Defaults | None = defaults
            self._rate_limiter: BaseRateLimiter | None = rate_limiter
            self._callback_data_cache: CallbackDataCache | None = None

            # set up callback_data
            if arbitrary_callback_data is False:
                return

            if not isinstance(arbitrary_callback_data, bool):
                maxsize = cast("int", arbitrary_callback_data)
            else:
                maxsize = 1024

            self._callback_data_cache = CallbackDataCache(bot=self, maxsize=maxsize)

    def __repr__(self) -> str:
        """Give a string representation of the bot in the form ``ExtBot[token=...]``.

        As this class doesn't implement :meth:`object.__str__`, the default implementation
        will be used, which is equivalent to :meth:`__repr__`.

        Returns:
            :obj:`str`
        """
        return build_repr_with_selected_attrs(self, token=self.token)

    @classmethod
    def _warn(
        cls,
        message: str | PTBUserWarning,
        category: type[Warning] = PTBUserWarning,
        stacklevel: int = 0,
    ) -> None:
        """We override this method to add one more level to the stacklevel, so that the warning
        points to the user's code, not to the PTB code.
        """
        pass

    @property
    def callback_data_cache(self) -> CallbackDataCache | None:
        """:class:`telegram.ext.CallbackDataCache`: Optional. The cache for
        objects passed as callback data for :class:`telegram.InlineKeyboardButton`.

        Examples:
            :any:`Arbitrary Callback Data Bot <examples.arbitrarycallbackdatabot>`

        .. versionchanged:: 20.0
           * This property is now read-only.
           * This property is now optional and can be :obj:`None` if
             :paramref:`~telegram.ext.ExtBot.arbitrary_callback_data` is set to :obj:`False`.
        """
        pass

    async def initialize(self) -> None:
        """See :meth:`telegram.Bot.initialize`. Also initializes the
        :paramref:`ExtBot.rate_limiter` (if set)
        by calling :meth:`telegram.ext.BaseRateLimiter.initialize`.
        """
        pass

    async def shutdown(self) -> None:
        """See :meth:`telegram.Bot.shutdown`. Also shuts down the
        :paramref:`ExtBot.rate_limiter` (if set) by
        calling :meth:`telegram.ext.BaseRateLimiter.shutdown`.
        """
        # Shut down the rate limiter before shutting down the request objects!
        if self.rate_limiter:
            await self.rate_limiter.shutdown()
        await super().shutdown()

    @classmethod
    def _merge_api_rl_kwargs(
        cls, api_kwargs: JSONDict | None, rate_limit_args: RLARGS | None
    ) -> JSONDict | None:
        """Inserts the `rate_limit_args` into `api_kwargs` with the special key `__RL_KEY` so
        that we can extract them later without having to modify the `telegram.Bot` class.
        """
        if not rate_limit_args:
            return api_kwargs
        if api_kwargs is None:
            api_kwargs = {}
        api_kwargs[cls.__RL_KEY] = rate_limit_args
        return api_kwargs

    @classmethod
    def _extract_rl_kwargs(cls, data: JSONDict | None) -> RLARGS | None:
        """Extracts the `rate_limit_args` from `data` if it exists."""
        if not data:
            return None
        return data.pop(cls.__RL_KEY, None)

    async def _do_post(
        self,
        endpoint: str,
        data: JSONDict,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
    ) -> bool | JSONDict | list[JSONDict]:
        """Order of method calls is: Bot.some_method -> Bot._post -> Bot._do_post.
        So we can override Bot._do_post to add rate limiting.
        """
        rate_limit_args = self._extract_rl_kwargs(data)
        if not self.rate_limiter and rate_limit_args is not None:
            raise ValueError(
                "`rate_limit_args` can only be used if a `ExtBot.rate_limiter` is set."
            )

        # getting updates should not be rate limited!
        if endpoint == "getUpdates" or not self.rate_limiter:
            return await super()._do_post(
                endpoint=endpoint,
                data=data,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
                read_timeout=read_timeout,
            )

        kwargs = {
            "read_timeout": read_timeout,
            "write_timeout": write_timeout,
            "connect_timeout": connect_timeout,
            "pool_timeout": pool_timeout,
        }
        self._LOGGER.debug(
            "Passing request through rate limiter of type %s with rate_limit_args %s",
            type(self.rate_limiter),
            rate_limit_args,
        )
        return await self.rate_limiter.process_request(
            callback=super()._do_post,
            args=(endpoint, data),
            kwargs=kwargs,
            endpoint=endpoint,
            data=data,
            rate_limit_args=rate_limit_args,
        )

    @property
    def defaults(self) -> "Defaults | None":
        """The :class:`telegram.ext.Defaults` used by this bot, if any."""
        pass

    @property
    def rate_limiter(self) -> "BaseRateLimiter[RLARGS] | None":
        """The :class:`telegram.ext.BaseRateLimiter` used by this bot, if any.

        .. versionadded:: 20.0
        """
        pass

    def _merge_lpo_defaults(self, lpo: ODVInput[LinkPreviewOptions]) -> LinkPreviewOptions | None:
        # This is a standalone method because both _insert_defaults and
        # _insert_defaults_for_ilq_results need this logic
        #
        # If Defaults.LPO is set, and LPO is passed in the bot method we should fuse
        # them, giving precedence to passed values.
        # Defaults.LPO(True, "google.com", True) & LPO=LPO(True, ..., False) ->
        # LPO(True, "google.com", False)
        if self.defaults is None or (defaults_lpo := self.defaults.link_preview_options) is None:
            return DefaultValue.get_value(lpo)
        return LinkPreviewOptions(
            **{
                attr: (
                    getattr(defaults_lpo, attr)
                    # only use the default value
                    # if the value was explicitly passed to the LPO object
                    if isinstance(orig_attr := getattr(lpo, attr), DefaultValue)
                    else orig_attr
                )
                for attr in defaults_lpo.__slots__
            }
        )

    def _insert_defaults(self, data: dict[str, object]) -> None:
        """Inserts the defaults values for optional kwargs for which tg.ext.Defaults provides
        convenience functionality, i.e. the kwargs with a tg.utils.helpers.DefaultValue default

        data is edited in-place. As timeout is not passed via the kwargs, it needs to be passed
        separately and gets returned.

        This can only work, if all kwargs that may have defaults are passed in data!
        """
        if self.defaults is None:
            # If we have no defaults to insert, the behavior is the same as in `tg.Bot`
            super()._insert_defaults(data)
            return

        # if we have Defaults, we
        # 1) replace all DefaultValue instances with the relevant Defaults value. If there is none,
        #    we fall back to the default value of the bot method
        # 2) convert all datetime.datetime objects to timestamps wrt the correct default timezone
        # 3) set the correct parse_mode for all InputMedia objects
        # 4) handle the LinkPreviewOptions case (see below)
        # 5) handle the ReplyParameters case (see below)
        # 6) handle text_parse_mode in InputPollOption
        for key, val in data.items():
            # 1)
            if isinstance(val, DefaultValue):
                data[key] = self.defaults.api_defaults.get(key, val.value)

            # 2)
            elif isinstance(val, dtm.datetime):
                data[key] = to_timestamp(val, tzinfo=self.defaults.tzinfo)

            # 3)
            elif isinstance(val, InputMedia) and val.parse_mode is DEFAULT_NONE:
                # Copy object as not to edit it in-place
                copied_val = copy(val)
                with copied_val._unfrozen():
                    copied_val.parse_mode = self.defaults.parse_mode
                data[key] = copied_val
            elif (
                key == "media"
                and isinstance(val, Sequence)
                and not isinstance(val[0], InputPaidMedia)
            ):
                # Copy objects as not to edit them in-place
                copy_list = [copy(media) for media in val]
                for media in copy_list:
                    if media.parse_mode is DEFAULT_NONE:
                        with media._unfrozen():
                            media.parse_mode = self.defaults.parse_mode

                data[key] = copy_list

            # 4) LinkPreviewOptions:
            elif isinstance(val, LinkPreviewOptions):
                data[key] = self._merge_lpo_defaults(val)

            # 5)
            # Similar to LinkPreviewOptions, but only two of the arguments of RPs have a default
            elif isinstance(val, ReplyParameters) and (
                (defaults_aswr := self.defaults.allow_sending_without_reply) is not None
                or self.defaults.quote_parse_mode is not None
            ):
                new_value = copy(val)
                with new_value._unfrozen():
                    new_value.allow_sending_without_reply = (
                        defaults_aswr
                        if isinstance(val.allow_sending_without_reply, DefaultValue)
                        else val.allow_sending_without_reply
                    )
                    new_value.quote_parse_mode = (
                        self.defaults.quote_parse_mode
                        if isinstance(val.quote_parse_mode, DefaultValue)
                        else val.quote_parse_mode
                    )

                data[key] = new_value

            # 6)
            elif isinstance(val, Sequence) and all(
                isinstance(obj, InputPollOption) for obj in val
            ):
                new_val = []
                for option in val:
                    if not isinstance(option.text_parse_mode, DefaultValue):
                        new_val.append(option)
                    else:
                        new_option = copy(option)
                        with new_option._unfrozen():
                            new_option.text_parse_mode = self.defaults.text_parse_mode
                        new_val.append(new_option)
                data[key] = new_val

    def _replace_keyboard(self, reply_markup: KT | None) -> KT | None:
        # If the reply_markup is an inline keyboard and we allow arbitrary callback data, let the
        # CallbackDataCache build a new keyboard with the data replaced. Otherwise return the input
        if isinstance(reply_markup, InlineKeyboardMarkup) and self.callback_data_cache is not None:
            # for some reason mypy doesn't understand that IKB is a subtype of KT | None
            return self.callback_data_cache.process_keyboard(  # type: ignore[return-value]
                reply_markup
            )

        return reply_markup

    def insert_callback_data(self, update: Update) -> None:
        """If this bot allows for arbitrary callback data, this inserts the cached data into all
        corresponding buttons within this update.

        Note:
            Checks :attr:`telegram.Message.via_bot` and :attr:`telegram.Message.from_user`
            to figure out if a) a reply markup exists and b) it was actually sent by this
            bot. If not, the message will be returned unchanged.

            Note that this will fail for channel posts, as :attr:`telegram.Message.from_user` is
            :obj:`None` for those! In the corresponding reply markups, the callback data will be
            replaced by :class:`telegram.ext.InvalidCallbackData`.

        Warning:
            *In place*, i.e. the passed :class:`telegram.Message` will be changed!

        Args:
            update (:class:`telegram.Update`): The update.

        """
        # The only incoming updates that can directly contain a message sent by the bot itself are:
        # * CallbackQueries
        # * Messages where the pinned_message is sent by the bot
        # * Messages where the reply_to_message is sent by the bot
        # * Messages where via_bot is the bot
        # Finally there is effective_chat.pinned message, but that's only returned in get_chat
        if update.callback_query:
            self._insert_callback_data(update.callback_query)
        # elif instead of if, as effective_message includes callback_query.message
        # and that has already been processed
        elif update.effective_message:
            self._insert_callback_data(update.effective_message)

    def _insert_callback_data(self, obj: HandledTypes) -> HandledTypes:
        if self.callback_data_cache is None:
            return obj

        if isinstance(obj, CallbackQuery):
            self.callback_data_cache.process_callback_query(obj)
            return obj

        if isinstance(obj, Message):
            if obj.reply_to_message:
                # reply_to_message can't contain further reply_to_messages, so no need to check
                self.callback_data_cache.process_message(obj.reply_to_message)
                if isinstance(obj.reply_to_message.pinned_message, Message):
                    # pinned messages can't contain reply_to_message, no need to check
                    self.callback_data_cache.process_message(obj.reply_to_message.pinned_message)
            if isinstance(obj.pinned_message, Message):
                # pinned messages can't contain reply_to_message, no need to check
                self.callback_data_cache.process_message(obj.pinned_message)

            # Finally, handle the message itself
            self.callback_data_cache.process_message(message=obj)
            return obj

        if isinstance(obj, ChatFullInfo) and obj.pinned_message:
            self.callback_data_cache.process_message(obj.pinned_message)

        return obj

    async def _send_message(
        self,
        endpoint: str,
        data: JSONDict,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        link_preview_options: ODVInput["LinkPreviewOptions"] = None,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
    ) -> Any:
        # We override this method to call self._replace_keyboard and self._insert_callback_data.
        # This covers most methods that have a reply_markup
        result = await super()._send_message(
            endpoint=endpoint,
            data=data,
            reply_to_message_id=reply_to_message_id,
            disable_notification=disable_notification,
            reply_markup=self._replace_keyboard(reply_markup),
            allow_sending_without_reply=allow_sending_without_reply,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            caption=caption,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            link_preview_options=link_preview_options,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=api_kwargs,
            business_connection_id=business_connection_id,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )
        if isinstance(result, Message):
            self._insert_callback_data(result)
        return result


    def _effective_inline_results(
        self,
        results: (
            Sequence["InlineQueryResult"] | Callable[[int], Sequence["InlineQueryResult"] | None]
        ),
        next_offset: str | None = None,
        current_offset: str | None = None,
    ) -> tuple[Sequence["InlineQueryResult"], str | None]:
        """This method is called by Bot.answer_inline_query to build the actual results list.
        Overriding this to call self._replace_keyboard suffices
        """
        pass

    @no_type_check  # mypy doesn't play too well with hasattr
    def _insert_defaults_for_ilq_results(self, res: "InlineQueryResult") -> "InlineQueryResult":
        """This method is called by Bot.answer_inline_query to replace `DefaultValue(obj)` with
        `obj`.
        Overriding this to call insert the actual desired default values.
        """
        pass



    async def copy_message(
        self,
        chat_id: int | str,
        from_chat_id: str | int,
        message_id: int,
        caption: str | None = None,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        caption_entities: Sequence["MessageEntity"] | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        message_thread_id: int | None = None,
        reply_parameters: "ReplyParameters | None" = None,
        show_caption_above_media: bool | None = None,
        allow_paid_broadcast: bool | None = None,
        video_start_timestamp: int | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        message_effect_id: str | None = None,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> MessageId:
        # We override this method to call self._replace_keyboard
        return await super().copy_message(
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
            caption=caption,
            video_start_timestamp=video_start_timestamp,
            parse_mode=parse_mode,
            caption_entities=caption_entities,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=allow_sending_without_reply,
            reply_markup=self._replace_keyboard(reply_markup),
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            show_caption_above_media=show_caption_above_media,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
            message_effect_id=message_effect_id,
        )












































































    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        entities: Sequence["MessageEntity"] | None = None,
        disable_notification: ODVInput[bool] = DEFAULT_NONE,
        protect_content: ODVInput[bool] = DEFAULT_NONE,
        reply_markup: "ReplyMarkup | None" = None,
        message_thread_id: int | None = None,
        link_preview_options: ODVInput["LinkPreviewOptions"] = DEFAULT_NONE,
        reply_parameters: "ReplyParameters | None" = None,
        business_connection_id: str | None = None,
        message_effect_id: str | None = None,
        allow_paid_broadcast: bool | None = None,
        direct_messages_topic_id: int | None = None,
        suggested_post_parameters: "SuggestedPostParameters | None" = None,
        *,
        disable_web_page_preview: bool | None = None,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: ODVInput[bool] = DEFAULT_NONE,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
        api_kwargs: JSONDict | None = None,
        rate_limit_args: RLARGS | None = None,
    ) -> Message:
        return await super().send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            entities=entities,
            disable_web_page_preview=disable_web_page_preview,
            disable_notification=disable_notification,
            business_connection_id=business_connection_id,
            protect_content=protect_content,
            message_thread_id=message_thread_id,
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=allow_sending_without_reply,
            reply_markup=reply_markup,
            reply_parameters=reply_parameters,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
            api_kwargs=self._merge_api_rl_kwargs(api_kwargs, rate_limit_args),
            link_preview_options=link_preview_options,
            message_effect_id=message_effect_id,
            allow_paid_broadcast=allow_paid_broadcast,
            direct_messages_topic_id=direct_messages_topic_id,
            suggested_post_parameters=suggested_post_parameters,
        )
























































































    # updated camelCase aliases
    # getMe = get_me  # stubbed out
    sendMessage = send_message
    # sendMessageDraft = send_message_draft  # stubbed out
    # deleteMessage = delete_message  # stubbed out
    # deleteMessages = delete_messages  # stubbed out
    # forwardMessage = forward_message  # stubbed out
    # forwardMessages = forward_messages  # stubbed out
    # sendPhoto = send_photo  # stubbed out
    # sendAudio = send_audio  # stubbed out
    # sendDocument = send_document  # stubbed out
    # sendSticker = send_sticker  # stubbed out
    # sendVideo = send_video  # stubbed out
    # sendAnimation = send_animation  # stubbed out
    # sendVoice = send_voice  # stubbed out
    # sendVideoNote = send_video_note  # stubbed out
    # sendMediaGroup = send_media_group  # stubbed out
    # sendLocation = send_location  # stubbed out
    # editMessageLiveLocation = edit_message_live_location  # stubbed out
    # stopMessageLiveLocation = stop_message_live_location  # stubbed out
    # sendVenue = send_venue  # stubbed out
    # sendContact = send_contact  # stubbed out
    # sendGame = send_game  # stubbed out
    # sendChatAction = send_chat_action  # stubbed out
    # answerInlineQuery = answer_inline_query  # stubbed out
    # savePreparedInlineMessage = save_prepared_inline_message  # stubbed out
    # getUserProfilePhotos = get_user_profile_photos  # stubbed out
    # getFile = get_file  # stubbed out
    # banChatMember = ban_chat_member  # stubbed out
    # banChatSenderChat = ban_chat_sender_chat  # stubbed out
    # unbanChatMember = unban_chat_member  # stubbed out
    # unbanChatSenderChat = unban_chat_sender_chat  # stubbed out
    # answerCallbackQuery = answer_callback_query  # stubbed out
    # editMessageText = edit_message_text  # stubbed out
    # editMessageCaption = edit_message_caption  # stubbed out
    # editMessageMedia = edit_message_media  # stubbed out
    # editMessageReplyMarkup = edit_message_reply_markup  # stubbed out
    # getUpdates = get_updates  # stubbed out
    # setWebhook = set_webhook  # stubbed out
    # deleteWebhook = delete_webhook  # stubbed out
    # leaveChat = leave_chat  # stubbed out
    # getChat = get_chat  # stubbed out
    # getChatAdministrators = get_chat_administrators  # stubbed out
    # getChatMember = get_chat_member  # stubbed out
    # setChatStickerSet = set_chat_sticker_set  # stubbed out
    # deleteChatStickerSet = delete_chat_sticker_set  # stubbed out
    # getChatMemberCount = get_chat_member_count  # stubbed out
    # getWebhookInfo = get_webhook_info  # stubbed out
    # setGameScore = set_game_score  # stubbed out
    # getGameHighScores = get_game_high_scores  # stubbed out
    # sendInvoice = send_invoice  # stubbed out
    # answerShippingQuery = answer_shipping_query  # stubbed out
    # answerPreCheckoutQuery = answer_pre_checkout_query  # stubbed out
    # answerWebAppQuery = answer_web_app_query  # stubbed out
    # restrictChatMember = restrict_chat_member  # stubbed out
    # promoteChatMember = promote_chat_member  # stubbed out
    # setChatPermissions = set_chat_permissions  # stubbed out
    # setChatAdministratorCustomTitle = set_chat_administrator_custom_title  # stubbed out
    # exportChatInviteLink = export_chat_invite_link  # stubbed out
    # createChatInviteLink = create_chat_invite_link  # stubbed out
    # editChatInviteLink = edit_chat_invite_link  # stubbed out
    # revokeChatInviteLink = revoke_chat_invite_link  # stubbed out
    # approveChatJoinRequest = approve_chat_join_request  # stubbed out
    # declineChatJoinRequest = decline_chat_join_request  # stubbed out
    # setChatPhoto = set_chat_photo  # stubbed out
    # deleteChatPhoto = delete_chat_photo  # stubbed out
    # setChatTitle = set_chat_title  # stubbed out
    # setChatDescription = set_chat_description  # stubbed out
    # setUserEmojiStatus = set_user_emoji_status  # stubbed out
    # pinChatMessage = pin_chat_message  # stubbed out
    # unpinChatMessage = unpin_chat_message  # stubbed out
    # unpinAllChatMessages = unpin_all_chat_messages  # stubbed out
    # getStickerSet = get_sticker_set  # stubbed out
    # getCustomEmojiStickers = get_custom_emoji_stickers  # stubbed out
    # uploadStickerFile = upload_sticker_file  # stubbed out
    # createNewStickerSet = create_new_sticker_set  # stubbed out
    # addStickerToSet = add_sticker_to_set  # stubbed out
    # setStickerPositionInSet = set_sticker_position_in_set  # stubbed out
    # deleteStickerFromSet = delete_sticker_from_set  # stubbed out
    # setStickerSetThumbnail = set_sticker_set_thumbnail  # stubbed out
    # setPassportDataErrors = set_passport_data_errors  # stubbed out
    # sendPoll = send_poll  # stubbed out
    # stopPoll = stop_poll  # stubbed out
    # sendChecklist = send_checklist  # stubbed out
    # editMessageChecklist = edit_message_checklist  # stubbed out
    # sendDice = send_dice  # stubbed out
    # getMyCommands = get_my_commands  # stubbed out
    # setMyCommands = set_my_commands  # stubbed out
    # deleteMyCommands = delete_my_commands  # stubbed out
    # logOut = log_out  # stubbed out
    copyMessage = copy_message
    # copyMessages = copy_messages  # stubbed out
    # getChatMenuButton = get_chat_menu_button  # stubbed out
    # setChatMenuButton = set_chat_menu_button  # stubbed out
    # getMyDefaultAdministratorRights = get_my_default_administrator_rights  # stubbed out
    # setMyDefaultAdministratorRights = set_my_default_administrator_rights  # stubbed out
    # createInvoiceLink = create_invoice_link  # stubbed out
    # getForumTopicIconStickers = get_forum_topic_icon_stickers  # stubbed out
    # createForumTopic = create_forum_topic  # stubbed out
    # editForumTopic = edit_forum_topic  # stubbed out
    # closeForumTopic = close_forum_topic  # stubbed out
    # reopenForumTopic = reopen_forum_topic  # stubbed out
    # deleteForumTopic = delete_forum_topic  # stubbed out
    # unpinAllForumTopicMessages = unpin_all_forum_topic_messages  # stubbed out
    # editGeneralForumTopic = edit_general_forum_topic  # stubbed out
    # closeGeneralForumTopic = close_general_forum_topic  # stubbed out
    # reopenGeneralForumTopic = reopen_general_forum_topic  # stubbed out
    # hideGeneralForumTopic = hide_general_forum_topic  # stubbed out
    # unhideGeneralForumTopic = unhide_general_forum_topic  # stubbed out
    # setMyDescription = set_my_description  # stubbed out
    # getMyDescription = get_my_description  # stubbed out
    # setMyShortDescription = set_my_short_description  # stubbed out
    # getMyShortDescription = get_my_short_description  # stubbed out
    # setCustomEmojiStickerSetThumbnail = set_custom_emoji_sticker_set_thumbnail  # stubbed out
    # setStickerSetTitle = set_sticker_set_title  # stubbed out
    # deleteStickerSet = delete_sticker_set  # stubbed out
    # setStickerEmojiList = set_sticker_emoji_list  # stubbed out
    # setStickerKeywords = set_sticker_keywords  # stubbed out
    # setStickerMaskPosition = set_sticker_mask_position  # stubbed out
    # setMyName = set_my_name  # stubbed out
    # getMyName = get_my_name  # stubbed out
    # unpinAllGeneralForumTopicMessages = unpin_all_general_forum_topic_messages  # stubbed out
    # getUserChatBoosts = get_user_chat_boosts  # stubbed out
    # setMessageReaction = set_message_reaction  # stubbed out
    # giftPremiumSubscription = gift_premium_subscription  # stubbed out
    # getBusinessConnection = get_business_connection  # stubbed out
    # getBusinessAccountGifts = get_business_account_gifts  # stubbed out
    # getBusinessAccountStarBalance = get_business_account_star_balance  # stubbed out
    # readBusinessMessage = read_business_message  # stubbed out
    # deleteBusinessMessages = delete_business_messages  # stubbed out
    # postStory = post_story  # stubbed out
    # editStory = edit_story  # stubbed out
    # deleteStory = delete_story  # stubbed out
    # setBusinessAccountName = set_business_account_name  # stubbed out
    # setBusinessAccountUsername = set_business_account_username  # stubbed out
    # setBusinessAccountBio = set_business_account_bio  # stubbed out
    # setBusinessAccountGiftSettings = set_business_account_gift_settings  # stubbed out
    # setBusinessAccountProfilePhoto = set_business_account_profile_photo  # stubbed out
    # removeBusinessAccountProfilePhoto = remove_business_account_profile_photo  # stubbed out
    # convertGiftToStars = convert_gift_to_stars  # stubbed out
    # upgradeGift = upgrade_gift  # stubbed out
    # transferGift = transfer_gift  # stubbed out
    # transferBusinessAccountStars = transfer_business_account_stars  # stubbed out
    # replaceStickerInSet = replace_sticker_in_set  # stubbed out
    # refundStarPayment = refund_star_payment  # stubbed out
    # getStarTransactions = get_star_transactions  # stubbed out
    # editUserStarSubscription = edit_user_star_subscription  # stubbed out
    # createChatSubscriptionInviteLink = create_chat_subscription_invite_link  # stubbed out
    # editChatSubscriptionInviteLink = edit_chat_subscription_invite_link  # stubbed out
    # sendPaidMedia = send_paid_media  # stubbed out
    # getAvailableGifts = get_available_gifts  # stubbed out
    # sendGift = send_gift  # stubbed out
    # verifyChat = verify_chat  # stubbed out
    # verifyUser = verify_user  # stubbed out
    # removeChatVerification = remove_chat_verification  # stubbed out
    # removeUserVerification = remove_user_verification  # stubbed out
    # getMyStarBalance = get_my_star_balance  # stubbed out
    # approveSuggestedPost = approve_suggested_post  # stubbed out
    # declineSuggestedPost = decline_suggested_post  # stubbed out
    # repostStory = repost_story  # stubbed out
    # getUserGifts = get_user_gifts  # stubbed out
    # getChatGifts = get_chat_gifts  # stubbed out
    # setMyProfilePhoto = set_my_profile_photo  # stubbed out
    # removeMyProfilePhoto = remove_my_profile_photo  # stubbed out
    # getUserProfileAudios = get_user_profile_audios  # stubbed out
    # setChatMemberTag = set_chat_member_tag  # stubbed out
