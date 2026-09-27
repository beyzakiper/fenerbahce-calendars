from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fbcal.ics import css_color_name
from fbcal.merge import apply_round_dates, combine
from fbcal.models import Match
from fbcal.names import fold, pretty
from fbcal.timeutil import fmt_local, local_to_utc, season_of

NY = ZoneInfo("America/New_York")


def test_istanbul_to_utc_and_new_york_across_dst():
    summer = local_to_utc(date(2026, 10, 4), 19, 0)  # US daylight time (EDT, UTC-4)
    winter = local_to_utc(date(2026, 12, 6), 19, 0)  # US standard time (EST, UTC-5)
    assert summer == datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc)
    assert winter == datetime(2026, 12, 6, 16, 0, tzinfo=timezone.utc)
    assert fmt_local(summer, NY) == "12:00" and fmt_local(winter, NY) == "11:00"


def test_season_boundary():
    assert season_of(date(2026, 7, 1)) == "2026-27" and season_of(date(2027, 6, 30)) == "2026-27"


def test_turkish_names():
    assert fold("FENERBAHÇE MEDİCANA") == "fenerbahce medicana"
    assert fold("Işıklar İLBANK") == "isiklar ilbank"
    assert pretty("ECZACIBAŞI PERON İSTANBUL") == "Eczacıbaşı Peron İstanbul"
    assert pretty("MANİSA B.ŞEHİR BLD. SPOR") == "Manisa B.Şehir Bld. Spor"
    assert pretty("Real Madrid") == "Real Madrid"
    assert pretty("CHOBANI STADYUMU FB ŞÜKRÜ SARACOĞLU") == "Chobani Stadyumu FB Şükrü Saracoğlu"


def test_css_color_names():
    assert css_color_name("#1E3A8A") in {"midnightblue", "darkblue", "navy"}
    assert css_color_name("#FFD100") == "gold"


def _m(stage, **kw):
    return Match(team="t-men", competition="c", stage=stage, side="home", home="FB", away="X", season="2026-27", **kw)


def test_combine_prefers_timed_copy_and_fills_gaps():
    tba = _m("r01", venue="Salon", url="pdf")
    timed = _m("r01", kickoff=datetime(2026, 1, 1, 17, tzinfo=timezone.utc))
    merged = combine([[tba], [timed]])["2026-27/t-men/c/r01"]
    assert merged.kickoff and merged.venue == "Salon"


def test_round_dates_are_used_and_nothing_is_estimated(config):
    matches = {"a": _m("r01", day=date(2026, 10, 4)), "b": _m("r02"), "c": _m("r03")}
    comps = {"c": config.competitions["sultanlar-ligi"].model_copy(update={"round_dates": {2: date(2026, 10, 11)}})}
    assert apply_round_dates(matches, comps) == ["c"]
    assert matches["b"].day == date(2026, 10, 11) and matches["c"].day is None
