"""Merge sources and estimate missing match days."""

from __future__ import annotations

import copy
from collections import defaultdict
from datetime import date, timedelta

from .config import Competition
from .models import Match, round_number

FILL_FIELDS = ("venue", "city", "url", "broadcast", "round_label", "score_note")


def _quality(match: Match) -> int:
    if match.kickoff is not None:
        return 2
    if match.day is not None and not match.date_estimated:
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


def _interpolate(target: int, known: dict[int, date]) -> date | None:
    if not known:
        return None
    if target in known:
        return known[target]
    before = [r for r in known if r < target]
    after = [r for r in known if r > target]
    if before and after:
        lo, hi = max(before), min(after)
        span = (known[hi] - known[lo]).days
        return known[lo] + timedelta(days=round(span * (target - lo) / (hi - lo)))
    nearest = max(before) if before else min(after)
    return known[nearest] + timedelta(days=7 * (target - nearest))


def fill_estimated_days(matches: dict[str, Match], competitions: dict[str, Competition]) -> list[str]:
    """Give a day to league matches without one: round_dates first, else interpolate from known rounds.

    Returns the keys of matches that could not be placed (they are left out of the feed).
    """
    known: dict[str, dict[int, date]] = defaultdict(dict)
    for m in matches.values():
        number = round_number(m.stage)
        if number is not None and m.start_day and not m.date_estimated:
            known[m.competition][number] = m.start_day
    unplaced: list[str] = []
    for key, m in matches.items():
        if m.kickoff is not None or m.day is not None:
            continue
        number = round_number(m.stage)
        comp = competitions.get(m.competition)
        configured = comp.round_dates.get(number) if comp and number is not None else None
        if configured:  # expected day entered from the official calendar
            m.day, m.date_estimated = configured, False
            continue
        anchors = {**(comp.estimate_anchors if comp else {}), **(comp.round_dates if comp else {}), **known[m.competition]}
        guess = _interpolate(number, anchors) if number else None
        if guess:
            m.day, m.date_estimated = guess, True
        else:
            unplaced.append(key)
    return unplaced
