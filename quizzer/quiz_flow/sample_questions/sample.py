from __future__ import annotations

import random

import pinject
from boto3.dynamodb.conditions import Key

from sutd.trivia_bot.common.bindings import ALL_BINDINGS
from sutd.trivia_bot.common.database import QuestionRepository

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

import sutd.trivia_bot.common.database
import sutd.trivia_bot.common.quizzer

OBJ_GRAPH = pinject.new_object_graph(
    modules=[sutd.trivia_bot.common.database, sutd.trivia_bot.common.quizzer],
    binding_specs=ALL_BINDINGS,
)


def lambda_handler(event, context):
    questions_to_ask = event.get("questions_to_ask")
    question_repository: QuestionRepository = OBJ_GRAPH.provide(QuestionRepository)
    all_question_ids = list(question_repository.list_ids())

    sample_question_ids = random.sample(all_question_ids, questions_to_ask)

    return {"sample_question_ids": list(sample_question_ids), "already_asked": []}
