"""Source adapters. Each lives in its own module, so a broken source only affects its own data."""

from __future__ import annotations

from collections.abc import Callable

from . import euroleague, fiba, tbf, tff, tvf, tvf_pdf, uefa
from .base import Context

Adapter = Callable[[Context, dict], list]

ADAPTERS: dict[str, Adapter] = {
    "tff": tff.fetch,
    "uefa": uefa.fetch,
    "tbf": tbf.fetch,
    "euroleague": euroleague.fetch,
    "fiba": fiba.fetch,
    "tvf": tvf.fetch,
    "tvf_pdf": tvf_pdf.fetch,
}


def source_key(spec: dict) -> str:
    """Stable name of a source within a team (used in data/*.json)."""
    adapter = spec["adapter"]
    target = spec.get("competition") or "+".join(sorted((spec.get("competitions") or {}).values()))
    extra = spec.get("kind") or spec.get("prefix") or ""
    return ":".join(p for p in (adapter, target, extra) if p)
