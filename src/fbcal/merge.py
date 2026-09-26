"""Merge copies of the same match from different sources and apply official round dates."""

from __future__ import annotations

import copy
from collections import defaultdict

from .config import Competition
from .models import Match, round_number

FILL_FIELDS = ("venue", "city", "url", "broadcast", "round_label", "score_note")


def _quality(match: Match) -> int:
    if match.kickoff is not None:
        return 2
    if match.day is not None:
        return 1
    return 0


def combine(groups: list[list[Match]]) -> dict[str, Match]:
    """Merge copies of the same match. `groups` is in source-priority order (earlier wins ties).

    The copy with a kick-off time is the base; empty fields are filled from the other copies; a copy with a
    score provides the score.
    """
    by_key: dict[str, list[tuple[int, Match]]] = defaultdict(list)
    for order, group in enumerate(groups):
        for match in group:
            by_key[match.key].append((order, match))
    merged: dict[str, Match] = {}
    for key, copies in by_key.items():
        copies.sort(key=lambda item: (-_quality(item[1]), item[0]))
        base = copy.deepcopy(copies[0][1])
        for _, other in copies[1:]:
            for name in FILL_FIELDS:
                if not getattr(base, name) and getattr(other, name):
                    setattr(base, name, getattr(other, name))
            if not base.has_score and other.has_score:
                base.home_score, base.away_score, base.status = other.home_score, other.away_score, other.status
            if base.status == "scheduled" and other.status in ("postponed", "cancelled") and _quality(other) >= _quality(base):
                base.status = other.status
        merged[key] = base
    return merged


def apply_round_dates(matches: dict[str, Match], competitions: dict[str, Competition]) -> list[str]:
    """Give undated league matches their official day from `round_dates` in competitions.yaml.

    Returns the keys of matches that still have no official date; they are left out of the feeds
    until a source (or round_dates) provides one. Nothing is ever estimated.
    """
    undated: list[str] = []
    for key, m in matches.items():
        if m.kickoff is not None or m.day is not None:
            continue
        number = round_number(m.stage)
        comp = competitions.get(m.competition)
        official = comp.round_dates.get(number) if comp and number is not None else None
        if official:
            m.day = official
        else:
            undated.append(key)
    return undated
