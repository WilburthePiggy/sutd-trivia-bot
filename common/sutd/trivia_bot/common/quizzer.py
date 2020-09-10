from __future__ import annotations

import json
from datetime import timedelta
from random import shuffle
import time
import traceback

import pinject
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from sutd.trivia_bot.common.models import Question, GameInfo, QuestionMessage


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, List
    from mypy_boto3_dynamodb.service_resource import Table
    from mypy_boto3_stepfunctions import Client as SFNClient
    from telegram.bot import Bot
    from telegram.message import Message
    from datetime import datetime
    from sutd.trivia_bot.common.database import (
        GameInfoRepository,
        QuestionMessageRepository,
        ScoreRepository,
        CallbackRepository,
    )
    from python_dynamodb_lock.python_dynamodb_lock import DynamoDBLockClient

MAX_RESPONSE_TIME = 15


class QuestionAsker:
    def __init__(
        self,
        chat_id: str,
        step_function_execution_arn: str,
        bot: Bot,
        question_message_repository: QuestionMessageRepository,
        callback_repository: CallbackRepository,
    ):
        self.chat_id = chat_id
        self.step_function_execution_arn = step_function_execution_arn
        self.bot = bot
        self.question_message_repository = question_message_repository
        self.callback_repository = callback_repository

    @classmethod
    def generate_question_message_text(cls, question: Question) -> str:
        if question.type == Question.QuestionType.open:
            answering_instructions = "Reply to this message to answer!"
        elif question.type == Question.QuestionType.mcq:
            answering_instructions = "Press one of the buttons below!"
        else:
            raise ValueError("Question type was neither open or mcq!")
        message_text = f"""
        <b>Question:</b> {question.question}

        {answering_instructions}
        """
        return message_text

    def ask(self, question: Question) -> QuestionMessage:
        if question.type == Question.QuestionType.open:
            answering_instructions = "Reply to this message to answer!"
            reply_markup = None
            callback_infos = None
        elif question.type == Question.QuestionType.mcq:
            answering_instructions = "Press one of the buttons below!"
            keyboard: List[List[InlineKeyboardButton]] = []
            answers: List[str] = [question.correct_answer] + question.other_answers
            shuffle(answers)
            callback_infos = []
            for answer in answers:
                callback_data = {
                    "chat_id": self.chat_id,
                    "question_id": question.id,
                    "answer": answer,
                }
                callback_infos.append(callback_data)
                callback_id = self.callback_repository.create(
                    chat_id=self.chat_id, callback_data=callback_data
                )
                keyboard.append(
                    [InlineKeyboardButton(answer, callback_data=callback_id)]
                )
            reply_markup = InlineKeyboardMarkup(keyboard)
        else:
            raise ValueError("Question type was neither open or mcq!")
        message_text = f"""
        <b>Question:</b> {question.question}

        {answering_instructions}
        """
        message: Message = self.bot.send_message(
            text=message_text,
            parse_mode="HTML",
            chat_id=self.chat_id,
            reply_markup=reply_markup,
        )
        question_message = QuestionMessage(
            message_id=message.message_id,
            chat_id=message.chat_id,
            question_id=question.id,
            question_data=question,
            sent_at=message.date,
            step_function_execution_arn=self.step_function_execution_arn,
            callback_infos_json=json.dumps(callback_infos)
            if question.type == question.QuestionType.mcq
            else None,
        )
        self.question_message_repository.create(question_message)
        return question_message


class QuestionAskerFactory:
    @pinject.inject()
    def __init__(
        self,
        bot: Bot,
        question_message_repository: QuestionMessageRepository,
        callback_repository: CallbackRepository,
    ):
        self.bot = bot
        self.question_message_repository = question_message_repository
        self.callback_repository = callback_repository

    def create(self, chat_id: str, step_function_execution_arn: str) -> QuestionAsker:
        return QuestionAsker(
            chat_id=chat_id,
            step_function_execution_arn=step_function_execution_arn,
            bot=self.bot,
            question_message_repository=self.question_message_repository,
            callback_repository=self.callback_repository,
        )


