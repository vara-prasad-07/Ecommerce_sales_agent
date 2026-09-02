"""
One-time setup script: creates a LiveKit outbound SIP trunk backed by your
Twilio number, so the agent can dial out via CreateSIPParticipant.

Run this ONCE before your first outbound call:
    python scripts/setup_sip_trunk.py

It prints a LIVEKIT_SIP_TRUNK_ID — paste that into your .env file.

Prerequisites (must already be done in the Twilio console, this script does
NOT do this part for you):
  1. Buy/have a Twilio phone number.
  2. Create an Elastic SIP Trunk in Twilio (Twilio Console -> Elastic SIP
     Trunking -> Trunks -> Create new Trunk).
  3. Under that trunk's "Termination" settings, note the Termination SIP
     URI (looks like yourtrunk.pstn.twilio.com).
  4. Under "Credential Lists", create a credential list with a
     username/password (use the same values you put in .env as
     SIP_TRUNK_USERNAME / SIP_TRUNK_PASSWORD) and attach it to the trunk.
  5. Under "Origination", you do NOT need an origination URI for outbound-
     only calling from LiveKit -> Twilio -> PSTN.
  6. Assign your Twilio phone number to the trunk.
"""

import asyncio
import os

from dotenv import load_dotenv
from livekit import api

load_dotenv()


async def main():
    livekit_api = api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )

    twilio_number = os.environ["TWILIO_PHONE_NUMBER"]
    sip_username = os.environ["SIP_TRUNK_USERNAME"]
    sip_password = os.environ["SIP_TRUNK_PASSWORD"]

    # Twilio's generic termination domain pattern for Elastic SIP Trunking.
    # Replace with your exact Termination SIP URI from the Twilio console
    # if it differs (Console -> Elastic SIP Trunking -> your trunk -> General).
    twilio_termination_uri = os.environ.get(
        "TWILIO_TERMINATION_URI", "your-trunk-name.pstn.twilio.com"
    )

    trunk = api.SIPOutboundTrunkInfo(
        name="ElevateBox Outbound Trunk",
        address=twilio_termination_uri,
        destination_country="IN",
        numbers=[twilio_number],
        auth_username=sip_username,
        auth_password=sip_password,
    )

    request = api.CreateSIPOutboundTrunkRequest(trunk=trunk)
    created = await livekit_api.sip.create_sip_outbound_trunk(request)

    print("\n✅ Outbound SIP trunk created successfully.\n")
    print(f"   Trunk ID: {created.sip_trunk_id}")
    print("\nAdd this to your .env file:\n")
    print(f"   LIVEKIT_SIP_TRUNK_ID={created.sip_trunk_id}\n")

    await livekit_api.aclose()


if __name__ == "__main__":
    asyncio.run(main())
