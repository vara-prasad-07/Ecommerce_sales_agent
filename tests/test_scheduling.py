import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from agent.scheduling import parse_callback_time, format_confirmation

IST = ZoneInfo("Asia/Kolkata")


class SchedulingTests(unittest.TestCase):
    def test_tomorrow_morning(self):
        now = datetime(2026, 3, 4, 14, 0, tzinfo=IST)  # a Wednesday
        result = parse_callback_time("call me back tomorrow morning", now=now)
        self.assertEqual(result.date().isoformat(), "2026-03-05")
        self.assertEqual(result.hour, 10)

    def test_named_weekday_in_the_future(self):
        now = datetime(2026, 3, 4, 14, 0, tzinfo=IST)  # Wednesday
        result = parse_callback_time("Thursday afternoon works", now=now)
        self.assertEqual(result.date().isoformat(), "2026-03-05")
        self.assertEqual(result.hour, 15)

    def test_same_weekday_as_today_means_next_week(self):
        now = datetime(2026, 3, 4, 14, 0, tzinfo=IST)  # Wednesday
        result = parse_callback_time("let's talk Wednesday", now=now)
        self.assertEqual(result.date().isoformat(), "2026-03-11")

    def test_later_today_after_default_time_rolls_to_tomorrow(self):
        """Regression: 'later today' with no explicit time used to default
        to 10 AM regardless of the current time, which could book a
        callback in the past if the call happened later in the day."""
        now = datetime(2026, 3, 4, 15, 0, tzinfo=IST)  # 3 PM
        result = parse_callback_time("call me back later today", now=now)
        self.assertGreater(result, now)
        self.assertEqual(result.date().isoformat(), "2026-03-05")

    def test_today_before_default_time_stays_today(self):
        now = datetime(2026, 3, 4, 8, 0, tzinfo=IST)  # 8 AM
        result = parse_callback_time("today please", now=now)
        self.assertEqual(result.date().isoformat(), "2026-03-04")
        self.assertGreater(result, now)

    def test_explicit_clock_time(self):
        now = datetime(2026, 3, 4, 8, 0, tzinfo=IST)
        result = parse_callback_time("call at 3:30 pm tomorrow", now=now)
        self.assertEqual(result.hour, 15)
        self.assertEqual(result.minute, 30)

    def test_never_raises_on_nonsense_input(self):
        now = datetime(2026, 3, 4, 8, 0, tzinfo=IST)
        result = parse_callback_time("uhh maybe whenever, not sure", now=now)
        self.assertGreater(result, now)

    def test_format_confirmation_is_human_readable(self):
        dt = datetime(2026, 3, 5, 10, 0, tzinfo=IST)
        self.assertEqual(format_confirmation(dt), "Thursday at 10:00 AM")


if __name__ == "__main__":
    unittest.main()
