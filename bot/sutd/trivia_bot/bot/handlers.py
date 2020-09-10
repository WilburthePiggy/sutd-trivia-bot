from __future__ import annotations

import os
from datetime import datetime

from sutd.trivia_bot.common.database import CallbackRepository
from sutd.trivia_bot.common.models import GameInfo
from sutd.trivia_bot.common.quizzer import GameMasterFactory, QuestionResponderFactory

from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    BaseFilter,
)
import pinject

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram import Update, Chat, User, CallbackQuery, Message, MessageEntity
    from telegram.ext import CallbackContext
    from telegram.ext import Dispatcher


class GameStateCommands:
    @pinject.inject()
    def __init__(self, game_master_factory: GameMasterFactory):
        self.game_master_factory = game_master_factory

    def start_command(self, update: Update, context: CallbackContext):
        print("start command?")
        # ask the game master to start the game for this chat
        game_master = self.game_master_factory.create(update.effective_chat.id)
        game_master.start_game(trigger_message_id=update.effective_message.message_id)

    def end_command(self, update: Update, context: CallbackContext):
        # ask the game master to end the current game for this chat
        game_master = self.game_master_factory.create(update.effective_chat.id)
        game_master.force_end_game(
            trigger_message_id=update.effective_message.message_id
        )

    def register_handlers(self, dispatcher: Dispatcher):
        dispatcher.add_handler(CommandHandler("start", self.start_command))
        dispatcher.add_handler(CommandHandler("end", self.end_command))


class PrivacyModeFilter(BaseFilter):
    name = "privacy_mode_filter"

    def filter(self, message: Message):
        bot_id = os.environ["BOT_TOKEN"].split(":")[0]
        if message.reply_to_message is not None:
            return message.reply_to_message.from_user.id == bot_id
        return MessageEntity.BOT_COMMAND in [e.type for e in message.entities]


class AnsweringHandlers:
    @pinject.inject()
    def __init__(
        self,
        question_responder_factory: QuestionResponderFactory,
        callback_repository: CallbackRepository,
    ):
        self.question_responder_factory = question_responder_factory
        self.callback_repository = callback_repository

    def answer_mcq_callback_query(self, update: Update, context: CallbackContext):
        chat: Chat = update.effective_chat
        callback_query: CallbackQuery = update.callback_query
        user: User = callback_query.from_user
        original_question_message: Message = callback_query.message
        # see if context data still exists
        callback_data = self.callback_repository.retrieve(
            callback_id=callback_query.data, chat_id=chat.id
        )
        if callback_data is None:
            context.bot.answer_callback_query(
                callback_query_id=callback_query.id, text="Expired", cache_time=100
            )
            return
        question_responder = self.question_responder_factory.create(
            chat_id=chat.id, message_id=original_question_message.message_id
        )
        user_data = dict()
        if user.first_name is not None:
            user_data["first_name"] = user.first_name
        if user.last_name is not None:
            user_data["last_name"] = user.last_name
        if user.username is not None:
            user_data["username"] = user.username
        print(user_data)
        question_responder.attempt(
            answer=str(callback_data["answer"]).lower(),
            answer_time=int(datetime.utcnow().timestamp()),
            answer_callback_query_id=callback_query.id,
            user_id=user.id,
            user_data=user_data,
        )

    def answer_reply_message(self, update: Update, context: CallbackContext):
        chat: Chat = update.effective_chat
        user: User = update.effective_user
        message: Message = update.effective_message
        question_responder = self.question_responder_factory.create(
            chat_id=chat.id, message_id=message.reply_to_message.message_id
        )
        user_data = dict()
        if user.first_name is not None:
            user_data["first_name"] = user.first_name
        if user.last_name is not None:
            user_data["last_name"] = user.last_name
        if user.username is not None:
            user_data["username"] = user.username
        question_responder.attempt(
            answer=str(message.text).lower(),
            answer_time=int(message.date.timestamp()),
            user_id=user.id,
            user_data=user_data,
            answer_message_id=message.message_id,
        )

    def warn_non_privacy_mode(self, update: Update, context: CallbackContext):
        chat: Chat = update.effective_chat
        context.bot.send_message(
            text="Hey! I am not supposed to be able to read your messages. Please tell the admin to remove me, and add me again in privacy mode (uncheck allow bot to read all group messages).",
            chat_id=chat.id,
        )

    def register_handlers(self, dispatcher: Dispatcher):
        dispatcher.add_handler(CallbackQueryHandler(self.answer_mcq_callback_query))
        dispatcher.add_handler(
            MessageHandler(
                Filters.text & Filters.group & Filters.reply, self.answer_reply_message,
            )
        )
        # dispatcher.add_handler(
        #     MessageHandler(
        #         Filters.text & Filters.group & Filters.reply & PrivacyModeFilter(),
        #         self.answer_reply_message,
        #     )
        # )
        # dispatcher.add_handler(
        #     MessageHandler(
        #         Filters.text & Filters.group & ~PrivacyModeFilter(),
        #         self.warn_non_privacy_mode,
        #     )
        # )
