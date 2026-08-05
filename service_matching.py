"""Match a claimed PP/FS amount against the known service claim rates.

Matches against `rate_claim` (the full SPSC schedule rate) -- that is what
actually appears in the raw PP/FS amounts recorded in the uploaded reports.
`rate_facility_share` (the discounted provincial-agreement amount) is a
downstream allocation and must never be used for matching -- see
service_analysis.py's reconciliation step for where that belongs.
"""
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
        if not item.get("matchable") or item.get("rate_claim") is None:
            continue
        rate = round(float(item["rate_claim"]), 2)
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
    `amount`. Tries depth 1 first and stops at the first depth with any match,
    so the simplest explanation (fewest total items) always wins.

    Known limitation: a bundle of 3 of the same per-unit item (e.g. 3 packs
    of one contraceptive pill) can lose out to an unrelated but shorter
    2-item combo that happens to sum to the same amount -- both are equally
    plausible real visits, and there is no reliable way to prefer one without
    more context. Such cases surface as 🟡 ambiguous (or occasionally miss the
    true explanation from the candidate list); a human confirms via the
    manual "จัดสรรบริการ" tab either way, so nothing false is ever asserted."""
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


def _closest_combo(target: float, max_items: int = _MAX_COMBO_ITEMS) -> tuple[float, list[float]] | None:
    """Find the bundle of known rates (repetition allowed, up to `max_items`)
    whose sum is closest to `target`, even if not exact. Prefers the smaller
    absolute difference; ties broken by fewest items. Exhaustive but cheap --
    the matchable set is small (single digits) by design."""
    rates = sorted(RATE_INDEX.keys())
    if not rates:
        return None
    best: tuple[float, int, list[float]] | None = None

    for depth in range(1, max_items + 1):
        def search(start_idx: int, path: list[float]) -> None:
            nonlocal best
            if len(path) == depth:
                total = sum(path)
                diff = abs(total - target)
                if best is None or (diff, depth) < (best[0], best[1]):
                    best = (diff, depth, list(path))
                return
            for idx in range(start_idx, len(rates)):
                path.append(rates[idx])
                search(idx, path)
                path.pop()

        search(0, [])

    if best is None:
        return None
    diff, _depth, combo = best
    return diff, combo


def resolve_combo(amount: float) -> tuple[str, list[list[str]], float]:
    """Return (status, combos, diff) for one amount.
    - "-": amount is zero/blank, nothing to predict; combos=[], diff=0
    - "🟢 คาดการณ์": exactly one bundle matches exactly, combos=[that bundle], diff=0
    - "🟡 ไม่แน่ชัด": several bundles match exactly, combos=all of them (capped), diff=0
    - "🟠 ใกล้เคียง": no exact bundle, but the closest bundle is returned with
      its baht difference so a human can judge whether it's a real match
    - "🔴 ไม่พบ": no bundle at all could be formed (empty rate table)
    """
    if amount is None or amount <= 0:
        return "-", [], 0.0
    combos = match_combo(amount)
    if combos:
        if len(combos) == 1:
            return "🟢 คาดการณ์", combos, 0.0
        return "🟡 ไม่แน่ชัด", combos, 0.0

    closest = _closest_combo(amount)
    if closest is None:
        return "🔴 ไม่พบ", [], 0.0
    diff, rate_combo = closest
    name_combos = _expand_names(rate_combo)
    return "🟠 ใกล้เคียง", name_combos[:1], round(diff, 2)


def format_combo_text(status: str, combos: list[list[str]], diff: float = 0.0) -> str:
    if status == "-":
        return "-"
    if status == "🔴 ไม่พบ":
        return "ไม่พบชุดบริการที่รวมแล้วตรงยอดนี้"
    if status == "🟢 คาดการณ์":
        return " + ".join(combos[0])
    if status == "🟠 ใกล้เคียง":
        return f"{' + '.join(combos[0])} (ต่างจากยอดจริง {diff:,.2f} บาท)"
    return "อาจเป็น: " + " | ".join(" + ".join(combo) for combo in combos)


def predict_combo_label(amount: float) -> tuple[str, str]:
    """Convenience wrapper: (status, formatted label) for one amount."""
    status, combos, diff = resolve_combo(amount)
    return status, format_combo_text(status, combos, diff)
