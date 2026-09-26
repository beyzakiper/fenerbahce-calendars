"""End-to-end pipeline: fetch sources → validate → merge → apply overrides → write ICS and site data."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from .config import Combined, Config, Team
from .http import SourceError, new_session
from .ics import build_calendar, update_ledger
from .merge import apply_round_dates, combine
from .overrides import added_match, apply_edit, load_overrides
from .render import EventSpec, Namer, build_event
from .sources import ADAPTERS, source_key
from .sources.base import Context
from .state import EventRecord, SourceState, TeamState

log = logging.getLogger("fbcal")
KEEP_DAYS = 400  # older matches are dropped from stored data


@dataclass
class SourceResult:
    team: str
    source: str
    status: str  # ok / failed / suspicious / skipped
    count: int = 0
    previous: int = 0
    message: str = ""


@dataclass
class Report:
    sources: list[SourceResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unknown_opponents: set[str] = field(default_factory=set)
    changed_teams: list[str] = field(default_factory=list)

    @property
    def problems(self) -> list[SourceResult]:
        return [r for r in self.sources if r.status in ("failed", "suspicious")]

    def to_markdown(self) -> str:
        lines = ["## Source status", "", "| Team | Source | Status | Matches | Previous | Note |", "|---|---|---|---|---|---|"]
        icons = {"ok": "✅", "failed": "❌", "suspicious": "⚠️", "skipped": "⏭️"}
        for r in self.sources:
            lines.append(f"| {r.team} | `{r.source}` | {icons[r.status]} {r.status} | {r.count} | {r.previous} | {r.message} |")
        if self.unknown_opponents:
            lines += ["", "## Opponents missing from opponents.yaml", ""]
            lines += [f"- {name}" for name in sorted(self.unknown_opponents)]
        if self.warnings:
            lines += ["", "## Warnings", ""] + [f"- {w}" for w in self.warnings]
        return "\n".join(lines) + "\n"


def _refresh_source(
    ctx: Context, spec: dict[str, Any], stored: SourceState, guard: float, report: Report, offline: bool
) -> None:
    skey = source_key(spec)
    result = SourceResult(ctx.team.key, skey, "ok", previous=stored.count)
    report.sources.append(result)
    if offline:
        result.status, result.count, result.message = "skipped", len(stored.matches), "offline run"
        return
    adapter = ADAPTERS.get(spec["adapter"])
    if adapter is None:
        result.status, result.message = "failed", f"unknown adapter {spec['adapter']!r}"
        return
    ctx.previous = stored.matches
    try:
        fresh = adapter(ctx, spec)
    except (SourceError, requests.RequestException, KeyError, ValueError, TypeError) as exc:
        result.status, result.message = "failed", f"{type(exc).__name__}: {exc}"[:300]
        log.warning("%s %s failed: %s", ctx.team.key, skey, exc)
        return
    result.count = len(fresh)
    if stored.count >= 4 and len(fresh) < guard * stored.count:
        result.status = "suspicious"
        result.message = f"expected ~{stored.count} matches, got {len(fresh)}; kept previous data"
        return
    # New data overwrites old; matches no longer listed by the source (e.g. past cup rounds) are kept.
    merged = {m.key: m for m in stored.matches}
    merged.update({m.key: m for m in fresh})
    cutoff = ctx.today - timedelta(days=KEEP_DAYS)
    stored.matches = [m for m in merged.values() if not m.start_day or m.start_day >= cutoff]
    stored.count = len(fresh)


def build(config: Config, *, out_dir: Path, today: date | None = None, now: datetime | None = None,
          offline: bool = False, only: list[str] | None = None, session: requests.Session | None = None) -> Report:
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    today = today or now.date()
    report = Report()
    session = session or new_session()
    edits, adds = load_overrides(config.root / "overrides" / "manual.yaml", config)
    used_edits: set[str] = set()
    namer = Namer(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    site_teams: list[dict[str, Any]] = []
    all_specs: list[EventSpec] = []
    all_events: dict[str, EventRecord] = {}

    for team in config.teams.values():
        state_path = config.root / "data" / f"{team.key}.json"
        state = TeamState.load(state_path, team.key)
        if not only or team.key in only:
            ctx = Context(config=config, team=team, session=session, today=today)
            for spec in team.sources:
                stored = state.sources.setdefault(source_key(spec), SourceState())
                _refresh_source(ctx, spec, stored, config.settings.shrink_guard, report, offline)
            report.warnings += [f"{team.key}: {w}" for w in ctx.warnings]

        groups = [state.sources.get(source_key(spec), SourceState()).matches for spec in team.sources]
        groups.append([added_match(a, config) for a in adds if a.team == team.key])
        # manually added matches take top priority
        matches = combine([groups[-1], *groups[:-1]])

        hidden: set[str] = set()
        for edit in edits:
            if edit.match in matches:
                used_edits.add(edit.match)
                if edit.hide:
                    hidden.add(edit.match)
                else:
                    apply_edit(matches[edit.match], edit)
        # Only matches with an official date are published; the rest wait until a date is announced.
        hidden |= set(apply_round_dates(matches, config.competitions))

        specs: list[EventSpec] = [build_event(m, config, namer) for k, m in matches.items() if k not in hidden]
        update_ledger(specs, state, config, now)
        if state.save(state_path):
            report.changed_teams.append(team.key)

        _write_feed(out_dir, team.key, team, specs, state.events, config)
        site_teams.append(_site_entry(team, specs, config, now))
        all_specs += specs
        all_events.update(state.events)

    site_combined = []
    for feed in config.combined.values():
        _write_feed(out_dir, feed.key, feed, all_specs, all_events, config)
        site_combined.append(_site_entry(feed, all_specs, config, now))

    for edit in edits:
        if edit.match not in used_edits:
            report.warnings.append(f"overrides: no match with code '{edit.match}' (typo?)")
    report.unknown_opponents = namer.unknown
    site = {
        "generated": now.isoformat().replace("+00:00", "Z"),
        "site_url": config.settings.site_url,
        "teams": site_teams,
        "combined": site_combined,
    }
    (out_dir / "data.json").write_text(json.dumps(site, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return report


def _write_feed(out_dir: Path, key: str, feed: Team | Combined, specs: list[EventSpec],
                events: dict[str, EventRecord], config: Config) -> None:
    """Write <key>.ics (feed's default alert) plus one <key>-alarm-<min>.ics per alert option."""
    for variant in sorted({feed.alarm_minutes or 0, *config.settings.alert_variants}):
        (out_dir / f"{key}-alarm-{variant}.ics").write_bytes(build_calendar(feed, specs, events, config, variant or None))
    (out_dir / f"{key}.ics").write_bytes(build_calendar(feed, specs, events, config, feed.alarm_minutes))


def _site_entry(feed: Team | Combined, specs: list[EventSpec], config: Config, now: datetime) -> dict[str, Any]:
    def start_iso(spec: EventSpec) -> str:
        return spec.start.isoformat().replace("+00:00", "Z") if isinstance(spec.start, datetime) else spec.start.isoformat()

    upcoming = []
    for spec in specs:
        end = spec.end if isinstance(spec.end, datetime) else datetime.combine(spec.end, datetime.min.time(), timezone.utc)
        if end >= now and spec.status != "CANCELLED":
            upcoming.append(spec)
    upcoming.sort(key=lambda s: start_iso(s))
    is_team = isinstance(feed, Team)
    return {
        "key": feed.key,
        "calendar_name": feed.calendar_name,
        "sport": feed.sport if is_team else None,
        "gender": feed.gender if is_team else None,
        "emoji": config.settings.emoji[feed.sport] if is_team else "📅",
        "color": feed.color,
        "alarm_minutes": feed.alarm_minutes,
        "alert_variants": config.settings.alert_variants,
        "match_count": len(specs),
        "upcoming": [
            {"title": s.summary, "start": start_iso(s), "all_day": s.all_day, "status": s.status,
             "competition": config.competitions[s.match.competition].name, "round": s.match.round_label,
             "location": s.location, "team": s.match.team}
            for s in upcoming[:5]
        ],
    }

