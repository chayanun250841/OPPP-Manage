"""Proof-grade OPPP mapper for FY2569.

Never uses closest-match or chooses an interpretation because it pays more.
Presentation-certified mappings require explicit evidence and condition checks.
This module is read-only and never writes the production database.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

import service_conditions

_BASE = os.path.dirname(__file__)
_RATES_PATH = os.path.join(_BASE, "assets", "service_rates.json")
_RULES_PATH = os.path.join(_BASE, "assets", "amount_rules.json")
_USER_CONFIRMED_PATH = os.path.join(_BASE, "assets", "user_confirmed_mapping_2569.json")
_PROVINCIAL_CLOSURE_PATH = os.path.join(_BASE, "assets", "provincial_closure_2569.json")
_ADJUSTMENTS_PATH = os.path.join(_BASE, "assets", "manual_adjustments.json")
_PRIVATE_RECORDS_PATH = os.path.join(_BASE, ".local-artifacts", "proof-grade", "records_private.json")
_CONTEXT_V2_PATH = os.path.join(_BASE, ".local-artifacts", "full-universe", "records_context_private_v2.json")
_REPORT_PATH = os.path.join(_BASE, ".local-artifacts", "proof-grade", "PROOF_GRADE_RESULT.json")
_TOL = 0.01


def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as file:
        return json.load(file)


RATES_DATA = _load(_RATES_PATH)
RULES_DATA = _load(_RULES_PATH)
USER_CONFIRMED_DATA = _load(_USER_CONFIRMED_PATH)
PROVINCIAL_CLOSURE_DATA = _load(_PROVINCIAL_CLOSURE_PATH)
ADJUSTMENTS_DATA = _load(_ADJUSTMENTS_PATH)
ITEMS = {str(item["code"]): item for item in RATES_DATA.get("items", [])}
RULES = {round(float(rule["amount"]), 2): rule for rule in RULES_DATA.get("rules", [])}
USER_CONFIRMED = {
    round(float(rule["amount"]), 2): rule
    for rule in USER_CONFIRMED_DATA.get("mappings", [])
}
TRANSFER_BILLED_RULES = {
    round(float(rule["billed_amount"]), 2): rule
    for rule in (PROVINCIAL_CLOSURE_DATA.get("transfer_service_basis") or {}).get("mappings", [])
}
TRANSFER_RAW_FALLBACK = {
    round(float(raw_pp), 2): round(float(billed), 2)
    for raw_pp, billed in (
        ((PROVINCIAL_CLOSURE_DATA.get("transfer_service_basis") or {})
         .get("legacy_db_fallback") or {})
        .get("raw_pp_to_billed", {})
    ).items()
}
OUTSIDE_LOCAL_RESOLUTION = {
    round(float(rule["raw_pp_amount"]), 2): rule
    for rule in PROVINCIAL_CLOSURE_DATA.get("outside_local_pp_resolution", [])
}

# 9.1 and 9.2 are package aliases for three packs. Atomic variants preserve
# the same economics and avoid fake ambiguity from package representation.
_ATOMIC_SKIP = {"9.1", "9.2"}


@dataclass(frozen=True)
class Candidate:
    codes: tuple[str, ...]
    condition_status: str
    provincial_amount: float | None


@dataclass
class FieldDecision:
    status: str
    amount: float
    codes: list[str]
    provincial_amount: float | None
    proof_basis: str
    reasons: list[str]

    @property
    def certified(self) -> bool:
        return self.status.startswith("certified")


def _claim_rate(code: str) -> float:
    return float(ITEMS[str(code)]["rate_claim"])


def _prov_rate(code: str) -> float | None:
    value = ITEMS[str(code)].get("rate_facility_share")
    return None if value is None else float(value)


def _sum_claim(codes: Iterable[str]) -> float:
    return round(sum(_claim_rate(code) for code in codes), 2)


def _sum_prov(codes: Iterable[str]) -> float | None:
    total = 0.0
    for code in codes:
        rate = _prov_rate(code)
        if rate is None:
            return None
        total += rate
    return round(total, 2)


def _rule_for_amount(amount: float) -> dict | None:
    key = round(float(amount), 2)
    for rule_amount, rule in RULES.items():
        if abs(rule_amount - key) <= _TOL:
            return rule
    return None


def _max_occurrences_for_search(code: str, target: float) -> int:
    rule = service_conditions.condition_for_code(code) or {}
    max_occ = (rule.get("same_claim") or {}).get("max_occurrences")
    if max_occ is not None:
        return max(0, int(max_occ))
    rate = _claim_rate(code)
    return max(0, int((target + _TOL) // rate))


def exact_candidates(amount: float, limit: int = 200) -> tuple[list[Candidate], bool]:
    """Find exact non-rejected atomic service compositions."""
    target = round(float(amount), 2)
    if target <= 0:
        return [], False
    if abs(target - round(target)) > _TOL:
        return [], False

    catalog = [
        code
        for code, item in ITEMS.items()
        if code not in _ATOMIC_SKIP
        and item.get("rate_claim") is not None
        and float(item["rate_claim"]) > 0
    ]
    catalog.sort(key=lambda c: (-_claim_rate(c), c))
    target_i = int(round(target * 100))
    rates_i = {code: int(round(_claim_rate(code) * 100)) for code in catalog}
    caps = {code: _max_occurrences_for_search(code, target) for code in catalog}

    found: dict[tuple[str, ...], Candidate] = {}
    truncated = False

    def walk(index: int, remaining: int, path: list[str]) -> None:
        nonlocal truncated
        if truncated:
            return
        if remaining == 0:
            assessment = service_conditions.assess_same_claim_codes(path)
            if assessment.status == "reject":
                return
            signature = tuple(sorted(path))
            if signature not in found:
                found[signature] = Candidate(
                    codes=signature,
                    condition_status=assessment.status,
                    provincial_amount=_sum_prov(signature),
                )
                if len(found) > limit:
                    truncated = True
            return
        if index >= len(catalog) or remaining < 0:
            return
        code = catalog[index]
        rate = rates_i[code]
        max_count = min(caps[code], remaining // rate)
        for count in range(max_count, -1, -1):
            if count:
                path.extend([code] * count)
            walk(index + 1, remaining - count * rate, path)
            if count:
                del path[-count:]
            if truncated:
                return

    walk(0, target_i, [])
    return list(found.values()), truncated


def decide_pp_amount(amount: float) -> FieldDecision:
    """Return only presentation-defensible PP decisions.

    Evidence order:
    1) approved local mapping rules recorded from the reference workbook,
       always gated by FY2569 service conditions;
    2) exact allocation invariance inside the current provincial 15-item
       universe when no approved rule exists.

    A historical rule is never presentation evidence merely because it has an
    item list.  Its explicit presentation_eligible flag controls certification.
    """
    amount = round(float(amount), 2)
    if amount <= 0:
        return FieldDecision("empty", amount, [], 0.0, "none", [])

    user_rule = USER_CONFIRMED.get(amount)
    if user_rule is not None:
        codes = [str(code) for code in user_rule.get("codes", [])]
        if not codes or any(code not in ITEMS for code in codes):
            return FieldDecision(
                "unresolved_invalid_user_confirmed_rule",
                amount,
                codes,
                None,
                "user_confirmed_rule_invalid",
                ["unknown or empty service code in user-confirmed mapping"],
            )
        claim_sum = _sum_claim(codes)
        if abs(claim_sum - amount) > _TOL:
            return FieldDecision(
                "unresolved_invalid_user_confirmed_rule",
                amount,
                codes,
                None,
                "user_confirmed_rule_arithmetic_mismatch",
                [
                    f"user-confirmed component sum {claim_sum:.2f} != raw PP {amount:.2f}",
                    str(user_rule.get("label") or ""),
                ],
            )
        assessment = service_conditions.assess_same_claim_codes(codes)
        if assessment.status == "reject":
            return FieldDecision(
                "unresolved_user_confirmed_rule_rejected_by_hard_condition",
                amount,
                codes,
                None,
                "hard_condition_rejects_user_confirmed_rule",
                list(assessment.reasons),
            )
        provincial = _sum_prov(codes)
        if provincial is None:
            return FieldDecision(
                "unresolved_user_confirmed_rule_missing_provincial_rate",
                amount,
                codes,
                None,
                "user_confirmed_rule_missing_provincial_rate",
                [str(user_rule.get("label") or "")],
            )
        return FieldDecision(
            "certified_user_confirmed_operational_rule",
            amount,
            codes,
            provincial,
            "user_confirmed_operational_mapping_2026-09-23",
            [str(user_rule.get("label") or "")] + list(assessment.reasons),
        )

    rule = _rule_for_amount(amount)
    if rule is not None:
        eligibility = rule.get("presentation_eligible", False)
        alternatives = [
            [str(code) for code in alternative]
            for alternative in rule.get("alternatives", [])
        ]

        if rule.get("kind") == "กำกวม" or not rule.get("items"):
            surviving: list[tuple[list[str], service_conditions.ComboAssessment, float | None]] = []
            rejected: list[str] = []
            for codes in alternatives:
                if not codes or any(code not in ITEMS for code in codes):
                    rejected.append("invalid alternative: " + "+".join(codes))
                    continue
                if abs(_sum_claim(codes) - amount) > _TOL:
                    rejected.append(
                        f"alternative {'+'.join(codes)} sum {_sum_claim(codes):.2f} != {amount:.2f}"
                    )
                    continue
                assessment = service_conditions.assess_same_claim_codes(codes)
                if assessment.status == "reject":
                    rejected.append(
                        "+".join(codes) + " rejected: " + "; ".join(assessment.reasons)
                    )
                    continue
                surviving.append((codes, assessment, _sum_prov(codes)))

            if (
                eligibility == "when_condition_resolves_unique"
                and alternatives
                and len(surviving) == 1
            ):
                codes, assessment, provincial = surviving[0]
                if provincial is not None:
                    return FieldDecision(
                        "certified_approved_rule_resolved_by_condition",
                        amount,
                        codes,
                        provincial,
                        "approved_local_alternatives+hard_condition_elimination",
                        rejected + list(assessment.reasons),
                    )

            if eligibility is True and alternatives and surviving:
                provincial_values = {entry[2] for entry in surviving}
                if None not in provincial_values and len(provincial_values) == 1:
                    return FieldDecision(
                        "certified_approved_rule_allocation_invariant",
                        amount,
                        [],
                        next(iter(provincial_values)),
                        "approved_local_alternatives_same_allocation",
                        rejected + [rule.get("label", "")],
                    )

            return FieldDecision(
                "unresolved_approved_alternatives",
                amount,
                [],
                None,
                "approved_rule_not_uniquely_resolved_for_presentation",
                rejected + [rule.get("label", "")],
            )

        codes = [str(code) for code in rule.get("items", [])]
        if any(code not in ITEMS for code in codes):
            return FieldDecision(
                "unresolved_invalid_rule", amount, [], None,
                "approved_rule_invalid", ["rule references unknown service code"]
            )
        if abs(_sum_claim(codes) - amount) > _TOL:
            return FieldDecision(
                "unresolved_invalid_rule", amount, codes, None,
                "approved_rule_invalid",
                [f"rule claim sum {_sum_claim(codes):.2f} != raw {amount:.2f}"]
            )

        assessment = service_conditions.assess_same_claim_codes(codes)
        if assessment.status == "reject":
            return FieldDecision(
                "unresolved_rule_rejected_by_condition", amount, codes, None,
                "condition_rejects_approved_rule", list(assessment.reasons)
            )

        if eligibility is not True:
            return FieldDecision(
                "unresolved_rule_not_presentation_approved", amount, codes, None,
                "historical_rule_retained_but_not_presentation_eligible",
                [str(rule.get("reason") or rule.get("label") or "not approved")],
            )

        provincial = _sum_prov(codes)
        if provincial is None:
            return FieldDecision(
                "unresolved_unknown_provincial_rate", amount, codes, None,
                "approved_rule_but_provincial_rate_unknown", []
            )
        return FieldDecision(
            "certified_approved_local_rule", amount, codes, provincial,
            "approved_local_mapping_rule+condition_gate", list(assessment.reasons)
        )

    candidates, truncated_search = exact_candidates(amount)
    if truncated_search:
        return FieldDecision(
            "unresolved_many_exact_candidates", amount, [], None,
            "exact_search_found_many_candidates", []
        )
    if not candidates:
        return FieldDecision(
            "unresolved_no_exact_candidate", amount, [], None,
            "no_exact_service_composition", []
        )

    # Exact arithmetic is diagnostic only.  The PP Fee universe contains
    # services outside the provincial 15-item table, so a locally unique sum is
    # not enough evidence for a presentation claim.  Certification requires an
    # explicitly approved rule above.
    preview = ["+".join(c.codes) for c in candidates[:8]]
    return FieldDecision(
        "unresolved_unapproved_exact_candidates", amount, [], None,
        "exact_math_without_approved_mapping_evidence", preview
    )


def decide_pp_record(row: dict) -> FieldDecision:
    """Apply record-context closure rules before generic amount-only mapping.

    Two cases need record context:
    - child PP30/PP50 are identified FY2569 services but are outside the
      documented Phetchabun P&P 15-item resolution (agreement pp.13-14);
    - HTYPE0016 HCODE07847 uses the report's billed_amount as the canonical
      service/package amount because its PP column is a transferred-unit
      payment presentation rather than the standard full PP Fee rate.
    """
    amount = round(float(row.get("pp") or 0), 2)
    if amount <= 0:
        return FieldDecision("empty", amount, [], 0.0, "none", [])

    outside_rule = OUTSIDE_LOCAL_RESOLUTION.get(amount)
    if outside_rule is not None and str(row.get("age_hint") or "") == "child":
        return FieldDecision(
            "certified_outside_local_provincial_resolution",
            amount,
            [],
            float(outside_rule.get("provincial_amount_in_this_resolution", 0) or 0),
            "fy2569_service_identified_but_not_in_phetchabun_pp15_resolution_pages_13_14",
            [
                str(outside_rule.get("service") or ""),
                str(outside_rule.get("reason") or ""),
            ],
        )

    transfer = PROVINCIAL_CLOSURE_DATA.get("transfer_service_basis") or {}
    htype = str(row.get("htype_hcode") or "")
    hcode = str(row.get("hcode") or "")
    context_transfer = (
        htype == str(transfer.get("htype_hcode") or "")
        and hcode == str(transfer.get("hcode") or "")
    )
    legacy_transfer = (
        not htype
        and hcode == str(transfer.get("hcode") or "")
        and amount in TRANSFER_RAW_FALLBACK
    )
    is_transfer = context_transfer or legacy_transfer
    if is_transfer:
        billed = round(float(row.get("billed_amount") or 0), 2)
        if billed <= 0 and legacy_transfer:
            billed = TRANSFER_RAW_FALLBACK.get(amount, 0.0)
        rule = TRANSFER_BILLED_RULES.get(billed)
        if rule is None:
            return FieldDecision(
                "unresolved_transfer_billed_amount_not_mapped",
                amount,
                [],
                None,
                "htype0016_transfer_billed_mapping",
                [f"no approved transfer billed mapping for {billed:.2f}"],
            )
        codes = [str(code) for code in rule.get("codes", [])]
        if not codes or any(code not in ITEMS for code in codes):
            return FieldDecision(
                "unresolved_invalid_transfer_rule",
                amount,
                codes,
                None,
                "htype0016_transfer_billed_mapping",
                ["unknown/empty service code in transfer rule"],
            )
        claim_sum = _sum_claim(codes)
        if abs(claim_sum - billed) > _TOL:
            return FieldDecision(
                "unresolved_invalid_transfer_rule",
                amount,
                codes,
                None,
                "htype0016_transfer_billed_mapping",
                [f"service claim sum {claim_sum:.2f} != billed amount {billed:.2f}"],
            )
        assessment = service_conditions.assess_same_claim_codes(codes)
        if assessment.status == "reject":
            return FieldDecision(
                "unresolved_transfer_rule_rejected_by_hard_condition",
                amount,
                codes,
                None,
                "htype0016_transfer_billed_mapping",
                list(assessment.reasons),
            )
        provincial = _sum_prov(codes)
        expected = float(rule.get("provincial_per_record"))
        if provincial is None or abs(float(provincial) - expected) > _TOL:
            return FieldDecision(
                "unresolved_transfer_rule_rate_mismatch",
                amount,
                codes,
                None,
                "htype0016_transfer_billed_mapping",
                [
                    f"catalog provincial={provincial}; "
                    f"agreement closure expected={expected:.2f}"
                ],
            )
        return FieldDecision(
            "certified_transfer_billed_service_rule",
            amount,
            codes,
            float(provincial),
            "htype0016_billed_service_mapping+phetchabun_resolution_pages_13_14",
            [
                str(rule.get("label") or ""),
                f"raw PP={amount:.2f}; billed service/package={billed:.2f}",
                str(transfer.get("reason") or ""),
            ] + list(assessment.reasons),
        )

    if str(row.get("htype_hcode") or "") == "0016":
        return FieldDecision(
            "unresolved_transfer_payment_model",
            amount,
            [],
            None,
            "htype0016_requires_payment_normalization",
            [
                "HTYPE0016 row is not covered by the approved transfer closure rule",
            ],
        )

    return decide_pp_amount(amount)


def decide_fs_amount(amount: float, projcode: str = "") -> FieldDecision:
    amount = round(float(amount), 2)
    if amount <= 0:
        return FieldDecision("empty", amount, [], 0.0, "none", [])
    if str(projcode or "").strip().upper() == "WALKIN":
        return FieldDecision(
            "excluded_fs_walkin",
            amount,
            [],
            None,
            "source_projcode_walkin_outside_pp_fee_scope",
            [],
        )
    return FieldDecision(
        "unresolved_fs_scope", amount, [], None,
        "fs_not_certified_by_pp_rulebook", []
    )


def _fiscal_limits_by_code() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for code, rule in service_conditions.CONDITIONS_BY_CODE.items():
        for freq in rule.get("frequency", []):
            if freq.get("scope") != "fiscal_year":
                continue
            requires = set(freq.get("requires", []))
            if not requires.issubset({"PID", "visit_date"}):
                continue
            if freq.get("max") is not None:
                result.setdefault(code, {})["max_occurrences"] = int(freq["max"])
            if freq.get("max_units") is not None:
                result.setdefault(code, {})["max_units"] = int(freq["max_units"])
                result[code]["units_per_occurrence"] = int(
                    (rule.get("same_claim") or {}).get("represents_units", 1)
                )
    return result


def _apply_pid_frequency_gate(rows: list[dict]) -> None:
    limits = _fiscal_limits_by_code()
    occurrences: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        pid = str(row.get("pid") or "")
        if not pid:
            continue
        decision: FieldDecision = row["pp_decision"]
        if not decision.certified:
            continue
        for code in decision.codes:
            if code in limits:
                occurrences[(pid, code)].append(row)

    for (pid, code), members in occurrences.items():
        limit = limits[code]
        occurrence_count = len(members)
        unit_count = occurrence_count * int(limit.get("units_per_occurrence", 1))
        too_many_occurrences = (
            limit.get("max_occurrences") is not None
            and occurrence_count > int(limit["max_occurrences"])
        )
        too_many_units = (
            limit.get("max_units") is not None
            and unit_count > int(limit["max_units"])
        )
        if not too_many_occurrences and not too_many_units:
            continue

        parts = [f"PID has {occurrence_count} certified occurrences of {code}"]
        if limit.get("max_occurrences") is not None:
            parts.append(f"FY max occurrences={limit['max_occurrences']}")
        if limit.get("max_units") is not None:
            parts.append(
                f"units={unit_count}, FY max units={limit['max_units']}"
            )
        reason = "; ".join(parts) + "; all affected mappings revoked"

        # Do not arbitrarily keep the first N visits. If the annual total is
        # impossible, available data cannot prove which individual transaction
        # should be discarded, so every affected mapping is removed from the
        # presentation-certified set.
        for row in members:
            old: FieldDecision = row["pp_decision"]
            row["pp_decision"] = FieldDecision(
                "unresolved_pid_frequency_conflict",
                old.amount,
                old.codes,
                None,
                "pid_date_frequency_gate",
                old.reasons + [reason],
            )


def build_proof_report(records_path: str = _PRIVATE_RECORDS_PATH) -> dict:
    payload = _load(records_path)

    # Enrich the older proof-grade extraction with raw-report context that is
    # required for HTYPE/payment-model gating and later record-level evidence.
    # The public/aggregate report still omits these identifiers and contexts.
    context_by_tran: dict[str, dict] = {}
    if os.path.exists(_CONTEXT_V2_PATH):
        context_payload = _load(_CONTEXT_V2_PATH)
        context_by_tran = {
            str(record.get("tran_id") or ""): record
            for record in context_payload.get("records", [])
            if str(record.get("tran_id") or "")
        }

    rows: list[dict] = []
    for record in payload.get("records", []):
        row = dict(record)
        richer = context_by_tran.get(str(record.get("tran_id") or ""))
        if richer:
            for key in (
                "htype_hcode", "htype_hcode_paid", "hcode_paid", "billed_amount",
                "sex", "age_hint", "visit_day", "maininscl", "rep", "source_suffix",
            ):
                if key in richer:
                    row[key] = richer.get(key)
        pp_amount = round(float(row.get("pp") or 0), 2)
        row["pp_decision"] = decide_pp_record(row)
        row["fs_decision"] = decide_fs_amount(float(record.get("fs") or 0), str(record.get("projcode") or ""))
        rows.append(row)

    _apply_pid_frequency_gate(rows)

    hcodes: dict[str, dict] = {}
    status_counter = Counter()
    proof_counter = Counter()
    service_counts = Counter()
    service_claim = Counter()
    service_prov = Counter()
    unresolved_amounts = Counter()

    overall = {
        "raw_pp": 0.0, "raw_fs": 0.0, "raw_total": 0.0,
        "certified_claim_amount": 0.0,
        "certified_provincial_allocation": 0.0,
        "unresolved_amount": 0.0,
        "excluded_fs_amount": 0.0,
        "certified_field_count": 0,
        "unresolved_field_count": 0,
        "excluded_fs_field_count": 0,
    }

    def init_hcode() -> dict:
        return {
            "raw_pp": 0.0, "raw_fs": 0.0, "raw_total": 0.0,
            "certified_claim_amount": 0.0,
            "certified_provincial_allocation": 0.0,
            "unresolved_amount": 0.0,
            "excluded_fs_amount": 0.0,
            "certified_field_count": 0,
            "unresolved_field_count": 0,
            "excluded_fs_field_count": 0,
            "services": Counter(),
            "statuses": Counter(),
            "unresolved_amounts": Counter(),
        }

    for row in rows:
        hcode = str(row["hcode"])
        agg = hcodes.setdefault(hcode, init_hcode())
        pp = round(float(row.get("pp") or 0), 2)
        fs = round(float(row.get("fs") or 0), 2)
        agg["raw_pp"] += pp
        agg["raw_fs"] += fs
        agg["raw_total"] += pp + fs
        overall["raw_pp"] += pp
        overall["raw_fs"] += fs
        overall["raw_total"] += pp + fs

        for field, amount, decision in (
            ("PP", pp, row["pp_decision"]),
            ("FS", fs, row["fs_decision"]),
        ):
            if amount <= 0:
                continue
            status_counter[decision.status] += 1
            proof_counter[decision.proof_basis] += 1
            agg["statuses"][decision.status] += 1
            if decision.certified:
                agg["certified_claim_amount"] += amount
                agg["certified_provincial_allocation"] += float(decision.provincial_amount or 0)
                agg["certified_field_count"] += 1
                overall["certified_claim_amount"] += amount
                overall["certified_provincial_allocation"] += float(decision.provincial_amount or 0)
                overall["certified_field_count"] += 1
                for code in decision.codes:
                    service_counts[code] += 1
                    service_claim[code] += _claim_rate(code)
                    service_prov[code] += float(_prov_rate(code) or 0)
                    agg["services"][code] += 1
            elif decision.status == "excluded_fs_walkin":
                agg["excluded_fs_amount"] += amount
                agg["excluded_fs_field_count"] += 1
                overall["excluded_fs_amount"] += amount
                overall["excluded_fs_field_count"] += 1
            else:
                agg["unresolved_amount"] += amount
                agg["unresolved_field_count"] += 1
                overall["unresolved_amount"] += amount
                overall["unresolved_field_count"] += 1
                unresolved_amounts[(field, amount, decision.status)] += 1
                agg["unresolved_amounts"][(field, amount, decision.status)] += 1

    # Apply facility-confirmed zero-claim-money reallocations after record
    # classification. They preserve NHSO claim money exactly but can change the
    # provincial allocation because local shares differ by service. This is the
    # same audit trail used by the production summary.
    applied_adjustments: list[dict] = []
    for entry in ADJUSTMENTS_DATA.get("adjustments", []):
        hcode = str(entry.get("hcode") or "")
        agg = hcodes.get(hcode)
        if not agg:
            continue
        deltas: list[tuple[str, int]] = []
        claim_delta = 0.0
        provincial_delta = 0.0
        valid = True
        for item in entry.get("items", []):
            code = str(item.get("code") or "")
            if code not in ITEMS:
                valid = False
                break
            delta = int(item.get("delta") or 0)
            deltas.append((code, delta))
            claim_delta += delta * _claim_rate(code)
            provincial_delta += delta * float(_prov_rate(code) or 0)
        if not valid or abs(claim_delta) > _TOL:
            continue
        if any(agg["services"].get(code, 0) + delta < 0 for code, delta in deltas):
            continue
        for code, delta in deltas:
            agg["services"][code] += delta
            service_counts[code] += delta
            service_claim[code] += delta * _claim_rate(code)
            service_prov[code] += delta * float(_prov_rate(code) or 0)
        agg["certified_provincial_allocation"] += provincial_delta
        overall["certified_provincial_allocation"] += provincial_delta
        applied_adjustments.append({
            "hcode": hcode,
            "recorded_at": entry.get("recorded_at"),
            "claim_delta": round(claim_delta, 2),
            "provincial_delta": round(provincial_delta, 2),
            "reason": entry.get("reason", ""),
            "items": [{"code": code, "delta": delta} for code, delta in deltas],
        })

    def r2(value: float) -> float:
        return round(float(value), 2)

    hcode_rows = []
    for hcode, agg in sorted(hcodes.items()):
        raw_total = r2(agg["raw_total"])
        cert = r2(agg["certified_claim_amount"])
        raw_pp = r2(agg["raw_pp"])
        hcode_rows.append({
            "hcode": hcode,
            "raw_pp": raw_pp,
            "raw_fs": r2(agg["raw_fs"]),
            "raw_total": raw_total,
            "certified_claim_amount": cert,
            "certified_claim_coverage_pct": round((cert / raw_pp * 100) if raw_pp else 0, 2),
            "certified_provincial_allocation": r2(agg["certified_provincial_allocation"]),
            "unresolved_amount": r2(agg["unresolved_amount"]),
            "excluded_fs_amount": r2(agg["excluded_fs_amount"]),
            "certified_field_count": agg["certified_field_count"],
            "unresolved_field_count": agg["unresolved_field_count"],
            "excluded_fs_field_count": agg["excluded_fs_field_count"],
            "services": dict(sorted(agg["services"].items())),
            "statuses": dict(sorted(agg["statuses"].items())),
            "top_unresolved": [
                {
                    "field": key[0], "amount": key[1], "status": key[2],
                    "count": count, "sum": r2(key[1] * count)
                }
                for key, count in agg["unresolved_amounts"].most_common(10)
            ],
        })

    for key in ("raw_pp", "raw_fs", "raw_total", "certified_claim_amount",
                "certified_provincial_allocation", "unresolved_amount",
                "excluded_fs_amount"):
        overall[key] = r2(overall[key])
    raw_total = float(overall["raw_total"])
    raw_pp = float(overall["raw_pp"])
    cert_total = float(overall["certified_claim_amount"])
    overall["certified_claim_coverage_pct"] = round(
        (cert_total / raw_pp * 100) if raw_pp else 0, 2
    )
    overall["reconciles"] = abs(
        float(overall["certified_claim_amount"])
        + float(overall["unresolved_amount"])
        + float(overall["excluded_fs_amount"])
        - raw_total
    ) <= _TOL

    service_rows = [{
        "code": code,
        "name": ITEMS[code]["name"],
        "count": count,
        "claim_amount": r2(service_claim[code]),
        "provincial_allocation": r2(service_prov[code]),
    } for code, count in service_counts.most_common()]

    unresolved_rows = [{
        "field": field,
        "amount": amount,
        "status": status,
        "count": count,
        "sum": r2(amount * count),
    } for (field, amount, status), count in unresolved_amounts.most_common()]

    return {
        "schema_version": 1,
        "source": {
            "source_file_count": payload.get("source_file_count"),
            "record_count": payload.get("record_count"),
            "duplicate_count": payload.get("duplicate_count"),
            "conflicting_duplicate_count": payload.get("conflicting_duplicate_count"),
            "privacy": "aggregate output only; PID/date used internally and omitted",
        },
        "policy": {
            "closest_match": False,
            "maximize_payment": False,
            "presentation_gate": "certified only",
            "pp_human_rules": "condition-gated; single-item same-rate collisions rejected",
            "fs": "excluded from PP Fee allocation when source PROJCODE=WALKIN; preserved separately",
            "manual_adjustments": "facility-confirmed zero-claim-money reallocations are applied after validation; they may change provincial allocation",
        },
        "overall": overall,
        "applied_manual_adjustments": applied_adjustments,
        "by_hcode": hcode_rows,
        "certified_services": service_rows,
        "status_counts": dict(status_counter),
        "proof_basis_counts": dict(proof_counter),
        "unresolved": unresolved_rows,
    }


def write_report(output_path: str = _REPORT_PATH) -> dict:
    report = build_proof_report()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    return report


if __name__ == "__main__":
    report = write_report()
    print(json.dumps({
        "source": report["source"],
        "overall": report["overall"],
        "by_hcode": report["by_hcode"],
        "certified_services": report["certified_services"],
        "status_counts": report["status_counts"],
        "top_unresolved": report["unresolved"][:20],
    }, ensure_ascii=True, indent=2))
