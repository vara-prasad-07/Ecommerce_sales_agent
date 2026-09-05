"""Twilio WhatsApp template messaging service.

This module keeps the original call lifecycle and trigger points in
agent/main.py unchanged, but swaps the underlying WhatsApp transport to the
Twilio Python SDK and template-based messages.
"""

import json
import logging
import os
import re

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

logger = logging.getLogger("whatsapp")

MID_CALL_TEMPLATE_SID = "HX4ef21c8a141b2fa28574d5c1a4e7e31d"  # Utility-approved (was Marketing, silently throttled by Meta — see error 63049)
POST_CALL_TEMPLATE_SID = "HX2f327669489ed03af33a064ca3485999"


def _fmt_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if len(digits) == 10:
        return f"+91 {digits}"
    if len(digits) > 10 and digits.startswith("91"):
        return f"+{digits[:2]} {digits[2:]}"
    return f"+{digits}"


def _recipient_whatsapp_number(call_phone_number: str = "") -> str:
    """Prefer the number actually dialed for this call (passed in from the
    job that placed it — e.g. the number typed into the "Call me now" form)
    so the WhatsApp follow-up reaches the same person who was called. Falls
    back to the fixed env vars only when no per-call number is known, which
    keeps the old default-recipient behavior for manual/dev runs."""
    recipient = (call_phone_number or "").strip()
    if not recipient or recipient.lower() == "unknown":
        recipient = (os.getenv("WHATSAPP_RECIPIENT_NUMBER") or "").strip()
    if not recipient:
        recipient = (os.getenv("TARGET_PHONE_NUMBER") or "").strip()
    if not recipient:
        return ""
    if recipient.startswith("whatsapp:"):
        return recipient
    if not recipient.startswith("+"):
        recipient = f"+{recipient}"
    return f"whatsapp:{recipient}"


def _from_whatsapp_number() -> str:
    value = (os.getenv("TWILIO_WHATSAPP_FROM") or "").strip()
    if not value:
        raise ValueError("TWILIO_WHATSAPP_FROM is not set")
    if value.startswith("whatsapp:"):
        return value
    return f"whatsapp:{value}"


def _client() -> Client:
    account_sid = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
    auth_token = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
    if not account_sid or not auth_token:
        raise ValueError("Missing Twilio credentials: TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN")
    return Client(account_sid, auth_token)


def _safe_env(key: str, default: str = "") -> str:
    value = (os.getenv(key) or default).strip()
    return value


def _template_variable(value: str, fallback: str = "") -> str:
    """Keep dynamic WhatsApp template values single-line and normalized."""
    cleaned = re.sub(r"\s+", " ", (value or "")).strip()
    return cleaned or fallback


CLASSIFICATION_LABELS = {
    "hot": "Hot lead — high buying intent",
    "warm": "Warm lead — interested, working through a barrier",
    "cold": "Cold lead — just exploring",
}

MID_CALL_TONE_LABELS = {
    "hot": "High buying intent right now.",
    "cold": "Low intent for now — sending a quick info note to keep the door open.",
}


def _build_post_call_summary(call_context_paragraph: str, classification: str) -> str:
    """Variable 2: a short classification tag. The real conversation detail
    goes into variable 3 (see `_build_template_2_intro`) so it isn't lost."""
    _ = call_context_paragraph
    return CLASSIFICATION_LABELS.get(
        (classification or "").lower().strip(), "Thanks for taking the call"
    )


def _build_template_3_context(call_context_paragraph: str, caller_name: str = "") -> str:
    """Variable 3: the call context, personally addressed when we captured
    the caller's name during the call — this is what makes the follow-up
    read like a real person wrote it, not a log pasted into WhatsApp."""
    context = _template_variable(call_context_paragraph, "")
    name = (caller_name or "").strip()
    if name and context:
        return f"Hi {name}! {context}"
    if name:
        return f"Hi {name}!"
    return context


async def _send_template(content_sid: str, variables: dict, to: str, from_: str) -> str:
    try:
        client = _client()
        message = client.messages.create(
            content_sid=content_sid,
            from_=from_,
            to=to,
            content_variables=json.dumps(variables),
        )
        logger.info(
            "Twilio WhatsApp template accepted (sid=%s, status=%s, content_sid=%s, to=%s)",
            getattr(message, "sid", "unknown"),
            getattr(message, "status", "unknown"),
            content_sid,
            to,
        )
        return getattr(message, "sid", "")
    except TwilioRestException as exc:
        logger.exception(
            "Twilio WhatsApp template failed (content_sid=%s, status=%s, code=%s)",
            content_sid,
            getattr(exc, "status", None),
            getattr(exc, "code", None),
        )
        raise
    except ValueError:
        logger.exception("Twilio WhatsApp template failed because environment config is missing")
        raise
    except Exception:
        logger.exception("Unexpected Twilio WhatsApp template failure")
        raise


