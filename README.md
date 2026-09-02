# ElevateBox Voice Agent — Outbound Sales Call System

An AI voice agent that calls a number, pitches e-commerce website
development, discovers requirements naturally, classifies the lead as
Hot/Warm/Cold, fires a mid-call WhatsApp on high intent, books callbacks
from spoken time references, and sends a full post-call WhatsApp summary
with resume + architecture diagram.

Built for the ElevateBox SDE Intern assignment.

**Stack:** LiveKit Agents (self-hosted orchestration) + Sarvam AI (STT, TTS,
and the LLM decision engine — all via the LiveKit Sarvam plugin, chosen for
native Hindi/Telugu/English handling in one provider) + Twilio (SIP
trunk/number + WhatsApp sending).

---

## 1. What you need before starting

- A LiveKit Cloud project (free tier is fine) — https://cloud.livekit.io
- Twilio account with a phone number capable of outbound calling, plus a
  WhatsApp sender (sandbox number is fine for testing) and two approved
  WhatsApp Content Templates (mid-call + post-call — see `agent/whatsapp.py`
  for the template SIDs and variable contract)
- Sarvam AI API key (`SARVAM_API_KEY`) — used for STT, TTS, and the LLM
- Python 3.10+

---

## 2. Install

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in every value. See inline comments in `.env.example`
for what each one is and where to get it. Key ones people miss:

- `RESUME_PUBLIC_URL` and `ARCHITECTURE_DIAGRAM_URL` must be **public,
  direct-fetchable links** (WhatsApp's servers fetch these — a Google Drive
  "view" link with sharing set to "Anyone with the link" works if you use
  the direct-download format, or just host them anywhere public).
- `TARGET_PHONE_NUMBER` is already set to `+917658975169` (the assignment's
  number) in the example — leave it unless told otherwise.
- `SARVAM_API_KEY` is required for the real-time Sarvam STT/TTS pipeline.
- `WHATSAPP_RECIPIENT_NUMBER` is who receives BOTH the mid-call and
  post-call WhatsApp messages — also `917658975169` per the assignment.

---

## 4. One-time SIP trunk setup (Twilio ↔ LiveKit)

You only do this once. Two options:

**Option A — automated (recommended):**
```bash
python scripts/setup_twilio_trunk.py
# copy the printed TWILIO_TERMINATION_URI into .env
python scripts/setup_sip_trunk.py
# copy the printed LIVEKIT_SIP_TRUNK_ID into .env
```

**Option B — manual via Twilio console:** see the docstring at the top of
`scripts/setup_sip_trunk.py` for the exact console steps, if you'd rather
click through it yourself or the automated script hits a permissions issue.

---

## 5. Run the preflight check

Catches missing/bad credentials before you spend a real phone call finding
out something is misconfigured:

```bash
python scripts/preflight_check.py
```

Fix anything it flags before continuing.

---

## 6. Iterate on the conversation logic without spending call minutes

Before placing a real phone call, test the agent's brain — discovery
questions, classification behavior, tool firing — over plain text:

```bash
python scripts/test_conversation_text.py
```

Type as if you were the customer. This uses your real WhatsApp credentials
(so mid-call/post-call messages actually send) but skips voice entirely, so
it's free to iterate on and fast to run repeatedly. Use this to tune
`agent/prompts.py` until classification and discovery feel right.

---

## 7. Run the real voice agent

**Terminal 1 — start the agent worker** (keep this running):
```bash
python -m agent.main dev
```
Wait until you see it connect to LiveKit and register as
`elevatebox-sales-agent`.

**Terminal 2 — place the call:**
```bash
python scripts/make_call.py
# or override the number:
python scripts/make_call.py +917658975169
```

Watch Terminal 1 for live logs of the conversation, tool calls, and
classification decisions as the call happens.

---

## 7b. On-demand web trigger — call any number from a browser

Instead of running `scripts/make_call.py` yourself, `server/app.py` serves a
tiny password-gated web page: enter a phone number (with country code) and
the shared password, and it dispatches the exact same call as the script
above. This is what makes the prototype work "on demand" for someone who
isn't you and doesn't have this repo — they just need the URL and the
password.

It's a separate, lightweight process from the agent worker — it only talks
to the LiveKit API to kick off a call; it doesn't do any audio/STT/TTS/LLM
itself. **The agent worker (Terminal 1 above) must still be running** for a
triggered call to actually be answered.

