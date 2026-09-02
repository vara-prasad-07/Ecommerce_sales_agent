# Project Details — What Was Done

This documents a review-and-improve pass over the existing ElevateBox voice
agent codebase, done against the assignment brief
(`ElevateBox_SDE_Intern_Assignment.pdf`). No live call was placed as part of
this pass (no telephony/API access from this session) — everything below was
verified by reading the code, running the unit test suite, and a direct
smoke test of the storage layer.

## Starting point

The project was already substantially built: LiveKit Agents orchestration,
Twilio SIP trunk for outbound calling, Sarvam AI for STT/TTS/LLM, a system
prompt handling English/Hindi/Telugu, tool-calling for classification,
callback booking, and WhatsApp sends, plus a SQLite call log. Target number
and WhatsApp recipient were already set to `+917658975169` in `.env`.

## Critical bug fixed: post-call WhatsApp ignored the actual call

`agent/whatsapp.py` had two functions — `_build_post_call_summary` and
`_build_template_2_intro` — that were **hardcoded to fixed strings**,
completely ignoring the `call_context_paragraph` argument passed in. In
practice this meant the post-call WhatsApp (the message required by
assignment Section 06) never actually contained anything from the
conversation — it always sent the same generic text regardless of what the
caller said, their budget, timeline, or classification. This directly fails
Section 06 requirement #1 ("the context of our call... specifics from the
conversation, not a summary that could apply to anyone") and would have cost
points on "Follow up and WhatsApp quality" in the scorecard. A test in the
existing suite had actually locked in this broken behavior with a hardcoded
assertion.

**Fixed:** the post-call message now embeds a real, structured summary of
what was discovered, framed as a natural follow-up sentence, plus a short
classification tag (Hot/Warm/Cold). The mid-call `tone` parameter (also
previously computed but silently discarded) now actually changes the
message wording.

## Structural fix: language-agnostic discovery tracking

The gate that decides "has enough been discovered to fire the mid-call
WhatsApp" (`_has_required_discovery` in `agent/main.py`) worked by scanning
the raw transcript for **English keyword phrases** like "what do you sell"
or "budget". This is a real problem for this assignment specifically: if a
call happens in Hindi or Telugu (which the whole system is built to
support), the transcript never contains those English phrases, so the gate
could silently never pass — meaning the mid-call WhatsApp (15 points on the
rubric) might never fire on a non-English call, and the post-call summary
would fall back to pasting raw Telugu/Hindi transcript text into an English
WhatsApp message.

**Fixed** by adding a new tool, `update_discovery(category, catalog_size,
timeline, features, budget)`, that the LLM calls after every discovery
answer — instructed (via `agent/prompts.py`) to always record the value in
English regardless of what language the caller used. This is language
extraction work the LLM is already good at, done once, instead of asking a
regex to re-derive it from raw text. The mid-call gate, the mid-call
message, and the post-call summary now all prefer this structured English
state over raw transcript scraping. The old English-keyword heuristic is
kept only as a fallback (documented in the code) for the text-mode test
harness or in case the LLM skips the tool.

Also added: the post-call summary now includes the booked callback time
(if any) — previously that information was captured but never surfaced in
the follow-up message.

## Follow-up round: two issues reported after a live call

After the fixes above, a real call surfaced two more issues, fixed in this
round:

### 1. Agent never asked for the caller's name

The opening `generate_reply` instructions went straight to "ask if they have
a couple of minutes" — the caller's name was never requested, so the whole
call happened without a name to build rapport around.

**Fixed:**
- The greeting instructions in `agent/main.py` (`entrypoint`) now explicitly
  ask for the caller's name first, before anything else.
- A new tool, `record_caller_name(name)`, captures it once given.
- `agent/prompts.py` instructs the agent to use the name naturally a few
  times through the call (not every sentence) — in the pitch, when
  confirming details, at close.
