"""Per-facility service reconciliation pipeline (admin only -- has PID/name).

Follows this exact workflow:
  1. Group raw records by HCODE
  2. Each HCODE's people: PID, name, PP, FS
  3. Per record, predict service(s) from PP and FS separately using combo
     matching against the 15-item provincial rate list
  4. Summarize predicted item counts for the facility
  5. Two reconciliation tables: value at SPSC's full rate vs value actually
     allocated per the provincial agreement

Prediction runs on PP and FS separately (not combined into ยอดรวม) because the
15 reference items are PP Fee schedule items -- mixing in FS would corrupt the
match. Each record's PP and FS amounts are decomposed independently.
"""
from __future__ import annotations

import json
import os

import pandas as pd

import db
import service_matching

_RATES_PATH = os.path.join(os.path.dirname(__file__), "assets", "service_rates.json")


def _load_items() -> list[dict]:
    try:
        with open(_RATES_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in data.get("items", []) if item.get("matchable")]


MATCHABLE_ITEMS = _load_items()
ITEM_NAMES = [item["name"] for item in MATCHABLE_ITEMS]
RATE_FULL_BY_NAME = {item["name"]: float(item["rate_full"]) for item in MATCHABLE_ITEMS}
RATE_PROVINCIAL_BY_NAME = {item["name"]: float(item["rate"]) for item in MATCHABLE_ITEMS}

PEOPLE_COLUMNS = ["HCODE", "PID", "ชื่อ-นามสกุล", "PP", "FS", "ยอดรวม"]
PREDICTION_COLUMNS = ["PID", "ชื่อ-นามสกุล", "PP", "FS", "บริการที่คาดการณ์ (PP)", "บริการที่คาดการณ์ (FS)", "สถานะ"]
COUNT_COLUMNS = ["รายการบริการ", "จำนวนครั้ง"]
RECONCILE_COLUMNS = [
    "รายการบริการ", "จำนวนครั้ง",
    "อัตราเต็ม สปสช. (บาท/ครั้ง)", "ยอดที่สปสช.ชดเชย (บาท)",
    "อัตราจังหวัด (บาท/ครั้ง)", "ยอดที่ได้รับจัดสรรจริง (บาท)",
]

_STATUS_RANK = {"🔴 ไม่พบ": 0, "🟡 ไม่แน่ชัด": 1, "🟢 คาดการณ์": 2, "-": 3}


def get_people_for_hcode(hcode: str) -> pd.DataFrame:
    """Step 1+2: raw people list for one facility."""
    try:
        people = db.get_people_records_for_hcode(hcode)
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=PEOPLE_COLUMNS)
    if people.empty:
        return pd.DataFrame(columns=PEOPLE_COLUMNS)
    return people[PEOPLE_COLUMNS]


def predict_records(people: pd.DataFrame) -> pd.DataFrame:
    """Step 3: per-record combo prediction, PP and FS decomposed separately."""
    if people.empty:
        return pd.DataFrame(columns=PREDICTION_COLUMNS)

    rows = []
    for rec in people.to_dict(orient="records"):
        pp_status, pp_combos = service_matching.resolve_combo(float(rec["PP"]))
        fs_status, fs_combos = service_matching.resolve_combo(float(rec["FS"]))
        overall_status = min(pp_status, fs_status, key=lambda s: _STATUS_RANK[s])
        rows.append({
            "PID": rec["PID"],
            "ชื่อ-นามสกุล": rec["ชื่อ-นามสกุล"],
            "PP": rec["PP"],
            "FS": rec["FS"],
            "บริการที่คาดการณ์ (PP)": service_matching.format_combo_text(pp_status, pp_combos),
            "บริการที่คาดการณ์ (FS)": service_matching.format_combo_text(fs_status, fs_combos),
            "สถานะ": overall_status,
            "_pp_status": pp_status,
            "_pp_combo": pp_combos[0] if pp_status == "🟢 คาดการณ์" else [],
            "_fs_status": fs_status,
            "_fs_combo": fs_combos[0] if fs_status == "🟢 คาดการณ์" else [],
        })
    return pd.DataFrame(rows)


