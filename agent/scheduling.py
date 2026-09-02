"""
Turns a spoken time phrase ("tomorrow morning", "Thursday afternoon",
"next week sometime") into an actual datetime.

This is intentionally a pragmatic rule-based parser rather than a full NLP
date parser, because the LLM has already done the hard work of extracting
the phrase from natural speech — this module just needs to resolve common
relative-time patterns reliably. Falls back to a sensible default
(tomorrow, 10 AM IST) if nothing matches, rather than failing the call flow.
"""

import re
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

DAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

TIME_OF_DAY_DEFAULTS = {
    "morning": dtime(10, 0),
    "afternoon": dtime(15, 0),
    "evening": dtime(18, 30),
    "night": dtime(20, 0),
    "noon": dtime(12, 0),
}


def parse_callback_time(phrase: str, now: datetime | None = None) -> datetime:
    """
    Best-effort parse of a natural callback phrase into an IST datetime.
    Always returns something usable — never raises.
    """
    now = now or datetime.now(IST)
    phrase_lower = phrase.lower().strip()

    target_date = now.date()
    target_time = dtime(10, 0)  # default: 10 AM

    # explicit "tomorrow"
    if "tomorrow" in phrase_lower:
        target_date = (now + timedelta(days=1)).date()
    # explicit "next week"
    elif "next week" in phrase_lower:
        target_date = (now + timedelta(days=7)).date()
    # named weekday, e.g. "thursday" or "on thursday"
    else:
        for name, weekday_idx in DAY_NAMES.items():
            if name in phrase_lower:
                days_ahead = (weekday_idx - now.weekday()) % 7
                # if they say a day that IS today, assume they mean next week's
                if days_ahead == 0:
                    days_ahead = 7
                target_date = (now + timedelta(days=days_ahead)).date()
                break
        else:
            # "today", "later", or nothing matched: default to tomorrow
            # rather than assuming today (safer for a callback promise)
            if "today" in phrase_lower:
                target_date = now.date()
            else:
                target_date = (now + timedelta(days=1)).date()

    # time of day
    for tod_name, tod_default in TIME_OF_DAY_DEFAULTS.items():
        if tod_name in phrase_lower:
            target_time = tod_default
            break

    # explicit clock time, e.g. "3 pm", "10:30 am", "5 o'clock"
    match = re.search(r"(\d{1,2})(:(\d{2}))?\s*(am|pm)?", phrase_lower)
    if match and (match.group(4) or ":" in phrase_lower):
        hour = int(match.group(1))
        minute = int(match.group(3) or 0)
        meridiem = match.group(4)
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23:
            target_time = dtime(hour, minute)

    result = datetime.combine(target_date, target_time, tzinfo=IST)

    # "call me back later today" (no explicit time) or "this evening" said
    # after the default time has already passed would otherwise book a
    # callback in the past. If the resolved time has already gone, treat it
    # as a promise for the same time tomorrow instead.
    if result <= now:
        result += timedelta(days=1)

    return result


def format_confirmation(dt: datetime) -> str:
    """Human-readable confirmation string, e.g. 'Thursday at 10:00 AM'."""
    return dt.strftime("%A at %I:%M %p").replace(" 0", " ")
