"""
Places the actual outbound call from the command line (for your own testing).

The number to call defaults to TARGET_PHONE_NUMBER from .env, but you can
override it on the command line:

    python scripts/make_call.py
    python scripts/make_call.py +917658975169

IMPORTANT: the agent worker (python -m agent.main dev) must already be
running and connected before you run this script, or there will be nothing
to dispatch into the room.

For the on-demand web trigger (any caller enters a number + password in a
browser), see server/app.py instead — both share the same dispatch logic in
agent/dispatch.py.
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

from agent.dispatch import DispatchError, dispatch_call

load_dotenv()


async def main():
    phone_number = sys.argv[1] if len(sys.argv) > 1 else os.environ["TARGET_PHONE_NUMBER"]

    print(f"Dispatching agent and dialing {phone_number}...")
    try:
        result = await dispatch_call(phone_number, wait_until_answered=True)
    except DispatchError as exc:
        print(f"\n❌ {exc}")
        raise SystemExit(1)

    print(f"\n✅ Call placed. Participant: {result['participant_identity']}")
    print(f"   Room: {result['room_name']}")
    print("   Watch the agent worker's console output for live call logs.\n")


if __name__ == "__main__":
    asyncio.run(main())
