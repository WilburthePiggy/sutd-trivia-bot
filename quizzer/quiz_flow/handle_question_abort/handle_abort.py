import json

import boto3

sfn_client = boto3.client("stepfunctions")


def lambda_handler(event, context):
    cause = json.loads(event["Cause"])
    execution_arn = cause["ExecutionArn"]

    # sfn_client
