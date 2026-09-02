"""
Run this before your first real call to catch config problems early —
much cheaper than discovering a typo mid-call.

    python scripts/preflight_check.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

REQUIRED_VARS = [
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "TWILIO_WHATSAPP_FROM",
    "LIVEKIT_SIP_TRUNK_ID",
    "SARVAM_API_KEY",
    "WHATSAPP_RECIPIENT_NUMBER",
    "YOUR_NAME",
    "YOUR_PHONE_NUMBER",
    "TARGET_PHONE_NUMBER",
]

RECOMMENDED_VARS = [
    "RESUME_PUBLIC_URL",
    "ARCHITECTURE_DIAGRAM_URL",
]


def check_env():
    missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
    missing_recommended = [v for v in RECOMMENDED_VARS if not os.getenv(v)]

    if missing:
        print("❌ Missing required environment variables:")
        for v in missing:
            print(f"   - {v}")
    else:
        print("✅ All required environment variables are set.")

    if missing_recommended:
        print("\n⚠️  Missing recommended variables (post-call WhatsApp will be incomplete):")
        for v in missing_recommended:
            print(f"   - {v}")

    return len(missing) == 0


async def check_whatsapp():
    from twilio.rest import Client

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_WHATSAPP_FROM")
    if not account_sid or not auth_token or not from_number:
        print("⏭️  Skipping Twilio WhatsApp check (missing credentials).")
        return

    try:
        client = Client(account_sid, auth_token)
        client.api.accounts(account_sid).fetch()
        print("✅ Twilio WhatsApp credentials look valid.")
    except Exception as e:
        print(f"❌ Twilio WhatsApp check errored: {e}")


async def check_livekit():
    from livekit import api

    try:
        lk = api.LiveKitAPI(
            url=os.environ["LIVEKIT_URL"],
            api_key=os.environ["LIVEKIT_API_KEY"],
            api_secret=os.environ["LIVEKIT_API_SECRET"],
        )
        trunks = await lk.sip.list_sip_outbound_trunk(api.ListSIPOutboundTrunkRequest())
        trunk_id = os.getenv("LIVEKIT_SIP_TRUNK_ID")
        found = any(t.sip_trunk_id == trunk_id for t in trunks.items)
        if found:
            print(f"✅ LiveKit SIP outbound trunk '{trunk_id}' found and reachable.")
        else:
            print(
                f"⚠️  Connected to LiveKit, but trunk ID '{trunk_id}' was not found. "
                "Did you run scripts/setup_sip_trunk.py and update .env?"
            )
        await lk.aclose()
    except Exception as e:
        print(f"❌ LiveKit API check errored: {e}")


async def main():
    print("Running preflight checks...\n")
    env_ok = check_env()
    print()
    await check_livekit()
    await check_whatsapp()

    print()
    if env_ok:
        print("You're good to try scripts/make_call.py — start the agent worker first.")
    else:
        print("Fix the missing variables above before making a real call.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
