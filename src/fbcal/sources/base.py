"""Shared context and helpers for adapters."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import requests

from ..config import Config, Team
from ..models import Match, Side

log = logging.getLogger("fbcal.sources")


@dataclass
class Context:
    config: Config
    team: Team
    session: requests.Session
    today: date
    previous: list[Match] = field(default_factory=list)  # last good data from this source
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        log.warning("%s: %s", self.team.key, message)
        self.warnings.append(message)


def side_of(team: Team, home: str, away: str) -> Side | None:
    """Fenerbahçe's side, or None if the match does not involve this team."""
    home_us, away_us = team.is_us(home), team.is_us(away)
    if home_us and not away_us:
        return "home"
    if away_us and not home_us:
        return "away"
    return None


def int_or_none(value: object) -> int | None:
    try:
        text = str(value).strip()
        return int(float(text)) if text not in {"", "None", "-"} else None
    except (TypeError, ValueError):
        return None