def summarize_item_counts(predictions: pd.DataFrame) -> pd.DataFrame:
    """Step 4: count confident (🟢) item hits across the facility; ambiguous/
    unmatched amounts are kept visible as their own catch-all rows rather than
    silently dropped or guessed into a specific item."""
    if predictions.empty:
        return pd.DataFrame(columns=COUNT_COLUMNS)

    counts: dict[str, int] = {name: 0 for name in ITEM_NAMES}
    unclear = 0
    notfound = 0
    for rec in predictions.to_dict(orient="records"):
        for status_key, combo_key in (("_pp_status", "_pp_combo"), ("_fs_status", "_fs_combo")):
            status = rec[status_key]
            if status == "🟢 คาดการณ์":
                for name in rec[combo_key]:
                    counts[name] = counts.get(name, 0) + 1
            elif status == "🟡 ไม่แน่ชัด":
                unclear += 1
            elif status == "🔴 ไม่พบ":
                notfound += 1

    rows = [{"รายการบริการ": name, "จำนวนครั้ง": count} for name, count in counts.items() if count > 0]
    if unclear:
        rows.append({"รายการบริการ": "🟡 ยังไม่แน่ชัด (ต้องตรวจสอบ)", "จำนวนครั้ง": unclear})
    if notfound:
        rows.append({"รายการบริการ": "🔴 ไม่พบรายการที่ตรงกัน", "จำนวนครั้ง": notfound})
    if not rows:
        return pd.DataFrame(columns=COUNT_COLUMNS)
    return pd.DataFrame(rows).sort_values("จำนวนครั้ง", ascending=False).reset_index(drop=True)


def build_reconciliation(counts: pd.DataFrame) -> pd.DataFrame:
    """Step 5: SPSC full-rate value vs actual provincial-agreement value."""
    if counts.empty:
        return pd.DataFrame(columns=RECONCILE_COLUMNS)

    rows = []
    total_full = 0.0
    total_provincial = 0.0
    for rec in counts.to_dict(orient="records"):
        name = rec["รายการบริการ"]
        count = int(rec["จำนวนครั้ง"])
        rate_full = RATE_FULL_BY_NAME.get(name)
        rate_provincial = RATE_PROVINCIAL_BY_NAME.get(name)
        if rate_full is None or rate_provincial is None:
            rows.append({
                "รายการบริการ": name, "จำนวนครั้ง": f"{count:,}",
                "อัตราเต็ม สปสช. (บาท/ครั้ง)": "-", "ยอดที่สปสช.ชดเชย (บาท)": "-",
                "อัตราจังหวัด (บาท/ครั้ง)": "-", "ยอดที่ได้รับจัดสรรจริง (บาท)": "-",
            })
            continue
        full_value = count * rate_full
        provincial_value = count * rate_provincial
        total_full += full_value
        total_provincial += provincial_value
        rows.append({
            "รายการบริการ": name, "จำนวนครั้ง": f"{count:,}",
            "อัตราเต็ม สปสช. (บาท/ครั้ง)": f"{rate_full:,.2f}",
            "ยอดที่สปสช.ชดเชย (บาท)": f"{full_value:,.2f}",
            "อัตราจังหวัด (บาท/ครั้ง)": f"{rate_provincial:,.2f}",
            "ยอดที่ได้รับจัดสรรจริง (บาท)": f"{provincial_value:,.2f}",
        })

    rows.append({
        "รายการบริการ": "รวม (เฉพาะรายการที่ยืนยันชัดเจน)", "จำนวนครั้ง": "-",
        "อัตราเต็ม สปสช. (บาท/ครั้ง)": "-", "ยอดที่สปสช.ชดเชย (บาท)": f"{total_full:,.2f}",
        "อัตราจังหวัด (บาท/ครั้ง)": "-", "ยอดที่ได้รับจัดสรรจริง (บาท)": f"{total_provincial:,.2f}",
    })
    return pd.DataFrame(rows, columns=RECONCILE_COLUMNS)


def format_people_display(people: pd.DataFrame) -> pd.DataFrame:
    if people.empty:
        return people
    display = people.copy()
    for col in ("PP", "FS", "ยอดรวม"):
        display[col] = display[col].map(lambda v: f"{float(v):,.2f}")
    return display


def format_predictions_display(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame(columns=PREDICTION_COLUMNS)
    display = predictions[PREDICTION_COLUMNS].copy()
    display["PP"] = display["PP"].map(lambda v: f"{float(v):,.2f}")
    display["FS"] = display["FS"].map(lambda v: f"{float(v):,.2f}")
    return display


def analyze_hcode(hcode: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the full 5-step pipeline for one facility."""
    people = get_people_for_hcode(hcode)
    predictions = predict_records(people)
    counts = summarize_item_counts(predictions)
    reconciliation = build_reconciliation(counts)
    return (
        format_people_display(people),
        format_predictions_display(predictions),
        counts,
        reconciliation,
    )
