"""
Fast local iteration loop: chat with the agent's LLM brain over plain text
in your terminal, WITHOUT placing a real phone call or spending Sarvam/Twilio
call-minute credits.

This exercises the exact same system prompt and tool-calling logic that the
voice agent uses, minus STT/TTS/telephony — so it's the cheapest way to
sanity-check discovery questions, classification behavior, and whether
send_whatsapp_now / book_callback fire at the right moments.

NOTE: this sends real WhatsApp messages if triggered (same as a live call)
and logs to the same SQLite DB, so classification/callback testing is
faithful. It just skips voice entirely.

Run:
    python scripts/test_conversation_text.py
Type 'quit' to exit.
"""

import asyncio
import os
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from openai import AsyncOpenAI

from agent.prompts import build_system_prompt
from agent import storage
from agent.whatsapp import send_mid_call_message, send_post_call_summary
from agent.scheduling import parse_callback_time, format_confirmation
from agent.main import classify_caller_turn, LANGUAGE_TURN_HINTS, _clean_discovery_value

load_dotenv()

client = AsyncOpenAI(
    api_key=os.environ["SARVAM_API_KEY"],
    base_url=os.getenv("SARVAM_LLM_BASE_URL", "https://api.sarvam.ai/v1"),
    default_headers={"X-Title": "ElevateBox Voice Agent"},
)
MODEL = os.getenv("SARVAM_LLM_MODEL", "sarvam-105b")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "record_caller_name",
            "description": "Record the caller's first name once they give it.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_discovery",
            "description": "Record discovery field(s) the caller just answered, in English.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "catalog_size": {"type": "string"},
                    "timeline": {"type": "string"},
                    "features": {"type": "string"},
                    "budget": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_lead",
            "description": "Record or update the lead's classification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["hot", "warm", "cold"]},
                    "reasoning": {"type": "string"},
                },
                "required": ["status", "reasoning"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_whatsapp_now",
            "description": "Fire a WhatsApp message immediately, mid-call.",
            "parameters": {
                "type": "object",
                "properties": {
                    "call_context": {"type": "string"},
                    "tone": {"type": "string", "enum": ["hot", "cold"]},
                },
                "required": ["call_context", "tone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_callback",
            "description": "Parse a spoken callback time phrase.",
            "parameters": {
                "type": "object",
                "properties": {"natural_time_phrase": {"type": "string"}},
                "required": ["natural_time_phrase"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_call_summary",
            "description": "Trigger the post-call WhatsApp summary.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


DISCOVERY_LABELS = {
    "category": "sells",
    "catalog_size": "catalog size",
    "timeline": "timeline",
    "features": "features needed",
    "budget": "budget",
}


def discovery_context(discovery: dict) -> str:
    parts = [f"{DISCOVERY_LABELS[k]}: {v}" for k, v in discovery.items() if v]
    return "; ".join(parts)


async def handle_tool_call(
    call_id: str, name: str, args: dict, transcript_so_far: str, discovery: dict, state: dict
) -> str:
    if name == "record_caller_name":
        state["caller_name"] = (args.get("name") or "").strip()
        print(f"   [TOOL] record_caller_name -> {state['caller_name']}")
        return f"Got it — I'll address them as {state['caller_name']}."

    if name == "update_discovery":
        for field in DISCOVERY_LABELS:
            value = _clean_discovery_value(args.get(field) or "")
            if value:
                discovery[field] = value
        filled = sum(1 for v in discovery.values() if v)
        print(f"   [TOOL] update_discovery -> {discovery} ({filled}/5)")
        return f"Discovery recorded ({filled}/5 fields captured)."

    if name == "classify_lead":
        await storage.set_classification(call_id, args["status"], args["reasoning"])
        print(f"   [TOOL] classify_lead -> {args['status']} ({args['reasoning']})")
        return f"Classification recorded: {args['status']}"

    if name == "send_whatsapp_now":
        structured = discovery_context(discovery)
        call_context = f"{structured} — {args['call_context']}" if structured else args["call_context"]
        print(f"   [TOOL] send_whatsapp_now -> tone={args['tone']}")
        print(f"          context: {call_context}")
        success = await send_mid_call_message(call_context, args["tone"], state["caller_name"])
        print(f"          Twilio accepted request: {success}")
        return (
            "Twilio accepted the WhatsApp request; delivery status will be visible in Twilio."
            if success
            else "WhatsApp send failed before Twilio accepted the request."
        )

    if name == "book_callback":
        parsed = parse_callback_time(args["natural_time_phrase"])
        confirmation = format_confirmation(parsed)
        await storage.record_callback(call_id, args["natural_time_phrase"], parsed.isoformat())
        print(f"   [TOOL] book_callback -> '{args['natural_time_phrase']}' => {confirmation}")
        return f"Callback booked for {confirmation}."

    if name == "end_call_summary":
        print("   [TOOL] end_call_summary -> sending post-call WhatsApp")
        call = await storage.get_call(call_id)
        classification = call["current_classification"] if call else "unclassified"
        structured = discovery_context(discovery)
        context_paragraph = (
            f"On the call we covered — {structured}."
            if structured
            else transcript_so_far[-800:]
        )
        success = await send_post_call_summary(
            context_paragraph, classification, state["caller_name"]
        )
        print(f"          sent: {success}")
        return "Summary sent."

    return "Unknown tool."


async def main():
    await storage.init_db()
    call_id = str(uuid.uuid4())
    await storage.create_call(call_id, "text-test-room", "text-test")

    messages = [{"role": "system", "content": build_system_prompt()}]
    transcript_so_far = ""
    discovery = {field: "" for field in DISCOVERY_LABELS}
    state = {"caller_name": ""}

    print("=== ElevateBox Agent — Text Test Mode ===")
    print("Type as the customer. Type 'quit' to exit.\n")

    # kick off with the greeting, same as generate_reply in main.py
    messages.append({
        "role": "user",
        "content": (
            "[CALL CONNECTED — greet the person and warmly ask for their "
            "name before anything else]"
        ),
    })

    while True:
        response = await client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto"
        )
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if msg.content:
            print(f"\nAGENT: {msg.content}")
            transcript_so_far += f"\nAgent: {msg.content}"

        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                result = await handle_tool_call(
                    call_id, tc.function.name, args, transcript_so_far, discovery, state
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            continue  # let the model react to tool results before waiting for user input

        user_input = input("\nYOU: ")
        if user_input.strip().lower() == "quit":
            break
        transcript_so_far += f"\nCaller: {user_input}"
        messages.append({"role": "user", "content": user_input})

        # Mirror agent/main.py's on_user_turn_completed: give the LLM an
        # explicit signal for what language to reply in, instead of relying
        # on it to infer that purely from the system prompt's general rules.
        verdict, _locale = classify_caller_turn(user_input)
        hint = LANGUAGE_TURN_HINTS.get(verdict)
        if hint:
            messages.append({"role": "system", "content": hint})

    await storage.end_call(call_id)
    print("\n=== Call ended ===")


if __name__ == "__main__":
    asyncio.run(main())