Set a password in `.env` first:
```bash
CALL_TRIGGER_PASSWORD=pick-something-only-you-know
```

**Terminal 2 — run the web trigger** (instead of `make_call.py`):
```bash
uvicorn server.app:app --reload --port 8000
```
Open `http://localhost:8000`, enter a number and the password, click
**Call now**. A 30-second cooldown between triggers (configurable via
`MIN_SECONDS_BETWEEN_CALLS`) stops the password, once known, from being used
to spam calls. Every triggered call is logged to SQLite
(`call_triggers` table: number, requester IP, timestamp) for an audit trail.

---

## 8. What happens on a call

1. `make_call.py` dispatches the agent into a fresh LiveKit room and dials
   the target number via your Twilio SIP trunk.
2. When answered, the agent greets the person and pitches the service.
3. It asks about products, budget, timeline, and features naturally, and
   records each answer in English via `update_discovery` as it comes out —
   this is what both WhatsApp messages are built from, so it works the same
   whether the call happened in English, Hindi, or Telugu.
4. It continuously re-classifies the lead (Hot/Warm/Cold) as the
   conversation develops, logging reasoning each time.
5. Once at least 4 of the 5 discovery fields are captured and Hot or Cold
   intent is detected, it fires a WhatsApp message **immediately, without
   pausing the conversation** (`send_whatsapp_now`), built from the
   structured discovery data.
6. If the caller names a callback time, it's parsed and booked
   (`book_callback`), and confirmed back out loud.
7. Right before hanging up, it triggers the post-call summary
   (`end_call_summary`), which sends a WhatsApp message containing: the
   specific call context (from the same structured discovery data), your
   number, the architecture diagram image, and your resume as a document.

All call data (transcript, classification history, callbacks, WhatsApp
sends) is logged to a local SQLite file (`call_data.db` by default) for
debugging and for writing your submission note.

---

## 9. Project structure

```
elevatebox-voice-agent/
├── .env.example              # copy to .env and fill in
├── requirements.txt
├── Dockerfile                  # one image, used for both the worker and the web trigger
├── docker-compose.yml            # optional local two-container run
├── call_data.db               # created automatically on first run
├── agent/
│   ├── main.py                # LiveKit entrypoint, session setup, function tools
│   ├── dispatch.py             # shared call-dispatch logic (used by make_call.py + server/app.py)
│   ├── prompts.py                # the system prompt (persona/discovery/classification)
│   ├── storage.py                 # SQLite: calls, transcripts, discovery, classifications, callbacks
│   ├── whatsapp.py                 # Twilio WhatsApp template sender (mid-call + post-call)
│   └── scheduling.py                # natural-language time phrase -> datetime
├── server/
│   ├── app.py                # FastAPI: password-gated "call this number now" web trigger
│   └── static/index.html       # the trigger form
├── scripts/
│   ├── setup_twilio_trunk.py       # (optional) automates the Twilio-side trunk setup
│   ├── setup_sip_trunk.py           # creates the LiveKit outbound SIP trunk
│   ├── make_call.py                  # CLI: dispatches agent + dials a number
│   ├── preflight_check.py             # validates all credentials before a real call
│   └── test_conversation_text.py       # text-only debugging loop, no telephony cost
└── templates/
    └── architecture_diagram_prompt.md  # notes on the diagram you need to draw/create
```

---

## 10. Known limitations / what to mention in your submission note

- The time parser in `scheduling.py` is rule-based, not a full NLP date
  parser — it handles the common phrasings well ("tomorrow morning",
  "Thursday afternoon", "next week") but very unusual phrasing may fall
  back to a default (tomorrow, 10 AM IST) rather than failing outright.
- Language detection relies on Sarvam's `language="unknown"` STT mode plus
  the LLM naturally responding in-kind; this handles Indian-language
  code-mixing reasonably well, but very short utterances can still be
  misdetected if they are extremely noisy or clipped.
- `send_whatsapp_now` is fire-and-forget (`asyncio.create_task`), so if
  the WhatsApp API is slow or briefly down, the call continues regardless —
  the send result is logged to SQLite but not read back to the caller.
- No retry/backoff logic on WhatsApp sends — a single failure is logged,
  not retried. Fine for a demo, worth adding for production.
