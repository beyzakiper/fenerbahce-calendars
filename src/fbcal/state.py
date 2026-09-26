"""Per-team persistent state (data/<team>.json): last known-good data per source and the event ledger.

The file only changes when the data really changes (no run timestamps are written), so the workflow
only commits when something changed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Match

VERSION = 1


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
