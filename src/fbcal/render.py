"""Turn a match into calendar event content (title, description, location, time, status).

All user-facing text produced here is Turkish by design; labels live in config/settings.yaml where possible.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import Config, Team
from .models import Match
from .names import join, pretty
from .sources.fiba import TBD
from .timeutil import fmt_day_tr, fmt_local


@dataclass
class EventSpec:
    key: str
    match: Match
    summary: str
    description: str
    location: str
    start: datetime | date
    end: datetime | date
    all_day: bool
    status: str  # CONFIRMED / TENTATIVE / CANCELLED
    url: str

    def content_hash(self) -> str:
        payload = [self.summary, self.description, self.location, str(self.start), str(self.end), self.status, self.url]
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:16]


class Namer:
    """Resolve team/opponent display names from config and record opponents missing from the list."""

    def __init__(self, config: Config):
        self.config = config
        self.unknown: set[str] = set()

    def name(self, team: Team, raw: str) -> str:
        if team.is_us(raw):
            return team.display_name
        known = self.config.opponent_display(raw)
        if known:
            return known
        if raw == TBD:
            return raw
        self.unknown.add(pretty(raw))
        return pretty(raw)


def build_event(match: Match, config: Config, namer: Namer) -> EventSpec:
    s = config.settings
    team = config.teams[match.team]
    comp = config.competitions[match.competition]
    home, away = namer.name(team, match.home), namer.name(team, match.away)
    t = s.title

    prefix = ""
    if match.status == "cancelled":
        prefix = t.cancelled_prefix
    elif match.status == "postponed":
        prefix = t.postponed_prefix
    elif comp.friendly:
        prefix = t.friendly_prefix
    suffix = ""
    if match.kickoff is None and match.status not in ("finished", "cancelled"):
        suffix = t.tba_suffix
    fields = {
        "prefix": prefix, "emoji": s.emoji[team.sport], "marker": t.markers[team.gender],
        "home": home, "away": away, "suffix": suffix,
    }
    if match.status == "finished" and match.has_score and s.score_in_title:
        summary = t.result_template.format(**fields, home_score=match.home_score, away_score=match.away_score)
        if match.score_note:
            summary += f" ({match.score_note})"
    else:
        summary = t.template.format(**fields)

    # description (Turkish)
    lines = [join(comp.name, match.round_label, sep=" · ")]
    where = {"home": "İç saha", "away": "Deplasman", "neutral": "Tarafsız saha"}[match.side]
    lines.append(where)
    location = join(match.venue, match.city)
    if location:
        lines.append(f"Yer: {location}")
    if match.kickoff:
        times = " · ".join(f"{fmt_local(match.kickoff, ZoneInfo(z.tz))} {z.label}" for z in s.description_timezones)
        lines.append(f"Başlama: {times}")
        lines.append(f"Tarih: {fmt_day_tr(match.kickoff.astimezone(ZoneInfo(s.source_timezone)).date())}")
    elif match.day:
        lines.append(f"Tarih: {fmt_day_tr(match.day)}")
        if match.status not in ("finished", "cancelled"):
            lines.append("Saat henüz açıklanmadı.")
    if match.status == "postponed":
        lines.append("Maç ertelendi; yeni tarih açıklanınca güncellenecek.")
    if match.status == "cancelled":
        lines.append("Maç iptal edildi.")
    if match.has_score and match.status == "finished":
        lines.append(f"Sonuç: {home} {match.home_score}–{match.away_score} {away}" + (f" ({match.score_note})" if match.score_note else ""))
    if match.extra.get("note"):
        lines.append(f"Not: {match.extra['note']}")
    description = "\n".join(lines)

    if match.kickoff:
        start: datetime | date = match.kickoff
        end: datetime | date = match.kickoff + timedelta(minutes=s.durations[team.sport])
        all_day = False
    else:
        assert match.day is not None
        start, end, all_day = match.day, match.day + timedelta(days=1), True

    if match.status == "cancelled":
        status = "CANCELLED"
    elif match.status == "postponed" or (all_day and match.status != "finished"):
        status = "TENTATIVE"
    else:
        status = "CONFIRMED"
    return EventSpec(
        key=match.key, match=match, summary=summary, description=description, location=location,
        start=start, end=end, all_day=all_day, status=status, url=match.url,
    )
