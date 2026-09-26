"""TVF fixture-draw PDF: the season's full opponent order (no dates).

The PDF table comes in blocks of four rounds: a header row with "N. HAFTA", then rows holding a
(home, away) column pair per round. There are no dates; days come from round_dates or estimation.
"""

from __future__ import annotations

import io
import re
from typing import Any

import pdfplumber

from ..http import SourceError, get_bytes
from ..models import Match, stage_for_round
from .base import Context, side_of

_WEEK = re.compile(r"(\d+)\.\s*HAFTA", re.IGNORECASE)


def parse_pdf(data: bytes, ctx: Context, competition: str, url: str = "") -> list[Match]:
    matches: list[Match] = []
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # pdfplumber can raise many exception types
        raise SourceError(f"could not open TVF PDF: {exc}") from exc
    with pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                weeks: list[int | None] = []
                for row in table:
                    cells = [" ".join((c or "").split()) for c in row]
                    if any(_WEEK.fullmatch(c) for c in cells if c):
                        weeks = []
                        for i in range(0, len(cells), 2):
                            found = _WEEK.fullmatch(cells[i]) if cells[i] else None
                            weeks.append(int(found.group(1)) if found else None)
                        continue
                    for pair, week in enumerate(weeks):
                        if week is None or 2 * pair + 1 >= len(cells):
                            continue
                        home, away = cells[2 * pair], cells[2 * pair + 1]
                        side = side_of(ctx.team, home, away)
                        if side is None:
                            continue
                        matches.append(
                            Match(
                                team=ctx.team.key,
                                competition=competition,
                                stage=stage_for_round(week),
                                side=side,
                                home=home,
                                away=away,
                                round_label=f"{week}. Hafta",
                                url=url,
                                source="tvf_pdf",
                                source_id=f"r{week}",
                            )
                        )
    return matches


def fetch(ctx: Context, spec: dict[str, Any]) -> list[Match]:
    url = spec["url"]
    return parse_pdf(get_bytes(ctx.session, url), ctx, spec["competition"], "")
