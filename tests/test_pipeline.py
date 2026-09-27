"""End to end: ICS validity, UID stability, TBA → confirmed, keeping data when a source fails, overrides."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml
from icalendar import Calendar

from fbcal import pipeline
from fbcal.config import load_config
from fbcal.http import SourceError
from fbcal.models import Match
from fbcal.sources import source_key

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
TEAM = "volleyball-women"


def vb(stage: str, home: str, away: str, **kw) -> Match:
    side = "home" if "FENERBAH" in home.upper() else "away"
    return Match(team=TEAM, competition="sultanlar-ligi", stage=stage, side=side, home=home, away=away,
                 round_label=f"{int(stage[1:])}. Hafta", **kw)


class FakeSources:
    """Return the scripted response (a list or an exception) for each source."""

    def __init__(self):
        self.responses: dict[str, object] = {}

    def __call__(self, ctx, spec):
        response = self.responses.get(f"{ctx.team.key}|{source_key(spec)}", [])
        if isinstance(response, Exception):
            raise response
        return list(response)


@pytest.fixture
def fake(monkeypatch):
    fake = FakeSources()
    monkeypatch.setattr(pipeline, "ADAPTERS", {name: fake for name in pipeline.ADAPTERS})
    return fake


def run(root: Path, now: datetime = NOW):
    cfg = load_config(root)
    report = pipeline.build(cfg, out_dir=root / "public", now=now, session=object())
    cal = Calendar.from_ical((root / "public" / f"{TEAM}.ics").read_bytes())
    return report, cal, {str(e["UID"]): e for e in cal.walk("VEVENT")}


def pdf_key():
    return f"{TEAM}|tvf_pdf:sultanlar-ligi"


def site_key():
    return f"{TEAM}|tvf:sultanlar-ligi"


def test_ics_is_valid_and_apple_ready(repo_copy, fake):
    fake.responses[site_key()] = [
        vb("r01", "FENERBAHÇE MEDICANA", "ECZACIBAŞI PERON İSTANBUL",
           kickoff=datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc), venue="Burhan Felek Voleybol Salonu", city="İstanbul"),
    ]
    _, cal, events = run(repo_copy)
    assert str(cal["X-WR-CALNAME"]) == "FB Voleybol Kadın"
    assert str(cal["X-APPLE-CALENDAR-COLOR"]) == "#63C98F"
    assert cal["COLOR"] and cal["REFRESH-INTERVAL"] and str(cal["X-PUBLISHED-TTL"]) == "PT1H"
    [event] = events.values()
    assert str(event["SUMMARY"]) == "🏐 K · Fenerbahçe – Eczacıbaşı"
    assert event["DTSTART"].dt == datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc)
    assert str(event["STATUS"]) == "CONFIRMED"
    assert "Başlama: 13:00 Türkiye saati" in str(event["DESCRIPTION"])
    raw = (repo_copy / "public" / f"{TEAM}.ics").read_bytes()
    assert b"DTSTART:20261004T100000Z" in raw  # written as UTC
    assert all(len(line) <= 75 for line in raw.split(b"\r\n"))  # line folding (octets)
    alarms = [c for c in event.walk("VALARM")]
    assert alarms and str(alarms[0]["TRIGGER"].to_ical(), "ascii") == "-PT30M"
    no_alarm = Calendar.from_ical((repo_copy / "public" / f"{TEAM}-alarm-0.ics").read_bytes())
    assert not list(no_alarm.walk("VALARM"))


def test_undated_matches_are_hidden_until_official(repo_copy, fake):
    fake.responses[pdf_key()] = [vb("r05", "FENERBAHÇE MEDICANA", "VAKIFBANK")]
    _, _, events = run(repo_copy)
    assert events == {}


def test_tba_then_confirmed_keeps_uid_and_bumps_sequence(repo_copy, fake):
    fake.responses[pdf_key()] = [vb("r05", "FENERBAHÇE MEDICANA", "VAKIFBANK")]
    fake.responses[site_key()] = [vb("r05", "FENERBAHÇE MEDICANA", "VAKIFBANK", day=date(2026, 11, 8))]
    _, _, events = run(repo_copy)
    [(uid, ev)] = events.items()
    assert uid == "2026-27-volleyball-women-sultanlar-ligi-r05-home@beyzakiper.github.io"
    assert str(ev["STATUS"]) == "TENTATIVE" and not isinstance(ev["DTSTART"].dt, datetime)
    assert "(saat belli değil)" in str(ev["SUMMARY"])

    fake.responses[site_key()] = [
        vb("r05", "FENERBAHÇE MEDICANA", "VAKIFBANK", kickoff=datetime(2026, 11, 8, 16, 0, tzinfo=timezone.utc))
    ]
    _, _, events2 = run(repo_copy, now=datetime(2026, 11, 1, tzinfo=timezone.utc))
    ev2 = events2[uid]
    assert len(events2) == 1
    assert str(ev2["STATUS"]) == "CONFIRMED" and ev2["DTSTART"].dt == datetime(2026, 11, 8, 16, 0, tzinfo=timezone.utc)
    assert int(ev2["SEQUENCE"]) == 1
    assert ev2["LAST-MODIFIED"].dt > ev["LAST-MODIFIED"].dt


def test_renaming_names_does_not_change_uid(repo_copy, fake):
    fake.responses[site_key()] = [vb("r05", "FENERBAHÇE MEDICANA", "ECZACIBAŞI PERON İSTANBUL", day=date(2026, 11, 8))]
    _, _, before = run(repo_copy)
    for name, key, field, value in (
        ("teams.yaml", ["teams", TEAM], "display_name", "Fener"),
        ("opponents.yaml", ["opponents", "eczacibasi"], "display", "Ecza"),
    ):
        path = repo_copy / "config" / name
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data[key[0]][key[1]][field] = value
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    _, _, after = run(repo_copy)
    assert before.keys() == after.keys()
    [ev] = after.values()
    assert "Fener – Ecza" in str(ev["SUMMARY"])


def test_failed_or_shrunken_source_keeps_last_good_data(repo_copy, fake):
    fake.responses[site_key()] = [
        vb(f"r{i:02d}", "FENERBAHÇE MEDICANA", f"TEAM {i}", day=date(2026, 10, 1 + i)) for i in range(1, 11)
    ]
    _, _, events = run(repo_copy)
    assert len(events) == 10
    fake.responses[site_key()] = SourceError("timeout")
    report, _, events = run(repo_copy)
    assert len(events) == 10 and report.problems[0].status == "failed"
    fake.responses[site_key()] = [vb("r01", "FENERBAHÇE MEDICANA", "TEAM 1", day=date(2026, 10, 2))]
    report, _, events = run(repo_copy)
    assert len(events) == 10 and report.problems[0].status == "suspicious"


def test_postponed_and_cancelled(repo_copy, fake):
    fake.responses[site_key()] = [
        vb("r01", "FENERBAHÇE MEDICANA", "VAKIFBANK", day=date(2026, 10, 4), status="postponed"),
        vb("r02", "BEŞİKTAŞ", "FENERBAHÇE MEDICANA", kickoff=datetime(2026, 10, 11, 16, 0, tzinfo=timezone.utc), status="cancelled"),
    ]
    _, _, events = run(repo_copy)
    by_summary = {str(e["SUMMARY"]): e for e in events.values()}
    postponed = next(e for s, e in by_summary.items() if s.startswith("ERTELENDİ"))
    cancelled = next(e for s, e in by_summary.items() if s.startswith("İPTAL"))
    assert str(postponed["STATUS"]) == "TENTATIVE" and str(cancelled["STATUS"]) == "CANCELLED"


def test_overrides_fix_hide_and_add(repo_copy, fake):
    fake.responses[site_key()] = [
        vb("r05", "FENERBAHÇE MEDICANA", "VAKIFBANK", day=date(2026, 11, 8)),
        vb("r06", "THY", "FENERBAHÇE MEDICANA", day=date(2026, 11, 15)),
    ]
    (repo_copy / "overrides" / "manual.yaml").write_text(
        """
