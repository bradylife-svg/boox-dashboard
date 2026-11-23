#!/usr/bin/env python3
"""抓取晨間看板資料，產出 BOOX Go 10.3 用的灰階直向頁面。

預設尺寸 1860×2480。行程來自環境變數 GCAL_ICS_URLS（私人 Google 日曆 iCal，
可多筆，以換行或逗號分隔）。沒有設定時，行程區顯示「尚未設定日曆」，
腳本仍會產出頁面。秘密網址不會寫入頁面或日誌。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")
PAGE_WIDTH = 1860
PAGE_HEIGHT = 2480

# 新竹市
HSINCHU_LAT = 24.8138
HSINCHU_LON = 120.9675

USER_AGENT = (
    "BOOXMorningDashboard/1.0 "
    "(personal e-ink dashboard; +https://github.com/bradylife-svg/boox-dashboard)"
)

ROOT = Path(__file__).resolve().parent
DEFAULT_HTML = ROOT / "site" / "index.html"
DEFAULT_PNG = ROOT / "site" / "dashboard.png"
SNAPSHOT_NAME = "snapshot.json"
PAGES_SNAPSHOT_URL = "https://bradylife-svg.github.io/boox-dashboard/snapshot.json"
OPEN_METEO_HOSTS = (
    "https://api.open-meteo.com/v1/forecast",
    "https://previous-runs-api.open-meteo.com/v1/forecast",
)

WMO_ZH: dict[int, str] = {
    0: "晴",
    1: "大致晴朗",
    2: "多雲時晴",
    3: "陰",
    45: "霧",
    48: "霧",
    51: "微毛雨",
    53: "毛雨",
    55: "濃毛雨",
    56: "凍毛雨",
    57: "凍毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "凍雨",
    67: "凍雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "小陣雨",
    81: "陣雨",
    82: "強陣雨",
    85: "陣雪",
    86: "陣雪",
    95: "雷雨",
    96: "雷雨伴冰雹",
    99: "雷雨伴冰雹",
}

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
WEEKDAYS_SHORT = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def http_get_bytes(
    url: str,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
    *,
    redact: bool = False,
    accept: str = "application/json",
) -> bytes:
    req_headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if redact:
            raise RuntimeError(f"HTTP {exc.code}") from None
        raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        if redact:
            raise RuntimeError("網路錯誤") from None
        raise RuntimeError(f"Network error for {url}: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        if redact:
            raise RuntimeError("連線逾時") from None
        raise RuntimeError(f"Timeout for {url}: {exc}") from exc


def http_get_json(
    url: str,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
) -> Any:
    raw = http_get_bytes(url, timeout=timeout, headers=headers, redact=False)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Non-JSON response from {url}") from exc


def http_get_json_retry(
    url: str,
    attempts: int = 2,
    *,
    backoff: bool = False,
    **kwargs: Any,
) -> Any:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return http_get_json(url, **kwargs)
        except Exception as exc:  # noqa: BLE001 — surface later as unavailable
            last = exc
            if i + 1 >= attempts:
                break
            if backoff:
                time.sleep(min(8, 2**i))
    assert last is not None
    raise last


def http_get_text(url: str, timeout: float = 45.0) -> str:
    """下載文字。錯誤訊息不含網址，供私人 iCal 使用。"""
    raw = http_get_bytes(
        url,
        timeout=timeout,
        redact=True,
        accept="text/calendar, text/plain, */*",
    )
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class DayForecast:
    date: date
    condition: str
    temp_min: float | None
    temp_max: float | None
    rain_prob: int | None
    precip_mm: float | None


@dataclass
class HourlyPoint:
    time: datetime
    temp: float | None
    rain_prob: int | None


@dataclass
class Weather:
    source: str
    ok: bool
    error: str | None = None
    location: str = "新竹"
    as_of: datetime | None = None
    current_temp: float | None = None
    current_humidity: int | None = None
    current_condition: str | None = None
    days: list[DayForecast] = field(default_factory=list)
    hours: list[HourlyPoint] = field(default_factory=list)
    fetched_at: datetime | None = None
    carried: bool = False
    raw: dict[str, Any] | None = None


@dataclass
class CalendarEvent:
    summary: str
    start: str | None
    end: str | None
    all_day: bool = False
    location: str = ""
    calendar: str = ""


@dataclass
class CalendarData:
    source: str
    ok: bool
    error: str | None = None
    date: str | None = None
    range_start: str | None = None
    range_end: str | None = None
    calendars_checked: list[dict[str, Any]] = field(default_factory=list)
    events: list[CalendarEvent] = field(default_factory=list)
    not_configured: bool = False
    warnings: list[str] = field(default_factory=list)
    fetched_at: datetime | None = None
    carried: bool = False


@dataclass
class Quote:
    symbol: str
    name: str
    close: float | None
    change: float | None
    change_pct: float | None
    as_of: date | None
    currency: str = ""
    source: str = ""
    error: str | None = None
    carried: bool = False

    @property
    def ok(self) -> bool:
        return self.close is not None and self.error is None


@dataclass
class MarketData:
    indices: list[Quote] = field(default_factory=list)
    watchlist: list[Quote] = field(default_factory=list)
    fetched_at: datetime | None = None
    carried: bool = False
    partial_carry: bool = False


# ---------------------------------------------------------------------------
# Weather (Open-Meteo, no API key)
# ---------------------------------------------------------------------------

def wmo_label(code: int | None) -> str:
    if code is None:
        return "天氣不明"
    return WMO_ZH.get(int(code), f"天氣代碼 {code}")


def open_meteo_query() -> str:
    params = {
        "latitude": str(HSINCHU_LAT),
        "longitude": str(HSINCHU_LON),
        "timezone": "Asia/Taipei",
        "forecast_days": "8",
        "current": "temperature_2m,weather_code,relative_humidity_2m,precipitation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
        "hourly": "temperature_2m,precipitation_probability",
    }
    return urllib.parse.urlencode(params)


def parse_open_meteo(data: dict[str, Any], today: date | None = None) -> Weather:
    try:
        current = data.get("current") or {}
        daily = data.get("daily") or {}
        times = daily.get("time") or []
        days: list[DayForecast] = []
        for i, raw_day in enumerate(times):
            days.append(
                DayForecast(
                    date=date.fromisoformat(raw_day),
                    condition=wmo_label(_maybe_int(_at(daily.get("weather_code"), i))),
                    temp_min=_maybe_float(_at(daily.get("temperature_2m_min"), i)),
                    temp_max=_maybe_float(_at(daily.get("temperature_2m_max"), i)),
                    rain_prob=_maybe_int(_at(daily.get("precipitation_probability_max"), i)),
                    precip_mm=_maybe_float(_at(daily.get("precipitation_sum"), i)),
                )
            )
        if not days:
            return Weather(source="Open-Meteo", ok=False, error="天氣資料暫時無法取得")
        hours: list[HourlyPoint] = []
        hourly = data.get("hourly") or {}
        if today is None:
            today = datetime.now(TZ).date()
        for i, raw_t in enumerate(hourly.get("time") or []):
            try:
                when = datetime.fromisoformat(str(raw_t)).replace(tzinfo=TZ)
            except ValueError:
                continue
            if when.date() != today:
                continue
            if when.hour < 6 or when.hour > 23:
                continue
            hours.append(
                HourlyPoint(
                    time=when,
                    temp=_maybe_float(_at(hourly.get("temperature_2m"), i)),
                    rain_prob=_maybe_int(_at(hourly.get("precipitation_probability"), i)),
                )
            )
        as_of = None
        if current.get("time"):
            as_of = datetime.fromisoformat(str(current["time"])).replace(tzinfo=TZ)
        return Weather(
            source="Open-Meteo",
            ok=True,
            location="新竹",
            as_of=as_of,
            current_temp=_maybe_float(current.get("temperature_2m")),
            current_humidity=_maybe_int(current.get("relative_humidity_2m")),
            current_condition=wmo_label(_maybe_int(current.get("weather_code"))),
            days=days,
            hours=hours,
            raw=data,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"天氣資料無法解析：{exc}", flush=True)
        return Weather(source="Open-Meteo", ok=False, error="天氣資料暫時無法取得")


def fetch_weather(today: date | None = None, *, attempts: int = 4) -> Weather:
    """抓 Open-Meteo。每個主機最多試四次，失敗再換備援主機。細節只寫日誌。"""
    query = open_meteo_query()
    if today is None:
        today = datetime.now(TZ).date()
    for base in OPEN_METEO_HOSTS:
        url = base + "?" + query
        host = urllib.parse.urlparse(base).netloc
        try:
            data = http_get_json_retry(url, attempts=attempts, timeout=30, backoff=True)
        except Exception as exc:  # noqa: BLE001
            print(f"天氣下載失敗（{host}，已試 {attempts} 次）：{exc}", flush=True)
            continue
        if not isinstance(data, dict):
            print(f"天氣回應不是物件（{host}）", flush=True)
            continue
        weather = parse_open_meteo(data, today)
        if weather.ok:
            weather.fetched_at = datetime.now(TZ)
            if "previous-runs" in host:
                weather.source = "Open-Meteo previous-runs"
            return weather
        print(f"天氣內容不完整（{host}）", flush=True)
    return Weather(source="Open-Meteo", ok=False, error="天氣資料暫時無法取得")


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def split_ics_urls(raw: str | None) -> list[str]:
    """拆開 GCAL_ICS_URLS。接受換行或逗號，空白略過。"""
    if not raw:
        return []
    urls: list[str] = []
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    for line in text.split("\n"):
        for piece in line.split(","):
            piece = piece.strip()
            if piece:
                urls.append(piece)
    return urls


def load_events_from_json(path: Path) -> CalendarData:
    if not path.exists():
        return CalendarData(source="本機 JSON", ok=False, error="找不到行程檔")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return CalendarData(source="本機 JSON", ok=False, error=f"行程檔無法解析：{exc}")

    events: list[CalendarEvent] = []
    for raw in payload.get("events") or []:
        events.append(
            CalendarEvent(
                summary=_one_line(str(raw.get("summary") or "（無標題）")),
                start=raw.get("start"),
                end=raw.get("end"),
                all_day=bool(raw.get("all_day")),
                location=_one_line(str(raw.get("location") or "")),
                calendar=_one_line(str(raw.get("calendar") or "")),
            )
        )
    events.sort(key=_event_sort_key)
    return CalendarData(
        source="本機 JSON",
        ok=True,
        date=payload.get("date"),
        range_start=payload.get("range_start"),
        range_end=payload.get("range_end"),
        calendars_checked=list(payload.get("calendars_checked") or []),
        events=events,
    )


def _event_sort_key(ev: CalendarEvent) -> tuple[int, str]:
    if ev.all_day or not ev.start:
        return (0, ev.start or "")
    return (1, ev.start)


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _ical_text(component: Any, key: str) -> str:
    prop = component.get(key)
    if prop is None:
        return ""
    try:
        decoded = component.decoded(key)
    except Exception:  # noqa: BLE001
        decoded = prop
    if isinstance(decoded, bytes):
        text = decoded.decode("utf-8", errors="replace")
    elif isinstance(decoded, list):
        text = " ".join(str(item) for item in decoded)
    else:
        text = str(decoded)
    return _one_line(text)


def _to_taipei_iso(value: date | datetime) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=TZ)
        else:
            value = value.astimezone(TZ)
        return value.isoformat(timespec="seconds")
    return value.isoformat()


def _is_date_only(value: Any) -> bool:
    return isinstance(value, date) and not isinstance(value, datetime)


def events_from_ics(text: str, calendar_name: str, window_start: datetime, window_end: datetime) -> list[CalendarEvent]:
    """展開一份 iCal 裡落在 [window_start, window_end) 的行程，含重複與全天。"""
    import recurring_ical_events
    from icalendar import Calendar

    calendar = Calendar.from_ical(text)
    name = _one_line(str(calendar.get("X-WR-CALNAME") or calendar_name)) or calendar_name
    occurrences = recurring_ical_events.of(calendar).between(window_start, window_end)
    events: list[CalendarEvent] = []
    for component in occurrences:
        status = _ical_text(component, "STATUS").upper()
        if status == "CANCELLED":
            continue
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue
        start_raw = dtstart.dt
        dtend = component.get("DTEND")
        end_raw = dtend.dt if dtend is not None else None
        all_day = _is_date_only(start_raw)
        summary = _ical_text(component, "SUMMARY") or "（無標題）"
        events.append(
            CalendarEvent(
                summary=summary,
                start=_to_taipei_iso(start_raw),
                end=_to_taipei_iso(end_raw) if end_raw is not None else None,
                all_day=all_day,
                location=_ical_text(component, "LOCATION"),
                calendar=name,
            )
        )
    return events


def not_configured_calendar() -> CalendarData:
    return CalendarData(source="未設定", ok=True, not_configured=True)


def fetch_events_from_icals(urls: list[str], now: datetime) -> CalendarData:
    """下載一或多份私人 iCal。日誌與錯誤訊息都不含網址。"""
    if not urls:
        return not_configured_calendar()

    today = now.astimezone(TZ).date()
    window_start = datetime.combine(today, time.min, tzinfo=TZ)
    window_end = window_start + timedelta(days=7)
    events: list[CalendarEvent] = []
    calendars: list[dict[str, Any]] = []
    failed = 0

    for index, url in enumerate(urls, start=1):
        label = f"日曆 {index}"
        try:
            text = http_get_text(url)
            parsed = events_from_ics(text, label, window_start, window_end)
        except Exception:  # noqa: BLE001 — 不把網址或例外原文送出去
            failed += 1
            continue
        if parsed:
            name = parsed[0].calendar
        else:
            name = _calendar_name_from_ics(text, label)
        calendars.append({"name": name})
        events.extend(parsed)

    if not calendars:
        return CalendarData(
            source="Google Calendar iCal",
            ok=False,
            error="無法讀取日曆，請確認秘密網址",
            date=today.isoformat(),
            range_start=window_start.date().isoformat(),
            range_end=(window_end.date() - timedelta(days=1)).isoformat(),
        )

    events.sort(key=_event_sort_key)
    warnings: list[str] = []
    if failed:
        warnings.append(f"另有 {failed} 本日曆無法讀取。")
    return CalendarData(
        source="Google Calendar iCal",
        ok=True,
        date=today.isoformat(),
        range_start=window_start.date().isoformat(),
        range_end=(window_end.date() - timedelta(days=1)).isoformat(),
        calendars_checked=calendars,
        events=events,
        warnings=warnings,
        fetched_at=now.astimezone(TZ),
    )


def _calendar_name_from_ics(text: str, fallback: str) -> str:
    try:
        from icalendar import Calendar

        calendar = Calendar.from_ical(text)
        name = calendar.get("X-WR-CALNAME")
        if name:
            return _one_line(str(name)) or fallback
    except Exception:  # noqa: BLE001
        pass
    return fallback


def load_calendar(now: datetime, events_path: Path | None, ics_urls: list[str]) -> CalendarData:
    if events_path is not None:
        return load_events_from_json(events_path)
    if ics_urls:
        return fetch_events_from_icals(ics_urls, now)
    return not_configured_calendar()


# ---------------------------------------------------------------------------
# Stocks
# ---------------------------------------------------------------------------

def _parse_twse_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace(",", "").replace("+", "").replace(" ", "")
    if text in {"", "--", "---", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_twse_sign(value: Any) -> int:
    """從證交所漲跌欄的 HTML 或純文字判斷 +1／-1／0。"""
    text = str(value or "")
    if "green" in text or "-" in text or "－" in text:
        return -1
    if "+" in text or "＋" in text or "red" in text:
        return 1
    return 0


def _roc_date_to_ad(raw: str) -> date | None:
    text = str(raw).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{8}", text):
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    match = re.fullmatch(r"(\d{2,3})[/\-]?(\d{2})[/\-]?(\d{2})", text)
    if match:
        year = int(match.group(1))
        if year < 1911:
            year += 1911
        return date(year, int(match.group(2)), int(match.group(3)))
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def fetch_taiex() -> Quote:
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&type=IND"
    try:
        data = http_get_json_retry(url, headers={"Referer": "https://www.twse.com.tw/"})
    except Exception as exc:  # noqa: BLE001
        return Quote("TAIEX", "加權指數", None, None, None, None, source="臺灣證券交易所", error=str(exc))

    as_of = _roc_date_to_ad(str(data.get("date") or ""))
    try:
        for table in data.get("tables") or []:
            for row in table.get("data") or []:
                if not row or str(row[0]).strip() != "發行量加權股價指數":
                    continue
                close = _parse_twse_number(row[1])
                sign = _parse_twse_sign(row[2] if len(row) > 2 else "")
                points = _parse_twse_number(row[3] if len(row) > 3 else None)
                pct = _parse_twse_number(row[4] if len(row) > 4 else None)
                change = None if points is None else abs(points) * (sign or (1 if (pct or 0) >= 0 else -1))
                if pct is not None and sign < 0 and pct > 0:
                    pct = -pct
                return Quote(
                    symbol="TAIEX",
                    name="加權指數",
                    close=close,
                    change=change,
                    change_pct=pct,
                    as_of=as_of,
                    source="臺灣證券交易所 MI_INDEX",
                )
        return Quote(
            "TAIEX",
            "加權指數",
            None,
            None,
            None,
            as_of,
            source="臺灣證券交易所",
            error="回傳資料中找不到發行量加權股價指數",
        )
    except Exception as exc:  # noqa: BLE001
        return Quote("TAIEX", "加權指數", None, None, None, as_of, source="臺灣證券交易所", error=str(exc))


def fetch_twse_watchlist(codes: list[tuple[str, str]]) -> list[Quote]:
    """臺灣證券交易所 OpenAPI STOCK_DAY_ALL 的最新公布收盤。"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        data = http_get_json_retry(url, timeout=30, headers={"Referer": "https://openapi.twse.com.tw/"})
    except Exception as exc:  # noqa: BLE001
        return [
            Quote(code, name, None, None, None, None, source="臺灣證券交易所 OpenAPI", error=str(exc))
            for code, name in codes
        ]

    if not isinstance(data, list):
        err = "STOCK_DAY_ALL 格式不符預期"
        return [
            Quote(code, name, None, None, None, None, source="臺灣證券交易所 OpenAPI", error=err)
            for code, name in codes
        ]

    by_code: dict[str, dict[str, Any]] = {
        str(row.get("Code")): row for row in data if isinstance(row, dict)
    }
    quotes: list[Quote] = []
    for code, fallback_name in codes:
        row = by_code.get(code)
        if not row:
            quotes.append(
                Quote(code, fallback_name, None, None, None, None, source="臺灣證券交易所 OpenAPI", error="查無此代號")
            )
            continue
        close = _parse_twse_number(row.get("ClosingPrice"))
        change = _parse_twse_number(row.get("Change"))
        pct = None
        if close is not None and change is not None:
            prev = close - change
            if prev:
                pct = change / prev * 100.0
        quotes.append(
            Quote(
                symbol=code,
                name=str(row.get("Name") or fallback_name),
                close=close,
                change=change,
                change_pct=pct,
                as_of=_roc_date_to_ad(str(row.get("Date") or "")),
                currency="TWD",
                source="臺灣證券交易所 STOCK_DAY_ALL",
            )
        )
    return quotes


