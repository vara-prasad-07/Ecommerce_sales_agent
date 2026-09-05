# ElevateBox Voice Agent

An AI voice agent that calls a number, pitches e-commerce website development,
and has a natural sales conversation. It figures out the caller's needs
(products, budget, timeline, features), classifies the lead as Hot / Warm /
Cold, sends a WhatsApp message mid-call if the lead looks promising, books a
callback if a time is mentioned, and sends a WhatsApp summary (with resume +
architecture diagram) after the call ends.

Built for the ElevateBox SDE Intern assignment.

**Stack:** LiveKit Agents (orchestration) + Sarvam AI (STT, TTS, and the LLM —
also handles Hindi/Telugu/English) + Twilio (calling + WhatsApp).

Architecture Diagram: https://res.cloudinary.com/diryolcmm/image/upload/v1788351273/final_arch_t8p4oc.png

Live website: https://elevatebox-web.kindisland-53999716.centralindia.azurecontainerapps.io/
---

## Setup

1. **Install**
   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure**
   ```bash
   cp .env.example .env
   ```
   Fill in every value (see comments in `.env.example`). You'll need a
   LiveKit Cloud project, a Twilio number + WhatsApp sender with two approved
   Content Templates, and a Sarvam AI API key.

3. **One-time SIP trunk setup** (Twilio ↔ LiveKit)
   ```bash
   python scripts/setup_twilio_trunk.py   # copy TWILIO_TERMINATION_URI into .env
   python scripts/setup_sip_trunk.py      # copy LIVEKIT_SIP_TRUNK_ID into .env
   ```

4. **Preflight check** — catches bad/missing credentials before a real call:
   ```bash
   python scripts/preflight_check.py
   ```

---

## Running it

**Text-only iteration** (no telephony cost, tune `agent/prompts.py`):
```bash
python scripts/test_conversation_text.py
```

**Real voice call:**
```bash
# Terminal 1 — agent worker (keep running)
python -m agent.main dev

# Terminal 2 — place the call
python scripts/make_call.py +917658975169
```

**On-demand web trigger** — a password-gated page so someone without this
repo can trigger a call:
```bash
uvicorn server.app:app --reload --port 8000
```
Requires `CALL_TRIGGER_PASSWORD` set in `.env`, and the agent worker (above)
running in parallel.

---

## Project structure

```
agent/            LiveKit entrypoint, prompts, WhatsApp sender, scheduling, SQLite storage
server/           FastAPI web trigger (password-gated "call this number now")
scripts/          Trunk setup, make_call, preflight_check, text-mode test
templates/        Notes for the architecture diagram asset
call_data.db       SQLite log of calls/transcripts/classifications (auto-created)
```

---

## Known limitations

- Time parsing (`scheduling.py`) is rule-based, not full NLP — unusual
  phrasings fall back to a default (tomorrow, 10 AM IST).
- WhatsApp sends are fire-and-forget with no retry — a failure is logged,
  not retried.
- The mid-call WhatsApp trigger relies on the LLM calling `update_discovery`;
  there's an English-keyword fallback, but it doesn't help on Hindi/Telugu
  calls.

---

## Deploying

Ships as a single Docker image (see `Dockerfile`) with two long-running
processes that need separate containers: the **worker**
(`python -m agent.main start`, always-on, no public ingress) and the **web**
trigger (`uvicorn server.app:app`, public ingress). Azure Container Apps
works well for this — push the image to ACR, register your `.env` values as
Container Apps secrets, and create the two apps referencing them.