class QuestionResponder:
    def __init__(
        self,
        chat_id: str,
        message_id: str,
        bot: Bot,
        sfn_client: SFNClient,
        score_repository: ScoreRepository,
        callback_repository: CallbackRepository,
        question_message_repository: QuestionMessageRepository,
        lock_client: DynamoDBLockClient,
    ):
        self.chat_id = chat_id
        self.message_id = message_id
        self.bot = bot
        self.sfn_client = sfn_client
        self.score_repository = score_repository
        self.callback_repository = callback_repository
        self.question_message_repository = question_message_repository
        self.lock_client = lock_client

    def fail(self):
        question_lock = f"chat.{self.chat_id}.message.{self.message_id}"
        with self.lock_client.acquire_lock(
            question_lock, retry_period=timedelta(0.25), raise_context_exception=False
        ):
            self.question_message_repository.mark_as_inactive(
                chat_id=self.chat_id, message_id=self.message_id
            )
            question_message = self.question_message_repository.find(
                chat_id=self.chat_id, message_id=self.message_id
            )
            self.bot.send_message(
                text=f"Too slow! The answer is {question_message.question_data.correct_answer}",
                chat_id=self.chat_id,
            )

    def attempt(
        self,
        answer: str,
        answer_time: int,
        user_id: str,
        user_data: dict,
        answer_message_id: Optional[str] = None,
        answer_callback_query_id: Optional[str] = None,
    ) -> bool:
        if answer_message_id is None and answer_callback_query_id is None:
            raise ValueError(
                "Either answer_message_id or answer_callback_query_id must be present"
            )

        player_name = (
            user_data.get("first_name")
            or user_data.get("last_name")
            or user_data.get("username")
        )
        question_lock = f"chat.{self.chat_id}.message.{self.message_id}"
        _start = time.time()
        with self.lock_client.acquire_lock(
            question_lock, retry_period=timedelta(0.25), raise_context_exception=True
        ):
            _end = time.time()
            print(f"It took {_end - _start} seconds to acquire the lock")
            result = self.question_message_repository.attempt(
                chat_id=self.chat_id,
                message_id=self.message_id,
                answer=answer,
                answer_time=answer_time,
                user_display_name=player_name,
                no_retries=answer_message_id is None,
            )
            correct = result[0]
        if correct:
            _, time_delta, correct_answer = result
            # calculate number of points to give
            # constant 100 points for mcq questions
            award_value = (
                max(
                    10,
                    int(
                        (abs(MAX_RESPONSE_TIME - time_delta) / MAX_RESPONSE_TIME) * 100
                    ),
                )
                if answer_message_id is not None
                else 100
            )
            # award points
            self.score_repository.award_points(
                chat_id=self.chat_id,
                user_id=user_id,
                award_points=award_value,
                user_data=user_data,
            )
            # stop question step function execution
            question_message = self.question_message_repository.find(
                self.chat_id, self.message_id
            )
            if question_message.step_function_execution_arn is not None:
                self.sfn_client.stop_execution(
                    executionArn=question_message.step_function_execution_arn,
                    error="Answered",
                    cause="Question Answered",
                )
            # give feedback
            if answer_callback_query_id is not None:
                # mcq feedback
                mcq_extra_message = f"The answer is {correct_answer}. "
                self.bot.send_message(
                    text=f"🎉 Correct! {mcq_extra_message}{player_name} has been awarded {award_value} points.",
                    chat_id=self.chat_id,
                )
                self.bot.answer_callback_query(
                    text="🎉 Correct!", callback_query_id=answer_callback_query_id
                )
                self.callback_repository.delete_by_question_id(
                    chat_id=self.chat_id, question_id=question_message.question_id
                )
            elif answer_message_id is not None:
                self.bot.send_message(
                    text=f"🎉 Correct! {player_name} has been awarded {award_value} points.",
                    chat_id=self.chat_id,
                    reply_to_message_id=answer_message_id,
                )
        else:
            _, wrong_users, rejected_before, beaten_to = result
            if answer_callback_query_id is not None:
                question_message = self.question_message_repository.find(
                    self.chat_id, self.message_id
                )
                base_message_text = QuestionAsker.generate_question_message_text(
                    question_message.question_data
                )
                message_text = f"{base_message_text}\n\n ❌ Disqualified: \n {','.join(wrong_users)}"

                callback_infos = json.loads(question_message.callback_infos_json)
                keyboard: List[List[InlineKeyboardButton]] = []
                for callback_info in callback_infos:
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                callback_info["answer"],
                                callback_data=callback_info["callback_id"],
                            )
                        ]
                    )
                if not beaten_to:
                    if not rejected_before:
                        self.bot.edit_message_text(
                            text=message_text,
                            parse_mode="HTML",
                            message_id=self.message_id,
                            chat_id=self.chat_id,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                        )
                        self.bot.answer_callback_query(
                            text="❌ Wrong :(",
                            callback_query_id=answer_callback_query_id,
                        )
                    else:
                        self.bot.answer_callback_query(
                            text="You already chose the wrong answer!",
                            callback_query_id=answer_callback_query_id,
                        )
                else:
                    self.bot.answer_callback_query(
                        text="Oops! Someone beat you to it!",
                        callback_query_id=answer_callback_query_id,
                    )

        return correct