def _parse_cnbc_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("+", "").replace("%", "")
    if text in {"", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_cnbc_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if re.search(r"[+-]\d{4}$", text):
            text = text[:-5] + text[-5:-2] + ":" + text[-2:]
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def fetch_us_index_cnbc(symbol: str, name: str) -> Quote:
    qs = urllib.parse.urlencode(
        {
            "symbols": symbol,
            "requestMethod": "itv",
            "noform": "1",
            "partnerId": "2",
            "output": "json",
        }
    )
    url = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?" + qs
    try:
        data = http_get_json_retry(url)
    except Exception as exc:  # noqa: BLE001
        return Quote(symbol, name, None, None, None, None, source="CNBC Quotes", error=str(exc))

    try:
        quotes = (data.get("FormattedQuoteResult") or {}).get("FormattedQuote") or []
        if not quotes:
            return Quote(symbol, name, None, None, None, None, source="CNBC Quotes", error="沒有回傳報價")
        quote = quotes[0]
        if quote.get("code") not in (0, "0", None) and quote.get("last") in (None, ""):
            return Quote(symbol, name, None, None, None, None, source="CNBC Quotes", error="查無此指數")
        close = _parse_cnbc_number(quote.get("last"))
        change = _parse_cnbc_number(quote.get("change"))
        pct = _parse_cnbc_number(quote.get("change_pct"))
        if quote.get("changetype") == "DOWN" and change is not None and change > 0:
            change = -change
        if quote.get("changetype") == "DOWN" and pct is not None and pct > 0:
            pct = -pct
        if quote.get("changetype") == "UP" and change is not None and change < 0:
            change = abs(change)
        return Quote(
            symbol=symbol,
            name=name,
            close=close,
            change=change,
            change_pct=pct,
            as_of=_parse_cnbc_date(quote.get("last_time")),
            currency="USD",
            source="CNBC Quotes",
        )
    except Exception as exc:  # noqa: BLE001
        return Quote(symbol, name, None, None, None, None, source="CNBC Quotes", error=str(exc))


def fetch_us_index_yahoo(yahoo_symbol: str, name: str, display_symbol: str) -> Quote:
    """CNBC 失敗時改走 Yahoo Finance。資料中心 IP 常被限流。"""
    encoded = urllib.parse.quote(yahoo_symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range=5d"
    try:
        data = http_get_json_retry(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
    except Exception as exc:  # noqa: BLE001
        return Quote(display_symbol, name, None, None, None, None, source="Yahoo Finance", error=str(exc))
    try:
        result = (data.get("chart") or {}).get("result") or []
        if not result:
            err = (data.get("chart") or {}).get("error") or "沒有回傳走勢"
            return Quote(display_symbol, name, None, None, None, None, source="Yahoo Finance", error=str(err))
        meta = result[0].get("meta") or {}
        timestamps = result[0].get("timestamp") or []
        closes = ((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        pairs = [(stamp, close) for stamp, close in zip(timestamps, closes) if close is not None]
        if not pairs:
            return Quote(display_symbol, name, None, None, None, None, source="Yahoo Finance", error="沒有收盤價")
        last_ts, last_close = pairs[-1]
        prev_close = pairs[-2][1] if len(pairs) >= 2 else meta.get("chartPreviousClose") or meta.get("previousClose")
        change = last_close - prev_close if prev_close is not None else None
        pct = (change / prev_close * 100.0) if change is not None and prev_close else None
        as_of = datetime.fromtimestamp(last_ts, tz=timezone.utc).date()
        return Quote(
            symbol=display_symbol,
            name=name,
            close=float(last_close),
            change=None if change is None else float(change),
            change_pct=None if pct is None else float(pct),
            as_of=as_of,
            source="Yahoo Finance",
        )
    except Exception as exc:  # noqa: BLE001
        return Quote(display_symbol, name, None, None, None, None, source="Yahoo Finance", error=str(exc))


def fetch_us_indices() -> list[Quote]:
    specs = [
        (".DJI", "道瓊", "^DJI"),
        (".SPX", "標普 500", "^GSPC"),
        (".IXIC", "那斯達克", "^IXIC"),
    ]
    out: list[Quote] = []
    for cnbc_symbol, name, yahoo_symbol in specs:
        quote = fetch_us_index_cnbc(cnbc_symbol, name)
        if not quote.ok:
            fallback = fetch_us_index_yahoo(yahoo_symbol, name, cnbc_symbol)
            if fallback.ok:
                quote = fallback
        out.append(quote)
    return out


def fetch_markets() -> MarketData:
    taiex = fetch_taiex()
    us = fetch_us_indices()
    watch = fetch_twse_watchlist(
        [
            ("0050", "元大台灣50"),
            ("2330", "台積電"),
            ("00400A", "主動國泰動能高息"),
        ]
    )
    return MarketData(indices=[taiex, *us], watchlist=watch, fetched_at=datetime.now(TZ))


# ---------------------------------------------------------------------------
# Snapshot / fallback
# ---------------------------------------------------------------------------

def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=TZ)
    return value.astimezone(TZ).isoformat(timespec="seconds")


def _parse_stamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return parse_now(value)
    except ValueError:
        return None


def carried_label(when: datetime | None) -> str:
    if when is None:
        return "上一版"
    local = when.astimezone(TZ)
    return f"{local.month}/{local.day} {local.strftime('%H:%M')}"


def quote_to_dict(quote: Quote) -> dict[str, Any]:
    return {
        "symbol": quote.symbol,
        "name": quote.name,
        "close": quote.close,
        "change": quote.change,
        "change_pct": quote.change_pct,
        "as_of": quote.as_of.isoformat() if quote.as_of else None,
        "currency": quote.currency,
        "source": quote.source,
    }


def quote_from_dict(raw: dict[str, Any]) -> Quote:
    as_of = raw.get("as_of")
    try:
        parsed_day = date.fromisoformat(as_of) if isinstance(as_of, str) and as_of else None
    except ValueError:
        parsed_day = None
    return Quote(
        symbol=str(raw.get("symbol") or ""),
        name=str(raw.get("name") or ""),
        close=_maybe_float(raw.get("close")),
        change=_maybe_float(raw.get("change")),
        change_pct=_maybe_float(raw.get("change_pct")),
        as_of=parsed_day,
        currency=str(raw.get("currency") or ""),
        source=str(raw.get("source") or ""),
    )


def calendar_to_dict(calendar: CalendarData) -> dict[str, Any]:
    return {
        "fetched_at": _iso(calendar.fetched_at),
        "source": calendar.source,
        "date": calendar.date,
        "range_start": calendar.range_start,
        "range_end": calendar.range_end,
        "calendars_checked": calendar.calendars_checked,
        "warnings": calendar.warnings,
        "events": [
            {
                "summary": event.summary,
                "start": event.start,
                "end": event.end,
                "all_day": event.all_day,
                "location": event.location,
                "calendar": event.calendar,
            }
            for event in calendar.events
        ],
    }


def calendar_from_dict(raw: dict[str, Any]) -> CalendarData | None:
    events: list[CalendarEvent] = []
    for item in raw.get("events") or []:
        if not isinstance(item, dict):
            continue
        events.append(
            CalendarEvent(
                summary=_one_line(str(item.get("summary") or "（無標題）")),
                start=item.get("start"),
                end=item.get("end"),
                all_day=bool(item.get("all_day")),
                location=_one_line(str(item.get("location") or "")),
                calendar=_one_line(str(item.get("calendar") or "")),
            )
        )
    if not events and not raw.get("calendars_checked"):
        return None
    events.sort(key=_event_sort_key)
    return CalendarData(
        source=str(raw.get("source") or "上一版"),
        ok=True,
        date=raw.get("date"),
        range_start=raw.get("range_start"),
        range_end=raw.get("range_end"),
        calendars_checked=list(raw.get("calendars_checked") or []),
        events=events,
        warnings=list(raw.get("warnings") or []),
        fetched_at=_parse_stamp(raw.get("fetched_at")),
        carried=True,
    )


def markets_to_dict(markets: MarketData) -> dict[str, Any]:
    return {
        "fetched_at": _iso(markets.fetched_at),
        "indices": [quote_to_dict(quote) for quote in markets.indices if quote.ok],
        "watchlist": [quote_to_dict(quote) for quote in markets.watchlist if quote.ok],
    }


def _quotes_from_list(raw: Any) -> list[Quote]:
    if not isinstance(raw, list):
        return []
    quotes: list[Quote] = []
    for item in raw:
        if isinstance(item, dict):
            quote = quote_from_dict(item)
            if quote.close is not None:
                quotes.append(quote)
    return quotes


def markets_from_dict(raw: dict[str, Any]) -> MarketData | None:
    indices = _quotes_from_list(raw.get("indices"))
    watchlist = _quotes_from_list(raw.get("watchlist"))
    if not indices and not watchlist:
        return None
    return MarketData(
        indices=indices,
        watchlist=watchlist,
        fetched_at=_parse_stamp(raw.get("fetched_at")),
        carried=True,
    )


def build_snapshot(
    weather: Weather,
    calendar: CalendarData,
    markets: MarketData,
    generated_at: datetime,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"generated_at": _iso(generated_at)}
    if weather.ok and isinstance(weather.raw, dict):
        payload["weather"] = {
            "fetched_at": _iso(weather.fetched_at or generated_at),
            "raw": weather.raw,
        }
    if calendar.ok and not calendar.not_configured:
        payload["calendar"] = calendar_to_dict(calendar)
    if any(quote.ok for quote in [*markets.indices, *markets.watchlist]):
        payload["markets"] = markets_to_dict(markets)
    return payload


def load_snapshot_dict(url: str = PAGES_SNAPSHOT_URL) -> dict[str, Any] | None:
    try:
        data = http_get_json(url, timeout=20)
    except Exception as exc:  # noqa: BLE001
        print(f"無法讀取上一版看板資料：{exc}", flush=True)
        return None
    if not isinstance(data, dict):
        print("上一版看板資料格式不符", flush=True)
        return None
    return data


def _merge_quotes(current: list[Quote], previous: list[Quote]) -> tuple[list[Quote], bool, bool]:
    prior = {quote.symbol: quote for quote in previous if quote.ok}
    merged: list[Quote] = []
    carried = False
    kept_fresh = False
    for quote in current:
        if quote.ok:
            merged.append(quote)
            kept_fresh = True
            continue
        old = prior.get(quote.symbol)
        if old is not None:
            old.carried = True
            merged.append(old)
            carried = True
            print(f"股市沿用上一版：{quote.name}", flush=True)
            continue
        quote.error = "資料暫缺"
        merged.append(quote)
    return merged, carried, kept_fresh


def apply_fallbacks(
    weather: Weather,
    calendar: CalendarData,
    markets: MarketData,
    today: date,
    snapshot: dict[str, Any] | None,
) -> tuple[Weather, CalendarData, MarketData]:
    if snapshot is None:
        return weather, calendar, markets

    weather_entry = snapshot.get("weather")
    if not weather.ok and isinstance(weather_entry, dict):
        raw = weather_entry.get("raw")
        if isinstance(raw, dict):
            restored = parse_open_meteo(raw, today)
            if restored.ok:
                restored.fetched_at = _parse_stamp(weather_entry.get("fetched_at"))
                restored.carried = True
                restored.raw = raw
                print(f"天氣沿用 {carried_label(restored.fetched_at)}", flush=True)
                weather = restored
            else:
                print("上一版天氣無法套用到今天", flush=True)

    calendar_entry = snapshot.get("calendar")
    if not calendar.ok and not calendar.not_configured and isinstance(calendar_entry, dict):
        restored_calendar = calendar_from_dict(calendar_entry)
        if restored_calendar is not None:
            print(f"行程沿用 {carried_label(restored_calendar.fetched_at)}", flush=True)
            calendar = restored_calendar

    markets_entry = snapshot.get("markets")
    if isinstance(markets_entry, dict):
        previous = markets_from_dict(markets_entry)
        if previous is not None and any(not quote.ok for quote in [*markets.indices, *markets.watchlist]):
            indices, carried_i, fresh_i = _merge_quotes(markets.indices, previous.indices)
            watch, carried_w, fresh_w = _merge_quotes(markets.watchlist, previous.watchlist)
            carried = carried_i or carried_w
            if carried:
                markets = MarketData(
                    indices=indices,
                    watchlist=watch,
                    fetched_at=previous.fetched_at,
                    carried=True,
                    partial_carry=carried and (fresh_i or fresh_w),
                )
    return weather, calendar, markets


# ---------------------------------------------------------------------------
# Formatting / HTML
# ---------------------------------------------------------------------------

def _at(seq: Any, index: int) -> Any:
    if not isinstance(seq, list) or index >= len(seq):
        return None
    return seq[index]


def _maybe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_int(value: Any) -> int | None:
    number = _maybe_float(value)
    return None if number is None else int(round(number))


def fmt_temp(value: float | None, unit: bool = True) -> str:
    if value is None:
        return "—"
    suffix = "°" if unit else ""
    return f"{value:.1f}{suffix}"


def fmt_price(value: float | None, digits: int | None = None) -> str:
    if value is None:
        return "—"
    if digits is None:
        digits = 0 if abs(value) >= 10000 else 2
    return f"{value:,.{digits}f}"


def fmt_signed(value: float | None, digits: int | None = None) -> str:
    if value is None:
        return "—"
    if digits is None:
        digits = 0 if abs(value) >= 1000 else 2
    sign = "＋" if value > 0 else "－" if value < 0 else ""
    return f"{sign}{abs(value):,.{digits}f}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "＋" if value > 0 else "－" if value < 0 else ""
    return f"{sign}{abs(value):.2f}%"


def movement_class(value: float | None) -> str:
    if value is None:
        return ""
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def movement_mark(value: float | None) -> str:
    if value is None:
        return ""
    if value > 0:
        return "▲"
    if value < 0:
        return "▼"
    return "－"


def format_event_time(ev: CalendarEvent) -> str:
    if ev.all_day:
        return "全天"
    if not ev.start:
        return "時間未定"

    def _parse(ts: str) -> datetime | date | None:
        text = ts.strip()
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                return date.fromisoformat(text)
            return datetime.fromisoformat(text).astimezone(TZ)
        except ValueError:
            return None

    start = _parse(ev.start)
    end = _parse(ev.end) if ev.end else None
    if isinstance(start, datetime):
        start_s = start.strftime("%H:%M")
        if isinstance(end, datetime):
            return f"{start_s}–{end.strftime('%H:%M')}"
        return start_s
    return "全天"


def unique_as_of(quotes: Iterable[Quote]) -> list[date]:
    return sorted({quote.as_of for quote in quotes if quote.as_of})


def parse_event_moment(value: str | None) -> datetime | date | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text)
        return datetime.fromisoformat(text).astimezone(TZ)
    except ValueError:
        return None


def event_dates_in_range(ev: CalendarEvent, start_day: date, end_day: date) -> list[date]:
    """行程要出現的日期（含起迄）。全天行程的結束日是獨家的。"""
    start = parse_event_moment(ev.start)
    end = parse_event_moment(ev.end)
    if start is None:
        return []
    if ev.all_day or _is_date_only(start):
        first = start if _is_date_only(start) else start.date()
        if _is_date_only(end):
            last = end - timedelta(days=1)
        elif isinstance(end, datetime):
            last = end.astimezone(TZ).date()
        else:
            last = first
    else:
        assert isinstance(start, datetime)
        first = start.date()
        if isinstance(end, datetime):
            last = end.astimezone(TZ).date()
            if end.astimezone(TZ).time() == time.min and last > first:
                last = last - timedelta(days=1)
        else:
            last = first
    if last < first:
        last = first
    out: list[date] = []
    day = first
    while day <= last:
        if start_day <= day <= end_day:
            out.append(day)
        day += timedelta(days=1)
    return out


def group_week_events(
    events: list[CalendarEvent], today: date, length: int = 7
) -> list[tuple[date, list[CalendarEvent]]]:
    start = today
    end = today + timedelta(days=length - 1)
    buckets: dict[date, list[CalendarEvent]] = {
        start + timedelta(days=i): [] for i in range(length)
    }
    for ev in events:
        for day in event_dates_in_range(ev, start, end):
            buckets[day].append(ev)
    for day in buckets:
        buckets[day].sort(key=_event_sort_key)
    return [(day, buckets[day]) for day in buckets]


def week_bounds(today: date, length: int = 7) -> tuple[date, date]:
    return today, today + timedelta(days=length - 1)


def truncate_title(text: str, max_chars: int = 14) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def render_hourly_svg(hours: list[HourlyPoint], width: int = 1716, height: int = 168) -> str:
    """06:00–23:00 氣溫折線，底下是降雨機率長條。"""
    if not hours:
        return ""
    left, right, top, bottom = 10, 10, 14, 10
    plot_w = width - left - right
    plot_h = height - top - bottom
    slot = plot_w / len(hours)
    temps = [point.temp for point in hours if point.temp is not None]
    if temps:
        tmin, tmax = min(temps), max(temps)
        pad = max(1.0, (tmax - tmin) * 0.35)
        ymin, ymax = tmin - pad, tmax + pad
    else:
        ymin, ymax = 0.0, 1.0

    def x_at(index: int) -> float:
        return left + slot * (index + 0.5)

    def y_temp(temp: float) -> float:
        return top + (ymax - temp) / (ymax - ymin) * plot_h

    parts = [
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#000" stroke-width="2"/>'
    ]
    for index, point in enumerate(hours):
        if point.rain_prob is None:
            continue
        bar_h = max(0.0, min(100.0, float(point.rain_prob))) / 100.0 * plot_h
        bar_w = slot * 0.5
        x = x_at(index) - bar_w / 2
        y = top + plot_h - bar_h
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="#000"/>'
        )
    pts: list[str] = []
    dots: list[str] = []
    for index, point in enumerate(hours):
        if point.temp is None:
            continue
        x, y = x_at(index), y_temp(point.temp)
        pts.append(f"{x:.1f},{y:.1f}")
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="#000"/>')
    if pts:
        parts.append(
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="#000" stroke-width="4" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        parts.extend(dots)
    return (
        f'<svg class="hourly-chart" viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" aria-label="今日每小時氣溫與降雨機率">'
        f"{''.join(parts)}</svg>"
    )


def render_hourly_block(hours: list[HourlyPoint], generated_at: datetime) -> str:
    if not hours:
        return '<p class="hourly-miss">今日每小時預報暫時無法取得</p>'
    current_hour = generated_at.astimezone(TZ).replace(minute=0, second=0, microsecond=0)
    cells = []
    for point in hours:
        is_now = point.time.replace(minute=0, second=0, microsecond=0) == current_hour
        rain = "—" if point.rain_prob is None else f"{point.rain_prob}%"
        temp = "—" if point.temp is None else f"{point.temp:.1f}°"
        klass = "hour now" if is_now else "hour"
        cells.append(
            f'<div class="{klass}">'
            f'<div class="h-time">{point.time.strftime("%H")}</div>'
            f'<div class="h-temp">{html.escape(temp)}</div>'
            f'<div class="h-rain">{html.escape(rain)}</div>'
            f"</div>"
        )
    return (
        '<div class="hourly">'
        '<div class="hourly-label">今日每小時　折線為氣溫，長條為降雨機率（0–100%）</div>'
        f"{render_hourly_svg(hours)}"
        f'<div class="hour-row">{"".join(cells)}</div>'
        "</div>"
    )


def render_html(weather: Weather, calendar: CalendarData, markets: MarketData, generated_at: datetime) -> str:
    generated_at = generated_at.astimezone(TZ)
    today = generated_at.date()
    date_line = f"{today.year}年{today.month}月{today.day}日　{WEEKDAYS[today.weekday()]}"
    updated = generated_at.strftime("%H:%M")
    week_start, week_end = week_bounds(today)

    if weather.ok and weather.days:
        today_fc = next((day for day in weather.days if day.date == today), weather.days[0])
        later = [day for day in weather.days if day.date != today_fc.date][:2]
        rain = "—" if today_fc.rain_prob is None else f"{today_fc.rain_prob}%"
        current_bits = []
        if weather.current_temp is not None:
            current_bits.append(f"目前 {fmt_temp(weather.current_temp)}")
        if weather.current_humidity is not None:
            current_bits.append(f"濕度 {weather.current_humidity}%")
        current_line = "　".join(current_bits)
        forecast_cells = []
        for day in later:
            rain_d = "—" if day.rain_prob is None else f"{day.rain_prob}%"
            forecast_cells.append(
                f"""
                <div class="forecast-day">
                  <div class="fc-date">{WEEKDAYS_SHORT[day.date.weekday()]} {day.date.month}/{day.date.day}</div>
                  <div class="fc-cond">{html.escape(day.condition)}</div>
                  <div class="fc-temp">{fmt_temp(day.temp_min)} – {fmt_temp(day.temp_max)}</div>
                  <div class="fc-rain">降雨 {html.escape(rain_d)}</div>
                </div>
                """
            )
        weather_body = f"""
        <div class="weather-top">
          <div class="wx-main">
            <div class="wx-kicker">今日</div>
            <div class="wx-cond">{html.escape(today_fc.condition or weather.current_condition or "—")}</div>
            <div class="wx-range">{fmt_temp(today_fc.temp_min)} – {fmt_temp(today_fc.temp_max)}</div>
            <div class="wx-meta">降雨機率 {html.escape(rain)}{("　" + html.escape(current_line)) if current_line else ""}</div>
          </div>
          <div class="forecast">{"".join(forecast_cells)}</div>
        </div>
        {render_hourly_block(weather.hours, generated_at)}
        {f'<p class="week-note">天氣資料沿用 {html.escape(carried_label(weather.fetched_at))}</p>' if weather.carried else ""}
        """
    else:
        weather_body = '<p class="empty">天氣資料暫時無法取得</p>'

    if calendar.not_configured:
        calendar_body = (
            '<p class="empty">尚未設定日曆'
            '<span class="sub">請在 GitHub Actions 密鑰設定 GCAL_ICS_URLS</span></p>'
        )
    elif not calendar.ok:
        calendar_body = '<p class="empty">行程資料暫時無法取得</p>'
    else:
        week = group_week_events(calendar.events, today, 7)
        day_rows = []
        for day, evs in week:
            is_today = day == today
            head = f"{WEEKDAYS_SHORT[day.weekday()]} {day.month}/{day.day}"
            if evs:
                items = []
                for ev in evs:
                    full = ev.summary
                    shown = truncate_title(full, 16)
                    cal = f'<span class="ev-cal">{html.escape(ev.calendar)}</span>' if ev.calendar else ""
                    items.append(
                        f'<div class="ev-item">'
                        f'<span class="ev-time">{html.escape(format_event_time(ev))}</span>'
                        f'<span class="ev-title" title="{html.escape(full)}">{html.escape(shown)}</span>'
                        f"{cal}"
                        f"</div>"
                    )
                body = f'<div class="ev-list">{"".join(items)}</div>'
            else:
                body = '<div class="ev-empty">—</div>'
            klass = "day-row today" if is_today else "day-row"
            tag_html = '<span class="day-tag">今日</span>' if is_today else ""
            day_rows.append(
                f'<div class="{klass}">'
                f'<div class="day-head"><span class="day-name">{html.escape(head)}</span>{tag_html}</div>'
                f"{body}"
                f"</div>"
            )
        count = len(calendar.calendars_checked)
        note = (
            f"已查詢 {count} 本日曆，期間 {week_start.month}/{week_start.day}–{week_end.month}/{week_end.day}。"
            if count
            else ""
        )
        if calendar.warnings:
            note = (note + " " + " ".join(calendar.warnings)).strip()
        if calendar.carried:
            note = (note + f" 行程資料沿用 {carried_label(calendar.fetched_at)}。").strip()
        calendar_body = f'<div class="week">{"".join(day_rows)}</div><p class="week-note">{html.escape(note)}</p>'

    def quote_tile(quote: Quote, show_symbol: bool) -> str:
        symbol_html = ""
        if show_symbol and quote.symbol not in {".DJI", ".SPX", ".IXIC", "TAIEX"}:
            symbol_html = f'<div class="tile-symbol">{html.escape(quote.symbol)}</div>'
        if not quote.ok:
            return (
                f'<div class="stock-tile miss">'
                f"{symbol_html}"
                f'<div class="tile-name">{html.escape(quote.name)}</div>'
                f'<div class="tile-miss">資料暫缺</div>'
                f"</div>"
            )
        klass = movement_class(quote.change if quote.change is not None else quote.change_pct)
        return (
            f'<div class="stock-tile {klass}">'
            f"{symbol_html}"
            f'<div class="tile-name">{html.escape(quote.name)}</div>'
            f'<div class="tile-close">{fmt_price(quote.close, 2)}</div>'
            f'<div class="tile-chg">{movement_mark(quote.change)} {fmt_signed(quote.change, 2)}</div>'
            f'<div class="tile-pct">{fmt_pct(quote.change_pct)}</div>'
            f"</div>"
        )

    index_tiles = "".join(quote_tile(quote, show_symbol=False) for quote in markets.indices)
    watch_tiles = "".join(quote_tile(quote, show_symbol=True) for quote in markets.watchlist)

    tw_dates = unique_as_of([markets.indices[0], *markets.watchlist] if markets.indices else markets.watchlist)
    us_dates = unique_as_of(markets.indices[1:] if len(markets.indices) > 1 else [])
    asof_bits = []
    if tw_dates:
        asof_bits.append("台股收盤 " + "、".join(day.strftime("%Y-%m-%d") for day in tw_dates))
    if us_dates:
        asof_bits.append("美股收盤 " + "、".join(day.strftime("%Y-%m-%d") for day in us_dates))
    asof_line = "；".join(asof_bits) if asof_bits else "尚未取得股市收盤日期"
    if markets.carried:
        prefix = "部分股市資料沿用" if markets.partial_carry else "股市資料沿用"
        asof_line = f"{prefix} {carried_label(markets.fetched_at)}。{asof_line}"

    return f"""<!DOCTYPE html>
<html lang="zh-Hant-TW">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width={PAGE_WIDTH}, height={PAGE_HEIGHT}, viewport-fit=cover">
  <meta name="color-scheme" content="light">
  <meta name="theme-color" content="#ffffff">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <title>晨間看板　{html.escape(date_line)}</title>
  <style>
    @page {{ size: {PAGE_WIDTH}px {PAGE_HEIGHT}px; margin: 0; }}
    * {{ box-sizing: border-box; }}
    html, body {{
      width: {PAGE_WIDTH}px;
      height: {PAGE_HEIGHT}px;
      margin: 0;
      padding: 0;
      background: #fff;
      color: #000;
      font-family: "Noto Sans CJK TC", "Noto Sans CJK", "Noto Sans TC", sans-serif;
      overflow: hidden;
      -webkit-text-size-adjust: 100%;
      text-size-adjust: 100%;
    }}
    body {{
      display: flex;
      flex-direction: column;
      padding: 48px 56px 36px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      border-bottom: 8px solid #000;
      padding-bottom: 20px;
      flex-shrink: 0;
    }}
    .kicker {{
      font-size: 28px;
      letter-spacing: 0.28em;
      font-weight: 700;
    }}
    h1 {{
      margin: 6px 0 0;
      font-size: 60px;
      line-height: 1.1;
      font-weight: 700;
      letter-spacing: 0.04em;
    }}
    .updated {{
      text-align: right;
      font-size: 28px;
      line-height: 1.4;
    }}
    .updated .loc {{
      font-size: 34px;
      font-weight: 700;
      letter-spacing: 0.12em;
    }}
    main {{
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }}
    section {{
      border-bottom: 4px solid #000;
      padding: 22px 0 20px;
      flex-shrink: 0;
    }}
    section.calendar {{
      flex: 0 0 auto;
    }}
    section.stocks {{
      flex: 1 1 auto;
      display: flex;
      flex-direction: column;
      border-bottom: 0;
      padding-bottom: 8px;
      min-height: 0;
    }}
    h2 {{
      margin: 0 0 16px;
      font-size: 36px;
      letter-spacing: 0.22em;
      font-weight: 700;
    }}
    .weather-top {{
      display: flex;
      gap: 20px;
      align-items: stretch;
      margin-bottom: 16px;
    }}
    .wx-main {{
      flex: 1.2;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}
    .wx-kicker {{
      font-size: 26px;
      font-weight: 700;
      letter-spacing: 0.22em;
    }}
    .wx-cond {{
      font-size: 44px;
      font-weight: 700;
      letter-spacing: 0.12em;
    }}
    .wx-range {{
      font-size: 76px;
      font-weight: 700;
      line-height: 1.05;
      margin: 2px 0 8px;
      letter-spacing: 0.02em;
    }}
    .wx-meta {{ font-size: 30px; }}
    .forecast {{
      flex: 0 0 520px;
      display: flex;
      gap: 14px;
    }}
    .forecast-day {{
      flex: 1;
      border: 3px solid #000;
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .fc-date {{ font-size: 26px; font-weight: 700; }}
    .fc-cond {{ font-size: 34px; font-weight: 700; margin: 8px 0; letter-spacing: 0.08em; }}
    .fc-temp {{ font-size: 30px; font-weight: 700; }}
    .fc-rain {{ font-size: 24px; margin-top: 6px; }}
    .hourly-label {{
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 0.08em;
      margin-bottom: 8px;
    }}
    .hourly-chart {{
      display: block;
      width: 100%;
      height: 168px;
    }}
    .hour-row {{
      display: grid;
      grid-template-columns: repeat(18, 1fr);
      gap: 0;
      margin-top: 4px;
      border-top: 2px solid #000;
    }}
    .hour {{
      text-align: center;
      padding: 6px 0 2px;
      font-variant-numeric: tabular-nums;
    }}
    .hour.now {{
      outline: 3px solid #000;
      outline-offset: -3px;
      background: #000;
      color: #fff;
    }}
    .h-time {{ font-size: 22px; font-weight: 700; }}
    .h-temp {{ font-size: 24px; font-weight: 700; margin: 2px 0; }}
    .h-rain {{ font-size: 20px; }}
    .hourly-miss, .empty {{
      margin: 8px 0 0;
      font-size: 36px;
      font-weight: 700;
    }}
    .empty .sub {{
      display: block;
      margin-top: 10px;
      font-size: 26px;
      font-weight: 400;
    }}
    .week {{
      display: flex;
      flex-direction: column;
      border-top: 3px solid #000;
    }}
    .day-row {{
      display: grid;
      grid-template-columns: 220px 1fr;
      gap: 16px;
      align-items: center;
      min-height: 56px;
      padding: 6px 4px;
      border-bottom: 2px solid #000;
    }}
    .day-row.today {{
      outline: 4px solid #000;
      outline-offset: -2px;
      padding: 10px 8px;
    }}
    .day-head {{
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}
    .day-name {{ font-size: 30px; font-weight: 700; letter-spacing: 0.04em; }}
    .day-tag {{
      font-size: 22px;
      font-weight: 700;
      letter-spacing: 0.16em;
      margin-top: 2px;
    }}
    .ev-list {{ display: flex; flex-direction: column; gap: 4px; }}
    .ev-item {{
      display: flex;
      align-items: baseline;
      gap: 20px;
      font-size: 30px;
      min-width: 0;
    }}
    .ev-time {{
      flex: 0 0 230px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }}
    .ev-title {{
      flex: 1;
      font-weight: 700;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .ev-cal {{
      flex: 0 0 auto;
      font-size: 24px;
      font-weight: 400;
    }}
    .ev-empty {{
      font-size: 32px;
      font-weight: 700;
      letter-spacing: 0.2em;
    }}
    .week-note {{
      margin: 10px 0 0;
      font-size: 24px;
    }}
    .stock-grid {{
      flex: 1;
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      grid-auto-rows: 1fr;
      gap: 16px;
      min-height: 0;
    }}
    .stock-tile {{
      border: 4px solid #000;
      padding: 16px 18px 14px;
      min-height: 210px;
      display: flex;
      flex-direction: column;
    }}
    .tile-symbol {{
      font-size: 22px;
      letter-spacing: 0.04em;
      margin-bottom: 2px;
    }}
    .tile-name {{
      font-size: 30px;
      font-weight: 700;
      letter-spacing: 0.04em;
      line-height: 1.2;
    }}
    .tile-close {{
      margin-top: auto;
      padding-top: 12px;
      font-size: 44px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      letter-spacing: 0.01em;
    }}
    .tile-chg, .tile-pct {{
      font-size: 28px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }}
    .tile-pct {{ margin-top: 2px; }}
    .tile-miss {{
      margin-top: auto;
      font-size: 32px;
      font-weight: 700;
    }}
    .tile-miss-reason {{
      font-size: 22px;
      margin-top: 6px;
    }}
    .asof {{
      margin: 14px 0 0;
      font-size: 24px;
    }}
    footer {{
      border-top: 3px solid #000;
      padding-top: 14px;
      font-size: 24px;
      line-height: 1.5;
      flex-shrink: 0;
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <div class="kicker">每日晨間看板</div>
      <h1>{html.escape(date_line)}</h1>
    </div>
    <div class="updated">
      <div class="loc">新竹</div>
      <div>更新於 {html.escape(updated)}（台北時間）</div>
    </div>
  </header>
  <main>
    <section class="weather">
      <h2>天氣</h2>
      {weather_body}
    </section>
    <section class="calendar">
      <h2>本週行程</h2>
      {calendar_body}
    </section>
    <section class="stocks">
      <h2>股市</h2>
      <div class="stock-grid">{index_tiles}{watch_tiles}</div>
      <p class="asof">{html.escape(asof_line)}。漲跌以文字與 ▲▼ 標示，不依賴顏色。</p>
    </section>
  </main>
  <footer>
    資料來源：天氣 Open-Meteo（含今日每小時氣溫與降雨機率）；台股為臺灣證券交易所公開資料（最新已公布收盤）；
    美股指數為 CNBC Quotes（必要時改試 Yahoo Finance）。
    行程來自私人 Google 日曆 iCal（今日起七日，已換算台北時間）。
    此頁為電子紙直向 1860×2480，僅使用黑白。
  </footer>
  <script>
    (function () {{
      if (location.protocol === "file:") return;
      var PAGE_W = {PAGE_WIDTH};
      var PAGE_H = {PAGE_HEIGHT};
      function fit() {{
        var vv = window.visualViewport;
        var vw = vv && vv.width ? vv.width : window.innerWidth;
        var vh = vv && vv.height ? vv.height : window.innerHeight;
        var body = document.body;
        var root = document.documentElement;
        if (!body || !root || !vw || !vh) return;
        root.style.background = "#fff";
        root.style.overflow = "hidden";
        body.style.background = "#fff";
        var scale = Math.min(vw / PAGE_W, vh / PAGE_H);
        if (Math.abs(scale - 1) < 0.02) {{
          body.style.transform = "none";
          body.style.position = "";
          body.style.left = "";
          body.style.top = "";
          return;
        }}
        body.style.transformOrigin = "0 0";
        body.style.transform = "scale(" + scale + ")";
        body.style.position = "absolute";
        body.style.margin = "0";
        body.style.left = Math.max(0, (vw - PAGE_W * scale) / 2) + "px";
        body.style.top = Math.max(0, (vh - PAGE_H * scale) / 2) + "px";
      }}
      window.addEventListener("resize", fit);
      window.addEventListener("load", fit);
      if (window.visualViewport) window.visualViewport.addEventListener("resize", fit);
      fit();
    }})();
  </script>
</body>
</html>
"""


def find_chrome() -> str:
    # 優先用真正的執行檔。部分環境的 google-chrome 包裝腳本會加上
    # remote debugging，導致 --screenshot 截完圖卻不結束。
    for candidate in (
        "/opt/google/chrome/chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "google-chrome-stable",
        "google-chrome",
        "chromium",
        "chromium-browser",
        "chrome",
    ):
        if candidate.startswith("/"):
            path = candidate if Path(candidate).is_file() else None
        else:
            path = _which(candidate)
        if path:
            return path
    raise RuntimeError("找不到 Chrome / Chromium，無法輸出 PNG")


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def render_png(html_path: Path, png_path: Path) -> None:
    import tempfile

    chrome = find_chrome()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="boox-chrome-") as profile:
        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--no-first-run",
            "--disable-extensions",
            "--force-device-scale-factor=1",
            "--virtual-time-budget=10000",
            f"--user-data-dir={profile}",
            f"--window-size={PAGE_WIDTH},{PAGE_HEIGHT}",
            "--default-background-color=FFFFFFFF",
            f"--screenshot={png_path}",
            html_path.resolve().as_uri(),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=90)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Chrome 截圖逾時") from exc
    if result.returncode != 0 or not png_path.exists():
        detail = result.stderr.strip() or result.stdout.strip() or "無訊息"
        raise RuntimeError(f"Chrome 截圖失敗 (exit {result.returncode}): {detail}")

    try:
        from PIL import Image
    except ImportError:
        return

    with Image.open(png_path) as image:
        gray = image.convert("L")
        if gray.size == (PAGE_WIDTH, PAGE_HEIGHT):
            gray.save(png_path)
            return
        canvas = Image.new("L", (PAGE_WIDTH, PAGE_HEIGHT), 255)
        cropped = gray.crop((0, 0, min(gray.width, PAGE_WIDTH), min(gray.height, PAGE_HEIGHT)))
        canvas.paste(cropped, (0, 0))
        canvas.save(png_path)


def print_summary(weather: Weather, calendar: CalendarData, markets: MarketData) -> None:
    print("=== 天氣 ===")
    if weather.ok:
        print(f"  來源 {weather.source}  目前 {weather.current_temp}°  {weather.current_condition}")
        for day in weather.days[:3]:
            print(f"  {day.date} {day.condition} {day.temp_min}–{day.temp_max} 降雨 {day.rain_prob}%")
        print(f"  每小時 {len(weather.hours)} 筆")
    else:
        print(f"  失敗：{weather.error}")

    print("=== 行程 ===")
    if calendar.not_configured:
        print("  尚未設定日曆（未提供 GCAL_ICS_URLS）")
    elif calendar.ok:
        print(
            f"  已讀取 {len(calendar.calendars_checked)} 本日曆，"
            f"行程 {len(calendar.events)} 則（內容不寫入日誌）"
        )
        for warning in calendar.warnings:
            print(f"  {warning}")
    else:
        print(f"  讀取失敗：{calendar.error}")

    print("=== 股市 ===")
    for quote in [*markets.indices, *markets.watchlist]:
        if quote.ok:
            print(f"  {quote.name} {quote.close} {quote.change} ({quote.change_pct}%)  {quote.as_of}  [{quote.source}]")
        else:
            print(f"  {quote.name} 失敗：{quote.error}  [{quote.source}]")


def parse_now(text: str | None) -> datetime:
    if not text:
        return datetime.now(TZ)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="產生 BOOX 晨間看板 HTML 與 PNG")
    parser.add_argument("--events", type=Path, default=None, help="改讀本機 JSON，不使用 GCAL_ICS_URLS")
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--png", type=Path, default=DEFAULT_PNG)
    parser.add_argument("--skip-png", action="store_true")
    parser.add_argument("--now", default=None, help="覆寫現在時間（ISO 8601，測試用）")
    args = parser.parse_args(argv)

    generated_at = parse_now(args.now)
    import os

    ics_urls = split_ics_urls(os.environ.get("GCAL_ICS_URLS"))
    weather = fetch_weather(generated_at.date())
    calendar = load_calendar(generated_at, args.events, ics_urls)
    markets = fetch_markets()
    needs_fallback = (
        not weather.ok
        or (not calendar.ok and not calendar.not_configured)
        or any(not quote.ok for quote in [*markets.indices, *markets.watchlist])
    )
    if needs_fallback:
        weather, calendar, markets = apply_fallbacks(
            weather,
            calendar,
            markets,
            generated_at.date(),
            load_snapshot_dict(),
        )

    html_text = render_html(weather, calendar, markets, generated_at)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(html_text, encoding="utf-8")
    snapshot_path = args.html.parent / SNAPSHOT_NAME
    snapshot_path.write_text(
        json.dumps(build_snapshot(weather, calendar, markets, generated_at), ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"已寫入 {args.html}")
    print(f"已寫入 {snapshot_path}")

    if not args.skip_png:
        render_png(args.html, args.png)
        print(f"已寫入 {args.png}")

    print_summary(weather, calendar, markets)
    failed = []
    if not weather.ok:
        failed.append("天氣")
    if not calendar.ok and not calendar.not_configured:
        failed.append("行程")
    for quote in [*markets.indices, *markets.watchlist]:
        if not quote.ok:
            failed.append(quote.name)
    if failed:
        print("部分資料暫缺（頁面已產出，未捏造數字）：" + "、".join(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
