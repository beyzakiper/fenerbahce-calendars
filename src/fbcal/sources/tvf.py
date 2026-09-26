"""TVF fixture system (fikstur.tvf.org.tr): Sultanlar Ligi, Efeler Ligi, Kupa Voley.

League links embed base64 of season, gender and league code; because sponsor names change, the link is
discovered from the index page on every run. The page only lists rounds whose dates are announced; the full
opponent order comes from the `tvf_pdf` adapter.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections import defaultdict
from datetime import date
from typing import Any
from urllib.parse import unquote

from bs4 import BeautifulSoup

from ..http import SourceError, get_text
from ..models import Match, stage_for_round
from ..names import fold, pretty, slug
from ..timeutil import local_to_utc
from .base import Context, int_or_none, side_of

BASE = "https://fikstur.tvf.org.tr"
INDEX = f"{BASE}/Fikst%C3%BCr"
ENCODING = "windows-1254"
_LINK = re.compile(r"""href=['"](/FS[MW]/[^'"]+)['"]""")
_CELL_ID = re.compile(r"gvmusabakaliste_(\w+?)_(\d+)$")
_HEADER = re.compile(r"HAFTA\s*:\s*(\d+)", re.IGNORECASE)
_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_TIME = re.compile(r"(\d{1,2}):(\d{2})")


def season_label(today: date) -> str:
    start = today.year if today.month >= 7 else today.year - 1
    return f"{start}-{start + 1}"


def _b64(segment: str) -> str:
    try:
        return base64.b64decode(unquote(segment)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return ""


def find_league_path(index_html: str, season: str, gender: str, code: str = "", name_contains: str = "") -> str | None:
    """Find the fixture path of the requested league among the index page links."""
    for path in dict.fromkeys(_LINK.findall(index_html)):
        parts = path.strip("/").split("/")
        if len(parts) != 5:
            continue
        p_season, p_gender, p_code, p_name = (_b64(p) for p in parts[1:])
        if p_season != season or p_gender != gender:
            continue
        if code and p_code == code:
            return path
        if name_contains and fold(name_contains) in fold(p_name):
            return path
    return None


def parse_fixture(html: str, ctx: Context, competition: str) -> list[Match]:
    rows: dict[int, dict[str, str]] = defaultdict(dict)
    # The markup differs per client (e.g. <font> wrappers), so cells are read by their element ids.
    for span in BeautifulSoup(html, "html.parser").find_all("span", id=_CELL_ID):
        field, index = _CELL_ID.search(span["id"]).groups()
        rows[int(index)][field] = " ".join(span.get_text(" ", strip=True).split())
    matches: list[Match] = []
    stage, label, week = "tur", "", 0
    for index in sorted(rows):
        row = rows[index]
        first = row.get("gtarih", "")
        header = _HEADER.search(first)
        if header:
            week = int(header.group(1))
            stage, label = stage_for_round(week), f"{week}. Hafta"
            continue
        if not _DATE.search(first):
            if first:  # cup round heading etc.
                stage, label = slug(first) or "tur", pretty(first)
            continue
        home, away = row.get("gevsahibi", ""), row.get("gmisafir", "")
        side = side_of(ctx.team, home, away)
        if side is None:
            continue
        d = _DATE.search(first)
        day = date(int(d.group(3)), int(d.group(2)), int(d.group(1)))
        clock = _TIME.search(row.get("gsaat", ""))
        city, _, venue = row.get("gyer", "").partition("-")
        if not venue:
            city, venue = "", city
        sa, sb = int_or_none(row.get("gseta")), int_or_none(row.get("gsetb"))
        finished = sa is not None and sb is not None and (sa == 3 or sb == 3)
        matches.append(
            Match(
                team=ctx.team.key,
                competition=competition,
                stage=stage,
                side=side,
                home=home,
                away=away,
                round_label=label,
                kickoff=local_to_utc(day, int(clock.group(1)), int(clock.group(2))) if clock else None,
                day=None if clock else day,
                venue=pretty(venue),
                city=pretty(city),
                status="finished" if finished else "scheduled",
                home_score=sa if finished else None,
                away_score=sb if finished else None,
                source="tvf",
                source_id=f"{stage}:{fold(home)}:{fold(away)}",
            )
        )
    return matches


def fetch(ctx: Context, spec: dict[str, Any]) -> list[Match]:
    index = get_text(ctx.session, INDEX, encoding=ENCODING)
    path = find_league_path(
        index, season_label(ctx.today), spec["gender"], spec.get("league_code", ""), spec.get("league_name_contains", "")
    )
    if path is None:
        if spec.get("league_code"):
            raise SourceError(f"TVF: link for {spec.get('league_code')} not found (page layout may have changed)")
        return []  # this season's cup is not published yet
    return parse_fixture(get_text(ctx.session, BASE + path, encoding=ENCODING), ctx, spec["competition"])
