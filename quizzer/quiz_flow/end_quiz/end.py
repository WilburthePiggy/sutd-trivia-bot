from __future__ import annotations

from telegram import Bot

from sutd.trivia_bot.common.bindings import ALL_BINDINGS
from sutd.trivia_bot.common.quizzer import GameMaster, GameMasterFactory

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table
import sutd.trivia_bot.common.database
import sutd.trivia_bot.common.quizzer

import pinject

OBJ_GRAPH = pinject.new_object_graph(
    modules=[sutd.trivia_bot.common.database, sutd.trivia_bot.common.quizzer],
    binding_specs=ALL_BINDINGS,
)


class NeedsTable:
    def __init__(self, table: Table):
        self.table = table


def lambda_handler(event, context):
    chat_id = event["chat_id"]

    bot: Bot = OBJ_GRAPH.provide(Bot)
    gmf: GameMasterFactory = OBJ_GRAPH.provide(GameMasterFactory)
    gm = gmf.create(chat_id)

    gm.end_game()
