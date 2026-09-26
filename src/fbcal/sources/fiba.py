"""FIBA competitions (fiba.basketball), e.g. EuroLeague Women.

The public games page is a Next.js app whose schedule is embedded as React Server Component payload
(`self.__next_f.push([1, "..."])` chunks). Each game is a JSON object starting with {"gameId": ...}; we decode
those objects directly instead of scraping the rendered HTML.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any

from ..http import SourceError, get_text
from ..models import Match
from ..names import slug
from .base import Context, int_or_none, side_of

BASE = "https://www.fiba.basketball/en/events"
_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)
_GAME = re.compile(r'\{"gameId":')
ROUND_TR = {
    "RS-FR": "Normal Sezon 1. Tur",
    "RS-SR": "Normal Sezon 2. Tur",
    "QF-PI": "Çeyrek Final Play-in",
    "QF": "Çeyrek Final",
    "SF-PI": "Yarı Final Play-in",
    "SF": "Yarı Final",
    "3PG": "Üçüncülük Maçı",
    "F": "Final",
}
TBD = "Rakip belli değil"


def season_slug(today: date) -> str:
    start = today.year if today.month >= 7 else today.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def extract_games(html: str) -> list[dict[str, Any]]:
    chunks = _CHUNK.findall(html)
    if not chunks:
        raise SourceError("FIBA: no embedded schedule data found (page layout may have changed)")
    text = "".join(json.loads(f'"{c}"') for c in chunks)
    decoder = json.JSONDecoder()
    games: dict[Any, dict[str, Any]] = {}
    for found in _GAME.finditer(text):
        try:
            obj, _ = decoder.raw_decode(text, found.start())
        except ValueError:
            continue
        games[obj.get("gameId")] = obj
    return list(games.values())


def parse_game(game: dict[str, Any], ctx: Context, competition: str) -> Match | None:
    team_a, team_b = game.get("teamA") or {}, game.get("teamB") or {}
    home, away = team_a.get("officialName") or TBD, team_b.get("officialName") or TBD
    side = side_of(ctx.team, home, away)
    if side is None:
        return None
    rnd = game.get("round") or {}
    code = rnd.get("roundCode") or "round"
    kickoff = day = None
    try:
        if game.get("hasTimeGameDateTime") and game.get("gameDateTimeUTC"):
            kickoff = datetime.fromisoformat(game["gameDateTimeUTC"]).replace(tzinfo=timezone.utc)
        elif game.get("gameDateTime"):
            day = datetime.fromisoformat(game["gameDateTime"]).date()
    except ValueError:
        ctx.warn(f"FIBA {game.get('gameId')}: could not parse date")
    finished = game.get("statusCode") in ("END", "FINAL", "CLOSED") or (
        game.get("statusCode") not in ("INIT", None) and not game.get("isLive") and (game.get("teamAScore") or game.get("teamBScore"))
    )
    status = "postponed" if game.get("isPostponed") else ("finished" if finished else "scheduled")
    return Match(
        team=ctx.team.key,
        competition=competition,
        stage=f"{slug(code)}-g{game.get('gameNumber')}",
        side=side,
        home=home,
        away=away,
        round_label=ROUND_TR.get(code, rnd.get("roundName") or ""),
        kickoff=kickoff,
        day=day,
        venue=game.get("venueName") or "",
        city=game.get("hostCity") or "",
        status=status,
        home_score=int_or_none(game.get("teamAScore")) if status == "finished" else None,
        away_score=int_or_none(game.get("teamBScore")) if status == "finished" else None,
        source="fiba",
        source_id=str(game.get("gameId")),
    )


def fetch(ctx: Context, spec: dict[str, Any]) -> list[Match]:
    """spec: event (slug prefix, e.g. "euroleague-women"), competition."""
    url = f"{BASE}/{spec['event']}-{season_slug(ctx.today)}/games"
    games = extract_games(get_text(ctx.session, url))
    return [m for g in games if (m := parse_game(g, ctx, spec["competition"]))]
