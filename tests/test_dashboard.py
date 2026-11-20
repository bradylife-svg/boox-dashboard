"""日曆解析與版面文字。不連外網，也不含真實行程。"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generate_dashboard as dash  # noqa: E402

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 11, 20, 6, 5, tzinfo=TZ)


ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//boox//EN
X-WR-CALNAME:測試日曆
X-WR-TIMEZONE:Asia/Taipei
BEGIN:VEVENT
UID:allday-span
DTSTART;VALUE=DATE:20261121
DTEND;VALUE=DATE:20261123
SUMMARY:全天兩日
END:VEVENT
BEGIN:VEVENT
UID:daily-utc
DTSTART:20261120T010000Z
DTEND:20261120T020000Z
RRULE:FREQ=DAILY;COUNT=3
SUMMARY:每日例會
END:VEVENT
BEGIN:VEVENT
UID:cancelled
DTSTART;TZID=Asia/Taipei:20261120T150000
DTEND;TZID=Asia/Taipei:20261120T160000
SUMMARY:已取消
STATUS:CANCELLED
END:VEVENT
BEGIN:VEVENT
UID:weekly
DTSTART;TZID=Asia/Taipei:20261116T070000
DTEND;TZID=Asia/Taipei:20261116T080000
RRULE:FREQ=WEEKLY;BYDAY=MO
EXDATE;TZID=Asia/Taipei:20261130T070000
SUMMARY:每週一
END:VEVENT
BEGIN:VEVENT
UID:before
DTSTART;VALUE=DATE:20261118
DTEND;VALUE=DATE:20261121
SUMMARY:跨到今天
END:VEVENT
END:VCALENDAR
"""


class SplitUrlTests(unittest.TestCase):
    def test_blank_is_empty(self) -> None:
        self.assertEqual(dash.split_ics_urls(None), [])
        self.assertEqual(dash.split_ics_urls("  \n  "), [])

    def test_newline_and_comma(self) -> None:
        raw = " https://example.com/a.ics , https://example.com/b.ics\nhttps://example.com/c.ics "
        self.assertEqual(
            dash.split_ics_urls(raw),
            [
                "https://example.com/a.ics",
                "https://example.com/b.ics",
                "https://example.com/c.ics",
            ],
        )


class IcsTests(unittest.TestCase):
    def setUp(self) -> None:
        window_start = datetime(2026, 11, 20, tzinfo=TZ)
        window_end = datetime(2026, 11, 27, tzinfo=TZ)
        self.events = dash.events_from_ics(ICS, "日曆 1", window_start, window_end)
        self.by_summary: dict[str, list[dash.CalendarEvent]] = {}
        for event in self.events:
            self.by_summary.setdefault(event.summary, []).append(event)

    def test_recurring_utc_becomes_taipei(self) -> None:
        meetings = self.by_summary["每日例會"]
        self.assertEqual(len(meetings), 3)
        self.assertEqual(meetings[0].start, "2026-11-20T09:00:00+08:00")
        self.assertEqual(meetings[0].end, "2026-11-20T10:00:00+08:00")
        self.assertFalse(meetings[0].all_day)
        self.assertEqual(dash.format_event_time(meetings[0]), "09:00–10:00")

    def test_all_day_exclusive_end(self) -> None:
        event = self.by_summary["全天兩日"][0]
        self.assertTrue(event.all_day)
        days = dash.event_dates_in_range(event, datetime(2026, 11, 20).date(), datetime(2026, 11, 26).date())
        self.assertEqual([day.isoformat() for day in days], ["2026-11-21", "2026-11-22"])
        self.assertEqual(dash.format_event_time(event), "全天")

    def test_cancelled_is_dropped(self) -> None:
        self.assertNotIn("已取消", self.by_summary)

    def test_weekly_inside_window_only(self) -> None:
        # 11/16 在窗外出、11/23 在窗內、11/30 被 EXDATE 排除且超出七日。
        mondays = self.by_summary["每週一"]
        self.assertEqual(len(mondays), 1)
        self.assertEqual(mondays[0].start, "2026-11-23T07:00:00+08:00")

    def test_event_started_earlier_still_shows_today(self) -> None:
        event = self.by_summary["跨到今天"][0]
        days = dash.event_dates_in_range(event, datetime(2026, 11, 20).date(), datetime(2026, 11, 26).date())
        self.assertEqual([day.isoformat() for day in days], ["2026-11-20"])

    def test_calendar_name(self) -> None:
        self.assertEqual(self.events[0].calendar, "測試日曆")


class RenderTests(unittest.TestCase):
    def test_missing_secret_message(self) -> None:
        page = dash.render_html(
            dash.Weather(source="Open-Meteo", ok=False, error="略過"),
            dash.not_configured_calendar(),
            dash.MarketData(),
            NOW,
        )
        self.assertIn("尚未設定日曆", page)
        self.assertIn("本週行程", page)
        self.assertIn('name="viewport"', page)
        self.assertIn("width=1860", page)
        self.assertIn('location.protocol === "file:"', page)
        self.assertNotIn("minimum-scale=1", page)
        self.assertNotIn("private-", page)
        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)

    def test_grouped_week_uses_taipei_days(self) -> None:
        window_start = datetime(2026, 11, 20, tzinfo=TZ)
        window_end = datetime(2026, 11, 27, tzinfo=TZ)
        events = dash.events_from_ics(ICS, "日曆 1", window_start, window_end)
        week = dict(dash.group_week_events(events, NOW.date(), 7))
        self.assertEqual(len(week), 7)
        self.assertTrue(any(event.summary == "每日例會" for event in week[NOW.date()]))
        self.assertTrue(any(event.summary == "全天兩日" for event in week[datetime(2026, 11, 21).date()]))
        self.assertTrue(any(event.summary == "全天兩日" for event in week[datetime(2026, 11, 22).date()]))
        self.assertFalse(any(event.summary == "全天兩日" for event in week[datetime(2026, 11, 23).date()]))

    def test_http_error_hides_url(self) -> None:
        secret = "http://127.0.0.1:1/private-token-do-not-log"
        with self.assertRaises(RuntimeError) as ctx:
            dash.http_get_text(secret, timeout=1.0)
        message = str(ctx.exception)
        self.assertNotIn("private-token", message)
        self.assertNotIn("127.0.0.1", message)


if __name__ == "__main__":
    unittest.main()
