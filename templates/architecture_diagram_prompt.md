# Architecture diagram — what to draw

Per Section 06 of the assignment: "One image showing your architecture and
flow. Hand drawn on paper is fine. We want to see how you think, not how
well you use a diagram tool."

Draw (or diagram) this flow, matching what's actually in this codebase:

```
[make_call.py] --dispatches--> [LiveKit Agent Worker]
                                        |
                          [CreateSIPParticipant via Twilio Trunk]
                                        |
                                  dials +91 76589 75169
                                        |
                                  call answered
                                        |
                    +-------------------+-------------------+
                    |                                        |
              Caller speaks                            Agent speaks
                    |                                        |
              Sarvam STT                              Sarvam TTS
              (Telugu/Hindi/English)                  (per-turn language switch)
                    |                                        ^
                    v                                        |
              +-------------------------------------------------+
              |   Sarvam LLM decision engine (agent/main.py)      |
              |  - update_discovery (records answers, in English)  |
              |  - classify_lead (hot/warm/cold)                     |
              |  - send_whatsapp_now (mid-call, async, non-blocking)  |
              |  - book_callback (parses spoken time)                  |
              |  - end_call_summary (post-call trigger)                 |
              +-------------------------------------------------+
                    |                    |                |
                    v                    v                v
            SQLite storage       Twilio WhatsApp API   scheduling.py
         (transcript, discov-    (mid-call message +   (time phrase ->
          ery, classification,   post-call summary +    datetime)
          callbacks)              resume + diagram)
```

Simplify this for a hand-drawn version — boxes and arrows are enough. What
matters per the rubric is that it clearly shows: call in → understanding →
decision engine → actions firing out while the call is still live. That
last part (actions firing DURING the call, not after) is worth calling out
explicitly since it's a scored line item.

Once drawn, take a photo or scan, host it somewhere with a public direct
link (e.g. upload to Google Drive → "Anyone with the link" → use a
direct-image link, or any public image host), and put that URL in
`ARCHITECTURE_DIAGRAM_URL` in your `.env` file.
