from datetime import datetime
from typing import Optional, List, Union, Dict
from enum import Enum

from pydantic import BaseModel, Json


class Question(BaseModel):
    class Config:
        extra = "ignore"

    class QuestionType(str, Enum):
        open = "open"
        mcq = "mcq"

    id: str
    type: QuestionType
    correct_answer: str
    question: str
    other_answers: Optional[List[str]] = None


class QuestionMessage(BaseModel):
    message_id: str
    chat_id: str
    question_id: str
    question_data: Question
    sent_at: datetime
    callback_infos_json: Optional[str] = None
    solved_at: Optional[datetime] = None
    step_function_execution_arn: Optional[str] = None

    class Config:
        extra = "ignore"
        json_encoders = {
            datetime: lambda v: int(v.timestamp()),
        }


class GameInfo(BaseModel):
    class Config:
        extra = "ignore"

    class GameState(Enum):
        IDLE = "IDLE"
        RUNNING = "RUNNING"
        CLEANING_UP = "CLEANING_UP"

    step_function_execution_arn: Optional[str] = None
    chat_id: str
    game_state: GameState


class Player(BaseModel):
    user_id: str
    score: int
    user_data: Dict

    class Config:
        extra = "ignore"
