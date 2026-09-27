"""Per-team persistent state (data/<team>.json): last known-good data per source and the event ledger.

The file only changes when the data really changes (no run timestamps are written), so the workflow
only commits when something changed.
"""

from __future__ import annotations

import json
import re
from datetime import date
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Match
from .timeutil import season_of

VERSION = 2  # 2: match keys include the season ("2026-27/volleyball-women/sultanlar-ligi/r01")
_UID_SEASON = re.compile(r"^(\d{4}-\d{2})-")


@dataclass
class SourceState:
    count: int = 0  # number of matches in the last successful fetch
    matches: list[Match] = field(default_factory=list)


@dataclass
class EventRecord:
    uid: str
    sequence: int
    hash: str
    created: str
    last_modified: str


@dataclass
class TeamState:
    team: str
    sources: dict[str, SourceState] = field(default_factory=dict)
    events: dict[str, EventRecord] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path, team: str) -> TeamState:
        if not path.exists():
            return cls(team=team)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version", 1) < 2:
            raw = _migrate_v1(raw)
        return cls(
            team=team,
            sources={
                k: SourceState(count=v.get("count", 0), matches=[Match.from_json(m) for m in v.get("matches", [])])
                for k, v in (raw.get("sources") or {}).items()
            },
            events={k: EventRecord(**v) for k, v in (raw.get("events") or {}).items()},
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "team": self.team,
            "sources": {
                k: {"count": v.count, "matches": [m.to_json() for m in sorted(v.matches, key=lambda m: m.key)]}
                for k, v in sorted(self.sources.items())
            },
            "events": {k: vars(v) for k, v in sorted(self.events.items())},
        }

    def save(self, path: Path) -> bool:
        """Write the file; return True if its content changed."""
        text = json.dumps(self.to_json(), ensure_ascii=False, indent=1, sort_keys=False) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True


def _migrate_v1(raw: dict[str, Any]) -> dict[str, Any]:
    """v1 keys had no season. Prefix each ledger key with the season already baked into its UID, so every
    subscriber keeps exactly the same UIDs; stored matches get their season from their date (or, if undated,
    from the ledger entry with the same code)."""
    events: dict[str, Any] = {}
    code_season: dict[str, str] = {}
    for code, record in (raw.get("events") or {}).items():
        found = _UID_SEASON.match(record["uid"])
        season = found.group(1) if found else season_of(date.today())
        events[f"{season}/{code}"] = record
        code_season[code] = season
    for source in (raw.get("sources") or {}).values():
        for m in source.get("matches", []):
            if m.get("season"):
                continue
            day = (m.get("kickoff") or m.get("day") or "")[:10]
            code = "/".join(p for p in (m["team"], m["competition"], m["stage"], m.get("leg") or "") if p)
            m["season"] = season_of(date.fromisoformat(day)) if day else code_season.get(code, season_of(date.today()))
    return {**raw, "version": VERSION, "events": events}
