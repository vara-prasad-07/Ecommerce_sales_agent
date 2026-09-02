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
├── call_data.db               # created automatically on first run
├── agent/
│   ├── main.py                # LiveKit entrypoint, session setup, function tools
│   ├── prompts.py              # the system prompt (persona/discovery/classification)
│   ├── storage.py               # SQLite: calls, transcripts, discovery, classifications, callbacks
│   ├── whatsapp.py               # Twilio WhatsApp template sender (mid-call + post-call)
│   └── scheduling.py              # natural-language time phrase -> datetime
├── scripts/
│   ├── setup_twilio_trunk.py       # (optional) automates the Twilio-side trunk setup
│   ├── setup_sip_trunk.py           # creates the LiveKit outbound SIP trunk
│   ├── make_call.py                  # dispatches agent + dials the target number
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

## 11. Before you send this in

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
