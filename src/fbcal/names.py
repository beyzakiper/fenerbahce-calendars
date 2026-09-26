"""Turkish-aware name handling: folding for comparisons and prettifying all-caps source names."""

from __future__ import annotations

import re
import unicodedata

# Acronyms that must stay upper-case when title-casing
KEEP_UPPER = {"FK", "SK", "JK", "KK", "BB", "BBSK", "GSK", "TED", "MCT", "THY", "İBB", "ÇBK", "TVF", "AŞ", "SC", "FC", "BC"}
_CORPORATE_SUFFIX = re.compile(r"\s+A\.\s?Ş\.?$", re.IGNORECASE)


def tr_lower(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower()


def tr_upper(text: str) -> str:
    return text.replace("i", "İ").replace("ı", "I").upper()


def fold(text: str) -> str:
    """Comparison key: lower-case, accent-free, single-spaced ASCII ("ÇAYKUR Rizespor" -> "caykur rizespor")."""
    lowered = tr_lower(text or "").replace("ı", "i")
    decomposed = unicodedata.normalize("NFKD", lowered)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_only).split())


def slug(text: str) -> str:
    return fold(text).replace(" ", "-")


def _title_word(word: str) -> str:
    if word in KEEP_UPPER or any(ch.isdigit() for ch in word) or re.fullmatch(r"(?:\w\.)+\w?\.?", word):
        return word
    parts = re.split(r"([-/'.])", word)
    out = []
    for part in parts:
        if part in {"-", "/", "'", "."} or not part:
            out.append(part)
        else:
            low = tr_lower(part)
            out.append(tr_upper(low[:1]) + low[1:])
    return "".join(out)


def pretty(raw: str) -> str:
    """"ECZACIBAŞI PERON İSTANBUL" -> "Eczacıbaşı Peron İstanbul"; mixed-case names are returned unchanged."""
    text = _CORPORATE_SUFFIX.sub("", " ".join((raw or "").split()))
    if not text or text != tr_upper(text):
        return text
    return " ".join(_title_word(word) for word in text.split(" "))


def join(*parts: str, sep: str = ", ") -> str:
    return sep.join(p for p in parts if p)
