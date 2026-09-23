"""Condition registry for FY2569 OPPP amount-to-service mapping.

This module does NOT decide a service from money by itself. It provides
machine-readable constraints that a mapper can use to reject impossible
combinations and to downgrade cases that require context we do not have.

The authoritative condition data lives in assets/service_conditions_2569.json.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

_BASE = os.path.dirname(__file__)
_CONDITIONS_PATH = os.path.join(_BASE, "assets", "service_conditions_2569.json")
_RATES_PATH = os.path.join(_BASE, "assets", "service_rates.json")
_TOLERANCE = 0.01


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


CONDITION_DATA = _load_json(_CONDITIONS_PATH)
RATE_DATA = _load_json(_RATES_PATH)
CONDITIONS_BY_CODE: dict[str, dict] = {
    str(code): value for code, value in CONDITION_DATA.get("services", {}).items()
}
RATE_ITEMS_BY_CODE: dict[str, dict] = {
    str(item["code"]): item for item in RATE_DATA.get("items", [])
}
CODE_BY_NAME: dict[str, str] = {
    item["name"]: str(item["code"]) for item in RATE_DATA.get("items", [])
}
NAME_BY_CODE: dict[str, str] = {
    str(item["code"]): item["name"] for item in RATE_DATA.get("items", [])
}


@dataclass(frozen=True)
class ComboAssessment:
    status: str
    reasons: tuple[str, ...]

    @property
    def allowed(self) -> bool:
        return self.status != "reject"


def condition_for_code(code: str) -> dict | None:
    return CONDITIONS_BY_CODE.get(str(code))


def codes_for_exact_amount(amount: float) -> list[str]:
    """All rule-book services whose NHSO claim rate equals amount.

    This intentionally ignores the legacy matchable flag. The condition
    registry describes the whole local allocation universe, so it must expose
    collisions such as 60 = FIT / contraceptive injection / local lab bundle
    instead of pretending 60 is unique.
    """
    target = round(float(amount), 2)
    result = []
    for code, rule in CONDITIONS_BY_CODE.items():
        rate = rule.get("claim_rate")
        if rate is None:
            continue
        if abs(round(float(rate), 2) - target) <= _TOLERANCE:
            result.append(code)
    return sorted(result)


def amount_is_ambiguous(amount: float) -> bool:
    configured = CONDITION_DATA.get("known_amount_ambiguity", {})
    key = f"{float(amount):g}"
    if key in configured:
        return True
    return len(codes_for_exact_amount(amount)) > 1


def _same_claim_cap(code: str) -> int | None:
    rule = condition_for_code(code) or {}
    value = (rule.get("same_claim") or {}).get("max_occurrences")
    return None if value is None else int(value)


def assess_same_claim_codes(codes: Iterable[str]) -> ComboAssessment:
    """Assess a proposed set of service codes for one TRAN_ID/encounter.

    Only conditions that are safe to evaluate without demographics are hard
    rejects. Rules requiring pregnancy status, age, risk group, vaccine type,
    etc. are surfaced as review reasons instead of being guessed.
    """
    codes = [str(code) for code in codes]
    counts = Counter(codes)
    reject_reasons: list[str] = []
    review_reasons: list[str] = []

    for code, count in counts.items():
        cap = _same_claim_cap(code)
        if cap is not None and count > cap:
            name = NAME_BY_CODE.get(code, code)
            reject_reasons.append(
                f"{name}: พบ {count} ครั้งใน transaction เดียว เกินเพดานต่อครั้ง {cap}"
            )

    proposed = set(codes)
    for constraint in CONDITION_DATA.get("hard_same_claim_constraints", []):
        pair = [str(code) for code in constraint.get("codes", [])]
        if len(pair) != 2 or not set(pair).issubset(proposed):
            continue
        relation = constraint.get("relation")
        reason = constraint.get("description") or "combination ต้องตรวจบริบท"
        if relation == "reject":
            reject_reasons.append(reason)
        else:
            review_reasons.append(reason)

    for code in proposed:
        rule = condition_for_code(code) or {}
        requires = (rule.get("target") or {}).get("requires_context", [])
        if requires:
            review_reasons.append(
                f"{NAME_BY_CODE.get(code, code)} ต้องใช้บริบทเพิ่มเติม: {', '.join(requires)}"
            )

    if reject_reasons:
        return ComboAssessment("reject", tuple(dict.fromkeys(reject_reasons)))
    if review_reasons:
        return ComboAssessment("review", tuple(dict.fromkeys(review_reasons)))
    return ComboAssessment("valid", ())


def assess_same_claim_names(names: Iterable[str]) -> ComboAssessment:
    codes: list[str] = []
    unknown: list[str] = []
    for name in names:
        code = CODE_BY_NAME.get(name)
        if code is None:
            unknown.append(name)
        else:
            codes.append(code)
    result = assess_same_claim_codes(codes)
    reasons = list(result.reasons)
    if unknown:
        reasons.append("ไม่พบรหัส condition สำหรับ: " + ", ".join(unknown))
        if result.status == "valid":
            return ComboAssessment("review", tuple(reasons))
    return ComboAssessment(result.status, tuple(reasons))


def validate_rulebook() -> list[str]:
    """Static consistency checks; returns [] when the registry is internally sound."""
    issues: list[str] = []
    condition_codes = set(CONDITIONS_BY_CODE)
    rate_codes = set(RATE_ITEMS_BY_CODE)

    missing_conditions = sorted(rate_codes - condition_codes)
    if missing_conditions:
        issues.append("service_rates ไม่มี condition: " + ", ".join(missing_conditions))

    extra_conditions = sorted(condition_codes - rate_codes)
    if extra_conditions:
        issues.append("condition ไม่มี service_rates: " + ", ".join(extra_conditions))

    for code in sorted(condition_codes & rate_codes):
        condition_rate = CONDITIONS_BY_CODE[code].get("claim_rate")
        rate_claim = RATE_ITEMS_BY_CODE[code].get("rate_claim")
        if condition_rate is None or rate_claim is None:
            continue
        if abs(float(condition_rate) - float(rate_claim)) > _TOLERANCE:
            issues.append(
                f"{code}: claim_rate condition={condition_rate} ไม่ตรง service_rates={rate_claim}"
            )

        cap = _same_claim_cap(code)
        if cap is not None and cap < 1:
            issues.append(f"{code}: same_claim.max_occurrences ต้อง >= 1 หรือ null")

    return issues


def mapping_policy() -> dict:
    return dict(CONDITION_DATA.get("_mapping_policy", {}))


if __name__ == "__main__":
    issues = validate_rulebook()
    if issues:
        print("SERVICE CONDITIONS INVALID")
        for issue in issues:
            print("-", issue)
        raise SystemExit(1)

    print("SERVICE CONDITIONS OK")
    print(f"services={len(CONDITIONS_BY_CODE)}")
    print("ambiguous exact amounts:")
    for amount in sorted(
        {
            float(rule["claim_rate"])
            for rule in CONDITIONS_BY_CODE.values()
            if rule.get("claim_rate") is not None
        }
    ):
        codes = codes_for_exact_amount(amount)
        if len(codes) > 1:
            print(f"  {amount:g}: {', '.join(codes)}")
