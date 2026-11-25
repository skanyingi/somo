from unittest.mock import patch

from django.test import Client, TestCase

from . import services
from .models import Learner, Lesson, Question, QuizAttempt, Subject
from .phone import normalize_phone
from .ussd import _pay_quiz_reward, handle_ussd


class PhoneNormalizationTests(TestCase):
    def test_already_normalized_number_is_unchanged(self):
        self.assertEqual(normalize_phone("+254700000001"), "+254700000001")

    def test_254_prefix_without_plus_is_fixed(self):
        self.assertEqual(normalize_phone("254700000001"), "+254700000001")

    def test_leading_zero_is_converted(self):
        self.assertEqual(normalize_phone("0700000001"), "+254700000001")

    def test_bare_subscriber_number_is_converted(self):
        self.assertEqual(normalize_phone("700000001"), "+254700000001")

    def test_number_with_spaces_is_cleaned(self):
        self.assertEqual(normalize_phone("0700 000 001"), "+254700000001")

    def test_garbage_input_returns_none(self):
        self.assertIsNone(normalize_phone("not-a-number"))

    def test_empty_input_returns_none(self):
        self.assertIsNone(normalize_phone(""))
        self.assertIsNone(normalize_phone(None))


class UssdMenuLogicTests(TestCase):
    """Unit tests for handle_ussd, with no HTTP involved."""

    def test_empty_text_shows_main_menu(self):
        response = handle_ussd("+254700000001", "")
        self.assertTrue(response.startswith("CON "))
        self.assertIn("1. Register", response)
        self.assertIn("2. My subjects", response)
        self.assertIn("3. Help", response)

    def test_help_choice_returns_help_text_and_ends(self):
        response = handle_ussd("+254700000001", "3")
        self.assertTrue(response.startswith("END "))
        self.assertIn("Somo", response)

    def test_invalid_top_level_choice_reprompts_with_main_menu(self):
        response = handle_ussd("+254700000001", "9")
        self.assertTrue(response.startswith("CON "))
        self.assertIn("Invalid choice", response)
        self.assertIn("1. Register", response)

    def test_invalid_choice_does_not_crash_on_garbage_input(self):
        response = handle_ussd("+254700000001", "abc")
        self.assertTrue(response.startswith("CON "))
        self.assertIn("Invalid choice", response)


class RegistrationFlowTests(TestCase):
    def test_register_prompts_for_name_first(self):
        response = handle_ussd("+254711000001", "1")
        self.assertEqual(response, "CON Enter your name:")

    def test_register_prompts_for_level_after_name(self):
        response = handle_ussd("+254711000001", "1*Jane Doe")
        self.assertEqual(response, "CON Enter your class/level (e.g. Grade 6):")

    def test_register_prompts_for_parent_phone_after_level(self):
        response = handle_ussd("+254711000001", "1*Jane Doe*Grade 6")
        self.assertEqual(response, "CON Enter a parent/guardian phone number, or 0 to skip:")

    def test_register_completes_and_creates_learner_with_parent(self):
        response = handle_ussd("+254711000001", "1*Jane Doe*Grade 6*0711999999")
        self.assertTrue(response.startswith("END Registration successful"))

        learner = Learner.objects.get(phone="+254711000001")
        self.assertEqual(learner.name, "Jane Doe")
        self.assertEqual(learner.level, "Grade 6")
        self.assertEqual(learner.parent_phone, "+254711999999")

    def test_register_completes_without_parent_when_skipped(self):
        response = handle_ussd("+254711000002", "1*John Doe*Grade 7*0")
        self.assertTrue(response.startswith("END Registration successful"))

        learner = Learner.objects.get(phone="+254711000002")
        self.assertIsNone(learner.parent_phone)

    def test_register_rejects_invalid_parent_phone(self):
        response = handle_ussd("+254711000003", "1*Jane Doe*Grade 6*notanumber")
        self.assertTrue(response.startswith("END "))
        self.assertIn("doesn't look valid", response)
        self.assertFalse(Learner.objects.filter(phone="+254711000003").exists())

    def test_already_registered_learner_is_told_so(self):
        Learner.objects.create(phone="+254711000004", name="Existing", level="Grade 5")
        response = handle_ussd("+254711000004", "1")
        self.assertTrue(response.startswith("END "))
        self.assertIn("already registered", response)
        self.assertIn("Existing", response)

    def test_already_registered_learner_is_not_duplicated(self):
        Learner.objects.create(phone="+254711000005", name="Existing", level="Grade 5")
        handle_ussd("+254711000005", "1*Someone Else*Grade 1*0")
        self.assertEqual(Learner.objects.filter(phone="+254711000005").count(), 1)


