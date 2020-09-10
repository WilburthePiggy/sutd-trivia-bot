from __future__ import annotations

import string
import random
import json
import logging


from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
import pinject

from sutd.trivia_bot.common.models import Question, QuestionMessage, GameInfo, Player

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, List, Tuple, Union, Set, Iterable
    from mypy_boto3_dynamodb.service_resource import Table

logger = logging.getLogger()


class QuestionRepository:
    def __init__(self, table: Table):
        self.table = table

    def create(self, question: Question):
        self.table.put_item(
            Item={"pk": "TRIVIA", "sk": f"QUESTION#{question.id}", **question.dict()}
        )
        self.table.update_item(
            Key={"pk": "TRIVIA", "sk": "SUMMARY"},
            UpdateExpression="ADD question_ids :q",
            ExpressionAttributeValues={":q": {question.id}},
        )

    def find(self, question_id: int) -> Question:
        response = self.table.get_item(
            Key={"pk": "TRIVIA", "sk": f"QUESTION#{question_id}"}
        )
        return Question(**response["Item"])

    def list_ids(self) -> Iterable[str]:
        response = self.table.get_item(Key={"pk": "TRIVIA", "sk": "SUMMARY"})
        return response["Item"]["question_ids"]

    def truncate(self):
        with self.table.batch_writer() as batch:
            # noinspection PyTypeChecker
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq("TRIVIA"),
                ProjectionExpression="pk, sk",
            )
            for item in response.get("Items", []):
                batch.delete_item(Key=item)


class QuestionMessageRepository:
    def __init__(self, table: Table):
        self.table = table

    def create(self, question_message: QuestionMessage):
        if question_message.step_function_execution_arn is None:
            raise ValueError(
                "Step Function Execution ARN must not be None when creating new QuestionMessage"
            )
        self.table.put_item(
            Item={
                "pk": f"CHAT#{question_message.chat_id}",
                "sk": f"MESSAGE#{question_message.message_id}",
                **json.loads(question_message.json(exclude_none=True)),
                "gsi_current_active_question": question_message.step_function_execution_arn,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )

    def attempt(
        self,
        chat_id: str,
        message_id: str,
        answer: str,
        answer_time: int,
        user_display_name: str,
        no_retries: bool,
    ) -> Union[Tuple[bool, int, str], Tuple[bool, Set[str], bool]]:
        try:
            no_retry_condition_clause = (
                "AND (attribute_not_exists(wrong_users) OR NOT contains(wrong_users, :user_display_name))"
                if no_retries
                else ""
            )
            response = self.table.update_item(
                Key={"pk": f"CHAT#{chat_id}", "sk": f"MESSAGE#{message_id}",},
                UpdateExpression="SET solved_at = :answer_time REMOVE step_function_execution_arn, gsi_current_active_question",
                ConditionExpression=f"question_data.correct_answer = :attempted_answer AND attribute_not_exists(solved_at) {no_retry_condition_clause}",
                ExpressionAttributeValues={
                    ":answer_time": int(answer_time),
                    ":attempted_answer": answer.lower(),
                    **(
                        {":user_display_name": user_display_name}
                        if no_retries
                        else dict()
                    ),
                },
                ReturnValues="ALL_OLD",
            )
            return (
                True,
                int(answer_time - response["Attributes"]["sent_at"]),
                response["Attributes"]["question_data"]["correct_answer"],
            )
        except ClientError as ex:
            if ex.response["Error"]["Code"] == "ConditionalCheckFailedException":
                # wrong answer
                response = self.table.update_item(
                    Key={"pk": f"CHAT#{chat_id}", "sk": f"MESSAGE#{message_id}",},
                    UpdateExpression="ADD wrong_users :w",
                    ExpressionAttributeValues={":w": {user_display_name}},
                    ReturnValues="ALL_OLD",
                )
                if "Attributes" not in response:
                    logging.warn("For some reason, attributes are epty")
                return (
                    False,
                    {user_display_name}.union(
                        response.get("Attributes", dict()).get("wrong_users", {})
                    ),
                    user_display_name
                    in response.get("Attributes", dict()).get("wrong_users", {}),
                )
            else:
                raise ex

    def mark_as_inactive(self, chat_id: str, message_id: str):
        self.table.update_item(
            Key={"pk": f"CHAT#{chat_id}", "sk": f"MESSAGE#{message_id}"},
            UpdateExpression="REMOVE step_function_execution_arn, gsi_current_active_question",
            ConditionExpression="attribute_not_exists(solved_at)",
        )

    def find(self, chat_id: str, message_id: str) -> Optional[QuestionMessage]:
        response = self.table.get_item(
            Key={"pk": f"CHAT#{chat_id}", "sk": f"MESSAGE#{message_id}"}
        )
        if response.get("Item") is None:
            return None
        return QuestionMessage(**response["Item"])

    def get_questions_in_group(self, chat_id: str) -> List[QuestionMessage]:
        response = self.table.query(
            KeyConditionExpression=Key("pk").eq(f"CHAT#{chat_id}")
            & Key("sk").begins_with("MESSAGE#")
        )
        return [QuestionMessage(**item) for item in response.get("Items", [])]

    def get_current_active_question(self, chat_id: str) -> Optional[QuestionMessage]:
        response = self.table.query(
            IndexName="CurrentActiveQuestion",
            KeyConditionExpression=Key("pk").eq(f"CHAT#{chat_id}"),
            Limit=1,
        )
        if len(response.get("Items")) == 0:
            return None
        return QuestionMessage(**response["Items"][0])

    def cleanup_questions(self, chat_id: str):
        with self.table.batch_writer() as batch:
            # noinspection PyTypeChecker
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq(f"CHAT#{chat_id}")
                & Key("sk").begins_with("MESSAGE#"),
                ProjectionExpression="pk, sk",
            )
            for item in response.get("Items", []):
                batch.delete_item(Key=item)


