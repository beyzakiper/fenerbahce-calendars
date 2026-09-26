"""Adapters are tested against real responses saved from each source."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from conftest import fixture_bytes, fixture_text

from fbcal.sources import euroleague, tbf, tff, tvf, tvf_pdf, uefa


def test_tff_league_week_with_time(ctx_for):
    ctx = ctx_for("football-men")
    [m] = tff.parse_league_week(fixture_text("tff_league_week7.html"), 7, ctx, "super-lig")
    assert m.key == "football-men/super-lig/r07"
    assert m.side == "away" and "RİZESPOR" in m.home
    assert m.kickoff == datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)  # 19:00 Istanbul
    assert m.url.endswith("macId=317841")


def test_tff_league_week_without_time_is_day_only(ctx_for):
    [m] = tff.parse_league_week(fixture_text("tff_league_week25.html"), 25, ctx_for("football-men"), "super-lig")
    assert m.kickoff is None and m.day == date(2027, 3, 14)


def test_tff_finished_score(ctx_for):
    [m] = tff.parse_league_week(fixture_text("tff_league_week2.html"), 2, ctx_for("football-men"), "super-lig")
    assert (m.status, m.home_score, m.away_score) == ("finished", 4, 2)


def test_tff_week_count():
    assert tff.parse_week_count(fixture_text("tff_league_overview.html")) == 34


def test_uefa(ctx_for):
    ctx = ctx_for("football-men")
    items = json.loads(fixture_text("uefa_ucl_2027.json"))
    matches = [uefa.parse_match(i, "uefa-sampiyonlar-ligi", "1", ctx, "52692") for i in items]
    keys = [m.key for m in matches]
    assert "football-men/uefa-sampiyonlar-ligi/second-qualifying/1" in keys
    assert "football-men/uefa-sampiyonlar-ligi/league-md2" in keys
    villa = next(m for m in matches if m.stage == "league-md2")
    assert villa.side == "away" and villa.kickoff == datetime(2026, 10, 14, 19, 0, tzinfo=timezone.utc)
    first = matches[0]
    assert (first.status, first.home_score, first.away_score) == ("finished", 1, 0)


def test_euroleague(ctx_for):
    ctx = ctx_for("basketball-men")
    games = json.loads(fixture_text("euroleague_E2025_ULK.json"))["data"]
    matches = [euroleague.parse_game(g, "euroleague", ctx, "ULK") for g in games]
    assert all(matches)
    r1 = next(m for m in matches if m.stage == "r01")
    assert r1.status == "finished" and r1.has_score
    assert any(m.stage.startswith("po-") for m in matches)
    assert len({m.key for m in matches}) == len(matches)


def test_tbf_league_row_tba_and_timed(ctx_for):
    ctx = ctx_for("basketball-men")
    rows = json.loads(fixture_text("tbf_bsl_week1.json"))["data"]
    [m] = [x for r in rows if (x := tbf.parse_row(r, ctx, "basketbol-super-ligi", 1, False))]
    assert m.kickoff == datetime(2026, 9, 27, 15, 0, tzinfo=timezone.utc) and m.side == "away"
    rows = json.loads(fixture_text("tbf_bsl_week20.json"))["data"]
    [m] = [x for r in rows if (x := tbf.parse_row(r, ctx, "basketbol-super-ligi", 20, False))]
    assert m.kickoff is None and m.day == date(2027, 2, 13)
    assert m.venue == "Ülker Spor ve Etkinlik Salonu"


def test_tvf_fixture_both_renderings(ctx_for):
    for name in ("tvf_sultanlar_fikstur.html", "tvf_sultanlar_fikstur_legacy.html"):
        [m] = tvf.parse_fixture(fixture_text(name), ctx_for("volleyball-women"), "sultanlar-ligi")
        assert m.key == "volleyball-women/sultanlar-ligi/r01", name
        assert m.kickoff == datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc)
        assert m.city == "İstanbul" and "Burhan Felek" in m.venue
        assert m.url == ""  # TVF has no per-match page


def test_tvf_league_link_discovery():
    path = tvf.find_league_path(fixture_text("tvf_index.html"), "2026-2027", "K", code="SULTANLAR")
    assert path and path.startswith("/FSW/")
    cup = tvf.find_league_path(fixture_text("tvf_index.html"), "2026-2027", "K", name_contains="Kupa Voley")
    assert cup and cup.startswith("/FSW/")


def test_tvf_pdf_full_order(ctx_for):
    matches = tvf_pdf.parse_pdf(fixture_bytes("tvf_sultanlar_fikstur.pdf"), ctx_for("volleyball-women"), "sultanlar-ligi")
    assert len(matches) == 26
    by_stage = {m.stage: m for m in matches}
    assert by_stage["r01"].side == "home" and "MANİSA" in by_stage["r01"].away
    assert by_stage["r02"].side == "away" and by_stage["r02"].home == "BEŞİKTAŞ"
    assert all(m.kickoff is None and m.day is None for m in matches)


def test_uefa_mini_tournament_matches_get_distinct_keys(ctx_for):
    ctx = ctx_for("football-women")
    items = json.loads(fixture_text("uefa_uwcl_2027_fbw.json"))
    keys = {uefa.parse_match(i, "uefa-kadinlar-sampiyonlar-ligi", "28", ctx, "2612244").key for i in items}
    assert len(keys) == len(items) == 2


def test_fiba_euroleague_women(ctx_for):
    from fbcal.sources import fiba

    ctx = ctx_for("basketball-women")
    games = fiba.extract_games(fixture_text("fiba_elw_2627_games.html"))
    matches = [m for g in games if (m := fiba.parse_game(g, ctx, "euroleague-women"))]
    assert len(matches) == 6 and len({m.key for m in matches}) == 6
    valencia = next(m for m in matches if m.stage == "rs-fr-g1")
    assert valencia.side == "away" and valencia.kickoff == datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc)
    assert any(fiba.TBD in (m.home, m.away) for m in matches)


def test_tff_women_league_uses_same_parser(ctx_for):
    [m] = tff.parse_league_week(fixture_text("tff_women_week5.html"), 5, ctx_for("football-women"), "kadin-futbol-super-ligi")
    assert m.side == "home" and m.kickoff == datetime(2026, 11, 18, 11, 0, tzinfo=timezone.utc)


def test_tvf_men_efeler(ctx_for):
    ctx = ctx_for("volleyball-men")
    order = tvf_pdf.parse_pdf(fixture_bytes("tvf_efeler_fikstur.pdf"), ctx, "efeler-ligi")
    dated = tvf.parse_fixture(fixture_text("tvf_efeler_fikstur.html"), ctx, "efeler-ligi")
    assert len(order) == 26 and [m.key for m in dated] == [order[0].key]
