from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from sutd.trivia_bot.common.models import Question
from sutd.trivia_bot.common.quizzer import QuestionAskerFactory
from sutd.trivia_bot.common.bindings import ALL_BINDINGS
import sutd.trivia_bot.common.database
import sutd.trivia_bot.common.quizzer

import pinject

OBJ_GRAPH = pinject.new_object_graph(
    modules=[sutd.trivia_bot.common.database, sutd.trivia_bot.common.quizzer],
    binding_specs=ALL_BINDINGS,
)


def lambda_handler(event, context):
    chat_id = event["chat_id"]
    execution_arn = event["execution_arn"]
    question = Question(**event["question"])

    qaf: QuestionAskerFactory = OBJ_GRAPH.provide(QuestionAskerFactory)
    qa = qaf.create(chat_id, step_function_execution_arn=execution_arn)
    question_message = qa.ask(question)

    return {"message_id": question_message.message_id}