class ScoreRepository:
    def __init__(self, table: Table):
        self.table = table

    def award_points(
        self, chat_id: str, user_id: str, award_points: int, user_data: dict
    ) -> int:
        response = self.table.update_item(
            Key={"pk": f"CHAT#{chat_id}", "sk": f"SCORE#{user_id}"},
            UpdateExpression="SET score = if_not_exists(score, :zero) + :award_points, user_data = :user_data, user_id = :user_id",
            ExpressionAttributeValues={
                ":zero": 0,
                ":award_points": int(award_points),
                ":user_data": user_data,
                ":user_id": user_id,
            },
            ReturnValues="ALL_NEW",
        )
        return response["Attributes"]["score"]

    def commit_to_global_scoreboard(self, chat_id: str):
        response = self.table.query(
            IndexName="ScoreBoard",
            KeyConditionExpression=Key("pk").eq(f"CHAT#{chat_id}"),
        )
        if response.get("Items") is None:
            return
        players = [Player(**item) for item in response["Items"]]
        for player in players:
            self.table.update_item(
                Key={"pk": "GLOBAL_SCORE", "sk": player.user_id},
                UpdateExpression="SET score = if_not_exists(score, :zero) + :award_points, user_data = :user_data, user_id = :user_id",
                ExpressionAttributeValues={
                    ":zero": 0,
                    ":award_points": int(player.score),
                    ":user_data": player.user_data,
                    ":user_id": player.user_id,
                },
            )
        with self.table.batch_writer() as batch:
            # noinspection PyTypeChecker
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq(f"CHAT#{chat_id}")
                & Key("sk").begins_with("SCORE#"),
                ProjectionExpression="pk, sk",
            )
            for item in response.get("Items", []):
                batch.delete_item(Key=item)

    def get_local_top_players(self, chat_id: str, count: int = 3) -> List[Player]:
        response = self.table.query(
            IndexName="ScoreBoard",
            KeyConditionExpression=Key("pk").eq(f"CHAT#{chat_id}"),
            Limit=count,
            ScanIndexForward=True,
        )
        if response.get("Items") is None:
            return []
        return [Player(**item) for item in response["Items"]]

    def get_global_top_players(self, count: int = 3) -> List[Player]:
        response = self.table.query(
            IndexName="ScoreBoard",
            KeyConditionExpression=Key("pk").eq("GLOBAL_SCORE"),
            Limit=count,
            ScanIndexForward=True,
        )
        if response.get("Items") is None:
            return []
        return [Player(**item) for item in response["Items"]]


