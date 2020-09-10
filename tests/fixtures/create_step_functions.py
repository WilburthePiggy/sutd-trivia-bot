import boto3

sf = boto3.client("stepfunctions", endpoint_url="http://localhost:8083")

f1 = open("quizzer/quiz_flow/statemachine.asl.json")

def1 = f1.read()

sf.create_state_machine(
    name="quiz_flow",
    definition=f1.read(),
    roleArn="arn:aws:iam::012345678901:role/DummyRole",
)

f1.close()

f2 = open("quizzer/open_flow/statemachine.asl.json")

sf.create_state_machine(
    name="open_flow",
    definition=f2.read(),
    roleArn="arn:aws:iam::012345678901:role/DummyRole",
)
