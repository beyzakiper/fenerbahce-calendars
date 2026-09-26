"""Manual overrides (overrides/manual.yaml). Always win over source data."""

from __future__ import annotations

import re
from datetime import date as Date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .config import Config, ConfigError
from .models import Match
from .names import slug
from .timeutil import ISTANBUL

_KICKOFF = re.compile(r"^\d{4}-\d{2}-\d{2} \d{1,2}:\d{2}$")


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kickoff: str | None = None  # "2026-11-08 19:00" (Istanbul time)
    date: Date | None = None  # when only the day is known
    venue: str | None = None
    city: str | None = None
    status: Literal["scheduled", "postponed", "cancelled", "finished"] | None = None
    home_score: int | None = None
    away_score: int | None = None
    round_label: str | None = None
    url: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.kickoff and not _KICKOFF.match(self.kickoff):
            raise ValueError(f"kickoff must look like 'YYYY-MM-DD HH:MM': {self.kickoff!r}")
        return self

    def kickoff_utc(self) -> datetime | None:
        if not self.kickoff:
            return None
        return datetime.strptime(self.kickoff, "%Y-%m-%d %H:%M").replace(tzinfo=ISTANBUL)


class Edit(_Base):
    match: str  # event code, e.g. "volleyball-women/sultanlar-ligi/r05"
    hide: bool = False


class Add(_Base):
    team: str
    competition: str
    opponent: str
    side: Literal["home", "away", "neutral"] = "home"
    stage: str | None = None  # defaults to the date (fine for friendlies)
    leg: str = ""


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    add: Add | None = None


def load_overrides(path: Path, config: Config) -> tuple[list[Edit], list[Add]]:
    if not path.exists():
        return [], []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} could not be read (YAML error): {exc}") from exc
    if not isinstance(raw, list):
        raise ConfigError(f"{path}: expected a list (each entry starts with '- ')")
    edits: list[Edit] = []
    adds: list[Add] = []
    for i, item in enumerate(raw, 1):
        try:
            if isinstance(item, dict) and "add" in item:
                add = _Entry(**item).add
                assert add is not None
                if add.team not in config.teams:
                    raise ValueError(f"unknown team {add.team!r}")
                if add.competition not in config.competitions:
                    raise ValueError(f"unknown competition {add.competition!r} (add it to competitions.yaml)")
                if not (add.kickoff or add.date):
                    raise ValueError("kickoff or date is required")
                adds.append(add)
            else:
                edits.append(Edit(**item))
        except (ValidationError, ValueError, TypeError, AssertionError) as exc:
            raise ConfigError(f"{path}: entry #{i} is invalid: {exc}") from exc
    return edits, adds


def added_match(add: Add, config: Config) -> Match:
    team = config.teams[add.team]
    us, them = team.display_name, add.opponent
    home, away = (them, us) if add.side == "away" else (us, them)
    kick = add.kickoff_utc()
    day = add.date if not kick else None
    stage = add.stage or ((kick.date() if kick else day).isoformat() if (kick or day) else "tbd")
    has_score = add.home_score is not None and add.away_score is not None
    return Match(
        team=add.team,
        competition=add.competition,
        stage=slug(stage) if add.stage else stage,
        leg=add.leg,
        side=add.side,
        home=home,
        away=away,
        round_label=add.round_label or "",
        kickoff=kick,
        day=day,
        venue=add.venue or "",
        city=add.city or "",
        status=add.status or ("finished" if has_score else "scheduled"),
        home_score=add.home_score,
        away_score=add.away_score,
        url=add.url or "",
        source="manual",
        extra={"note": add.note} if add.note else {},
    )


def apply_edit(match: Match, edit: Edit) -> Match:
    kick = edit.kickoff_utc()
    if kick:
        match.kickoff, match.day = kick, None
    elif edit.date:
        match.kickoff, match.day = None, edit.date
    for name in ("venue", "city", "status", "home_score", "away_score", "round_label", "url"):
        value = getattr(edit, name)
        if value is not None:
            setattr(match, name, value)
    if edit.home_score is not None and edit.away_score is not None and edit.status is None:
        match.status = "finished"
    if edit.note:
        match.extra = {**match.extra, "note": edit.note}
    return match