- The post-call WhatsApp now opens with "Hi {name}!" when a name was
  captured (`agent/whatsapp.py::_build_template_2_intro`), which also makes
  that message read more like a real personal follow-up.

### 2. Code-mixed Telugu/Hindi input got an English-only reply

Reported symptom: speaking "Teluguish" (Telugu + English mixed in the same
turn) was transcribed and understood correctly (STT was fine), but the
agent's *reply* came back in English only — not the required
Telugu/Hindi/mixed output.

**Root cause:** the system prompt's language rules (pure English / pure
Hindi / pure Telugu / Romanized Telugu / code-mixed / Telugu-priority) were
the *only* signal guiding the LLM's reply language, re-derived from the
whole conversation on every turn. There was no explicit, current, per-turn
signal — the model tended to default to English whenever the input mixed
languages, since the instruction is easy to under-weight with nothing to
force it. Separately, the code already computed a decent guess of what
language the caller had just used (`detect_tts_language_from_text`, used
only to pick the TTS voice) — that signal was never fed back to the LLM
that generates the actual reply text, so the TTS voice could be set to
Telugu while the underlying text was still English.

**Fixed** with two changes in `agent/main.py`:
- New function `classify_caller_turn(text)`, more precise than the existing
  TTS-voice heuristic: it distinguishes *pure* Telugu/Hindi from
  *code-mixed* Telugu+English/Hindi+English, using script detection
  (Telugu/Devanagari Unicode ranges) plus a word-level marker ratio for
  Romanized input.
- `ElevateBoxSalesAgent.on_user_turn_completed` (a LiveKit Agents hook that
  runs right before each LLM call) now injects a short, explicit system
  message — e.g. *"the caller just code-switched between Telugu and
  English... mirror that exact blend... do NOT reply in pure English"* —
  computed fresh from what the caller just said. The system prompt
  (`agent/prompts.py`) tells the model this cue is authoritative for that
  reply. This turns "hope the model infers the rule correctly from a long
  system prompt" into "tell it exactly what to do, every single turn."
- Also fixed a real bug found while touching this code:
  `detect_tts_language_from_text`'s Hindi-marker list included generic
  English sales words — "budget", "timeline", "website", "product",
  "features" — meaning a purely English sentence discussing the pitch could
  get mis-routed to the Hindi TTS voice. Removed; those aren't language
  signals.
- `scripts/test_conversation_text.py` mirrors both changes (name tool +
  per-turn language cue) so the free text-mode iteration loop tests the
  same behavior as a real call.

New tests: `test_classify_caller_turn_*` (pure English / pure Telugu script
/ Telugu-script-plus-English is code-mixed / Romanized Telugu / Romanized
Hindi), `test_on_user_turn_completed_injects_language_cue_for_code_mixed_telugu`
+ `test_on_user_turn_completed_no_cue_for_pure_english`,
`test_record_caller_name_sets_instance_state`,
`test_post_call_intro_greets_caller_by_name_when_known`. All 23 tests pass
(`python -m unittest tests.test_whatsapp_twilio`).

**Still worth watching on the next real call:** this fix makes the LLM's
*input* unambiguous about which language to reply in — it removes the
excuse, but Sarvam's model still has to comply. If you still see occasional
English replies to code-mixed input after this, the next lever to pull is
tightening `LANGUAGE_TURN_HINTS` wording further or lowering LLM
`temperature` (currently 0.2) for stricter instruction-following.

## Other changes

- `agent/storage.py`: added a `discovery_json` column (with a safe migration
  for the existing `call_data.db`) and `set_discovery` / `get_latest_callback`
  functions.
- `scripts/test_conversation_text.py`: added `update_discovery` to the tool
  list so the free text-mode iteration loop exercises the same logic as a
  real call.
