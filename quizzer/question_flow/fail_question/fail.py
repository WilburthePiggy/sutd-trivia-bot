from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from sutd.trivia_bot.common.quizzer import QuestionResponderFactory
from sutd.trivia_bot.common.bindings import ALL_BINDINGS
from sutd.trivia_bot.common.database import CallbackRepository
import sutd.trivia_bot.common.database
import sutd.trivia_bot.common.quizzer

import pinject

OBJ_GRAPH = pinject.new_object_graph(
    modules=[sutd.trivia_bot.common.database, sutd.trivia_bot.common.quizzer],
    binding_specs=ALL_BINDINGS,
)


def lambda_handler(event, context):
    chat_id = event["chat_id"]
    message_id = event["message_id"]
    question_id = event["question"]["id"]

    # mark question-message as failed

    qrf: QuestionResponderFactory = OBJ_GRAPH.provide(QuestionResponderFactory)
    question_responder = qrf.create(chat_id, message_id)
    question_responder.fail()

    # delete callbacks

    callback_repository: CallbackRepository = OBJ_GRAPH.provide(CallbackRepository)
    callback_repository.delete_by_question_id(chat_id, question_id)
