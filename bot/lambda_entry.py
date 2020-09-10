import json
import logging
import sys
import traceback

from telegram import Update, Bot
from telegram.ext import Dispatcher
import pinject

from sutd.trivia_bot.bot.handlers import GameStateCommands, AnsweringHandlers
from sutd.trivia_bot.common.bindings import ALL_BINDINGS as COMMON_BINDINGS
import sutd.trivia_bot.common.database
import sutd.trivia_bot.common.quizzer

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

OBJ_GRAPH = pinject.new_object_graph(
    modules=[sutd.trivia_bot.common.database, sutd.trivia_bot.common.quizzer],
    binding_specs=COMMON_BINDINGS,
)


def lambda_handler(event, context):
    # Create bot, update queue and dispatcher instances
    bot: Bot = OBJ_GRAPH.provide(Bot)

    dispatcher: Dispatcher = Dispatcher(bot, None, workers=0, use_context=True)
    dispatcher.bot_data = {"event": event}

    gsc: GameStateCommands = OBJ_GRAPH.provide(GameStateCommands)
    gsc.register_handlers(dispatcher)
    ah: AnsweringHandlers = OBJ_GRAPH.provide(AnsweringHandlers)
    ah.register_handlers(dispatcher)

    def error_callback(update, context):
        error: Exception = context.error
        traceback.print_exception(type(error), error, error.__traceback__)
        traceback.print_tb(error.__traceback__)
        context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"An error occurred: {context.error}"
        )

    dispatcher.add_error_handler(error_callback)

    input_data = json.loads(event["body"])

    update = Update.de_json(input_data, bot)
    dispatcher.process_update(update)

    return {"statusCode": 200, "body": ""}
