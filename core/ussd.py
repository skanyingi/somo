"""
USSD menu logic, kept as plain functions so they can be unit tested
without going through Django's request/response cycle.

`text` is the raw chain Africa's Talking sends: each input the user has
entered so far, joined with '*'. Example: user dials in, sees the main
menu, types 1, then types 2 -> text == "1*2".
"""

import math

from django.conf import settings
from django.utils import timezone

from . import services
from .models import Learner, Lesson, QuizAttempt, Subject
from .phone import normalize_phone

FEEDBACK_LABELS = {1: "easy", 2: "ok", 3: "hard"}
REWARD_THRESHOLD_RATIO = 2 / 3

MAIN_MENU = (
    "CON Welcome to Somo\n"
    "1. Register\n"
    "2. My subjects\n"
    "3. Help"
)

INVALID_CHOICE = "Invalid choice.\n"


def handle_ussd(phone_number, text):
    """Return the full USSD response string, starting with CON or END."""
    text = (text or "").strip()
    levels = text.split("*") if text else []

    if not levels:
        return MAIN_MENU

    first_choice = levels[0]

    if first_choice == "1":
        return _handle_register(phone_number, levels[1:])
    if first_choice == "2":
        return _handle_subjects(phone_number, levels[1:])
    if first_choice == "3":
        return _handle_help()

    return "CON " + INVALID_CHOICE + MAIN_MENU[4:]


def _handle_help():
    return (
        "END Somo delivers lessons and quizzes by SMS and USSD.\n"
        "Dial in again anytime to register or pick a subject."
    )


def _handle_register(phone_number, inputs):
    normalized_phone = normalize_phone(phone_number)

    if normalized_phone and Learner.objects.filter(phone=normalized_phone).exists():
        learner = Learner.objects.get(phone=normalized_phone)
        return (
            f"END You are already registered as {learner.name}. "
            "Dial in again and choose 'My subjects' to continue."
        )

    if len(inputs) == 0:
        return "CON Enter your name:"

    name = inputs[0].strip()
    if not name:
        return "CON Name cannot be empty.\nEnter your name:"

    if len(inputs) == 1:
        return "CON Enter your class/level (e.g. Grade 6):"

    level = inputs[1].strip()
    if not level:
        return "CON Level cannot be empty.\nEnter your class/level (e.g. Grade 6):"

    if len(inputs) == 2:
        return "CON Enter a parent/guardian phone number, or 0 to skip:"

    parent_input = inputs[2].strip()

    if len(inputs) == 3:
        parent_phone = None
        if parent_input != "0":
            parent_phone = normalize_phone(parent_input)
            if not parent_phone:
                return (
                    "END That parent phone number doesn't look valid. "
                    "Please dial in again and try once more."
                )

        if not normalized_phone:
            return "END We couldn't read your phone number. Please dial in again."

        Learner.objects.create(
            phone=normalized_phone,
            name=name,
            level=level,
            parent_phone=parent_phone,
        )
        return (
            "END Registration successful! Dial in again and choose "
            "'My subjects' to continue."
        )

    return "END Something went wrong with registration. Please dial in again."


def _handle_subjects(phone_number, inputs):
    normalized_phone = normalize_phone(phone_number)
    learner = Learner.objects.filter(phone=normalized_phone).first() if normalized_phone else None

    if not learner:
        return "END You are not registered yet. Please dial in and choose 'Register' first."

    subjects = list(Subject.objects.order_by("name"))
    if not subjects:
        return "END No subjects are available yet. Please check back later."

    menu = "CON Pick a subject:\n" + "\n".join(
        f"{i}. {subject.name}" for i, subject in enumerate(subjects, start=1)
    )

    if len(inputs) == 0:
        return menu

    choice = inputs[0].strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(subjects)):
        return "CON " + INVALID_CHOICE + menu[4:]

    subject = subjects[int(choice) - 1]
    return _handle_quiz(learner, subject, inputs[1:])


def _send_lesson_sms(learner, lesson):
    message = f"{lesson.title}\n{lesson.get_content()}"
    services.send_sms(learner.phone, message)


