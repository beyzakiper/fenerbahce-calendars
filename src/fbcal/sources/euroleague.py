"""Official EuroLeague Basketball API (api-live.euroleague.net)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..http import SourceError, get_json
from ..models import Match, stage_for_round
from .base import Context, int_or_none

API = "https://api-live.euroleague.net/v2/competitions"
PHASE_LABELS = {"PI": "Play-in", "PO": "Play-off", "FF": "Final Four"}


def _title(text: str) -> str:
    text = " ".join((text or "").split())
    return text.title() if text and text == text.upper() else text


def parse_game(game: dict[str, Any], competition: str, ctx: Context, team_code: str) -> Match | None:
    local, road = game.get("local") or {}, game.get("road") or {}
    home_code, away_code = (local.get("club") or {}).get("code"), (road.get("club") or {}).get("code")
    if team_code not in (home_code, away_code):
        return None
    side = "home" if home_code == team_code else "away"
    if game.get("isNeutralVenue"):
        side = "neutral"
    phase = (game.get("phaseType") or {}).get("code") or "RS"
    number = int(game.get("round") or 0)
    if phase == "RS":
        stage, label = stage_for_round(number), f"{number}. Hafta"
    else:
        stage, label = f"{phase.lower()}-r{number}", PHASE_LABELS.get(phase, game.get("roundName") or phase)

    kickoff = day = None
    try:
        moment = datetime.fromisoformat(str(game["utcDate"]).replace("Z", "+00:00"))
        if game.get("confirmedDate") and game.get("confirmedHour"):
            kickoff = moment
        elif game.get("confirmedDate"):
            day = datetime.fromisoformat(str(game.get("localDate"))).date()
    except (KeyError, TypeError, ValueError):
        ctx.warn(f"EuroLeague {game.get('identifier')}: could not parse date")

    played = bool(game.get("played"))
    code = game.get("gameCode")
    season_code = (game.get("season") or {}).get("code", "")
    return Match(
        team=ctx.team.key,
        competition=competition,
        stage=stage,
        side=side,
        home=(local.get("club") or {}).get("name") or "?",
        away=(road.get("club") or {}).get("name") or "?",
        round_label=label,
        kickoff=kickoff,
        day=day,
        venue=_title((game.get("venue") or {}).get("name", "")),
        status="finished" if played else "scheduled",
        home_score=int_or_none(local.get("score")) if played else None,
        away_score=int_or_none(road.get("score")) if played else None,
        url=f"https://www.euroleaguebasketball.net/euroleague/game-center/{season_code[1:]}/g/{code}/" if code else "",
        source="euroleague",
        source_id=str(game.get("identifier") or game.get("id")),
    )


def fetch(ctx: Context, spec: dict[str, Any]) -> list[Match]:
    team_code = spec["team_code"]
    matches: list[Match] = []
    for comp_code, competition in (spec.get("competitions") or {}).items():
        seasons = get_json(ctx.session, f"{API}/{comp_code}/seasons").get("data") or []
        started = [s for s in seasons if str(s.get("startDate", ""))[:10] <= ctx.today.isoformat()]
        if not started:
            continue
        season = max(started, key=lambda s: s.get("year", 0))["code"]
        payload = get_json(ctx.session, f"{API}/{comp_code}/seasons/{season}/games", teamCode=team_code)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise SourceError("EuroLeague: unexpected response format")
        for game in payload["data"]:
            match = parse_game(game, competition, ctx, team_code)
            if match:
                matches.append(match)
    return matches
