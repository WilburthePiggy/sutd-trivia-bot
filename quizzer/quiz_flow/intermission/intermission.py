from random import random
from bisect import bisect
import time

import pinject
from telegram import Bot

from sutd.trivia_bot.common.bindings import ALL_BINDINGS
from sutd.trivia_bot.common.database import ScoreRepository
import sutd.trivia_bot.common.database
import sutd.trivia_bot.common.quizzer


OBJ_GRAPH = pinject.new_object_graph(
    modules=[sutd.trivia_bot.common.database, sutd.trivia_bot.common.quizzer],
    binding_specs=ALL_BINDINGS,
)


# https://stackoverflow.com/a/4322940
def weighted_choice(choices):
    values, weights = zip(*choices)
    total = 0
    cum_weights = []
    for w in weights:
        total += w
        cum_weights.append(total)
    x = random() * total
    i = bisect(cum_weights, x)
    return values[i]


def lambda_handler(event, context):
    chat_id = event["chat_id"]
    sample_question_ids = event["sample_question_ids"]
    already_asked = event["already_asked"]
    question_just_asked = event["question_just_asked"]
    number_of_questions_remaining = event["number_of_questions_remaining"]

    bot: Bot = OBJ_GRAPH.provide(Bot)
    score_repository: ScoreRepository = OBJ_GRAPH.provide(ScoreRepository)

    choice = weighted_choice(
        [("PR", 2), ("LOCAL_SCORE", 2), ("GLOBAL_SCORE", 1), ("NOTHING", 8)]
    )
    if choice == "PR":
        bot.send_message(
            text="Did you know? You can contribute your own trivia questions! Just open a pull request on github here: https://github.com/OpenSUTD/sutd-trivia-bot",
            chat_id=chat_id,
        )
    elif choice == "LOCAL_SCORE":
        # show local scoreboards
        top_players = score_repository.get_local_top_players(chat_id=chat_id, count=10)
        message_header = "Current Scoreboard:\n"
        message_lines = [message_header]
        for i, player in enumerate(top_players):
            player_name = (
                player.user_data.get("first_name")
                or player.user_data.get("last_name")
                or player.user_data.get("username")
            )
            if i == 0:
                message_lines.append(f"🥇 {player.score} points: {player_name}")
            elif i == 1:
                message_lines.append(f"🥈 {player.score} points: {player_name}")
            elif i == 2:
                message_lines.append(f"🥉 {player.score} points: {player_name}")
            else:
                message_lines.append(f"{player.score} points: player_name")
        message_lines.append("\nOnly top 10 players shown")
        bot.send_message(text="\n".join(message_lines), chat_id=chat_id)
    elif choice == "GLOBAL_SCORE":
        # show global scoreboards
        top_players = score_repository.get_global_top_players(count=10)
        message_header = "Top players of all time:\n"
        message_lines = [message_header]
        for i, player in enumerate(top_players):
            player_name = (
                player.user_data.get("first_name")
                or player.user_data.get("last_name")
                or player.user_data.get("username")
            )
            if i == 0:
                message_lines.append(f"🥇 {player.score} points: {player_name}")
            elif i == 1:
                message_lines.append(f"🥈 {player.score} points: {player_name}")
            elif i == 2:
                message_lines.append(f"🥉 {player.score} points: {player_name}")
            else:
                message_lines.append(f"{player.score} points: player_name")
        message_lines.append("\nOnly top 10 players shown")
        bot.send_message(text="\n".join(message_lines), chat_id=chat_id)
    elif choice == "NOTHING":
        pass
    else:
        raise ValueError("Unexpected choice value")
    time.sleep(2.5)
