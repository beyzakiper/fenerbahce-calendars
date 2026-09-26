from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from fbcal.config import load_config
from fbcal.sources.base import Context

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def config():
    return load_config(ROOT)


@pytest.fixture
def ctx_for(config):
    def make(team: str, today: date = date(2026, 9, 25)) -> Context:
        return Context(config=config, team=config.teams[team], session=None, today=today)  # type: ignore[arg-type]

    return make


@pytest.fixture
def repo_copy(tmp_path):
    """Temporary copy of the real config (empty data/) for tests that modify configuration."""
    for name in ("config", "overrides"):
        shutil.copytree(ROOT / name, tmp_path / name)
    return tmp_path