- match: volleyball-women/sultanlar-ligi/r05
  kickoff: "2026-11-08 19:00"
  venue: "Burhan Felek"
- match: volleyball-women/sultanlar-ligi/r06
  hide: true
- add:
    team: volleyball-women
    competition: sultanlar-ligi
    stage: r09
    opponent: "Göztepe"
    side: away
    date: 2026-12-01
""",
        encoding="utf-8",
    )
    report, _, events = run(repo_copy)
    summaries = sorted(str(e["SUMMARY"]) for e in events.values())
    assert summaries == ["🏐 K · Fenerbahçe – VakıfBank", "🏐 K · Göztepe – Fenerbahçe (saat belli değil)"]
    fixed = next(e for e in events.values() if "VakıfBank" in str(e["SUMMARY"]))
    assert fixed["DTSTART"].dt == datetime(2026, 11, 8, 16, 0, tzinfo=timezone.utc)
    assert not [w for w in report.warnings if "overrides" in w]


def test_score_in_title_after_match(repo_copy, fake):
    fake.responses[site_key()] = [
        vb("r01", "FENERBAHÇE MEDICANA", "VAKIFBANK", kickoff=datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc),
           status="finished", home_score=3, away_score=1)
    ]
    _, _, events = run(repo_copy)
    [ev] = events.values()
    assert str(ev["SUMMARY"]) == "🏐 K · Fenerbahçe 3–1 VakıfBank"


def test_next_season_round_one_gets_its_own_event(repo_copy, fake):
    fake.responses[site_key()] = [
        vb("r01", "FENERBAHÇE MEDICANA", "MANİSA", kickoff=datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc))
    ]
    _, _, first = run(repo_copy)
    [(old_uid, old_event)] = first.items()
    fake.responses[site_key()] = [
        vb("r01", "FENERBAHÇE MEDICANA", "ZEREN", kickoff=datetime(2027, 10, 3, 10, 0, tzinfo=timezone.utc))
    ]
    _, _, second = run(repo_copy, now=datetime(2027, 9, 20, tzinfo=timezone.utc))
    assert len(second) == 2 and old_uid in second
    new_uid = next(u for u in second if u != old_uid)
    assert new_uid.startswith("2027-28-volleyball-women-sultanlar-ligi-r01-")
    kept = second[old_uid]
    assert kept["DTSTART"].dt == old_event["DTSTART"].dt and int(kept["SEQUENCE"]) == 0


def test_v1_state_migrates_without_changing_uids(repo_copy, fake):
    import json

    uid = "2026-27-volleyball-women-sultanlar-ligi-r01-home@beyzakiper.github.io"
    v1 = {
        "version": 1,
        "team": TEAM,
        "sources": {"tvf:sultanlar-ligi": {"count": 1, "matches": [
            {"team": TEAM, "competition": "sultanlar-ligi", "stage": "r01", "side": "home",
             "home": "FENERBAHÇE MEDICANA", "away": "MANİSA", "kickoff": "2026-10-04T10:00:00Z"},
        ]}},
        "events": {"volleyball-women/sultanlar-ligi/r01": {
            "uid": uid, "sequence": 3, "hash": "x", "created": "2026-09-25T00:00:00Z",
            "last_modified": "2026-09-25T00:00:00Z"}},
    }
    (repo_copy / "data").mkdir()
    (repo_copy / "data" / f"{TEAM}.json").write_text(json.dumps(v1), encoding="utf-8")
    fake.responses[site_key()] = SourceError("offline")
    _, _, events = run(repo_copy)
    assert list(events) == [uid]
    saved = json.loads((repo_copy / "data" / f"{TEAM}.json").read_text(encoding="utf-8"))
    assert saved["version"] == 2 and list(saved["events"]) == ["2026-27/volleyball-women/sultanlar-ligi/r01"]