class QuestionResponderFactory:
    @pinject.inject()
    def __init__(
        self,
        bot: Bot,
        sfn_client: SFNClient,
        score_repository: ScoreRepository,
        callback_repository: CallbackRepository,
        question_message_repository: QuestionMessageRepository,
        lock_client: DynamoDBLockClient,
    ):
        self.bot = bot
        self.sfn_client = sfn_client
        self.score_repository = score_repository
        self.callback_repository = callback_repository
        self.question_message_repository = question_message_repository
        self.lock_client = lock_client

    def create(self, chat_id: str, message_id: str) -> QuestionResponder:
        return QuestionResponder(
            chat_id=chat_id,
            message_id=message_id,
            bot=self.bot,
            sfn_client=self.sfn_client,
            score_repository=self.score_repository,
            callback_repository=self.callback_repository,
            question_message_repository=self.question_message_repository,
            lock_client=self.lock_client,
        )


class GameMaster:
    def __init__(
        self,
        chat_id: str,
        bot: Bot,
        table: Table,
        sfn_client: SFNClient,
        state_machine_arn: str,
        lock_client: DynamoDBLockClient,
        score_repository: ScoreRepository,
        callback_repository: CallbackRepository,
        game_info_repository: GameInfoRepository,
        question_message_repository: QuestionMessageRepository,
    ):
        self.chat_id = chat_id
        self.bot = bot
        self.table = table
        self.sfn_client = sfn_client
        self.state_machine_arn = state_machine_arn
        self.lock_client = lock_client
        self.score_repository = score_repository
        self.callback_repository = callback_repository
        self.game_info_repository = game_info_repository
        self.question_message_repository = question_message_repository

    def start_game(self, trigger_message_id: str = None):
        gamestate_lock_name = f"chat.{self.chat_id}.gamestate"
        with self.lock_client.acquire_lock(
            gamestate_lock_name, raise_context_exception=True
        ):
            current_game_state = self.game_info_repository.get(self.chat_id)
            if current_game_state.game_state == GameInfo.GameState.RUNNING:
                self.bot.send_message(
                    text="A game is already in progress!",
                    reply_to_message_id=trigger_message_id,
                    chat_id=self.chat_id,
                )
                return
            elif current_game_state.game_state == GameInfo.GameState.CLEANING_UP:
                self.bot.send_message(
                    text="Cleaning up the last game session, please wait a few seconds before trying again",
                    chat_id=self.chat_id,
                    reply_to_message_id=trigger_message_id,
                )
                return
            else:
                current_game_state.game_state = GameInfo.GameState.RUNNING
                self.bot.send_message(text="Starting game!", chat_id=self.chat_id)
                response = self.sfn_client.start_execution(
                    stateMachineArn=self.state_machine_arn,
                    input=json.dumps({"chat_id": self.chat_id}),
                )
                current_game_state.step_function_execution_arn = response[
                    "executionArn"
                ]
                self.game_info_repository.put(current_game_state)

    def end_game(self):
        gamestate_lock_name = f"chat.{self.chat_id}.gamestate"
        with self.lock_client.acquire_lock(
            gamestate_lock_name, raise_context_exception=True
        ):
            current_game_info = self.game_info_repository.get(self.chat_id)
            if current_game_info.game_state != GameInfo.GameState.RUNNING:
                raise ValueError("Game is not running")
            # decide winners
            self.announce_winners()
            self.question_message_repository.cleanup_questions(chat_id=self.chat_id)
            self.score_repository.commit_to_global_scoreboard(chat_id=self.chat_id)
            self.callback_repository.delete(chat_id=self.chat_id)
            # update game state
            current_game_info.game_state = GameInfo.GameState.IDLE
            current_game_info.step_function_execution_arn = None
            self.game_info_repository.put(current_game_info)
            # say goodbye
            self.bot.send_message(
                text="Thank you for playing. Please contribute trivia questions on our github if you can! It's as simple as editing a Python file. https://github.com/OpenSUTD/sutd-trivia-bot",
                chat_id=self.chat_id,
            )

    def force_end_game(self, trigger_message_id: str):
        gamestate_lock_name = f"chat.{self.chat_id}.gamestate"
        with self.lock_client.acquire_lock(
            gamestate_lock_name, raise_context_exception=True
        ):
            current_game_info = self.game_info_repository.get(self.chat_id)
            if current_game_info.game_state != GameInfo.GameState.RUNNING:
                self.bot.send_message(
                    text="No game in progress!",
                    reply_to_message_id=trigger_message_id,
                    chat_id=self.chat_id,
                )
                return
            # terminate existing step functions
            self.sfn_client.stop_execution(
                executionArn=current_game_info.step_function_execution_arn
            )
            # terminate question step function
            current_active_question = self.question_message_repository.get_current_active_question(
                chat_id=self.chat_id
            )
            if current_active_question is not None:
                current_question_step_function_execution_arn = (
                    current_active_question.step_function_execution_arn
                )
                self.sfn_client.stop_execution(
                    executionArn=current_question_step_function_execution_arn,
                    error="GameEnded",
                    cause="The user requested the game to end early",
                )
            # decide winners
            self.announce_winners()
            self.question_message_repository.cleanup_questions(chat_id=self.chat_id)
            self.score_repository.commit_to_global_scoreboard(chat_id=self.chat_id)
            self.callback_repository.delete(chat_id=self.chat_id)
            # update game state
            current_game_info.game_state = GameInfo.GameState.IDLE
            current_game_info.step_function_execution_arn = None
            self.game_info_repository.put(current_game_info)

    def announce_winners(self):
        players = self.score_repository.get_local_top_players(
            chat_id=self.chat_id, count=10
        )
        message_lines = ["Game has ended. Congratulations to the winners!\n"]
        for i, player in enumerate(players):
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
        self.bot.send_message(text="\n".join(message_lines), chat_id=self.chat_id)


class GameMasterFactory:
    @pinject.inject()
    def __init__(
        self,
        bot: Bot,
        table: Table,
        sfn_client: SFNClient,
        state_machine_arn: str,
        lock_client: DynamoDBLockClient,
        score_repository: ScoreRepository,
        callback_repository: CallbackRepository,
        game_info_repository: GameInfoRepository,
        question_message_repository: QuestionMessageRepository,
    ):
        self.bot = bot
        self.table = table
        self.sfn_client = sfn_client
        self.state_machine_arn = state_machine_arn
        self.lock_client = lock_client
        self.score_repository = score_repository
        self.callback_repository = callback_repository
        self.game_info_repository = game_info_repository
        self.question_message_repository = question_message_repository

    def create(self, chat_id: str) -> GameMaster:
        return GameMaster(
            chat_id=chat_id,
            bot=self.bot,
            table=self.table,
            sfn_client=self.sfn_client,
            state_machine_arn=self.state_machine_arn,
            lock_client=self.lock_client,
            score_repository=self.score_repository,
            callback_repository=self.callback_repository,
            game_info_repository=self.game_info_repository,
            question_message_repository=self.question_message_repository,
        )
