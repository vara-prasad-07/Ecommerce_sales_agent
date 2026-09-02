"""
Lightweight SQLite storage for call state.

Tracks per-call: transcript turns, classification history, and any booked
callback. This is intentionally simple (no ORM) since the assignment scope
doesn't need more — but it's the single source of truth the WhatsApp
message-builder and the callback scheduler both read from.
"""

import os
import json
import time
import aiosqlite
from typing import Optional

DB_PATH = os.getenv("DATABASE_PATH", "./call_data.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    call_id TEXT PRIMARY KEY,
    room_name TEXT,
    phone_number TEXT,
    started_at REAL,
    ended_at REAL,
    current_classification TEXT DEFAULT 'unclassified',
    classification_reasoning TEXT DEFAULT '',
    discovery_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS transcript_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT,
    role TEXT,           -- 'agent' or 'caller'
    text TEXT,
    ts REAL
);

CREATE TABLE IF NOT EXISTS classification_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT,
    status TEXT,
    reasoning TEXT,
    ts REAL
);

CREATE TABLE IF NOT EXISTS callbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT,
    raw_phrase TEXT,
    parsed_datetime_iso TEXT,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS whatsapp_sends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT,
    kind TEXT,            -- 'mid_call' or 'post_call_summary'
    payload TEXT,
    sent_at REAL,
    success INTEGER
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        # Migration for DBs created before discovery_json existed.
        try:
            await db.execute("ALTER TABLE calls ADD COLUMN discovery_json TEXT DEFAULT '{}'")
            await db.commit()
        except aiosqlite.OperationalError:
            pass


async def create_call(call_id: str, room_name: str, phone_number: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO calls (call_id, room_name, phone_number, started_at) "
            "VALUES (?, ?, ?, ?)",
            (call_id, room_name, phone_number, time.time()),
        )
        await db.commit()


async def end_call(call_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE calls SET ended_at = ? WHERE call_id = ?",
            (time.time(), call_id),
        )
        await db.commit()


async def log_turn(call_id: str, role: str, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO transcript_turns (call_id, role, text, ts) VALUES (?, ?, ?, ?)",
            (call_id, role, text, time.time()),
        )
        await db.commit()


async def set_classification(call_id: str, status: str, reasoning: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE calls SET current_classification = ?, classification_reasoning = ? "
            "WHERE call_id = ?",
            (status, reasoning, call_id),
        )
        await db.execute(
            "INSERT INTO classification_events (call_id, status, reasoning, ts) "
            "VALUES (?, ?, ?, ?)",
            (call_id, status, reasoning, time.time()),
        )
        await db.commit()


async def set_discovery(call_id: str, discovery: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE calls SET discovery_json = ? WHERE call_id = ?",
            (json.dumps(discovery), call_id),
        )
        await db.commit()


async def record_callback(call_id: str, raw_phrase: str, parsed_iso: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO callbacks (call_id, raw_phrase, parsed_datetime_iso, created_at) "
            "VALUES (?, ?, ?, ?)",
            (call_id, raw_phrase, parsed_iso, time.time()),
        )
        await db.commit()


async def record_whatsapp_send(call_id: str, kind: str, payload: dict, success: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO whatsapp_sends (call_id, kind, payload, sent_at, success) "
            "VALUES (?, ?, ?, ?, ?)",
            (call_id, kind, json.dumps(payload), time.time(), int(success)),
        )
        await db.commit()


async def get_transcript(call_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, text, ts FROM transcript_turns WHERE call_id = ? ORDER BY ts ASC",
            (call_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_latest_callback(call_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT raw_phrase, parsed_datetime_iso FROM callbacks "
            "WHERE call_id = ? ORDER BY created_at DESC LIMIT 1",
            (call_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_call(call_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM calls WHERE call_id = ?", (call_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
