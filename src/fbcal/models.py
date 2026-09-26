"""Common match model: every source adapter returns matches in this shape."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, timezone
from typing import Any, Literal

Side = Literal["home", "away", "neutral"]
Status = Literal["scheduled", "postponed", "cancelled", "finished"]


@dataclass
class Match:
    team: str  # team key, e.g. "volleyball-women"
    competition: str  # key in competitions.yaml
    stage: str  # round id: "r05" (round 5), "qf", "2qr", "final"; the date for friendlies
    side: Side  # Fenerbahçe's side
    home: str  # raw home team name from the source
    away: str  # raw away team name from the source
    leg: str = ""  # "1"/"2" for two-legged ties, "g3" for series games
    round_label: str = ""  # displayed round name (Turkish), e.g. "5. Hafta"
    kickoff: datetime | None = None  # UTC, when the time is known
    day: date | None = None  # when only the day is known
    venue: str = ""
    city: str = ""
    status: Status = "scheduled"
    home_score: int | None = None
    away_score: int | None = None
    score_note: str = ""  # e.g. "pen. 4-3"
    url: str = ""
    source: str = ""
    source_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kickoff is not None:
            if self.kickoff.tzinfo is None:
                raise ValueError(f"{self.key}: kickoff must be timezone-aware")
            self.kickoff = self.kickoff.astimezone(timezone.utc)

    @property
    def key(self) -> str:
        """Permanent match key (basis of the UID): team/competition/stage[/leg]. Never contains names or dates."""
        base = f"{self.team}/{self.competition}/{self.stage}"
        return f"{base}/{self.leg}" if self.leg else base

    @property
    def opponent(self) -> str:
        return self.away if self.side == "home" else self.home

    @property
    def has_time(self) -> bool:
        return self.kickoff is not None

    @property
    def start_day(self) -> date | None:
        return self.kickoff.date() if self.kickoff else self.day

    @property
    def has_score(self) -> bool:
        return self.home_score is not None and self.away_score is not None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["kickoff"] = self.kickoff.isoformat().replace("+00:00", "Z") if self.kickoff else None
        data["day"] = self.day.isoformat() if self.day else None
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Match:
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        if values.get("kickoff"):
            values["kickoff"] = datetime.fromisoformat(values["kickoff"].replace("Z", "+00:00"))
        if values.get("day"):
            values["day"] = date.fromisoformat(values["day"])
        return cls(**values)


def stage_for_round(number: int) -> str:
    return f"r{number:02d}"


def round_number(stage: str) -> int | None:
    if len(stage) == 3 and stage[0] == "r" and stage[1:].isdigit():
        return int(stage[1:])
    return None
