"""Shared HTTP session: identifying User-Agent, timeouts, retries and a polite pause between requests."""

from __future__ import annotations

import os
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TIMEOUT = (10, 40)
PAUSE_SECONDS = 0.2


class SourceError(RuntimeError):
    """A data source did not respond, or responded in an unexpected format."""


def new_session() -> requests.Session:
    retry = Retry(
        total=3,
        backoff_factor=2.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    repo = os.environ.get("GITHUB_REPOSITORY", "beyzakiper/fenerbahce-calendars")
    session.headers.update(
        {
            "User-Agent": f"fbcal/0.1 (unofficial fan calendar; +https://github.com/{repo})",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5",
        }
    )
    return session


def _get(session: requests.Session, url: str, params: dict[str, Any] | None, accept: str) -> requests.Response:
    time.sleep(PAUSE_SECONDS)
    try:
        response = session.get(url, params=params, timeout=TIMEOUT, headers={"Accept": accept})
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SourceError(f"could not fetch {url}: {exc}") from exc
    return response


def get_json(session: requests.Session, url: str, **params: Any) -> Any:
    response = _get(session, url, params, "application/json")
    try:
        return response.json()
    except ValueError as exc:
        raise SourceError(f"{url} did not return valid JSON") from exc


def get_text(session: requests.Session, url: str, *, encoding: str | None = None, **params: Any) -> str:
    response = _get(session, url, params, "text/html,application/xhtml+xml")
    if encoding:
        response.encoding = encoding
    return response.text


def get_bytes(session: requests.Session, url: str) -> bytes:
    return _get(session, url, None, "*/*").content
