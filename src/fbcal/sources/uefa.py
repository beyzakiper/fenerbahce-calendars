"""Official UEFA match API (match.uefa.com): Champions League, Europa League, Conference League, Super Cup."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..http import SourceError, get_json
from ..models import Match
from ..names import slug
from .base import Context, int_or_none

API = "https://match.uefa.com/v5/matches"
PAGE = 100
URL_SLUGS = {
    "1": "uefachampionsleague", "14": "uefaeuropaleague", "2019": "uefaconferenceleague", "2": "uefasupercup",
    "28": "womenschampionsleague",
}
ROUND_TR = {
    "FIRST_QUALIFYING": "1. Ön Eleme Turu",
    "SECOND_QUALIFYING": "2. Ön Eleme Turu",
    "THIRD_QUALIFYING": "3. Ön Eleme Turu",
    "PLAY_OFF": "Play-Off Turu",
    "KNOCKOUT_PLAYOFF": "Eleme Play-Off Turu",
    "ROUND_OF_16": "Son 16 Turu",
    "QUARTER_FINALS": "Çeyrek Final",
    "SEMIFINAL": "Yarı Final",
    "SEMI_FINALS": "Yarı Final",
    "FINAL": "Final",
}
STATUS = {"FINISHED": "finished", "POSTPONED": "postponed", "CANCELLED": "cancelled", "ABANDONED": "postponed"}


def season_year(today: date) -> int:
    """UEFA names seasons by their end year (2026/27 -> 2027)."""
    return today.year + 1 if today.month >= 7 else today.year


def _en(entity: dict[str, Any] | None, key: str = "name") -> str:
    return (((entity or {}).get("translations") or {}).get(key) or {}).get("EN") or ""


def parse_match(item: dict[str, Any], competition: str, comp_id: str, ctx: Context, team_id: str) -> Match | None:
    home, away = item.get("homeTeam") or {}, item.get("awayTeam") or {}
    if team_id == str(home.get("id")):
        side = "home"
    elif team_id == str(away.get("id")):
        side = "away"
    else:
        return None
    meta = (item.get("round") or {}).get("metaData") or {}
    rtype = meta.get("type") or ""
    number = (item.get("matchday") or {}).get("sequenceNumber")
    if rtype == "GROUP_STANDINGS" or meta.get("name") == "League Phase":
        stage, label, leg = f"league-md{number}", f"Lig Aşaması {number}. Maç", ""
    else:
        stage = slug(rtype or meta.get("name") or "round")
        label = ROUND_TR.get(rtype, meta.get("name") or "")
        leg_no = (item.get("leg") or {}).get("number")
        leg = str(leg_no) if leg_no and rtype != "FINAL" else ""
        if leg:
            label += f" ({leg}. maç)"
        elif item.get("type") == "GROUP_STAGE" and number:
            # mini-tournament rounds (e.g. women's qualifying) hold several single matches per team
            stage += f"-md{number}"

    kick = item.get("kickOffTime") or {}
    kickoff = day = None
    try:
        if kick.get("dateTime"):
            kickoff = datetime.fromisoformat(kick["dateTime"].replace("Z", "+00:00"))
        elif kick.get("date"):
            day = date.fromisoformat(kick["date"])
    except ValueError:
        ctx.warn(f"UEFA {item.get('id')}: could not parse date")

    status = STATUS.get(item.get("status") or "", "scheduled")
    total = (item.get("score") or {}).get("total") or {}
    penalty = (item.get("score") or {}).get("penalty") or {}
    note = ""
    if penalty.get("home") is not None and penalty.get("away") is not None:
        note = f"pen. {penalty['home']}-{penalty['away']}"
    stadium = item.get("stadium") or {}
    url_slug = URL_SLUGS.get(comp_id)
    return Match(
        team=ctx.team.key,
        competition=competition,
        stage=stage,
        leg=leg,
        side=side,
        home=home.get("internationalName") or "?",
        away=away.get("internationalName") or "?",
        round_label=label,
        kickoff=kickoff,
        day=day,
        venue=_en(stadium),
        city=_en(stadium.get("city")),
        status=status,
        home_score=int_or_none(total.get("home")) if status == "finished" else None,
        away_score=int_or_none(total.get("away")) if status == "finished" else None,
        score_note=note,
        url=f"https://www.uefa.com/{url_slug}/match/{item['id']}/" if url_slug else "",
        source="uefa",
        source_id=str(item.get("id")),
    )


def fetch(ctx: Context, spec: dict[str, Any]) -> list[Match]:
    team_id = str(spec["team_id"])
    matches: list[Match] = []
    for comp_id, competition in (spec.get("competitions") or {}).items():
        offset = 0
        while True:
            page = get_json(
                ctx.session, API, competitionId=comp_id, seasonYear=season_year(ctx.today), teamId=team_id,
                limit=PAGE, offset=offset, order="ASC",
            )
            if not isinstance(page, list):
                raise SourceError(f"UEFA: unexpected response format ({type(page).__name__})")
            for item in page:
                match = parse_match(item, competition, str(comp_id), ctx, team_id)
                if match:
                    matches.append(match)
            if len(page) < PAGE:
                break
            offset += PAGE
    return matches
