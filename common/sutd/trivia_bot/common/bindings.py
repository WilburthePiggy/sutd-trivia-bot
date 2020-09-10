import os
import boto3

from telegram import Bot
from python_dynamodb_lock.python_dynamodb_lock import DynamoDBLockClient
import pinject


class TelegramBotBinding(pinject.BindingSpec):
    def provide_token(self):
        return os.environ["BOT_TOKEN"]

    def provide_bot(self):
        return Bot(token=self.provide_token())


class DynamoDBBinding(pinject.BindingSpec):
    def provide_table(self):
        return boto3.resource(
            "dynamodb", endpoint_url=os.environ.get("DDB_ENDPOINT")
        ).Table(os.environ["TABLE_NAME"])


class LockClientBinding(pinject.BindingSpec):
    def provide_lock_client(self):
        resource = boto3.resource(
            "dynamodb", endpoint_url=os.environ.get("DDB_ENDPOINT")
        )
        return DynamoDBLockClient(resource, table_name=os.environ["LOCK_TABLE_NAME"])


class StateMachineBindings(pinject.BindingSpec):
    def provide_sfn_client(self):
        return boto3.client(
            "stepfunctions", endpoint_url=os.environ.get("SFN_ENDPOINT")
        )

    def provide_state_machine_arn(self):
        return os.environ["START_GAME_STATE_MACHINE_ARN"]


class IDKBindings(pinject.BindingSpec):
    def configure(self, bind):
        bind("game_master_factory")


ALL_BINDINGS = [
    TelegramBotBinding(),
    DynamoDBBinding(),
    LockClientBinding(),
    StateMachineBindings(),
]
