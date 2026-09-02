"""
Places the actual outbound call.

This does two things:
  1. Explicitly dispatches the agent (elevatebox-sales-agent) into a fresh
     room.
  2. Creates a SIP participant in that room targeting the phone number,
     which causes LiveKit SIP to dial out via your Twilio trunk.

The number to call defaults to TARGET_PHONE_NUMBER from .env, but you can
override it on the command line:

    python scripts/make_call.py
    python scripts/make_call.py +917658975169

IMPORTANT: the agent worker (python -m agent.main dev) must already be
running and connected before you run this script, or there will be nothing
to dispatch into the room.
"""

import asyncio
import os
import sys
import uuid

from dotenv import load_dotenv
from livekit import api

load_dotenv()


async def main():
    phone_number = sys.argv[1] if len(sys.argv) > 1 else os.environ["TARGET_PHONE_NUMBER"]

    livekit_api = api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )

    room_name = f"call-{uuid.uuid4().hex[:8]}"
    trunk_id = os.environ["LIVEKIT_SIP_TRUNK_ID"]

    print(f"Dispatching agent into room '{room_name}'...")
    await livekit_api.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name="elevatebox-sales-agent",
            room=room_name,
            metadata=phone_number,  # passed through to ctx.job.metadata
        )
    )

    print(f"Dialing {phone_number} via SIP trunk {trunk_id}...")
    participant = await livekit_api.sip.create_sip_participant(
        api.CreateSIPParticipantRequest(
            sip_trunk_id=trunk_id,
            sip_call_to=phone_number,
            room_name=room_name,
            participant_identity=f"caller-{phone_number}",
            participant_name="Customer",
            wait_until_answered=True,
        )
    )

    print(f"\n✅ Call placed. Participant: {participant.participant_identity}")
    print(f"   Room: {room_name}")
    print("   Watch the agent worker's console output for live call logs.\n")

    await livekit_api.aclose()


if __name__ == "__main__":
    asyncio.run(main())
