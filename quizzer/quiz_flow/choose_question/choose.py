from __future__ import annotations

import random

import pinject
from boto3.dynamodb.conditions import Key

from sutd.trivia_bot.common.bindings import ALL_BINDINGS
from sutd.trivia_bot.common.database import QuestionRepository

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import List

import sutd.trivia_bot.common.database
import sutd.trivia_bot.common.quizzer

OBJ_GRAPH = pinject.new_object_graph(
    modules=[sutd.trivia_bot.common.database, sutd.trivia_bot.common.quizzer],
    binding_specs=ALL_BINDINGS,
)


def lambda_handler(event, context):
    sample_question_ids: List[str] = event["sample_question_ids"]
    already_asked: List[str] = event["already_asked"]

    not_yet_asked = list(set(sample_question_ids) - set(already_asked))

    question_repository: QuestionRepository = OBJ_GRAPH.provide(QuestionRepository)

    question_id_to_ask = random.choice(not_yet_asked)

    question_to_ask = question_repository.find(question_id_to_ask)

    return {
        "sample_question_ids": list(sample_question_ids),
        "already_asked": list(already_asked) + [question_id_to_ask],
        "next_question": question_to_ask.dict(),
        "number_of_questions_remaining": len(sample_question_ids)
        - len(already_asked)
        - 1,
    }