- `tests/test_whatsapp_twilio.py`: fixed the test that had locked in the
  hardcoded post-call bug, added tests for tone-aware mid-call messages,
  structured discovery tracking, and a regression test proving the mid-call
  WhatsApp now fires from a call with **zero English discovery keywords**
  (simulating a Telugu-only call) — this would have failed before the fix.
- Removed dead code/config that didn't match the actual implementation:
  an unused `_extract_website_purpose` function, unused
  `livekit-plugins-groq` / `groq` / `livekit-plugins-openai` requirements,
  and unused `DEEPGRAM_API_KEY` / `AZURE_SPEECH_*` / `WHATSAPP_ACCESS_TOKEN`
  / `WHATSAPP_PHONE_NUMBER_ID` env vars (leftovers from an earlier version —
  the actual stack is Sarvam for STT/TTS/LLM and Twilio for WhatsApp, not
  Deepgram/Azure/Meta Cloud API).
- Added `TWILIO_WHATSAPP_FROM` and `TWILIO_TERMINATION_URI` to
  `.env.example` — both are required by the real code but were missing from
  the example file, so a fresh setup from the README would have hit
  confusing errors.
- README and `templates/architecture_diagram_prompt.md` updated to describe
  the stack that's actually in the code (Sarvam STT/TTS/LLM + Twilio
  WhatsApp) instead of the stale Groq/Deepgram/ElevenLabs/Meta description.

## Changing the target number later

Two env vars control this, both in `.env`:
- `TARGET_PHONE_NUMBER` — who `scripts/make_call.py` dials by default (can
  also be overridden per-run: `python scripts/make_call.py +91XXXXXXXXXX`)
- `WHATSAPP_RECIPIENT_NUMBER` — who receives both WhatsApp messages

Both are currently `+917658975169`. Change both together unless you
specifically want the call and the WhatsApp to go to different people.

## What's still unverified

No real phone call, LiveKit connection, or WhatsApp send was tested in this
session — there's no telephony access here. Before submitting:

