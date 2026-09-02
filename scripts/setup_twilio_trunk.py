"""
Optional helper: creates the Twilio-side Elastic SIP Trunk and attaches your
phone number + credential list automatically, using the Twilio Python SDK.

You can do this by hand in the Twilio console instead if you prefer — this
script just saves the clicking.

Run BEFORE scripts/setup_sip_trunk.py:
    python scripts/setup_twilio_trunk.py

It prints the Termination SIP URI — put that in .env as
TWILIO_TERMINATION_URI before running scripts/setup_sip_trunk.py.
"""

import os

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()


def main():
    account_sid = os.environ["TWILIO_ACCOUNT_SID"]
    auth_token = os.environ["TWILIO_AUTH_TOKEN"]
    twilio_number = os.environ["TWILIO_PHONE_NUMBER"]
    sip_username = os.environ["SIP_TRUNK_USERNAME"]
    sip_password = os.environ["SIP_TRUNK_PASSWORD"]

    client = Client(account_sid, auth_token)

    # 1. Create the trunk
    trunk = client.trunking.v1.trunks.create(friendly_name="ElevateBox-LiveKit-Trunk")
    print(f"Created Twilio trunk: {trunk.sid}")

    # 2. Create a credential list for LiveKit -> Twilio auth
    cred_list = client.sip.v1.credential_lists.create(
        friendly_name="elevatebox-livekit-creds"
    )
    client.sip.v1.credential_lists(cred_list.sid).credentials.create(
        username=sip_username, password=sip_password
    )
    print(f"Created credential list: {cred_list.sid}")

    # 3. Attach the credential list to the trunk (for origination auth —
    #    i.e. Twilio accepting calls FROM LiveKit)
    client.trunking.v1.trunks(trunk.sid).credentials_lists.create(
        credential_list_sid=cred_list.sid
    )

    # 4. Point an Origination URL at... wait, for OUTBOUND (LiveKit dials
    #    out through Twilio to the PSTN), what we actually need is for
    #    Twilio to accept the call as an ORIGINATION into the trunk, then
    #    Twilio terminates it to the real phone number. So: attach the
    #    Twilio number to the trunk, and note the trunk's termination URI.
    numbers = client.incoming_phone_numbers.list(phone_number=twilio_number)
    if not numbers:
        raise RuntimeError(
            f"Could not find {twilio_number} in this Twilio account's "
            "incoming phone numbers. Buy it first, or check the number format."
        )
    phone_number_sid = numbers[0].sid
    client.trunking.v1.trunks(trunk.sid).phone_numbers.create(
        phone_number_sid=phone_number_sid
    )
    print(f"Attached {twilio_number} to trunk.")

    termination_uri = f"{trunk.friendly_name.lower().replace('_', '-')}-{trunk.sid[-8:]}.pstn.twilio.com"
    # Twilio actually assigns the domain — fetch it back to be sure:
    trunk_fetched = client.trunking.v1.trunks(trunk.sid).fetch()
    print(f"\n✅ Twilio trunk ready.")
    print(f"   Termination SIP URI: {trunk_fetched.domain_name}")
    print("\nAdd this to your .env file:\n")
    print(f"   TWILIO_TERMINATION_URI={trunk_fetched.domain_name}\n")
    print("Now run: python scripts/setup_sip_trunk.py")


if __name__ == "__main__":
    main()
