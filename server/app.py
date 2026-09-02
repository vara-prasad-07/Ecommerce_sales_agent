"""
On-demand call trigger — a small password-gated web app.

Serves a one-page form (server/static/index.html): enter a phone number
with country code + the shared password, and it dispatches the voice agent
to call that number right away, via the exact same LiveKit/Twilio dispatch
path as scripts/make_call.py (see agent/dispatch.py).

This process is intentionally separate from the agent worker
(agent/main.py) — it's a thin, stateless-ish web service that only needs to
reach the LiveKit API to kick off a call; it does NOT itself handle any
audio/STT/TTS/LLM. The agent worker must be running and registered
separately (locally: `python -m agent.main dev`; in production:
`python -m agent.main start`) for a dispatched call to actually be answered
by the agent.

Run locally:
    uvicorn server.app:app --reload --port 8000

Required env vars (see .env.example):
    CALL_TRIGGER_PASSWORD   - the shared password the frontend form checks
    LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET / LIVEKIT_SIP_TRUNK_ID
Optional:
    MIN_SECONDS_BETWEEN_CALLS  - cooldown between triggered calls (default 30)
"""

import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, field_validator

from agent import storage
from agent.dispatch import DispatchError, dispatch_call, normalize_phone_number

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("call-trigger")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await storage.init_db()
    if not os.getenv("CALL_TRIGGER_PASSWORD"):
        logger.warning(
            "CALL_TRIGGER_PASSWORD is not set — /api/call will reject every "
            "request until it is configured."
        )
    yield


app = FastAPI(title="ElevateBox Voice Agent — Call Trigger", lifespan=_lifespan)

_last_trigger_at: float = 0.0


class CallRequest(BaseModel):
    phone_number: str
    password: str

    @field_validator("phone_number")
    @classmethod
    def _normalize(cls, value: str) -> str:
        try:
            return normalize_phone_number(value)
        except DispatchError as exc:
            raise ValueError(str(exc)) from exc


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/call")
async def trigger_call(payload: CallRequest, request: Request) -> JSONResponse:
    global _last_trigger_at

    expected_password = os.getenv("CALL_TRIGGER_PASSWORD", "")
    if not expected_password:
        raise HTTPException(status_code=500, detail="Server is not configured (missing password).")
    if not hmac.compare_digest(payload.password, expected_password):
        raise HTTPException(status_code=401, detail="Incorrect password.")

    min_seconds_between_calls = float(os.getenv("MIN_SECONDS_BETWEEN_CALLS", "30"))
    now = time.monotonic()
    remaining = min_seconds_between_calls - (now - _last_trigger_at)
    if remaining > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Please wait {int(remaining) + 1}s before triggering another call.",
        )

    try:
        result = await dispatch_call(payload.phone_number, wait_until_answered=False)
    except DispatchError as exc:
        logger.exception("Dispatch failed for %s", payload.phone_number)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _last_trigger_at = now
    client_ip = request.client.host if request.client else "unknown"
    await storage.record_call_trigger(payload.phone_number, client_ip)
    logger.info(
        "Call triggered: %s (room=%s, requested_by=%s)",
        payload.phone_number,
        result["room_name"],
        client_ip,
    )

    return JSONResponse(
        {
            "status": "dialing",
            "phone_number": payload.phone_number,
            "room": result["room_name"],
            "message": f"Calling {payload.phone_number} now. It should ring shortly.",
        }
    )
