"""TBF (Turkish Basketball Federation) web API: leagues and cups.

A time of "00:00" means the day is set but the tip-off time is not announced (published as all-day).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..http import SourceError, get_json
from ..models import Match, stage_for_round
from ..names import pretty
from ..timeutil import local_to_utc
from .base import Context, int_or_none, side_of

API = "https://miniappapi.tbf.org.tr/webapi-service/api"


def _seasons(ctx: Context, prefix: str) -> list[dict[str, Any]]:
    data = get_json(ctx.session, f"{API}/League/get-leagues-and-seasons-by-prefix", prefix=prefix).get("data") or []
    return sorted(data, key=lambda s: s["sezon_ID"], reverse=True)


def _weeks(ctx: Context, league_id: int, season_id: int) -> list[dict[str, Any]]:
    return get_json(ctx.session, f"{API}/League/get-league-weeks", seasonId=season_id, leagueId=league_id).get("data") or []


def parse_row(row: dict[str, Any], ctx: Context, competition: str, week_no: int, single_round: bool) -> Match | None:
    home, away = row.get("homeTeam") or {}, row.get("awayTeam") or {}
    side = side_of(ctx.team, home.get("name", ""), away.get("name", ""))
    if side is None:
        return None
    kickoff = day = None
    try:
        moment = datetime.fromisoformat(str(row["matchDate"]))
        if moment.hour == 0 and moment.minute == 0:
            day = moment.date()
        else:
            kickoff = local_to_utc(moment.date(), moment.hour, moment.minute)
    except (KeyError, TypeError, ValueError):
        ctx.warn(f"TBF: could not parse date for '{home.get('name')} - {away.get('name')}'")
    hs, as_ = int_or_none(home.get("score")), int_or_none(away.get("score"))
    finished = hs is not None and as_ is not None and (hs or as_)
    label = (row.get("week") or "").strip()
    return Match(
        team=ctx.team.key,
        competition=competition,
        stage="final" if single_round else stage_for_round(week_no),
        side=side,
        home=home.get("name", "?"),
        away=away.get("name", "?"),
        round_label="" if single_round else (label or f"{week_no}. Hafta"),
        kickoff=kickoff,
        day=day,
        venue=pretty(row.get("salonAdi") or ""),
        city=pretty(row.get("il") or ""),
        status="finished" if finished else "scheduled",
        home_score=hs if finished else None,
        away_score=as_ if finished else None,
        broadcast=row.get("broadcastChannel") or "",
        source="tbf",
        source_id=str(int_or_none(row.get("matchId")) or ""),
    )


def fetch(ctx: Context, spec: dict[str, Any]) -> list[Match]:
    """spec: prefix (bsl, kbsl, cbek, ...), competition, cup (bool).

    Leagues use the newest season; cups only count if they belong to the league's current season
    (an empty list until the federation creates this season's cup).
    """
    prefix, competition, is_cup = spec["prefix"], spec["competition"], bool(spec.get("cup"))
    seasons = _seasons(ctx, prefix)
    if not seasons:
        if is_cup:
            return []
        raise SourceError(f"TBF: empty season list for '{prefix}'")
    season = seasons[0]
    if is_cup:
        league_seasons = _seasons(ctx, spec.get("season_from", "bsl"))
        current = league_seasons[0]["sezon_ID"] if league_seasons else None
        if season["sezon_ID"] != current:
            return []  # this season's cup does not exist yet
    league_id, season_id = int(season["faaliyet_ID"]), int(season["sezon_ID"])
    weeks = _weeks(ctx, league_id, season_id)
    if not weeks and not is_cup:
        raise SourceError(f"TBF: empty week list for '{prefix}'")
    matches: list[Match] = []
    for week in weeks:
        week_no = int(week["sezon_Hafta"])
        params: dict[str, Any] = {"ActivityId": league_id, "WeekFilter": week_no, "Page": 1, "PageSize": -1}
        if int(week.get("devre_ID") or 1) not in (1, 2) and week.get("devre_Deger"):
            params["HalfValue"] = week["devre_Deger"]
        rows = get_json(ctx.session, f"{API}/Match/get-all-matches-for-filter", **params).get("data") or []
        for row in rows:
            if int_or_none(row.get("seasonId")) not in (None, season_id):
                continue  # cup queries also return past seasons
            match = parse_row(row, ctx, competition, week_no, single_round=is_cup and len(weeks) == 1)
            if match:
                matches.append(match)
    return matches