class CallbackRepository:
    def __init__(self, table: Table):
        self.table = table

    def __validate_value(self, key: str, value):
        if type(value) is float:
            raise TypeError(f"Float not supported, use Decimal! At {key}")
        if type(value) not in (str, int, bool):
            raise TypeError(f"Unexpected type at {key}")

    def __validate_list(self, key: str, data: list):
        for i, value in enumerate(data):
            self.__validate_value(key=str(i), value=value)

    def __validate_dict(self, key: str, data: dict):
        for k, value in data.items():
            _key = f"{key}.{k}"
            if type(value) is dict:
                self.__validate_dict(key=_key, data=value)
            elif type(value) is list:
                self.__validate_list(key=_key, data=value)
            else:
                self.__validate_value(key=_key, value=value)

    def __validate_item(self, data: dict):
        self.__validate_dict(key="", data=data)

    def create(self, chat_id: str, callback_data: dict) -> str:
        self.__validate_item(callback_data)
        callback_id = "".join([random.choice(string.ascii_letters) for _ in range(64)])
        callback_data["callback_id"] = callback_id
        try:
            self.table.put_item(
                Item={
                    "pk": f"CALLBACK#{chat_id}",
                    "sk": callback_id,
                    "callback_info": callback_data,
                    "gsi_callback_question_id": callback_data["question_id"],
                },
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return self.create(chat_id, callback_data)
            else:
                raise e
        return callback_id

    def retrieve(self, callback_id: str, chat_id: str) -> Optional[dict]:
        response = self.table.get_item(
            Key={"pk": f"CALLBACK#{chat_id}", "sk": callback_id}
        )
        if response.get("Item") is None:
            return None
        return response["Item"]["callback_info"]

    def find_by_question_id(self, chat_id: str, question_id: str) -> List[dict]:
        response = self.table.query(
            IndexName="CallbacksByQuestionId",
            KeyConditionExpression=Key("pk").eq(f"CALLBACK#{chat_id}")
            & Key("sk").eq(question_id),
        )

        return [item["callback_info"] for item in response["Items"]]

    def delete_by_question_id(self, chat_id: str, question_id: str):
        with self.table.batch_writer() as batch:
            # noinspection PyTypeChecker
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq(f"CALLBACK#{chat_id}"),
                ProjectionExpression="pk, sk",
                FilterExpression="callback_data.question_id = :question_id",
                ExpressionAttributeValues={":question_id": question_id},
            )
            for item in response.get("Items", []):
                batch.delete_item(Key=item)

    def delete(self, chat_id: str):
        with self.table.batch_writer() as batch:
            # noinspection PyTypeChecker
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq(f"CALLBACK#{chat_id}"),
                ProjectionExpression="pk, sk",
            )
            for item in response.get("Items", []):
                batch.delete_item(Key=item)


class GameInfoRepository:
    def __init__(self, table: Table):
        self.table = table

    def get(self, chat_id: str) -> GameInfo:
        response = self.table.get_item(Key={"pk": f"CHAT#{chat_id}", "sk": "GAMEINFO"})
        if response.get("Item") is None:
            return GameInfo(chat_id=chat_id, game_state=GameInfo.GameState.IDLE)
        return GameInfo(**response["Item"],)

    def put(self, game_info: GameInfo):
        response = self.table.put_item(
            Item={
                "pk": f"CHAT#{game_info.chat_id}",
                "sk": "GAMEINFO",
                **json.loads(game_info.json(exclude_none=True)),
            }
        )