def _mid_call_template_message(context: str, tone: str, caller_name: str = "") -> str:
    cleaned_context = _template_variable(
        context,
        "We had a good conversation about the project.",
    )
    label = MID_CALL_TONE_LABELS.get(tone, "")
    body = f"{label} {cleaned_context}".strip() if label else cleaned_context
    name = (caller_name or "").strip()
    return f"Hi {name}! {body}" if name else body


def _callback_template_message(context: str, confirmation: str, caller_name: str = "") -> str:
    cleaned_context = _template_variable(
        context,
        "We had a good initial conversation about building an e-commerce site.",
    )
    closing = (
        f"I'll send you the follow-up details right here on WhatsApp, and I'll call you back {confirmation}."
        if confirmation
        else "I'll send you the follow-up details right here on WhatsApp, and call you back soon."
    )
    body = f"{cleaned_context} {closing}".strip()
    name = (caller_name or "").strip()
    return f"Hi {name}! {body}" if name else body


async def send_callback_confirmation(
    context: str, confirmation: str, caller_name: str = "", call_phone_number: str = ""
) -> bool:
    """Send the template-1 (mid-call) WhatsApp confirming a just-booked callback.

    Uses the same content template as the Hot/Cold mid-call send, but is not
    gated on discovery being complete — a caller who says "I don't have time,
    call me later" may bail out before discovery finishes, and they should
    still get the "I'll send follow-up details" confirmation promised on the
    call.
    """
    to = _recipient_whatsapp_number(call_phone_number)
    if not to:
        logger.warning("Skipping callback WhatsApp: WHATSAPP_RECIPIENT_NUMBER is empty")
        return False

    your_name = _template_variable(_safe_env("YOUR_NAME", "Vara Prasad"), "Vara Prasad")
    your_phone = _fmt_phone(_safe_env("YOUR_PHONE_NUMBER"))
    try:
        from_ = _from_whatsapp_number()
        payload = {
            "1": your_name,
            "2": _callback_template_message(context, confirmation, caller_name),
            "3": _template_variable(your_phone, "+91 7658975169"),
        }
        await _send_template(MID_CALL_TEMPLATE_SID, payload, to, from_)
        return True
    except Exception:
        logger.exception("Callback WhatsApp send failed")
        return False


async def send_mid_call_message(
    context: str, tone: str, caller_name: str = "", call_phone_number: str = ""
) -> bool:
    """Send the template-based mid-call WhatsApp follow-up while the call is live."""
    to = _recipient_whatsapp_number(call_phone_number)
    if not to:
        logger.warning("Skipping mid-call WhatsApp: WHATSAPP_RECIPIENT_NUMBER is empty")
        return False

    your_name = _template_variable(_safe_env("YOUR_NAME", "Vara Prasad"), "Vara Prasad")
    your_phone = _fmt_phone(_safe_env("YOUR_PHONE_NUMBER"))
    try:
        from_ = _from_whatsapp_number()
        payload = {
            "1": your_name,
            "2": _mid_call_template_message(context, tone.lower().strip(), caller_name),
            "3": _template_variable(your_phone, "+91 7658975169"),
        }
        await _send_template(MID_CALL_TEMPLATE_SID, payload, to, from_)
        return True
    except Exception:
        logger.exception("Mid-call WhatsApp send failed")
        return False


async def send_post_call_summary(
    call_context_paragraph: str,
    classification: str,
    caller_name: str = "",
    call_phone_number: str = "",
) -> bool:
    """Send the template-based post-call WhatsApp summary after the call ends."""
    to = _recipient_whatsapp_number(call_phone_number)
    if not to:
        logger.warning("Skipping post-call WhatsApp: WHATSAPP_RECIPIENT_NUMBER is empty")
        return False

    your_name = _safe_env("YOUR_NAME", "Vara Prasad")
    your_phone = _fmt_phone(_safe_env("YOUR_PHONE_NUMBER"))
    resume_url = _safe_env("RESUME_PUBLIC_URL")
    diagram_url = _safe_env("ARCHITECTURE_DIAGRAM_URL")

    if not resume_url:
        logger.warning("RESUME_PUBLIC_URL not set — template variable 5 will be blank")
    if not diagram_url:
        logger.warning("ARCHITECTURE_DIAGRAM_URL not set — template variable 6 will be blank")

    try:
        from_ = _from_whatsapp_number()
        payload = {
            "1": your_name,
            "2": _build_post_call_summary(call_context_paragraph, classification),
            "3": _build_template_3_context(call_context_paragraph, caller_name),
            "4": _template_variable(your_phone, "+91 7658975169"),
            "5": _template_variable(resume_url, ""),
            "6": _template_variable(diagram_url, ""),
        }
        await _send_template(POST_CALL_TEMPLATE_SID, payload, to, from_)
        return True
    except Exception:
        logger.exception("Post-call WhatsApp send failed")
        return False
