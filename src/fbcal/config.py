"""Load and validate the YAML config files, with readable errors on typos."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .names import fold, pretty

Sport = Literal["football", "basketball", "volleyball"]
Gender = Literal["men", "women"]
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ConfigError(RuntimeError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TitleSettings(_Strict):
    template: str
    result_template: str
    markers: dict[Gender, str]
    tba_suffix: str
    postponed_prefix: str
    cancelled_prefix: str
    friendly_prefix: str


class TzLabel(_Strict):
    tz: str
    label: str


class Settings(_Strict):
    site_url: str
    uid_domain: str
    source_timezone: str
    calendar_timezone: str
    refresh_interval: str
    description_timezones: list[TzLabel]
    emoji: dict[Sport, str]
    durations: dict[Sport, int]
    title: TitleSettings
    score_in_title: bool = True
    alert_variants: list[int] = [0, 30, 60]
    shrink_guard: float = Field(0.6, ge=0, le=1)


class Team(_Strict):
    key: str = ""
    display_name: str
    aliases: list[str] = []
    match_terms: list[str] = []
    sport: Sport
    gender: Gender
    calendar_name: str
    color: str
    color_name: str = ""  # CSS colour name for RFC 7986 COLOR; nearest match is used when empty
    alarm_minutes: int | None = None
    sources: list[dict[str, Any]] = []

    @field_validator("color")
    @classmethod
    def _hex(cls, value: str) -> str:
        if not HEX.match(value):
            raise ValueError(f"color must look like #RRGGBB: {value!r}")
        return value.upper()

    def is_us(self, name: str) -> bool:
        folded = fold(name)
        if not folded:
            return False
        if folded in {fold(a) for a in [self.display_name, *self.aliases]}:
            return True
        return any(fold(term) in folded for term in self.match_terms)


class Combined(_Strict):
    key: str = ""
    calendar_name: str
    color: str
    color_name: str = ""
    alarm_minutes: int | None = None

    @field_validator("color")
    @classmethod
    def _hex(cls, value: str) -> str:
        if not HEX.match(value):
            raise ValueError(f"color must look like #RRGGBB: {value!r}")
        return value.upper()


class Competition(_Strict):
    key: str = ""
    name: str
    friendly: bool = False
    round_dates: dict[int, date] = {}


class Opponent(_Strict):
    display: str
    aliases: list[str] = []


class Config(BaseModel):
    settings: Settings
    teams: dict[str, Team]
    combined: dict[str, Combined] = {}
    competitions: dict[str, Competition]
    opponents: dict[str, Opponent]
    root: Path

    def opponent_display(self, raw: str) -> str | None:
        """Display name for an opponent, or None if it is not in opponents.yaml."""
        candidates = {fold(raw), fold(pretty(raw))}  # with and without a corporate suffix like "A.Ş."
        for opp in self.opponents.values():
            if candidates & {fold(n) for n in [opp.display, *opp.aliases]}:
                return opp.display
        return None


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise ConfigError(f"{path} not found") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} could not be read (YAML error): {exc}") from exc


def load_config(root: Path = Path(".")) -> Config:
    cfg_dir = root / "config"
    try:
        settings = Settings(**_load_yaml(cfg_dir / "settings.yaml"))
        teams_file = _load_yaml(cfg_dir / "teams.yaml")
        teams = {k: Team(key=k, **v) for k, v in (teams_file.get("teams") or {}).items()}
        combined = {k: Combined(key=k, **v) for k, v in (teams_file.get("combined") or {}).items()}
        comps = {
            k: Competition(key=k, **v)
            for k, v in (_load_yaml(cfg_dir / "competitions.yaml").get("competitions") or {}).items()
        }
        opps = {k: Opponent(**v) for k, v in (_load_yaml(cfg_dir / "opponents.yaml").get("opponents") or {}).items()}
    except ValidationError as exc:
        raise ConfigError(f"Invalid config:\n{exc}") from exc
    for key in combined:
        if key in teams or not re.fullmatch(r"[a-z]+", key):
            raise ConfigError(f"Invalid combined feed key: {key!r}")
    for team in teams.values():
        if not re.fullmatch(r"[a-z]+-(men|women)", team.key):
            raise ConfigError(f"Invalid team key: {team.key!r}")
        for src in team.sources:
            for comp in _source_competitions(src):
                if comp not in comps:
                    raise ConfigError(f"{team.key}: '{comp}' is not defined in competitions.yaml")
    return Config(settings=settings, teams=teams, combined=combined, competitions=comps, opponents=opps, root=root)


def _source_competitions(src: dict[str, Any]) -> list[str]:
    if "competition" in src:
        return [src["competition"]]
    return list((src.get("competitions") or {}).values())