- Discovery completion (the gate for firing the mid-call WhatsApp) is
  tracked via a dedicated `update_discovery` tool the LLM calls after each
  answer, in English regardless of the call's language — this is what makes
  the mid-call action work reliably on Hindi/Telugu calls. If the LLM
  forgets to call it, there's an English-keyword fallback over the raw
  transcript (`_has_required_discovery` in `agent/main.py`), but that
  fallback only works for English-language calls.
- Both WhatsApp messages (mid-call and post-call) go through pre-approved
  Twilio Content Templates with a fixed number of variable slots — the real
  call context is injected into those slots at send time
  (`agent/whatsapp.py`), so if you change the approved template wording,
  double-check the variable mapping still matches.

---

## 11. Deploying to Azure

This app has two long-running processes that both need to be up at the same
time:

- **worker** (`python -m agent.main start`) — connects to LiveKit and stays
  registered as `elevatebox-sales-agent`, waiting to be dispatched. This is
  a persistent background worker, not a request/response web service.
- **web** (`uvicorn server.app:app`) — the password-gated trigger page from
  section 7b. A normal stateless web service.

**Azure Container Apps** is the best fit: it runs both as always-on
containers without you managing a VM, and it's cheap to scale the web app to
zero later if you want (the worker should stay at `min-replicas 1`, since it
has to be connected and ready to receive a dispatch at all times).

### One-time setup

```bash
az login
az group create --name elevatebox-rg --location centralindia

az acr create --resource-group elevatebox-rg --name elevateboxacr --sku Basic
az acr login --name elevateboxacr

az containerapp env create \
  --name elevatebox-env \
  --resource-group elevatebox-rg \
  --location centralindia
```

### Build and push the image

Run this from the repo root (where the `Dockerfile` is):
```bash
az acr build --registry elevateboxacr --image elevatebox-agent:latest .
```
`az acr build` builds in the cloud, so you don't need Docker installed
locally — but `docker build . && docker push` to the same ACR works too if
you already have Docker.

### Push your secrets once, reference them everywhere

Every value currently in your local `.env` needs to reach both containers.
Don't put real secrets in plain `--env-vars`; register them as Container
Apps secrets first, then reference them:

```bash
az containerapp env show --name elevatebox-env --resource-group elevatebox-rg \
  --query id -o tsv   # sanity check the env exists

# repeat --secrets for every var in .env.example (one command, many pairs):
SECRETS="livekit-url=$LIVEKIT_URL livekit-api-key=$LIVEKIT_API_KEY livekit-api-secret=$LIVEKIT_API_SECRET \
twilio-account-sid=$TWILIO_ACCOUNT_SID twilio-auth-token=$TWILIO_AUTH_TOKEN twilio-phone-number=$TWILIO_PHONE_NUMBER \
twilio-whatsapp-from=$TWILIO_WHATSAPP_FROM livekit-sip-trunk-id=$LIVEKIT_SIP_TRUNK_ID \
sarvam-api-key=$SARVAM_API_KEY whatsapp-recipient-number=$WHATSAPP_RECIPIENT_NUMBER \
your-name=$YOUR_NAME your-phone-number=$YOUR_PHONE_NUMBER resume-public-url=$RESUME_PUBLIC_URL \
architecture-diagram-url=$ARCHITECTURE_DIAGRAM_URL target-phone-number=$TARGET_PHONE_NUMBER \
call-trigger-password=$CALL_TRIGGER_PASSWORD"
```
(Source your local `.env` into your shell first — `set -a; source .env; set +a`
on macOS/Linux, or paste real values directly — then run the `az
containerapp create` commands below with `--secrets $SECRETS`.)

### Create the worker (always on, no public ingress)

```bash
az containerapp create \
  --name elevatebox-worker \
  --resource-group elevatebox-rg \
  --environment elevatebox-env \
  --image elevateboxacr.azurecr.io/elevatebox-agent:latest \
  --registry-server elevateboxacr.azurecr.io \
  --command "python" --args "-m" "agent.main" "start" \
  --min-replicas 1 --max-replicas 1 \
  --secrets $SECRETS \
  --env-vars \
    LIVEKIT_URL=secretref:livekit-url \
    LIVEKIT_API_KEY=secretref:livekit-api-key \
    LIVEKIT_API_SECRET=secretref:livekit-api-secret \
    TWILIO_ACCOUNT_SID=secretref:twilio-account-sid \
    TWILIO_AUTH_TOKEN=secretref:twilio-auth-token \
    TWILIO_PHONE_NUMBER=secretref:twilio-phone-number \
    TWILIO_WHATSAPP_FROM=secretref:twilio-whatsapp-from \
    LIVEKIT_SIP_TRUNK_ID=secretref:livekit-sip-trunk-id \
    SARVAM_API_KEY=secretref:sarvam-api-key \
    WHATSAPP_RECIPIENT_NUMBER=secretref:whatsapp-recipient-number \
    YOUR_NAME=secretref:your-name \
    YOUR_PHONE_NUMBER=secretref:your-phone-number \
    RESUME_PUBLIC_URL=secretref:resume-public-url \
    ARCHITECTURE_DIAGRAM_URL=secretref:architecture-diagram-url \
    TARGET_PHONE_NUMBER=secretref:target-phone-number
```

