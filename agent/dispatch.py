"""
Shared outbound-call dispatch logic.

Used by both scripts/make_call.py (CLI, for your own testing) and
server/app.py (the password-gated web trigger). Kept deliberately separate
from agent/main.py — this only needs livekit.api (lightweight), not the
full livekit.agents + Sarvam plugin stack that the actual voice worker
process needs, so the web service that imports this stays thin.
"""

import os
import re
import uuid

from livekit import api

PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")

REQUIRED_ENV_VARS = (
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "LIVEKIT_SIP_TRUNK_ID",
)


class DispatchError(RuntimeError):
    """Raised when the phone number is invalid, config is missing, or
    dispatching the agent / placing the SIP call fails."""


def normalize_phone_number(raw: str) -> str:
    """Normalize to E.164 (e.g. '+919876543210'). Raises DispatchError if
    what's left after stripping formatting doesn't look like a real number
    with a country code."""
    cleaned = re.sub(r"[^\d+]", "", raw or "")
    if cleaned and not cleaned.startswith("+"):
        cleaned = f"+{cleaned}"
    if not PHONE_RE.match(cleaned):
        raise DispatchError(
            "Enter a valid phone number with country code, e.g. +919876543210"
        )
    return cleaned


async def dispatch_call(phone_number: str, wait_until_answered: bool = True) -> dict:
    """
    Dispatch the agent into a fresh LiveKit room and dial phone_number via
    the configured Twilio/LiveKit SIP trunk.

    The agent worker (`python -m agent.main start` / `dev`) must already be
    running and registered as "elevatebox-sales-agent", or the dispatch
    will succeed but nothing will answer the room.

    Returns {"room_name": str, "participant_identity": str}.
    """
    phone_number = normalize_phone_number(phone_number)

    missing = [key for key in REQUIRED_ENV_VARS if not os.getenv(key)]
    if missing:
        raise DispatchError(f"Missing required environment variables: {', '.join(missing)}")

    livekit_api = api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )

    room_name = f"call-{uuid.uuid4().hex[:8]}"
    trunk_id = os.environ["LIVEKIT_SIP_TRUNK_ID"]

    try:
        await livekit_api.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name="elevatebox-sales-agent",
                room=room_name,
                metadata=phone_number,
            )
        )

        participant = await livekit_api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=trunk_id,
                sip_call_to=phone_number,
                room_name=room_name,
                participant_identity=f"caller-{phone_number}",
                participant_name="Customer",
                wait_until_answered=wait_until_answered,
            )
        )
    except DispatchError:
        raise
    except Exception as exc:
        raise DispatchError(f"Failed to place call: {exc}") from exc
    finally:
        await livekit_api.aclose()

    return {"room_name": room_name, "participant_identity": participant.participant_identity}
