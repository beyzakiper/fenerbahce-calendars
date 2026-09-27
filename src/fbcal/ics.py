"""ICS writer and event ledger (UID, SEQUENCE, LAST-MODIFIED).

Output is deterministic: unless content changes, files stay byte-identical (DTSTAMP = LAST-MODIFIED).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from icalendar import Alarm, Calendar, Event, vDuration, vText

from .config import Combined, Config, Team
from .render import EventSpec
from .state import EventRecord, TeamState

# RFC 7986 COLOR expects a CSS colour name; Apple uses the exact hex from X-APPLE-CALENDAR-COLOR.
CSS_COLORS = {
    "navy": (0, 0, 128), "midnightblue": (25, 25, 112), "darkblue": (0, 0, 139), "mediumblue": (0, 0, 205),
    "royalblue": (65, 105, 225), "steelblue": (70, 130, 180), "cornflowerblue": (100, 149, 237),
    "dodgerblue": (30, 144, 255), "deepskyblue": (0, 191, 255), "skyblue": (135, 206, 235),
    "slateblue": (106, 90, 205), "teal": (0, 128, 128), "darkcyan": (0, 139, 139),
    "gold": (255, 215, 0), "yellow": (255, 255, 0), "khaki": (240, 230, 140), "goldenrod": (218, 165, 32),
    "darkgoldenrod": (184, 134, 11), "lemonchiffon": (255, 250, 205), "palegoldenrod": (238, 232, 170),
    "green": (0, 128, 0), "forestgreen": (34, 139, 34), "seagreen": (46, 139, 87),
    "mediumseagreen": (60, 179, 113), "limegreen": (50, 205, 50), "lightgreen": (144, 238, 144),
    "darkseagreen": (143, 188, 143), "yellowgreen": (154, 205, 50), "olivedrab": (107, 142, 35),
    "silver": (192, 192, 192), "gray": (128, 128, 128), "slategray": (112, 128, 144), "white": (255, 255, 255),
}


def css_color_name(hex_color: str) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return min(CSS_COLORS, key=lambda n: sum((a - c) ** 2 for a, c in zip(CSS_COLORS[n], (r, g, b))))


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_uid(spec: EventSpec, config: Config) -> str:
    m = spec.match
    parts = [m.season, m.team, m.competition, m.stage]
    if m.leg:
        parts.append(m.leg)
    parts.append(m.side)
    return "-".join(p.replace("/", "-") for p in parts) + f"@{config.settings.uid_domain}"


def update_ledger(specs: list[EventSpec], state: TeamState, config: Config, now: datetime) -> None:
    """Fix the UID on first sight; when content changes, bump SEQUENCE and refresh LAST-MODIFIED."""
    stamp = _iso(now)
    for spec in specs:
        digest = spec.content_hash()
        record = state.events.get(spec.key)
        if record is None:
            state.events[spec.key] = EventRecord(
                uid=new_uid(spec, config), sequence=0, hash=digest, created=stamp, last_modified=stamp
            )
        elif record.hash != digest:
            record.sequence += 1
            record.hash = digest
            record.last_modified = stamp


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def build_calendar(
    feed: Team | Combined, specs: list[EventSpec], events: dict[str, EventRecord], config: Config, alarm_minutes: int | None
) -> bytes:
    """Render one feed. `feed` is a team or a combined feed (name and colour); `events` is the UID ledger."""
    s = config.settings
    cal = Calendar()
    cal.add("prodid", "-//beyzakiper//fenerbahce-calendars//TR")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", feed.calendar_name)
    cal.add("x-wr-caldesc", f"{feed.calendar_name} maç takvimi. {s.site_url}")
    cal.add("x-wr-timezone", s.calendar_timezone)
    cal.add("name", feed.calendar_name)
    cal.add("refresh-interval", vDuration(_duration(s.refresh_interval)), parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", s.refresh_interval)
    cal.add("x-apple-calendar-color", feed.color)
    cal.add("color", feed.color_name or css_color_name(feed.color))

    def sort_key(spec: EventSpec):
        start = spec.start if isinstance(spec.start, datetime) else datetime.combine(spec.start, datetime.min.time(), timezone.utc)
        return (start, events[spec.key].uid)

    for spec in sorted(specs, key=sort_key):
        record = events[spec.key]
        modified = _parse(record.last_modified)
        ev = Event()
        ev.add("uid", record.uid)
        ev.add("dtstamp", modified)
        ev.add("created", _parse(record.created))
        ev.add("last-modified", modified)
        ev.add("sequence", record.sequence)
        ev.add("summary", spec.summary)
        ev.add("description", spec.description)
        if spec.location:
            ev.add("location", spec.location)
        if spec.url:
            ev.add("url", spec.url)  # Apple Calendar shows this as its own tappable URL row
        ev.add("dtstart", spec.start)
        ev.add("dtend", spec.end)
        ev.add("status", spec.status)
        ev.add("transp", "TRANSPARENT")
        ev.add("categories", [config.competitions[spec.match.competition].name])
        if alarm_minutes and not spec.all_day and spec.status != "CANCELLED":
            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("description", vText(spec.summary))
            alarm.add("trigger", timedelta(minutes=-alarm_minutes))
            ev.add_component(alarm)
        cal.add_component(ev)
    return cal.to_ical()


def _duration(text: str) -> timedelta:
    # only PT#H / PT#M forms are supported
    text = text.upper().removeprefix("PT")
    if text.endswith("H"):
        return timedelta(hours=int(text[:-1]))
    if text.endswith("M"):
        return timedelta(minutes=int(text[:-1]))
    raise ValueError(f"unsupported refresh_interval: {text}")

