"""Match a claimed PP/FS amount against the known provincial-agreement service rates."""
from __future__ import annotations

import json
import os
from collections import defaultdict

_RATES_PATH = os.path.join(os.path.dirname(__file__), "assets", "service_rates.json")
_AMOUNT_TOLERANCE = 0.01


def _load_rate_index() -> dict[float, list[str]]:
    try:
        with open(_RATES_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}

    index: dict[float, list[str]] = defaultdict(list)
    for item in data.get("items", []):
        if not item.get("matchable") or item.get("rate") is None:
            continue
        rate = round(float(item["rate"]), 2)
        if rate <= 0:
            continue
        index[rate].append(item["name"])
    return dict(index)


RATE_INDEX = _load_rate_index()


def match_candidates(amount: float) -> list[str]:
    """Return service names whose provincial rate equals `amount` (single exact match only)."""
    if amount is None or amount <= 0:
        return []
    rounded = round(float(amount), 2)
    for rate, names in RATE_INDEX.items():
        if abs(rate - rounded) <= _AMOUNT_TOLERANCE:
            return names
    return []


def predict_label(amount: float) -> str:
    """Format a prediction badge for display: matched, ambiguous, or no match."""
    candidates = match_candidates(amount)
    if not candidates:
        return "🔴 ไม่พบรายการที่ตรงกัน"
    if len(candidates) == 1:
        return f"🟢 {candidates[0]}"
    return "🟡 อาจเป็น: " + " / ".join(candidates)
