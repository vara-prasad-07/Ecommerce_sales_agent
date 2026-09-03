"""
ElevateBox outbound sales voice agent — main entrypoint.

Run with:
    python -m agent.main dev        # local dev, connects to LiveKit Cloud
    python -m agent.main start      # production worker mode

To actually place the outbound call, run scripts/make_call.py separately
once this worker is running and registered.
"""

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime

from dotenv import load_dotenv
import httpx

from livekit import agents, api, rtc
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
    llm,
)
from livekit.plugins import sarvam

from agent.prompts import build_system_prompt
from agent import storage, whatsapp
from agent.scheduling import parse_callback_time, format_confirmation

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("elevatebox-agent")

# Map Sarvam's detected language labels to supported Indian English/locales.
TTS_LANGUAGE_CODES = {
    "en": "en-IN",
    "hi": "hi-IN",
    "bn": "bn-IN",
    "gu": "gu-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "mr": "mr-IN",
    "od": "od-IN",
    "pa": "pa-IN",
    "ta": "ta-IN",
    "te": "te-IN",
}


DISCOVERY_FIELDS = ("category", "catalog_size", "timeline", "features", "budget")
DISCOVERY_LABELS = {
    "category": "sells",
    "catalog_size": "catalog size",
    "timeline": "timeline",
    "features": "features needed",
    "budget": "budget",
}

# The LLM occasionally passes the literal word "null" (or similar) instead
# of just leaving a discovery field blank when it has nothing to report.
# Confirmed in production: this leaked verbatim into a real WhatsApp message
# ("sells: null; catalog size: null..."). Treat these as "no answer."
_DISCOVERY_NON_ANSWERS = {
    "null", "none", "n/a", "na", "unknown", "not discussed", "not mentioned",
    "not applicable", "not specified", "-", "nil",
}


