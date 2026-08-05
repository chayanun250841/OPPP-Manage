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


# ---------------------------------------------------------------------------
# Combo matching: decompose one amount into a bundle of 1-3 service items
# whose provincial rates sum to it (e.g. ANC 360 + ตรวจปัสสาวะ 37.5 = 397.5).
# ---------------------------------------------------------------------------

_MAX_COMBO_ITEMS = 3
_MAX_COMBO_RESULTS = 6


def _rate_combinations(amount: float, max_items: int = _MAX_COMBO_ITEMS) -> list[list[float]]:
    """Non-decreasing combinations of known rates (repetition allowed) summing to
    `amount`. Tries depth 1 first and stops at the first depth with any match, so
    the simplest explanation is always preferred over a more convoluted bundle."""
    rates = sorted(RATE_INDEX.keys())
    if amount is None or amount <= 0 or not rates:
        return []
    target = round(float(amount), 2)

    for depth in range(1, max_items + 1):
        found: list[list[float]] = []

        def search(start_idx: int, remaining: float, path: list[float]) -> None:
            if len(path) == depth:
                if abs(remaining) <= _AMOUNT_TOLERANCE:
                    found.append(list(path))
                return
            for idx in range(start_idx, len(rates)):
                rate = rates[idx]
                if rate - remaining > _AMOUNT_TOLERANCE:
                    break  # rates ascending -- nothing smaller left to try
                path.append(rate)
                search(idx, remaining - rate, path)
                path.pop()

        search(0, target, [])
        if found:
            return found
    return []


def _expand_names(rate_combo: list[float]) -> list[list[str]]:
    """Cartesian-expand a combo of rates into concrete service-name combos."""
    results: list[list[str]] = [[]]
    for rate in rate_combo:
        names = RATE_INDEX[rate]
        results = [combo + [name] for combo in results for name in names]
    return results


def match_combo(amount: float, max_items: int = _MAX_COMBO_ITEMS) -> list[list[str]]:
    """All distinct service-name bundles (order-independent) whose rates sum to
    `amount`, preferring the fewest items. Capped to avoid combinatorial blowup
    when several items share the same rate."""
    rate_combos = _rate_combinations(amount, max_items)
    if not rate_combos:
        return []
    seen: set[tuple[str, ...]] = set()
    results: list[list[str]] = []
    for rate_combo in rate_combos:
        for name_combo in _expand_names(rate_combo):
            key = tuple(sorted(name_combo))
            if key in seen:
                continue
            seen.add(key)
            results.append(list(key))
            if len(results) >= _MAX_COMBO_RESULTS:
                return results
    return results


def resolve_combo(amount: float) -> tuple[str, list[list[str]]]:
    """Return (status, combos) for one amount.
    - "-": amount is zero/blank, nothing to predict
    - "🔴 ไม่พบ": no bundle of known rates sums to this amount, combos = []
    - "🟢 คาดการณ์": exactly one bundle matches, combos = [that bundle]
    - "🟡 ไม่แน่ชัด": several bundles match, combos = all of them (capped)
    """
    if amount is None or amount <= 0:
        return "-", []
    combos = match_combo(amount)
    if not combos:
        return "🔴 ไม่พบ", []
    if len(combos) == 1:
        return "🟢 คาดการณ์", combos
    return "🟡 ไม่แน่ชัด", combos


def format_combo_text(status: str, combos: list[list[str]]) -> str:
    if status == "-":
        return "-"
    if status == "🔴 ไม่พบ":
        return "ไม่พบชุดบริการที่รวมแล้วตรงยอดนี้"
    if status == "🟢 คาดการณ์":
        return " + ".join(combos[0])
    return "อาจเป็น: " + " | ".join(" + ".join(combo) for combo in combos)


def predict_combo_label(amount: float) -> tuple[str, str]:
    """Convenience wrapper: (status, formatted label) for one amount."""
    status, combos = resolve_combo(amount)
    return status, format_combo_text(status, combos)
