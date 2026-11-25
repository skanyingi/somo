"""
All Africa's Talking API calls live here, and nowhere else, so they can be
mocked in tests without hitting the network.
"""

import logging

import africastalking
from django.conf import settings

logger = logging.getLogger(__name__)

SMS_MAX_SEGMENT_LENGTH = 160
_SMS_PREFIX_RESERVED = 10  # room for a "(1/9) " style part marker

_initialized = False


def _ensure_initialized():
    global _initialized
    if not _initialized:
        africastalking.initialize(settings.AFRICASTALKING_USERNAME, settings.AFRICASTALKING_API_KEY)
        _initialized = True


def _get_sms_client():
    _ensure_initialized()
    return africastalking.SMS


def _get_airtime_client():
    _ensure_initialized()
    return africastalking.Airtime


def split_message(text, max_length=SMS_MAX_SEGMENT_LENGTH):
    """
    Split long text into SMS-sized parts. Short text is returned as a single
    part, unprefixed. Longer text is split on word boundaries (never mid-word
    unless a single "word" itself exceeds the budget) and each part is
    prefixed with "(n/total) " so learners can follow a multi-part lesson.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_length:
        return [text]

    budget = max(max_length - _SMS_PREFIX_RESERVED, 20)
    chunks = []
    current = ""

    for word in text.split():
        while len(word) > budget:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(word[:budget])
            word = word[budget:]

        candidate = f"{current} {word}".strip()
        if len(candidate) > budget:
            if current:
                chunks.append(current)
            current = word
        else:
            current = candidate

    if current:
        chunks.append(current)

    total = len(chunks)
    return [f"({i}/{total}) {chunk}" for i, chunk in enumerate(chunks, start=1)]


def send_sms(phone_numbers, message):
    """
    Send an SMS, splitting into multiple parts if needed. Never raises: a
    failed or partially failed send is logged and reported via the return
    value, so a flaky SMS gateway can't crash a USSD request.
    """
    if isinstance(phone_numbers, str):
        phone_numbers = [phone_numbers]

    parts = split_message(message)
    if not parts:
        return False

    client = _get_sms_client()
    all_succeeded = True

    for part in parts:
        try:
            response = client.send(part, phone_numbers)
            logger.info("SMS sent to %s: %s", phone_numbers, response)
        except Exception:
            logger.exception("Failed to send SMS part to %s", phone_numbers)
            all_succeeded = False

    return all_succeeded


def send_airtime(phone_number, amount=None, currency_code=None, idempotency_key=None):
    """
    Send an airtime reward to a single phone number. Never raises: failures
    are logged and reported via the return value (False), so the caller can
    decide not to mark a reward as paid without crashing the USSD request.
    An idempotency_key (e.g. derived from the QuizAttempt id) lets Africa's
    Talking de-duplicate retries of the exact same reward on their end.
    """
    amount = settings.AIRTIME_REWARD_AMOUNT if amount is None else amount
    currency_code = currency_code or settings.AIRTIME_CURRENCY_CODE

    client = _get_airtime_client()
    try:
        response = client.send(
            phone_number=phone_number,
            amount=amount,
            currency_code=currency_code,
            idempotency_key=idempotency_key,
        )
        logger.info("Airtime sent to %s: %s", phone_number, response)
        return True
    except Exception:
        logger.exception("Failed to send airtime to %s", phone_number)
        return False