def _select_quiz_questions(lesson):
    """Prefer a full set of generated questions; fall back to manual ones."""
    generated = list(lesson.questions.filter(is_generated=True).order_by("id"))
    if len(generated) >= 3:
        return generated[:3]

    manual = list(lesson.questions.filter(is_generated=False).order_by("id"))
    if manual:
        return manual[:3]

    return generated[:3]


def _handle_quiz(learner, subject, inputs):
    lesson = Lesson.objects.filter(subject=subject).order_by("-created_at").first()
    if not lesson:
        return f"END No lesson is available for {subject.name} yet. Please check back later."

    questions = _select_quiz_questions(lesson)
    if not questions:
        return f"END No quiz is available for {subject.name} yet. Please check back later."

    if not inputs:
        _send_lesson_sms(learner, lesson)

    total_questions = len(questions)
    quiz_answers, feedback, last_invalid = _parse_quiz_progress(inputs, total_questions)

    if len(quiz_answers) < total_questions:
        question_number = len(quiz_answers) + 1
        question = questions[question_number - 1]
        prompt = (
            f"Q{question_number}/{total_questions}: {question.text}\n"
            f"1. {question.choice_1}\n"
            f"2. {question.choice_2}\n"
            f"3. {question.choice_3}\n"
            f"4. {question.choice_4}"
        )
        if last_invalid:
            return "CON " + INVALID_CHOICE + prompt
        return "CON " + prompt

    if feedback is None:
        prompt = "Was this lesson:\n1. Easy\n2. OK\n3. Hard"
        if last_invalid:
            return "CON " + INVALID_CHOICE + prompt
        return "CON " + prompt

    score = sum(
        1 for answer, question in zip(quiz_answers, questions) if answer == question.correct_choice
    )
    threshold = math.ceil(total_questions * REWARD_THRESHOLD_RATIO)
    reward_eligible = score >= threshold

    attempt = QuizAttempt.objects.create(
        learner=learner,
        lesson=lesson,
        score=score,
        total_questions=total_questions,
        reward_paid=False,
        feedback=FEEDBACK_LABELS[feedback],
        completed_at=timezone.now(),
    )

    result_line = f"You scored {score}/{total_questions}."

    if reward_eligible:
        reward_paid = _pay_quiz_reward(attempt, learner)
        if reward_paid:
            result_line += (
                f" You've earned {settings.AIRTIME_REWARD_AMOUNT:g} "
                f"{settings.AIRTIME_CURRENCY_CODE} airtime!"
            )
        else:
            result_line += (
                " You qualified for an airtime reward, but we couldn't send it "
                "right now. We'll retry it for you."
            )
    else:
        result_line += " Keep practicing and try again!"

    return f"END {result_line}"


def _pay_quiz_reward(attempt, learner):
    """
    Pay the airtime reward for a QuizAttempt exactly once. `reward_paid` is
    only ever set True after a confirmed successful send, so a failed send
    can be retried later without risking a double payment.
    """
    if attempt.reward_paid:
        return True

    success = services.send_airtime(
        learner.phone,
        idempotency_key=f"quiz-attempt-{attempt.id}",
    )
    if success:
        attempt.reward_paid = True
        attempt.save(update_fields=["reward_paid"])

    return success


def _parse_quiz_progress(inputs, total_questions):
    """
    Walk through every input the learner has entered after picking a subject.
    Only syntactically valid answers advance the quiz/feedback position, so an
    invalid entry re-prompts the same question instead of crashing or skipping.
    """
    quiz_answers = []
    feedback = None
    last_invalid = False

    for raw in inputs:
        value = raw.strip()
        if len(quiz_answers) < total_questions:
            if value.isdigit() and 1 <= int(value) <= 4:
                quiz_answers.append(int(value))
                last_invalid = False
            else:
                last_invalid = True
        elif feedback is None:
            if value.isdigit() and 1 <= int(value) <= 3:
                feedback = int(value)
                last_invalid = False
            else:
                last_invalid = True
        else:
            last_invalid = False

    return quiz_answers, feedback, last_invalid
