"""Búsqueda por código exacto de PDV y etiquetas de supervisor para BEES Force."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

import pandas as pd

SUPERVISOR_NAMES = {"1": "Bruno Ismael", "2": "Hernán Casco"}


def supervisor_label(value: object) -> str:
    """Human-readable label; never changes the underlying supervisor join key."""
    raw = str(value or "").strip()
    match = re.fullmatch(r"Supervisor\s+([12])(?:\.0+)?", raw, flags=re.IGNORECASE)
    if match:
        number = match.group(1)
        return f"{SUPERVISOR_NAMES[number]} (Supervisor {number})"
    return raw or "Sin supervisor"


def normalize_poc(value: object) -> str:
    """Clean display/typing noise without removing leading zeros from codes."""
    if value is None or pd.isna(value):
        return ""
    code = unicodedata.normalize("NFKC", str(value)).strip()
    # Excel sometimes stores ID numerals as floats; 00123 is kept as 00123.
    if re.fullmatch(r"\d+\.0+", code):
        code = code.split(".", 1)[0]
    return code.casefold()


def matching_poc_ids(codes: Iterable[object], query: str, limit: int = 20) -> tuple[list[str], list[str]]:
    """Return exact IDs first and fallback suggestions (never silently mix IDs)."""
    wanted = normalize_poc(query)
    if not wanted:
        return [], []
    original = sorted({str(x).strip() for x in codes if normalize_poc(x)}, key=str.casefold)
    exact = [x for x in original if normalize_poc(x) == wanted]
    if exact:
        return exact, []
    suggestions = [x for x in original if wanted in normalize_poc(x)]
    return [], suggestions[:limit]


def select_poc_rows(frame: pd.DataFrame, selected_code: str) -> pd.DataFrame:
    target = normalize_poc(selected_code)
    if not target or "POC ID" not in frame.columns:
        return frame.iloc[0:0].copy()
    mask = frame["POC ID"].map(normalize_poc).eq(target)
    return frame.loc[mask].copy()
