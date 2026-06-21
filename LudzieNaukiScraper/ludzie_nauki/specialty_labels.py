"""Normalized comparison keys for Ludzie specialty labels (migration + ingest)."""

from __future__ import annotations

import re
import unicodedata
from typing import Optional


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def specialty_sig_pl(label: Optional[str]) -> str:
    if label is None:
        return ""
    raw = unicodedata.normalize("NFC", str(label))
    folded = _collapse_ws(raw).casefold()
    return folded


def specialty_sig_en(label: Optional[str]) -> str:
    return specialty_sig_pl(label)