### Create the web trigger (public ingress on port 8000)

```bash
az containerapp create \
  --name elevatebox-web \
  --resource-group elevatebox-rg \
  --environment elevatebox-env \
  --image elevateboxacr.azurecr.io/elevatebox-agent:latest \
  --registry-server elevateboxacr.azurecr.io \
  --target-port 8000 --ingress external \
  --min-replicas 1 --max-replicas 2 \
  --secrets $SECRETS \
  --env-vars \
    LIVEKIT_URL=secretref:livekit-url \
    LIVEKIT_API_KEY=secretref:livekit-api-key \
    LIVEKIT_API_SECRET=secretref:livekit-api-secret \
    LIVEKIT_SIP_TRUNK_ID=secretref:livekit-sip-trunk-id \
    CALL_TRIGGER_PASSWORD=secretref:call-trigger-password \
    MIN_SECONDS_BETWEEN_CALLS=30
```
(The web container only needs the LiveKit vars + the password — it never
talks to Twilio/Sarvam directly, `dispatch_call` just asks LiveKit to
dispatch the already-running worker.)

The command prints a `.azurecontainerapps.io` URL when it finishes — that's
your public trigger page.

### Redeploying after a code change

```bash
az acr build --registry elevateboxacr --image elevatebox-agent:latest .
az containerapp update --name elevatebox-worker --resource-group elevatebox-rg \
  --image elevateboxacr.azurecr.io/elevatebox-agent:latest
az containerapp update --name elevatebox-web --resource-group elevatebox-rg \
  --image elevateboxacr.azurecr.io/elevatebox-agent:latest
```

### Notes specific to this app

- `call_data.db` (SQLite) lives inside each container's filesystem, which
  is ephemeral on Container Apps — a restart wipes it. Fine for the
  assignment; if you want the audit trail (`call_triggers` table) and call
  history to survive restarts, mount an Azure Files share at
  `/app` (`az containerapp env storage set` + `--volume-mounts`) or move to
  Azure Database for PostgreSQL later.
- The worker has no public ingress — it's outbound-only (it connects out to
  LiveKit Cloud), so don't set `--ingress` on it.
- Double-check `WHATSAPP_RECIPIENT_NUMBER` and `TARGET_PHONE_NUMBER` are the
  values you actually want live *before* deploying — once `elevatebox-web`
  is public, anyone with the password (and, unless you lock it down,
  anyone who can guess your app's URL and doesn't know the password gets a
  401, not a call) can trigger a real outbound call and a real WhatsApp
  send, which costs real money.

---

## 12. Before you send this in

- [ ] Filled in every `.env` value, including `RESUME_PUBLIC_URL` and
      `ARCHITECTURE_DIAGRAM_URL` with real public links
- [ ] Ran `preflight_check.py` clean
- [ ] Ran at least one full text-mode conversation test
      (`test_conversation_text.py`) covering a Hot, a Warm, and a Cold path
- [ ] Placed at least one real test call to a number you control before
      calling the assignment's number
- [ ] Confirmed the mid-call WhatsApp actually arrives DURING the call, not
      after
- [ ] Confirmed the post-call WhatsApp contains all four required elements
      (context, framing, number, diagram) plus the resume attachment
- [ ] Drew/created your one-page architecture diagram (see
      `templates/architecture_diagram_prompt.md`) and hosted it publicly
- [ ] Wrote your under-200-word note on what works / what doesn't / what
      you'd fix next
- [ ] If sending the hosted web trigger link, confirmed `CALL_TRIGGER_PASSWORD`
      is set to a real value (not blank) and tested triggering a call through
      the deployed URL, not just locally