1. Run `python scripts/preflight_check.py` — confirms credentials are valid.
2. Run `python scripts/test_conversation_text.py` and walk through a Hot, a
   Warm, and a Cold path in text to sanity-check discovery, classification,
   and the mid-call WhatsApp firing (including in Hindi/Telugu — this is the
   main thing this pass changed, so it's worth specifically re-testing).
3. Specifically re-test the two follow-up fixes on a real call: confirm the
   agent asks for your name near the start and uses it later, and try
   answering a question in code-mixed Teluguish/Hinglish to confirm the
   reply mirrors that blend instead of dropping into pure English.
4. Place one real test call to a number you control before calling
   `+917658975169`.
5. Double-check the architecture diagram already hosted at
   `ARCHITECTURE_DIAGRAM_URL` still matches the real stack (Sarvam, not
   Deepgram/ElevenLabs) — the old `architecture_diagram_prompt.md` had the
   wrong providers, so if the diagram was drawn from that version it may
   need a small correction.

## Optimization pass: scorecard walkthrough against the actual `.env`

This pass re-read the assignment PDF's scorecard line by line against the
live code and the real (filled-in) `.env`, not just `.env.example`, and
fixed what didn't hold up. All 33 tests pass
(`python -m unittest discover -s tests`).

### 1. Resume link was not fetchable (Section 06 item 4 / "Follow up and WhatsApp quality")

`RESUME_PUBLIC_URL` in `.env` was a Google Drive `.../view?usp=sharing`
link. Confirmed by curling it directly: it returns `text/html` (Drive's
viewer page), not the PDF — so the WhatsApp media fetch for the resume
would have failed or attached the wrong thing. **Fixed** by switching to
the direct-download form
(`https://drive.google.com/uc?export=download&id=<FILE_ID>`), confirmed by
curl to now return `application/octet-stream` at the correct file size.
Updated `.env.example`'s comment to explain this so it doesn't regress.

### 2. Caller's name was captured but never reached WhatsApp

`record_caller_name` / `self._caller_name` existed and were used to
address the caller mid-call, but neither `send_mid_call_message` nor
`send_post_call_summary` ever received it — the WhatsApp messages never
opened with "Hi {name}!" despite the name being known. (An earlier version
of this doc claimed this was already wired up via
`_build_template_2_intro`; that function doesn't exist in the current code,
so either it regressed or the doc was aspirational — either way it wasn't
true of the code as found.) **Fixed**: `agent/whatsapp.py`'s
`_build_template_3_context` and `_mid_call_template_message` now accept a
`caller_name` and prefix "Hi {name}!" when known; `agent/main.py` and
`scripts/test_conversation_text.py` now thread `self._caller_name` /
`state["caller_name"]` through to both call sites. New tests:
`test_post_call_summary_greets_caller_by_name_when_known`,
`test_send_summary_passes_caller_name_through`.

### 3. Callback scheduling could book a time in the past

`parse_callback_time("call me back later today")` with no explicit clock
time defaulted to 10 AM regardless of the actual current time — if the
call happened at, say, 3 PM, this booked a callback 5 hours in the past.
**Fixed**: `agent/scheduling.py` now rolls the result forward one day if
the resolved datetime is `<= now`. Added `tests/test_scheduling.py` (8
tests, previously zero coverage on this file) covering this regression plus
tomorrow/weekday/next-week/explicit-time cases.

### 4. Leftover dead config removed from `.env`

`WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID` (Meta Cloud API
vars) were still sitting in the real `.env` — including a live-looking
access token — even though the actual send path is Twilio and nothing in
`agent/` reads either var (confirmed by grep). Removed.

### Verified correct, no change needed

- Interruption/barge-in: `livekit-agents` defaults `allow_interruptions` to
  `True` at the `SpeechHandle` level, so callers talking over the agent is
  already handled by the framework, not something this code turned off.
- The mid-call WhatsApp gate requiring ~4/5 discovery fields before firing
  (even for a Hot classification) is a deliberate, tested tradeoff — not a
  bug — to satisfy the *other* scorecard line ("references real content...
  not a summary that could apply to anyone"). Loosening it risks firing a
  near-empty WhatsApp on a fast Hot lead. Left as-is.
- Resume/architecture-diagram delivery as actual WhatsApp attachments
  (rather than a link a human has to click) depends on how the two Twilio
  Content Templates were built in the Twilio console (whether variables 5
  and 6 are bound to a `twilio/media` field). That's outside this
  codebase — worth a quick check in the Twilio console before submitting.

### Still needs a human decision before the real submission call

- `TARGET_PHONE_NUMBER` and `WHATSAPP_RECIPIENT_NUMBER` in `.env` are both
  currently `+919885541788` — a personal test number, not the assignment's
  `8688664337`. Intentional for testing, but must be changed before the
  real submission call.
- Optional, not scored ("reference, not a requirement," explicitly costs no
  marks): the assignment doc suggests a female voice and light background
  noise tend to reduce hang-ups on outbound sales calls in this market.
  Current `SARVAM_TTS_SPEAKER=shubh` is a male voice for `bulbul:v3`, and no
  background audio is mixed in. Left untouched since it's a persona/style
  choice, not a functional gap — worth an A/B if there's time.

## Known limitations carried over (unchanged from before this pass)

- The time parser in `scheduling.py` is rule-based, not a full NLP date
  parser — handles common phrasings well, falls back to a sane default
  otherwise.
- `send_whatsapp_now` is fire-and-forget; a WhatsApp API failure is logged
  to SQLite but not retried or read back to the caller.
- Both WhatsApp messages go through pre-approved Twilio Content Templates
  with a fixed number of variable slots (see `MID_CALL_TEMPLATE_SID` /
  `POST_CALL_TEMPLATE_SID` in `agent/whatsapp.py`) — if those templates are
  ever re-approved with different wording, double check the variable
  mapping still lines up with what's being sent.