class SubjectSelectionTests(TestCase):
    def setUp(self):
        self.maths = Subject.objects.create(name="Mathematics")
        self.english = Subject.objects.create(name="English")
        self.learner = Learner.objects.create(
            phone="+254722000001", name="Registered Learner", level="Grade 6"
        )

    def test_unregistered_number_cannot_browse_subjects(self):
        response = handle_ussd("+254722999999", "2")
        self.assertTrue(response.startswith("END "))
        self.assertIn("not registered", response)

    def test_registered_learner_sees_subject_list(self):
        response = handle_ussd("+254722000001", "2")
        self.assertTrue(response.startswith("CON "))
        self.assertIn("Pick a subject", response)
        self.assertIn("English", response)
        self.assertIn("Mathematics", response)

    def test_valid_subject_choice_with_no_lesson_ends_gracefully(self):
        response = handle_ussd("+254722000001", "2*1")
        self.assertTrue(response.startswith("END "))
        self.assertIn("No lesson is available", response)

    def test_invalid_subject_choice_reprompts(self):
        response = handle_ussd("+254722000001", "2*9")
        self.assertTrue(response.startswith("CON "))
        self.assertIn("Invalid choice", response)
        self.assertIn("Pick a subject", response)

    def test_no_subjects_available_ends_gracefully(self):
        Subject.objects.all().delete()
        response = handle_ussd("+254722000001", "2")
        self.assertTrue(response.startswith("END "))
        self.assertIn("No subjects", response)


class QuizFlowTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Mathematics")
        self.other_subject = Subject.objects.create(name="English")
        self.lesson = Lesson.objects.create(
            subject=self.subject, title="Fractions", manual_content="Fractions are parts of a whole."
        )
        self.questions = [
            Question.objects.create(
                lesson=self.lesson,
                text="Q1?",
                choice_1="A", choice_2="B", choice_3="C", choice_4="D",
                correct_choice=1,
            ),
            Question.objects.create(
                lesson=self.lesson,
                text="Q2?",
                choice_1="A", choice_2="B", choice_3="C", choice_4="D",
                correct_choice=2,
            ),
            Question.objects.create(
                lesson=self.lesson,
                text="Q3?",
                choice_1="A", choice_2="B", choice_3="C", choice_4="D",
                correct_choice=3,
            ),
        ]
        self.learner = Learner.objects.create(
            phone="+254744000001", name="Quiz Learner", level="Grade 6"
        )
        self.phone = "+254744000001"

        sms_patcher = patch("core.ussd.services.send_sms")
        self.mock_send_sms = sms_patcher.start()
        self.addCleanup(sms_patcher.stop)

        airtime_patcher = patch("core.ussd.services.send_airtime")
        self.mock_send_airtime = airtime_patcher.start()
        self.mock_send_airtime.return_value = True
        self.addCleanup(airtime_patcher.stop)

    def _subjects_menu_index(self, subject):
        names = list(Subject.objects.order_by("name").values_list("name", flat=True))
        return names.index(subject.name) + 1

    def test_first_question_is_shown_after_subject_choice(self):
        idx = self._subjects_menu_index(self.subject)
        response = handle_ussd(self.phone, f"2*{idx}")
        self.assertTrue(response.startswith("CON "))
        self.assertIn("Q1/3", response)

    def test_second_question_is_shown_after_first_answer(self):
        idx = self._subjects_menu_index(self.subject)
        response = handle_ussd(self.phone, f"2*{idx}*1")
        self.assertTrue(response.startswith("CON "))
        self.assertIn("Q2/3", response)

    def test_invalid_answer_reprompts_same_question(self):
        idx = self._subjects_menu_index(self.subject)
        response = handle_ussd(self.phone, f"2*{idx}*9")
        self.assertTrue(response.startswith("CON "))
        self.assertIn("Invalid choice", response)
        self.assertIn("Q1/3", response)

    def test_feedback_question_shown_after_all_answers(self):
        idx = self._subjects_menu_index(self.subject)
        response = handle_ussd(self.phone, f"2*{idx}*1*2*3")
        self.assertTrue(response.startswith("CON "))
        self.assertIn("Was this lesson", response)

    def test_invalid_feedback_reprompts_feedback_question(self):
        idx = self._subjects_menu_index(self.subject)
        response = handle_ussd(self.phone, f"2*{idx}*1*2*3*9")
        self.assertTrue(response.startswith("CON "))
        self.assertIn("Invalid choice", response)
        self.assertIn("Was this lesson", response)

    def test_perfect_score_pays_reward_and_saves_attempt(self):
        idx = self._subjects_menu_index(self.subject)
        response = handle_ussd(self.phone, f"2*{idx}*1*2*3*1")
        self.assertTrue(response.startswith("END "))
        self.assertIn("3/3", response)
        self.assertIn("airtime", response)

        attempt = QuizAttempt.objects.get(learner=self.learner)
        self.assertEqual(attempt.score, 3)
        self.assertEqual(attempt.total_questions, 3)
        self.assertEqual(attempt.feedback, "easy")
        self.assertTrue(attempt.reward_paid)

        self.mock_send_airtime.assert_called_once_with(
            self.phone, idempotency_key=f"quiz-attempt-{attempt.id}"
        )

    def test_low_score_ends_without_reward_and_without_airtime_call(self):
        idx = self._subjects_menu_index(self.subject)
        # All wrong answers (correct choices are 1, 2, 3)
        response = handle_ussd(self.phone, f"2*{idx}*4*4*4*2")
        self.assertTrue(response.startswith("END "))
        self.assertIn("0/3", response)
        self.assertIn("Keep practicing", response)

        attempt = QuizAttempt.objects.get(learner=self.learner)
        self.assertEqual(attempt.score, 0)
        self.assertEqual(attempt.feedback, "ok")
        self.assertFalse(attempt.reward_paid)
        self.mock_send_airtime.assert_not_called()

    def test_reward_not_marked_paid_when_airtime_send_fails(self):
        self.mock_send_airtime.return_value = False
        idx = self._subjects_menu_index(self.subject)
        response = handle_ussd(self.phone, f"2*{idx}*1*2*3*1")
        self.assertTrue(response.startswith("END "))
        self.assertIn("couldn't send it", response)

        attempt = QuizAttempt.objects.get(learner=self.learner)
        self.assertFalse(attempt.reward_paid)
        self.mock_send_airtime.assert_called_once()

    def test_already_paid_attempt_is_never_paid_twice(self):
        idx = self._subjects_menu_index(self.subject)
        handle_ussd(self.phone, f"2*{idx}*1*2*3*1")
        attempt = QuizAttempt.objects.get(learner=self.learner)
        self.assertTrue(attempt.reward_paid)
        self.mock_send_airtime.assert_called_once()

        # Calling the reward helper again for the same (already paid) attempt
        # must short-circuit without sending a second airtime request.
        result = _pay_quiz_reward(attempt, self.learner)
        self.assertTrue(result)
        self.mock_send_airtime.assert_called_once()


    def test_abandoned_quiz_never_creates_a_quiz_attempt(self):
        idx = self._subjects_menu_index(self.subject)
        handle_ussd(self.phone, f"2*{idx}")
        handle_ussd(self.phone, f"2*{idx}*1")
        self.assertEqual(QuizAttempt.objects.filter(learner=self.learner).count(), 0)

    def test_subject_with_no_lesson_ends_gracefully(self):
        idx = self._subjects_menu_index(self.other_subject)
        response = handle_ussd(self.phone, f"2*{idx}")
        self.assertTrue(response.startswith("END "))
        self.assertIn("No lesson is available", response)

    def test_subject_with_lesson_but_no_questions_ends_gracefully(self):
        Lesson.objects.create(subject=self.other_subject, title="Grammar", manual_content="...")
        idx = self._subjects_menu_index(self.other_subject)
        response = handle_ussd(self.phone, f"2*{idx}")
        self.assertTrue(response.startswith("END "))
        self.assertIn("No quiz is available", response)

    def test_lesson_sms_is_sent_once_on_fresh_subject_pick(self):
        idx = self._subjects_menu_index(self.subject)
        handle_ussd(self.phone, f"2*{idx}")
        self.mock_send_sms.assert_called_once()
        phone_arg, message_arg = self.mock_send_sms.call_args[0]
        self.assertEqual(phone_arg, self.phone)
        self.assertIn(self.lesson.title, message_arg)
        self.assertIn(self.lesson.get_content(), message_arg)

    def test_lesson_sms_is_not_resent_on_subsequent_answers(self):
        idx = self._subjects_menu_index(self.subject)
        handle_ussd(self.phone, f"2*{idx}")
        handle_ussd(self.phone, f"2*{idx}*1")
        handle_ussd(self.phone, f"2*{idx}*1*2")
        self.mock_send_sms.assert_called_once()

    def test_lesson_sms_not_sent_when_lesson_missing(self):
        idx = self._subjects_menu_index(self.other_subject)
        handle_ussd(self.phone, f"2*{idx}")
        self.mock_send_sms.assert_not_called()


