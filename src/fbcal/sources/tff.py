"""TFF (Turkish Football Federation) pages: Süper Lig, Türkiye Kupası and Süper Kupa.

TFF serves Windows-1254 HTML. The league fixture is read week by week; matches without an announced time only
have a day. The cup page shows only the current round (earlier rounds are kept in stored data).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup, Tag

from ..http import SourceError, get_text
from ..models import Match, stage_for_round
from ..names import pretty, slug, tr_lower
from ..timeutil import TR_MONTHS, local_to_utc
from .base import Context, side_of

BASE = "https://www.tff.org/Default.aspx"
ENCODING = "windows-1254"
LEAGUE_PAGE, CUP_PAGE, SUPER_CUP_PAGE, MATCH_PAGE = 198, 598, 329, 29

_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_TIME = re.compile(r"(\d{1,2}):(\d{2})")
_SCORE = re.compile(r"(\d+)\s*-\s*(\d+)")
_PEN = re.compile(r"\((\d+)\s*-\s*(\d+)\s*P\.?\)", re.IGNORECASE)
_MAC_ID = re.compile(r"macId=(\d+)", re.IGNORECASE)
_WEEK = re.compile(r"(\d+)\.\s*Hafta")
_CUP_DATE = re.compile(r"(\d{1,2})\s+([^\d\s]+)\s+(\d{4})(?:\s+(\d{1,2}):(\d{2}))?")


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _mac_id(node: Tag | None) -> str:
    if node is None:
        return ""
    link = node if node.name == "a" and node.has_attr("href") else node.find("a", href=True)
    found = _MAC_ID.search(link["href"]) if link else None
    return found.group(1) if found else ""


def _match_url(mac_id: str) -> str:
    return f"https://www.tff.org/Default.aspx?pageId={MATCH_PAGE}&macId={mac_id}" if mac_id else ""


def _build(
    ctx: Context, competition: str, stage: str, label: str, home: str, away: str,
    day: date, hour: int | None, minute: int | None, score_text: str, mac_id: str,
) -> Match | None:
    side = side_of(ctx.team, home, away)
    if side is None:
        return None
    score = _SCORE.search(score_text)
    pen = _PEN.search(score_text)
    return Match(
        team=ctx.team.key,
        competition=competition,
        stage=stage,
        side=side,
        home=home,
        away=away,
        round_label=label,
        kickoff=local_to_utc(day, hour, minute) if hour is not None and minute is not None else None,
        day=None if hour is not None else day,
        status="finished" if score else "scheduled",
        home_score=int(score.group(1)) if score else None,
        away_score=int(score.group(2)) if score else None,
        score_note=f"pen. {pen.group(1)}-{pen.group(2)}" if pen else "",
        url=_match_url(mac_id),
        source="tff",
        source_id=mac_id,
    )


# --- league ------------------------------------------------------------------------------------


def parse_week_count(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    weeks = [c for c in soup.select("td.belirginYazi") if _WEEK.fullmatch(_text(c))]
    if not weeks:
        raise SourceError("TFF: season fixture table not found (page layout may have changed)")
    return len(weeks)


def parse_league_week(html: str, week: int, ctx: Context, competition: str) -> list[Match]:
    soup = BeautifulSoup(html, "html.parser")
    matches: list[Match] = []
    for row in soup.select("tr.haftaninMaclariTr"):
        home = _text(row.select_one("td.haftaninMaclariEv"))
        away = _text(row.select_one("td.haftaninMaclariDeplasman"))
        date_text = _text(row.find("span", id=re.compile(r"lblTarih$")))
        time_text = _text(row.find("span", id=re.compile(r"lblSaat$")))
        found = _DATE.search(date_text)
        if not found:
            if side_of(ctx.team, home, away):
                ctx.warn(f"TFF: could not parse date for '{home} - {away}' ({date_text!r})")
            continue
        clock = _TIME.search(time_text)
        score_cell = row.select_one("td.haftaninMaclariSkor")
        match = _build(
            ctx, competition, stage_for_round(week), f"{week}. Hafta", home, away,
            date(int(found.group(3)), int(found.group(2)), int(found.group(1))),
            int(clock.group(1)) if clock else None, int(clock.group(2)) if clock else None,
            _text(score_cell), _mac_id(score_cell),
        )
        if match:
            matches.append(match)
    return matches


def parse_venue(html: str) -> tuple[str, str]:
    link = BeautifulSoup(html, "html.parser").find("a", id=re.compile(r"lnkStad$"))
    stadium, _, city = _text(link).partition(" - ")
    return pretty(stadium), pretty(city)


def _fill_venues(ctx: Context, matches: list[Match], known: dict[str, tuple[str, str]]) -> None:
    """Venues live on each match page; already-known venues are not fetched again."""
    for match in matches:
        if not match.source_id:
            continue
        if match.source_id in known:
            match.venue, match.city = known[match.source_id]
            continue
        try:
            venue = parse_venue(get_text(ctx.session, BASE, encoding=ENCODING, pageId=MATCH_PAGE, macId=match.source_id))
        except SourceError:
            continue
        if venue[0]:
            match.venue, match.city = venue


# --- cup -------------------------------------------------------------------------------------


def _cup_stage(label: str) -> tuple[str, str]:
    label = re.sub(r"\s*Maçları\s*$", "", label, flags=re.IGNORECASE).strip()
    label = re.sub(r"(\d)\.(?=\S)", r"\1. ", label)
    return slug(label) or "tur", label


def parse_cup(html: str, ctx: Context, competition: str) -> list[Match]:
    soup = BeautifulSoup(html, "html.parser")
    matches: list[Match] = []
    stage, label = "tur", ""
    for span in soup.find_all("span", id=re.compile(r"(lblGrup|lblTarih)$")):
        if span["id"].endswith("lblGrup"):
            stage, label = _cup_stage(_text(span))
            continue
        row = span.find_parent("tr")
        if row is None:
            continue
        home = _text(row.find(id=re.compile(r"lblTakim1$")))
        away = _text(row.find(id=re.compile(r"lblTakim2$")))
        if side_of(ctx.team, home, away) is None:
            continue
        found = _CUP_DATE.search(_text(span))
        month = TR_MONTHS.get(tr_lower(found.group(2))) if found else None
        if not found or month is None:
            ctx.warn(f"TFF cup: could not parse date for '{home} - {away}' ({_text(span)!r})")
            continue
        score_cell = row.find(id=re.compile(r"lblSkor$"))
        match = _build(
            ctx, competition, stage, label, home, away,
            date(int(found.group(3)), month, int(found.group(1))),
            int(found.group(4)) if found.group(4) else None, int(found.group(5)) if found.group(5) else None,
            _text(score_cell), _mac_id(score_cell),
        )
        if match:
            matches.append(match)
    return matches


# --- super cup ---------------------------------------------------------------------------------


def season_start(today: date) -> date:
    return date(today.year if today.month >= 7 else today.year - 1, 7, 1)


def parse_super_cup(html: str, ctx: Context, competition: str, since: date) -> list[Match]:
    """Archive table: date | stadium | team 1 | score | team 2. No time is given, so it is an all-day event."""
    matches: list[Match] = []
    for row in BeautifulSoup(html, "html.parser").find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != 5:
            continue
        found = _DATE.fullmatch(_text(cells[0]))
        if not found:
            continue
        played = date(int(found.group(3)), int(found.group(2)), int(found.group(1)))
        if played < since:
            continue
        match = _build(
            ctx, competition, "final", "", _text(cells[2]), _text(cells[4]), played, None, None,
            _text(cells[3]), _mac_id(cells[3]),
        )
        if match:
            match.side = "neutral"
            match.venue = pretty(_text(cells[1]))
            matches.append(match)
    return matches


# --- entry point ------------------------------------------------------------------------------


def fetch(ctx: Context, spec: dict[str, Any]) -> list[Match]:
    kind, competition = spec["kind"], spec["competition"]
    known = {m.source_id: (m.venue, m.city) for m in ctx.previous if m.source_id and m.venue}
    if kind == "league":
        page = int(spec.get("page_id", LEAGUE_PAGE))
        weeks = parse_week_count(get_text(ctx.session, BASE, encoding=ENCODING, pageID=page))
        matches: list[Match] = []
        for week in range(1, weeks + 1):
            html = get_text(ctx.session, BASE, encoding=ENCODING, pageID=page, hafta=week)
            matches += parse_league_week(html, week, ctx, competition)
    elif kind == "cup":
        matches = parse_cup(get_text(ctx.session, BASE, encoding=ENCODING, pageID=CUP_PAGE), ctx, competition)
    elif kind == "super-cup":
        html = get_text(ctx.session, BASE, encoding=ENCODING, pageID=SUPER_CUP_PAGE)
        return parse_super_cup(html, ctx, competition, season_start(ctx.today))
    else:
        raise SourceError(f"TFF: unknown kind {kind!r}")
    _fill_venues(ctx, matches, known)
    return matches