def _clean_discovery_value(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned or cleaned.lower() in _DISCOVERY_NON_ANSWERS:
        return ""
    return cleaned


def _has_required_discovery(call_context: str) -> bool:
    """Only trigger after the full discovery checklist is covered.

    We allow a send after either:
    - all five required questions have been asked; or
    - all five required discovery concepts are present in the actual call context.

    We do not allow a send after only the first question ("what do you sell?")
    because that is not enough discovery and causes false positives.

    This is an English-keyword fallback only. It cannot reliably detect
    discovery completion on a Hindi/Telugu call, since the transcript won't
    contain these English phrases. The primary gate is the structured
    `ElevateBoxSalesAgent._discovery` dict (see `update_discovery`), which the
    LLM fills in English regardless of what language the caller spoke. This
    function only matters as a safety net for callers of `send_whatsapp_now`
    that don't go through the agent instance (e.g. the text-mode test script).
    """
    context = (call_context or "").lower()
    if not context:
        return False

    category_terms = (
        "clothes", "fashion", "electronics", "food", "restaurant", "grocery",
        "real estate", "properties", "doctor", "clinic", "gym", "beauty",
        "jewellery", "jewelry", "bakery", "hotel", "travel",
    )
    catalog_terms = (
        "50", "few dozen", "few hundred", "catalog", "products", "items",
        "inventory", "stock",
    )
    timeline_terms = (
        "timeline", "launch", "go live", "deadline", "weeks", "days", "month",
    )
    features_terms = (
        "payments", "payment", "inventory", "tracking", "delivery", "features",
        "wishlist", "checkout", "login", "cart",
    )
    budget_terms = (
        "budget", "price", "30000", "inr", "rs", "rupees", "cost", "range",
    )

    answer_category = any(term in context for term in category_terms)
    answer_catalog = any(term in context for term in catalog_terms)
    answer_timeline = any(term in context for term in timeline_terms) and not any(
        phrase in context for phrase in ("no timeline", "timeline not discussed", "not discussed yet")
    )
    answer_features = any(term in context for term in features_terms) and not any(
        phrase in context for phrase in ("no features", "features not discussed", "not discussed yet")
    )
    answer_budget = any(term in context for term in budget_terms) and not any(
        phrase in context for phrase in ("no budget", "budget not discussed", "not discussed yet")
    )

    asked_category = any(
        phrase in context for phrase in (
            "what do you sell", "what are you selling", "what products do you sell",
            "what kind of products", "what type of products", "what business do you run",
            "what do you offer",
        )
    )
    asked_catalog = any(
        phrase in context for phrase in (
            "how many products", "how big is your catalog", "how many items",
            "catalog size", "what is your catalog size", "product count",
            "how large is your catalog",
        )
    )
    asked_timeline = any(
        phrase in context for phrase in (
            "what timeline", "when do you want to launch", "when do you plan to launch",
            "what is your timeline", "how soon", "when are you planning to go live",
            "launch timeline", "project deadline",
        )
    )
    asked_features = any(
        phrase in context for phrase in (
            "what features", "what functionality", "what features do you need",
            "must have features", "what functionality do you need",
            "which features matter most", "do you need payment",
            "inventory tracking", "delivery tracking", "checkout features",
        )
    )
    asked_budget = any(
        phrase in context for phrase in (
            "what budget", "what is your budget", "rough budget",
            "do you have a rough budget", "what is your price range",
            "what budget range", "price range", "cost range",
            "how much can you spend",
        )
    )

    all_questions_asked = asked_category and asked_catalog and asked_timeline and asked_features and asked_budget
    all_answers_present = answer_category and answer_catalog and answer_timeline and answer_features and answer_budget

    return all_questions_asked or all_answers_present


def normalize_tts_language(value: str) -> str | None:
    """Normalize a value from STT/TTS metadata into a Sarvam target language code."""
    if not value:
        return None

    normalized = value.strip().lower().replace("_", "-")
    if not normalized:
        return None

    for code, locale in TTS_LANGUAGE_CODES.items():
        if normalized.startswith(code) or normalized.startswith(code + "-"):
            return locale

    if normalized.startswith("telugu"):
        return "te-IN"
    if normalized.startswith("hindi"):
        return "hi-IN"
    if normalized.startswith("english"):
        return "en-IN"
    if "te" in normalized:
        return "te-IN"
    if "hi" in normalized:
        return "hi-IN"
    return None


def detect_tts_language_from_text(text: str) -> str:
    """Choose a TTS language based on the actual caller text, including Telugu script."""
    if not text:
        return "en-IN"

    lower = text.lower()

    telugu_phrases = [
        "telugu", "andariki", "chala", "bagundi", "ledu", "kavali", "vuntundi",
        "naku", "meeru", "mari", "cheppandi", "okay ra", "sari", "eppudu",
        "vachindi", "baga", "manam", "prathi", "app lu",
    ]
    if any(re.search(rf"\b{re.escape(marker)}\b", lower) for marker in telugu_phrases):
        return "te-IN"

    if " telugu" in lower or lower.startswith("telugu"):
        return "te-IN"

    hindi_phrases = [
        "hindi", "namaste", "hai", "kya", "kaise", "aap", "main", "hum", "kya karo",
    ]
    if any(re.search(rf"\b{re.escape(marker)}\b", lower) for marker in hindi_phrases):
        return "hi-IN"

    if re.search(r"[\u0C00-\u0C7F]", text):
        return "te-IN"
    if re.search(r"[\u0900-\u097F]", text):
        return "hi-IN"
    if re.search(r"[\u0B80-\u0BFF]", text):
        return "ta-IN"
    if re.search(r"[\u0A00-\u0A7F]", text):
        return "gu-IN"
    if re.search(r"[\u0B00-\u0B7F]", text):
        return "kn-IN"
    if re.search(r"[\u0980-\u09FF]", text):
        return "bn-IN"
    if re.search(r"[\u0D00-\u0D7F]", text):
        return "ml-IN"

    return "en-IN"


def resolve_tts_language(spoken_text: str, metadata_language: str | None) -> str:
    """Prefer the actual spoken text when it clearly indicates another language."""
    text_locale = detect_tts_language_from_text(spoken_text)
    metadata_locale = normalize_tts_language(metadata_language or "")

    if text_locale != "en-IN":
        return text_locale
    if metadata_locale and metadata_locale != "en-IN":
        return metadata_locale
    return text_locale or metadata_locale or "en-IN"


# Marker words used to tell Romanized Telugu/Hindi apart from English in
# Latin-script speech. Kept separate from ordinary sales vocabulary (budget,
# timeline, website, ...) which is common across all three languages here and
# is not a language signal on its own.
_TELUGU_ROMAN_MARKERS = {
    "telugu", "andariki", "chala", "bagundi", "ledu", "ledhu", "kavali",
    "vuntundi", "naku", "meeru", "mari", "cheppandi", "sari", "eppudu",
    "vachindi", "baga", "manam", "prathi", "nenu", "meeku", "vundi", "kuda",
    "kosam", "ela", "enti", "emiti", "chestunna", "cheddam", "avunu", "ra",
    "ante", "undi", "chala bagundi", "sare",
}
_HINDI_ROMAN_MARKERS = {
    "hindi", "namaste", "hai", "kya", "kaise", "aap", "main", "hum", "hoon",
    "nahi", "haan", "mera", "meri", "kar", "karo", "chahiye", "chahta",
    "chahti", "accha", "theek", "batao", "kitna", "kitne", "achha", "bhai",
}


def classify_caller_turn(text: str) -> tuple[str, str | None]:
    """
    Classify a single caller turn for the LLM's reply-language decision.

    Returns (verdict, locale). verdict is one of: "pure_telugu",
    "code_mixed_telugu", "telugu_romanized", "pure_hindi",
    "code_mixed_hindi", "hindi_romanized", "pure_english", "unknown".

    This is intentionally separate from `detect_tts_language_from_text`,
    which only needs a single best-guess TTS voice locale. Here we need to
    tell "pure Telugu" apart from "Telugu+English code-mixed" (Teluguish),
    since the system prompt requires different reply behavior for each —
    without an explicit per-turn signal like this, the LLM tended to default
    to English on code-mixed input.
    """
    if not text or not text.strip():
        return ("unknown", None)

    if re.search(r"[ఀ-౿]", text):
        has_latin_words = bool(re.search(r"[A-Za-z]{2,}", text))
        return ("code_mixed_telugu" if has_latin_words else "pure_telugu", "te-IN")

    if re.search(r"[ऀ-ॿ]", text):
        has_latin_words = bool(re.search(r"[A-Za-z]{2,}", text))
        return ("code_mixed_hindi" if has_latin_words else "pure_hindi", "hi-IN")

    words = re.findall(r"[a-z']+", text.lower())
    if not words:
        return ("unknown", None)

    telugu_hits = sum(1 for w in words if w in _TELUGU_ROMAN_MARKERS)
    hindi_hits = sum(1 for w in words if w in _HINDI_ROMAN_MARKERS)
    total = len(words)

    if telugu_hits and telugu_hits / total >= 0.5:
        return ("telugu_romanized", "te-IN")
    if telugu_hits:
        return ("code_mixed_telugu", "te-IN")
    if hindi_hits and hindi_hits / total >= 0.5:
        return ("hindi_romanized", "hi-IN")
    if hindi_hits:
        return ("code_mixed_hindi", "hi-IN")
    return ("pure_english", "en-IN")


LANGUAGE_TURN_HINTS = {
    "pure_telugu": (
        "LANGUAGE CUE: the caller just spoke in pure Telugu script. Reply "
        "ONLY in pure Telugu, in Telugu script. Do not switch to English or "
        "Romanized Telugu for this reply."
    ),
    "code_mixed_telugu": (
        "LANGUAGE CUE: the caller just code-switched between Telugu and "
        "English in the same turn (Teluguish). Mirror that exact blend in "
        "your reply, roughly the same ratio of Telugu to English words. Do "
        "NOT reply in pure English — that is the one thing to avoid here."
    ),
    "telugu_romanized": (
        "LANGUAGE CUE: the caller just spoke Telugu written in Roman "
        "letters (no Telugu script). Reply in the same Romanized Telugu "
        "style — Telugu words spelled in Latin letters. Do not reply in "
        "English and do not switch to Telugu script."
    ),
    "pure_hindi": (
        "LANGUAGE CUE: the caller just spoke in pure Hindi. Reply ONLY in "
        "pure Hindi, in Devanagari script. Do not switch to English for "
        "this reply."
    ),
    "code_mixed_hindi": (
        "LANGUAGE CUE: the caller just code-switched between Hindi and "
        "English in the same turn (Hinglish). Mirror that exact blend in "
        "your reply. Do NOT reply in pure English — that is the one thing "
        "to avoid here."
    ),
    "hindi_romanized": (
        "LANGUAGE CUE: the caller just spoke Hindi written in Roman "
        "letters. Reply in the same Romanized Hindi style. Do not switch to "
        "Devanagari script or pure English."
    ),
}


class ElevateBoxSalesAgent(Agent):
    """
    The persona + tool-bearing agent. All classification, WhatsApp firing,
    and callback booking logic lives in the function_tools below — the LLM
    decides when to call them based on the system prompt's instructions.
    """

    def __init__(self, call_id: str, ctx: JobContext, phone_number: str = "") -> None:
        super().__init__(instructions=build_system_prompt())
        self.call_id = call_id
        self.job_ctx = ctx
        self._phone_number = phone_number
        self._last_classification = "unclassified"
        self._summary_sent = False
        self._hangup_requested = False
        self._hangup_task = None
        self._mid_call_tones_sent = set()
        self._mid_call_whatsapp_sent = False
        self._classification_count = 0
        self._whatsapp_tasks = set()
        self._discovery: dict[str, str] = {field: "" for field in DISCOVERY_FIELDS}
        self._caller_name = ""
        self._classification_reasoning = ""

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        """Inject an explicit, per-turn language directive before the LLM
        generates its reply. The system prompt's language rules alone were
        not enough to keep the model out of English on code-mixed
        (Telugu/Hindi + English) turns — this gives it a concrete, current
        signal instead of relying on it to re-derive the rule from the full
        conversation every time."""
        verdict, _locale = classify_caller_turn(new_message.text_content or "")
        hint = LANGUAGE_TURN_HINTS.get(verdict)
        if hint:
            turn_ctx.add_message(role="system", content=hint)

    async def _get_transcript_context(self, fallback: str = "") -> str:
        transcript = await storage.get_transcript(self.call_id)
        if not transcript:
            return fallback

        caller_lines = [t["text"] for t in transcript if t.get("role") == "caller"]
        context = " ".join(caller_lines).strip()
        return context[-1200:] if context else fallback

    def _discovery_filled_count(self) -> int:
        return sum(1 for value in self._discovery.values() if value.strip())

    def _discovery_complete(self) -> bool:
        # Require 4 of 5 fields — budget is the one people are legitimately
        # cagey about, so don't hard-block a Hot/Cold send on it alone.
        return self._discovery_filled_count() >= 4

    def _discovery_context(self) -> str:
        """A structured, English, per-field summary built from what the LLM
        recorded via `update_discovery` — language-agnostic and safe to drop
        straight into a WhatsApp message, unlike raw transcript text which
        may be in Telugu/Hindi script or Romanized code-mixed speech."""
        parts = [
            f"{DISCOVERY_LABELS[field]}: {self._discovery[field]}"
            for field in DISCOVERY_FIELDS
            if self._discovery[field].strip()
        ]
        return "; ".join(parts)

    async def _resolve_call_context(self, fallback_text: str = "") -> str:
        """Best context available: structured discovery first, then the raw
        transcript fallback, then whatever free-text the LLM passed in."""
        structured = self._discovery_context()
        if structured:
            return structured
        transcript_context = await self._get_transcript_context()
        return transcript_context or fallback_text

    def _schedule_mid_call_whatsapp(self, call_context: str, tone: str) -> None:
        if self._mid_call_whatsapp_sent:
            logger.info("Skipping duplicate mid-call WhatsApp for this call")
            return

        if tone in self._mid_call_tones_sent:
            return

        if not (self._discovery_complete() or _has_required_discovery(call_context)):
            logger.info(
                "Deferring mid-call WhatsApp until required discovery is complete: %s",
                call_context,
            )
            return

        self._mid_call_whatsapp_sent = True
        self._mid_call_tones_sent.add(tone)

        async def _fire():
            success = await whatsapp.send_mid_call_message(
                call_context, tone, self._caller_name, self._phone_number
            )
            await storage.record_whatsapp_send(
                self.call_id,
                "mid_call",
                {"context": call_context, "tone": tone},
                success,
            )
            logger.info("Mid-call WhatsApp completed (success=%s, tone=%s)", success, tone)

        task = asyncio.create_task(_fire())
        self._whatsapp_tasks.add(task)
        task.add_done_callback(self._whatsapp_tasks.discard)

    def _schedule_callback_whatsapp(self, natural_time_phrase: str, confirmation: str) -> None:
        """Fire the "I'll send follow-up details" WhatsApp for a Warm caller
        who asked for a callback instead of continuing the pitch. Unlike
        `_schedule_mid_call_whatsapp`, this does not wait on discovery being
        complete — a caller who says "I don't have time, call me later" may
        bail out before discovery finishes, and still needs the confirmation
        they were just promised on the call."""
        if self._mid_call_whatsapp_sent:
            logger.info("Skipping callback WhatsApp: mid-call WhatsApp already sent for this call")
            return

        self._mid_call_whatsapp_sent = True
        self._mid_call_tones_sent.add("callback")

        call_context = self._discovery_context()

        async def _fire():
            success = await whatsapp.send_callback_confirmation(
                call_context, confirmation, self._caller_name, self._phone_number
            )
            await storage.record_whatsapp_send(
                self.call_id,
                "mid_call_callback",
                {"context": call_context, "time_phrase": natural_time_phrase, "confirmation": confirmation},
                success,
            )
            logger.info("Callback WhatsApp completed (success=%s)", success)

        task = asyncio.create_task(_fire())
        self._whatsapp_tasks.add(task)
        task.add_done_callback(self._whatsapp_tasks.discard)

    async def _try_fire_mid_call(self) -> None:
        """Fire the mid-call (template 1) WhatsApp the moment BOTH a hot/cold
        classification and sufficient discovery exist, regardless of which
        one completed first.

        A real Hot caller often asks about price on the very first answer —
        classify_lead("hot") can fire long before update_discovery has 4/5
        fields. The old code only attempted the send at the instant
        classify_lead/send_whatsapp_now was called, so a too-early
        classification silently dropped the send forever (nothing retried it
        once discovery caught up) — the caller only ever got the unconditional
        post-call summary (template 2) at hangup. Calling this from the tail
        of both update_discovery and classify_lead makes the send
        order-independent and guarantees it fires exactly once per call.
        """
        if self._mid_call_whatsapp_sent:
            return
        if self._last_classification not in ("hot", "cold"):
            return

        call_context = await self._resolve_call_context(self._classification_reasoning)
        if not (self._discovery_complete() or _has_required_discovery(call_context)):
            return

        self._schedule_mid_call_whatsapp(call_context, self._last_classification)

    # ---- Tool: record_caller_name ----
    @function_tool
    async def record_caller_name(self, context: RunContext, name: str) -> str:
        """
        Record the caller's first name once they give it, early in the call.
        Call this once, right after they tell you their name.

        Args:
            name: the caller's first name as they said it, e.g. "Ramesh"
        """
        self._caller_name = name.strip()
        logger.info("Caller name recorded: %s", self._caller_name)
        return f"Got it — I'll address them as {self._caller_name}."

    # ---- Tool: update_discovery ----
    @function_tool
    async def update_discovery(
        self,
        context: RunContext,
        category: str = "",
        catalog_size: str = "",
        timeline: str = "",
        features: str = "",
        budget: str = "",
    ) -> str:
        """
        Record any discovery fields the caller just answered. ALWAYS write the
        value in English, even if the caller answered in Hindi or Telugu —
        this is what powers the WhatsApp messages, which must be readable by
        an English-speaking recipient. Only pass the field(s) actually
        answered this turn; leave the rest blank. Safe to call multiple times
        as more details come out.

        Args:
            category: what they sell / their business type, e.g. "handmade jewelry"
            catalog_size: rough catalog size, e.g. "about 50 products"
            timeline: when they want to launch, e.g. "in 3-4 weeks"
            features: must-have features, e.g. "online payments, inventory tracking"
            budget: budget figure or range they gave, e.g. "around 30,000 INR"
        """
        for field, value in (
            ("category", category),
            ("catalog_size", catalog_size),
            ("timeline", timeline),
            ("features", features),
            ("budget", budget),
        ):
            cleaned = _clean_discovery_value(value)
            if cleaned:
                self._discovery[field] = cleaned

        await storage.set_discovery(self.call_id, self._discovery)
        filled = self._discovery_filled_count()
        logger.info("Discovery updated (%d/5 fields): %s", filled, self._discovery)

        # Discovery may be what was missing for a classification that
        # already fired earlier — check now rather than waiting on the LLM
        # to call send_whatsapp_now again (which the prompt tells it not to).
        await self._try_fire_mid_call()

        return f"Discovery recorded ({filled}/5 fields captured)."

    # ---- Tool: classify_lead ----
    @function_tool
    async def classify_lead(
        self,
        context: RunContext,
        status: str,
        reasoning: str,
    ) -> str:
        """
        Record or update the current read of the lead's buying intent.

        Args:
            status: one of "hot", "warm", "cold"
            reasoning: short explanation citing what the caller actually said
        """
        status = status.lower().strip()
        if status not in ("hot", "warm", "cold"):
            status = "warm"  # safe default rather than erroring the call
        self._classification_count += 1
        self._last_classification = status
        self._classification_reasoning = reasoning
        await storage.set_classification(self.call_id, status, reasoning)
        logger.info("Lead classified as %s — %s", status, reasoning)

        await self._try_fire_mid_call()

        return f"Classification recorded: {status}"

    # ---- Tool: send_whatsapp_now (mid-call, non-blocking) ----
    @function_tool
    async def send_whatsapp_now(
        self,
        context: RunContext,
        call_context: str,
        tone: str,
    ) -> str:
        """
        Fire a WhatsApp message immediately, while the call is still live.
        Must not block the conversation — this schedules the send as a
        background task and returns right away.

        Args:
            call_context: specific details actually discussed (business
                type, budget mentioned, timeline, features requested)
            tone: "hot" or "cold" — controls message style
        """
        tone = tone.lower().strip()
        if tone not in ("hot", "cold"):
            tone = "hot"

        if self._mid_call_whatsapp_sent:
            return "Mid-call WhatsApp was already sent for this call; no duplicate send."

        # In case classify_lead already recorded this tone and discovery is
        # now sufficient, this alone can satisfy the send — avoids rejecting
        # a call that's actually ready just because this path re-derives
        # discovery-completeness slightly differently below.
        if self._last_classification == "unclassified":
            self._last_classification = tone
            self._classification_reasoning = call_context
        await self._try_fire_mid_call()
        if self._mid_call_whatsapp_sent:
            return "WhatsApp message is being sent now in the background."

        if self._discovery_complete():
            # Structured discovery wins — it's language-agnostic and always
            # in English, unlike raw transcript text or free-form LLM text.
            structured = self._discovery_context()
            call_context = f"{structured} — {call_context}".strip(" —") if call_context else structured
        elif not _has_required_discovery(call_context):
            transcript_context = await self._get_transcript_context(call_context)
            if not _has_required_discovery(transcript_context):
                return (
                    "Not enough discovery yet to send the mid-call WhatsApp; call "
                    "update_discovery for catalog size, timeline, features, and "
                    "budget first."
                )
            call_context = transcript_context

        # Do not await this inline, or it blocks the voice loop.
        self._schedule_mid_call_whatsapp(call_context, tone)
        return "WhatsApp message is being sent now in the background."

    # ---- Tool: book_callback ----
    @function_tool
    async def book_callback(
        self,
        context: RunContext,
        natural_time_phrase: str,
    ) -> str:
        """
        Parse a spoken time phrase into an actual callback datetime, record
        it, and fire the "I'll send follow-up details" WhatsApp
        confirmation (template 1) in the background. Do not also call
        send_whatsapp_now for this lead — this tool already sends it.

        Args:
            natural_time_phrase: the caller's own words, e.g.
                "tomorrow morning", "Thursday afternoon", "next week"
        """
        parsed = parse_callback_time(natural_time_phrase)
        await storage.record_callback(
            self.call_id, natural_time_phrase, parsed.isoformat()
        )
        confirmation = format_confirmation(parsed)
        logger.info("Callback booked: '%s' -> %s", natural_time_phrase, parsed.isoformat())
        self._schedule_callback_whatsapp(natural_time_phrase, confirmation)
        return (
            f"Callback booked for {confirmation}. A WhatsApp confirmation is being sent now. "
            "Confirm the time back to the caller, mention the WhatsApp is on its way, then wrap "
            "up: call end_call_summary and hang_up."
        )

    # ---- Tool: end_call_summary ----
    @function_tool
    async def end_call_summary(self, context: RunContext) -> str:
        """
        Call this once, right before saying goodbye. Triggers the post-call
        WhatsApp summary assembly (context + resume + number + diagram).
        """
        await self._send_summary()
        return "Post-call summary was sent."

    async def _send_summary(self):
        if self._summary_sent:
            return

        call = await storage.get_call(self.call_id)
        classification = call["current_classification"] if call else "unclassified"
        callback = await storage.get_latest_callback(self.call_id)

        # Structured discovery is preferred: it's always in English and
        # per-field, regardless of what language the call happened in.
        # Raw transcript text is only a fallback for a call that never got
        # through discovery (e.g. hung up early).
        structured = self._discovery_context()
        if structured:
            context_paragraph = f"On the call we covered — {structured}."
        elif callback and callback.get("raw_phrase"):
            # No discovery to summarize (e.g. caller said "I don't have
            # time" before we got anywhere) — say that plainly instead of
            # dumping the raw "Agent: ... Caller: ..." transcript into the
            # message. A pasted log fails "written like a person" review.
            context_paragraph = "We didn't get into the details on this call since it wasn't a good time to talk."
        else:
            raw_context = await self._get_transcript_context()
            context_paragraph = (
                f"On the call, here's roughly what came up: {raw_context[-800:]}"
                if raw_context
                else "We had a good initial conversation about building an e-commerce site."
            )

        if callback and callback.get("raw_phrase"):
            try:
                callback_dt = datetime.fromisoformat(callback["parsed_datetime_iso"])
                confirmation = format_confirmation(callback_dt)
            except (KeyError, TypeError, ValueError):
                confirmation = callback["raw_phrase"]
            context_paragraph += f" I'll call you back {confirmation} like we agreed."

        success = await whatsapp.send_post_call_summary(
            context_paragraph, classification, self._caller_name, self._phone_number
        )
        await storage.record_whatsapp_send(
            self.call_id,
            "post_call_summary",
            {"context": context_paragraph, "classification": classification},
            success,
        )
        self._summary_sent = True
        logger.info("Post-call WhatsApp summary completed (success=%s)", success)

    async def _wait_for_whatsapp(self):
        if self._whatsapp_tasks:
            await asyncio.gather(*self._whatsapp_tasks, return_exceptions=True)

    @function_tool
    async def hang_up(self, context: RunContext) -> str:
        """End the phone call after the final goodbye has finished playing."""
        self._hangup_requested = True
        context.speech_handle.add_done_callback(self._schedule_hangup)
        return "Goodbye. The call will end after this final message."

    def _schedule_hangup(self, _speech_handle):
        if self._hangup_task is None or self._hangup_task.done():
            self._hangup_task = asyncio.create_task(self._finish_call())

    async def _finish_call(self):
        await self._wait_for_whatsapp()
        await self._send_summary()
        sip_participant = next(
            (
                participant
                for participant in self.job_ctx.room.remote_participants.values()
                if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
            ),
            None,
        )
        if sip_participant is None:
            logger.info("SIP participant already disconnected")
            return

        try:
            await self.job_ctx.api.room.remove_participant(
                api.RoomParticipantIdentity(
                    room=self.job_ctx.room.name,
                    identity=sip_participant.identity,
                )
            )
            logger.info("Call ended by agent")
        except Exception:
            logger.exception("Agent hangup failed")


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    call_id = str(uuid.uuid4())
    # phone number is passed via job metadata by scripts/make_call.py
    phone_number = ctx.job.metadata or os.getenv("TARGET_PHONE_NUMBER", "unknown")

    await storage.init_db()
    await storage.create_call(call_id, ctx.room.name, phone_number)

    tts = sarvam.TTS(
        target_language_code=os.getenv("SARVAM_TTS_LANGUAGE", "en-IN"),
        model=os.getenv("SARVAM_TTS_MODEL", "bulbul:v3"),
        speaker=os.getenv("SARVAM_TTS_SPEAKER", "shubh"),
    )

    llm_kwargs = {
        "model": os.getenv("SARVAM_LLM_MODEL", "sarvam-105b-conversations"),
        "api_key": os.getenv("SARVAM_API_KEY"),
        "extra_headers": {"X-Title": "ElevateBox Voice Agent"},
        "temperature": 0.2,
        "max_tokens": 350,
        "timeout": httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=30.0),
    }
    if base_url := os.getenv("SARVAM_LLM_BASE_URL"):
        llm_kwargs["base_url"] = base_url

    session = AgentSession(
        turn_detection="stt",
        min_endpointing_delay=0.07,
        stt=sarvam.STT(
            language=os.getenv("SARVAM_STT_LANGUAGE", "unknown"),
            model=os.getenv("SARVAM_STT_MODEL", "saaras:v3"),
            mode=os.getenv("SARVAM_STT_MODE", "transcribe"),
            flush_signal=True,
        ),
        llm=sarvam.LLM(**llm_kwargs),
        tts=tts,
    )

    agent = ElevateBoxSalesAgent(call_id=call_id, ctx=ctx, phone_number=phone_number)

    # Log every turn to storage so end_call_summary can build real context
    pending_turns = set()

    def _track_turn(coro):
        task = asyncio.create_task(coro)
        pending_turns.add(task)
        task.add_done_callback(pending_turns.discard)

    # NOTE: "user_speech_committed" / "agent_speech_committed" are not real
    # events on this version of livekit-agents (1.7.x) — the actual events
    # are "conversation_item_added" (both roles, once the turn is finalized)
    # and "user_input_transcribed" (STT result, carries the detected
    # language directly). session.on() doesn't validate event names, so the
    # old handlers registered here silently never fired: no transcript turn
    # was ever logged, and the per-turn TTS language switch below never ran
    # on a single real call. Confirmed by every row in transcript_turns
    # being empty across every call in call_data.db.
    @session.on("conversation_item_added")
    def _on_conversation_item(event):
        item = event.item
        role = getattr(item, "role", None)
        text = getattr(item, "text_content", None)
        if not text:
            return
        if role == "user":
            _track_turn(storage.log_turn(call_id, "caller", text))
        elif role == "assistant":
            _track_turn(storage.log_turn(call_id, "agent", text))

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(event):
        if not event.is_final:
            return

        spoken_text = event.transcript or ""
        detected_metadata = normalize_tts_language(event.language or "")
        selected_locale = resolve_tts_language(spoken_text, detected_metadata)

        if selected_locale:
            current = getattr(tts._opts, "target_language_code", None)
            if current != selected_locale:
                tts.update_options(target_language_code=selected_locale)
                logger.info(
                    "TTS language selected: %s (source=%s)",
                    selected_locale,
                    "text" if detect_tts_language_from_text(spoken_text) != "en-IN" else "metadata or fallback",
                )

    async def _on_shutdown():
        if not watchdog_task.done():
            watchdog_task.cancel()
        if pending_turns:
            await asyncio.gather(*pending_turns, return_exceptions=True)
        await agent._wait_for_whatsapp()
        await agent._send_summary()
        await storage.end_call(call_id)

    ctx.add_shutdown_callback(_on_shutdown)

    # Safety net: if the LLM books a callback (or otherwise ends the useful
    # part of the conversation) and never calls hang_up, the call stays live
    # and keeps burning Twilio minutes. Force it closed after a generous
    # ceiling rather than trusting tool-call compliance alone.
    max_call_seconds = float(os.getenv("MAX_CALL_DURATION_SECONDS", "360"))

    async def _call_duration_watchdog():
        await asyncio.sleep(max_call_seconds)
        if not agent._hangup_requested:
            logger.warning(
                "Call exceeded %.0fs without hang_up being called — forcing hangup",
                max_call_seconds,
            )
            agent._hangup_requested = True
            agent._schedule_hangup(None)

    watchdog_task = asyncio.create_task(_call_duration_watchdog())

    await session.start(room=ctx.room, agent=agent)

    await session.generate_reply(
        instructions=(
            "Greet the person who just picked up, introduce yourself by "
            "name, and warmly ask for their name before anything else — "
            "e.g. 'and who am I speaking with?'. Keep it short and natural. "
            "Do not ask about their time or the website yet; that's the "
            "next turn, after they give their name."
        )
    )


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="elevatebox-sales-agent",
        )
    )