class AirtimeServiceTests(TestCase):
    @patch("core.services._get_airtime_client")
    def test_send_airtime_uses_configured_defaults(self, mock_get_client):
        mock_client = mock_get_client.return_value
        result = services.send_airtime("+254700000001")
        self.assertTrue(result)
        mock_client.send.assert_called_once_with(
            phone_number="+254700000001",
            amount=10.0,
            currency_code="KES",
            idempotency_key=None,
        )

    @patch("core.services._get_airtime_client")
    def test_send_airtime_passes_through_idempotency_key(self, mock_get_client):
        mock_client = mock_get_client.return_value
        services.send_airtime("+254700000001", idempotency_key="quiz-attempt-42")
        mock_client.send.assert_called_once_with(
            phone_number="+254700000001",
            amount=10.0,
            currency_code="KES",
            idempotency_key="quiz-attempt-42",
        )

    @patch("core.services._get_airtime_client")
    def test_send_airtime_failure_is_caught_and_reported_false(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.send.side_effect = Exception("network error")
        result = services.send_airtime("+254700000001")
        self.assertFalse(result)


class SmsServiceTests(TestCase):
    def test_short_message_is_returned_as_single_unprefixed_part(self):
        parts = services.split_message("Short lesson text.")
        self.assertEqual(parts, ["Short lesson text."])

    def test_empty_message_returns_no_parts(self):
        self.assertEqual(services.split_message(""), [])
        self.assertEqual(services.split_message(None), [])

    def test_long_message_is_split_into_numbered_parts(self):
        long_text = "word " * 100
        parts = services.split_message(long_text, max_length=160)
        self.assertGreater(len(parts), 1)
        for i, part in enumerate(parts, start=1):
            self.assertTrue(part.startswith(f"({i}/{len(parts)}) "))
            self.assertLessEqual(len(part), 160)

    def test_split_never_breaks_a_word_unless_it_alone_exceeds_budget(self):
        long_text = "word " * 100
        parts = services.split_message(long_text, max_length=160)
        for part in parts:
            body = part.split(") ", 1)[1]
            for token in body.split():
                self.assertEqual(token, "word")

    def test_pathologically_long_single_token_is_hard_sliced(self):
        long_token = "a" * 500
        parts = services.split_message(long_token, max_length=160)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(len(part), 160)

    @patch("core.services._get_sms_client")
    def test_send_sms_calls_client_for_each_part(self, mock_get_client):
        mock_client = mock_get_client.return_value
        result = services.send_sms("+254700000001", "Short message")
        self.assertTrue(result)
        mock_client.send.assert_called_once_with("Short message", ["+254700000001"])

    @patch("core.services._get_sms_client")
    def test_send_sms_accepts_a_list_of_numbers(self, mock_get_client):
        mock_client = mock_get_client.return_value
        services.send_sms(["+254700000001", "+254700000002"], "Short message")
        mock_client.send.assert_called_once_with(
            "Short message", ["+254700000001", "+254700000002"]
        )

    @patch("core.services._get_sms_client")
    def test_send_sms_failure_is_caught_and_reported_false(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.send.side_effect = Exception("network error")
        result = services.send_sms("+254700000001", "Short message")
        self.assertFalse(result)

    @patch("core.services._get_sms_client")
    def test_send_sms_sends_every_part_of_a_long_message(self, mock_get_client):
        mock_client = mock_get_client.return_value
        long_text = "word " * 100
        services.send_sms("+254700000001", long_text)
        expected_parts = services.split_message(long_text)
        self.assertEqual(mock_client.send.call_count, len(expected_parts))


class UssdViewTests(TestCase):
    """HTTP-level tests hitting the /ussd/ endpoint directly."""

    def setUp(self):
        self.client = Client()

    def _post(self, text, phone="+254700000001"):
        return self.client.post(
            "/ussd/",
            {
                "sessionId": "test-session-1",
                "phoneNumber": phone,
                "serviceCode": "*384*1#",
                "text": text,
            },
        )

    def test_initial_dial_in_returns_main_menu(self):
        response = self._post("")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertTrue(response.content.decode().startswith("CON "))

    def test_help_selection_returns_end_response(self):
        response = self._post("3")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.decode().startswith("END "))

    def test_missing_text_field_defaults_to_main_menu(self):
        response = self.client.post(
            "/ussd/",
            {
                "sessionId": "test-session-2",
                "phoneNumber": "+254700000001",
                "serviceCode": "*384*1#",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.decode().startswith("CON "))

    def test_full_registration_over_http(self):
        response = self._post("1*Http Learner*Grade 4*0", phone="+254733000001")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.decode().startswith("END Registration successful"))
        self.assertTrue(Learner.objects.filter(phone="+254733000001").exists())
