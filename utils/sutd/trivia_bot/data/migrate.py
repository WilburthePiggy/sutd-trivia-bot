import pinject

from sutd.trivia_bot.common.models import Question
from sutd.trivia_bot.common.database import QuestionRepository
from sutd.trivia_bot.common.bindings import ALL_BINDINGS
from sutd.trivia_bot.data.mcq import questions as mcq_questions
from sutd.trivia_bot.data.open import questions as open_questions


if __name__ == "__main__":
    OBJ_GRAPH = pinject.new_object_graph(modules=None, binding_specs=ALL_BINDINGS)
    question_repository: QuestionRepository = OBJ_GRAPH.provide(QuestionRepository)

    # delete all questions
    question_repository.truncate()

    for i, mcq_question in enumerate(mcq_questions):
        if "question" not in mcq_question:
            raise ValueError(f"question attribute missing in index {i}")
        if "correct_answer" not in mcq_question:
            raise ValueError(f"correct_answer attribute missing in index {i}")
        if "wrong_answers" not in mcq_question:
            raise ValueError(f"wrong_answers attribute missing in index {i}")
        question = Question(
            id=f"mcq_{i}",
            question=mcq_question["question"],
            correct_answer=mcq_question["correct_answer"].lower(),
            other_answers=[a.lower() for a in mcq_question["wrong_answers"]],
            type=Question.QuestionType.mcq,
        )
        question_repository.create(question)

    for i, open_question in enumerate(open_questions):
        if "question" not in open_question:
            raise ValueError(f"question attribute missing in index {i}")
        if "answer" not in open_question:
            raise ValueError(f"answer attribute missing in index {i}")
        question = Question(
            id=f"open_{i}",
            question=open_question["question"],
            correct_answer=open_question["answer"].lower(),
            type=Question.QuestionType.open,
        )
        question_repository.create(question)
    print(f"Successfully created {len(mcq_questions) + len(open_questions)} questions")
