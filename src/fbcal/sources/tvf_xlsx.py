"""TVF general fixture spreadsheet ("Genel Fikstür ve Maç Programı", linked from the tvf.org.tr homepage).

One sheet lists every match TVF has scheduled for the season (leagues, cups, super cups, national teams) with
date, time, venue, league code, round and an official match number. It is published ahead of the fixture
website, so it is the main volleyball source. The file name contains the season, so the URL is built each run.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime, time
from typing import Any

import openpyxl

from ..http import SourceError, get_bytes
from ..models import Match, stage_for_round
from ..names import pretty, slug
from ..timeutil import local_to_utc
from .base import Context, side_of

URL_TEMPLATE = "https://tvf.org.tr/_dosyalar/Lig_Sezon_Arsivi/Genel_Fiksturler/{season}_genel_fikstur.xlsx"
REQUIRED = ("TARİH", "SAAT", "A TAKIMI", "B TAKIMI", "LİG", "E-K", "TÜR", "HAFTA", "NO", "MT/KULÜP")
_SCORE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


def season_label(today: date) -> str:
    start = today.year if today.month >= 7 else today.year - 1
    return f"{start}-{start + 1}"


def _time(value: Any) -> time | None:
    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, time):
        return None if (value.hour, value.minute) == (0, 0) else value  # 00:00 = not announced
    found = re.match(r"^\s*(\d{1,2})[:.](\d{2})", str(value or ""))
    return time(int(found.group(1)), int(found.group(2))) if found and found.group(1) != "0" else None


def _text(value: Any) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def read_rows(data: bytes) -> list[dict[str, Any]]:
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises several exception types for bad files
        raise SourceError(f"could not open TVF spreadsheet: {exc}") from exc
    for sheet in workbook.worksheets:
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None)
        if not header or not all(col in header for col in REQUIRED):
            continue
        names = [_text(h) for h in header]
        return [dict(zip(names, row)) for row in rows if any(v is not None for v in row)]
    raise SourceError("TVF spreadsheet: no sheet with the expected columns (layout may have changed)")


def parse_row(row: dict[str, Any], ctx: Context, leagues: dict[str, str], gender: str, season: str) -> Match | None:
    if _text(row.get("MT/KULÜP")).upper() != "KULÜP" or _text(row.get("E-K")).upper() != gender:
        return None
    competition = leagues.get(_text(row.get("LİG")))
    if competition is None:
        return None
    home, away = _text(row.get("A TAKIMI")), _text(row.get("B TAKIMI"))
    side = side_of(ctx.team, home, away)
    if side is None:
        return None
    day_value = row.get("TARİH")
    if not isinstance(day_value, (datetime, date)):
        ctx.warn(f"TVF spreadsheet: no date for '{home} - {away}'")
        return None
    day = day_value.date() if isinstance(day_value, datetime) else day_value
    clock = _time(row.get("SAAT"))

    kind, number = _text(row.get("TÜR")).upper(), row.get("HAFTA")
    if kind == "LE" and str(number or "").strip().isdigit():
        week = int(str(number).strip())
        stage, label = stage_for_round(week), f"{week}. Hafta"
    else:  # cups, super cups, play-offs: the official match number is the stable id
        stage = slug(_text(row.get("NO"))) or slug(f"{kind} {home} {away}")
        group = _text(row.get("GRUP"))
        label = f"{group}. Grup" if kind == "GRUP" and group else pretty(_text(row.get("TÜR")))

    score = _SCORE.match(_text(row.get("SONUÇ")))
    return Match(
        team=ctx.team.key,
        competition=competition,
        stage=stage,
        side=side,
        home=home,
        away=away,
        round_label=label,
        kickoff=local_to_utc(day, clock.hour, clock.minute) if clock else None,
        day=None if clock else day,
        venue=pretty(_text(row.get("SALON (ŞEHİR*)"))),
        city=pretty(_text(row.get("İL (ÜLKE*)"))),
        status="finished" if score else "scheduled",
        home_score=int(score.group(1)) if score else None,
        away_score=int(score.group(2)) if score else None,
        season=season,
        source="tvf_xlsx",
        source_id=_text(row.get("NO")),
    )


def fetch(ctx: Context, spec: dict[str, Any]) -> list[Match]:
    """spec: gender (K/E), leagues ({spreadsheet league code: competition key}), optional url_template."""
    label = season_label(ctx.today)
    url = spec.get("url_template", URL_TEMPLATE).format(season=label)
    rows = read_rows(get_bytes(ctx.session, url))
    season = f"{label[:4]}-{label[-2:]}"
    leagues = {str(k): v for k, v in spec["leagues"].items()}
    return [m for row in rows if (m := parse_row(row, ctx, leagues, spec["gender"], season))]
