# Maintaining

Notes for the repo owner. Subscribers only need the README.

## How it runs

GitHub Actions (`.github/workflows/update.yml`) runs every 6 hours, on manual trigger, and on every push to
`main`: fetch sources → merge → apply overrides → validate → write `.ics` + `data.json` → commit `data/` only if it
changed → deploy to GitHub Pages (skipped while the repo is private).

If a source fails or returns suspiciously few matches, the last known-good data in `data/<team>.json` is kept and
an issue labelled `source-problem` is opened (closed automatically once all sources recover).

## Config (no code changes needed)

| File | What it controls |
|---|---|
| `config/teams.yaml` | display name, sponsor aliases, calendar name, colour, default alert, sources |
| `config/opponents.yaml` | how opponents are named in the calendar |
| `config/competitions.yaml` | competition names, official round dates not covered by sources |
| `config/settings.yaml` | title templates and labels (Turkish), durations, time zones, alert options |

Renaming things never changes event UIDs. Never rename the keys (`football-men`, `super-lig`, …) or
`uid_domain`, or subscribers get duplicates.

## Manual fixes (optional)

`overrides/manual.yaml` can set a time, hide a match, mark it postponed, or add a match no source lists
(friendlies, CEV matches before CEV publishes). Each event shows its code at the bottom of its description.
Examples are in the file.

## Yearly chores

- Update both TVF fixture-draw PDF URLs in `config/teams.yaml` (`volleyball-women` and `volleyball-men` → `tvf_pdf`) each summer.
- Clear last season's `round_dates` in `config/competitions.yaml`.

Matches are only published once their date is official; the full fixture is never shown in advance.

## Data sources

| Team | Sources |
|---|---|
| Men's football | TFF (league, cup, super cup — HTML), UEFA match API (JSON) |
| Men's basketball | TBF web API (league, cups — JSON), EuroLeague API (JSON) |
| Women's volleyball | TVF fixture system (HTML), TVF fixture-draw PDF |
| Men's volleyball | TVF fixture system (HTML), TVF fixture-draw PDF |
| Women's basketball | TBF web API (KBSL, cups — JSON), FIBA EuroLeague Women (data embedded in fiba.basketball) |
| Women's football | TFF (Kadın Futbol Süper Ligi — HTML), UEFA match API (JSON) |

fenerbahce.org blocks automated access, so it is only used as a manual cross-check.

## Previewing the site locally

```bash
.venv/bin/python -m fbcal build --offline && python3 -m http.server 8765 --directory public
```

## Development

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m fbcal build            # fetch sources, write public/
.venv/bin/python -m fbcal build --offline  # render from stored data only
```

## Credits

The approach of reading official TFF/TBF/UEFA/EuroLeague sources was studied from
[trkenankement/fenerbahce-calendar](https://github.com/trkenankement/fenerbahce-calendar) (MIT). This project's
code is written separately.
