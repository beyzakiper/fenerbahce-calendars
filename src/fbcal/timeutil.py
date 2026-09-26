"""Time zone helpers. Sources give Turkish local time; feeds are written in UTC."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo("Europe/Istanbul")

TR_MONTHS = {
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
}
TR_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def local_to_utc(day: date, hour: int, minute: int, tz: ZoneInfo = ISTANBUL) -> datetime:
    """Convert local wall-clock time to UTC (honouring DST rules)."""
    return datetime.combine(day, time(hour, minute), tzinfo=tz).astimezone(timezone.utc)


def season_of(day: date) -> str:
    """Season label; a new season starts on 1 July ("2026-27")."""
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def fmt_local(moment: datetime, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).strftime("%H:%M")


def fmt_day_tr(day: date) -> str:
    months = list(TR_MONTHS)
    return f"{day.day} {months[day.month - 1].capitalize()} {day.year} {TR_DAYS[day.weekday()]}"
