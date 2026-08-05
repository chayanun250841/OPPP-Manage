"""OPPP compensation dashboard: public executive view + hidden developer console."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime

import gradio as gr
import pandas as pd

import db
import service_analysis
import service_matching

ADMIN_USERNAME = os.environ.get("OPPP_ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD_HASH = os.environ.get("OPPP_ADMIN_PASSWORD_HASH", "").strip().lower()

LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "ตรากระทรวงสาธารณสุขใหม่.png")
HCODE_NAMES_PATH = os.path.join(os.path.dirname(__file__), "assets", "hcode_names.json")


def load_logo_data_uri(path: str) -> str:
    try:
        with open(path, "rb") as file:
            encoded = base64.b64encode(file.read()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except OSError:
        return ""


def load_hcode_names(path: str) -> dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}


HCODE_NAMES = load_hcode_names(HCODE_NAMES_PATH)


def hcode_label(code: object) -> str:
    code_text = str(code).strip()
    name = HCODE_NAMES.get(code_text)
    return f"{code_text} {name}" if name else code_text


LOGO_DATA_URI = load_logo_data_uri(LOGO_PATH)

TERMINAL_GREEN = gr.themes.Color(
    name="terminal_green",
    c50="#e8fbf1", c100="#c3f5da", c200="#8fe9b9", c300="#5cdd9a",
    c400="#2fd47a", c500="#22b866", c600="#189454", c700="#127140",
    c800="#0c4c2c", c900="#06301b", c950="#03190d",
)
TERMINAL_DARK = gr.themes.Color(
    name="terminal_dark",
    c50="#cdd8d2", c100="#a9bdb1", c200="#6a9a80", c300="#3f5f4d",
    c400="#25392d", c500="#17281f", c600="#111d17", c700="#0d1712",
    c800="#0a1017", c900="#06080b", c950="#020304",
)

THEME = gr.themes.Soft(
    primary_hue=TERMINAL_GREEN,
    secondary_hue=TERMINAL_DARK,
    neutral_hue="slate",
    font=[
        "ui-monospace", "Cascadia Code", "JetBrains Mono", "SF Mono",
        "Menlo", "Consolas", gr.themes.GoogleFont("Sarabun"), "monospace",
    ],
)

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

:root, .dark, .gradio-container.dark {
    --oppp-bg: #06080b;
    --oppp-panel: #0a1017;
    --oppp-panel-alt: #0d1712;
    --oppp-input: #0a0f0c;
    --oppp-border: #17281f;
    --oppp-text: #cdd8d2;
    --oppp-text-dim: #6a9a80;
    --oppp-accent: #2fd47a;
    --oppp-accent-dark: #189454;
    --oppp-accent-text: #032312;
    --oppp-shadow: 0 1px 3px rgba(0, 0, 0, 0.5), 0 1px 2px rgba(0, 0, 0, 0.4);
}

/* Force the dark terminal look regardless of the visitor's OS/browser
   color-scheme preference -- Gradio's built-in skin otherwise overrides
   input/textarea backgrounds independently of the vars above. */
.gradio-container, .gradio-container * {
    font-family: ui-monospace, 'Cascadia Code', 'JetBrains Mono', 'SF Mono', Menlo, Consolas, 'Sarabun', 'Noto Sans Thai', monospace !important;
}
.gradio-container, .gradio-container.dark {
    background: var(--oppp-bg) !important;
    color: var(--oppp-text) !important;
    color-scheme: dark !important;
}
.gradio-container input,
.gradio-container textarea,
.gradio-container select,
.gradio-container .block,
.gradio-container .form,
.gradio-container .wrap {
    background: var(--oppp-panel);
    color: var(--oppp-text);
}
/* Gradio's label badge defaults to a primary-hue (green) fill, producing
   low-contrast green-on-green text -- force a dark badge everywhere. */
.gradio-container span[data-testid="block-info"] {
    background: var(--oppp-panel-alt) !important;
    color: var(--oppp-text-dim) !important;
    border: 1px solid var(--oppp-border) !important;
    border-radius: 4px !important;
    padding: 2px 8px !important;
}

/* ---------- Header ---------- */
.oppp-header {
    position: relative;
    display: flex;
    align-items: center;
    gap: 18px;
    background: var(--oppp-panel);
    color: var(--oppp-text);
    padding: 24px 30px;
    border-radius: 6px;
    margin-bottom: 22px;
    border: 1px solid var(--oppp-border);
    border-left: 4px solid var(--oppp-accent);
    box-shadow: var(--oppp-shadow);
}
.oppp-header .icon {
    font-size: 2rem;
    line-height: 1;
    width: 52px; height: 52px;
    display: flex; align-items: center; justify-content: center;
    background: rgba(47, 212, 122, 0.10);
    border-radius: 50%;
    border: 1px solid rgba(47, 212, 122, 0.35);
    flex-shrink: 0;
    overflow: hidden;
}
.oppp-header .icon img {
    width: 100%; height: 100%;
    object-fit: contain;
}
.oppp-header h1 {
    margin: 0; font-size: 1.35rem; font-weight: 700; letter-spacing: 0.2px;
    color: var(--oppp-accent);
}
.oppp-header p { margin: 4px 0 0; opacity: 0.8; font-size: 0.82rem; color: var(--oppp-text-dim); }
.oppp-header .badge {
    margin-left: auto;
    text-align: right;
    font-size: 0.76rem;
    opacity: 0.9;
    line-height: 1.5;
}

/* ---------- Section titles ---------- */
.section-title h3 {
    display: inline-flex;
    align-items: center;
    font-size: 0.92rem !important;
    font-weight: 700 !important;
    color: var(--oppp-accent) !important;
    padding-bottom: 8px !important;
    margin-bottom: 12px !important;
    border-bottom: 1px solid var(--oppp-border) !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

/* ---------- Cards ---------- */
.card {
    background: var(--oppp-panel) !important;
    border: 1px solid var(--oppp-border) !important;
    border-radius: 8px !important;
    padding: 20px 22px !important;
    box-shadow: var(--oppp-shadow);
    margin-bottom: 18px !important;
}
.dev-card { border-left: 3px solid var(--oppp-accent) !important; }

/* ---------- KPI cards ---------- */
.kpi-row { gap: 16px !important; margin-bottom: 16px !important; }
.kpi-card {
    position: relative;
    border-radius: 8px !important;
    padding: 8px 16px !important;
    background: var(--oppp-panel) !important;
    border: 1px solid var(--oppp-border) !important;
    border-left: 3px solid var(--oppp-accent) !important;
    box-shadow: var(--oppp-shadow);
}
.kpi-card.gold { border-left: 3px solid var(--oppp-text-dim) !important; }
.kpi-card .wrap, .kpi-card .block, .kpi-card .form {
    background: transparent !important;
}
.kpi-card label span[data-testid="block-info"] {
    background: var(--oppp-panel-alt) !important;
    color: var(--oppp-text) !important;
    font-weight: 600 !important;
    padding: 2px 8px !important;
    border-radius: 4px !important;
    border: 1px solid var(--oppp-border) !important;
}
.kpi-card textarea, .kpi-card input {
    font-size: 1.3rem !important;
    font-weight: 700 !important;
    color: var(--oppp-accent) !important;
    background: transparent !important;
    -webkit-text-fill-color: var(--oppp-accent) !important;
}

/* ---------- Misc ---------- */
.admin-toggle { max-width: 340px; margin: 0 0 10px auto !important; }
.admin-toggle .label-wrap {
    background: var(--oppp-panel) !important;
    border: 1px solid var(--oppp-border) !important;
    border-radius: 6px !important;
}
.admin-toggle .label-wrap span { font-size: 0.78rem !important; color: var(--oppp-text-dim) !important; }

.login-status { font-weight: 600 !important; font-size: 0.85rem !important; color: var(--oppp-text) !important; }
.hint-text { color: var(--oppp-text-dim) !important; font-size: 0.82rem !important; }
.footer-note { text-align: center !important; color: var(--oppp-text-dim) !important; font-size: 0.78rem !important; margin-top: 18px !important; opacity: 0.8; }

/* Buttons */
button.primary, .gr-button-primary {
    background: var(--oppp-accent) !important;
    color: var(--oppp-accent-text) !important;
    border: none !important;
    box-shadow: var(--oppp-shadow) !important;
    font-weight: 700 !important;
}
button.primary:hover, .gr-button-primary:hover {
    background: var(--oppp-accent-dark) !important;
}
button:not(.primary) {
    background: var(--oppp-panel-alt) !important;
    color: var(--oppp-text) !important;
    border: 1px solid var(--oppp-border) !important;
}

/* ---------- Tables / plots ---------- */
table, thead, tbody, tr, td, th {
    background: var(--oppp-panel) !important;
    color: var(--oppp-text) !important;
    border-color: var(--oppp-border) !important;
}
thead th { color: var(--oppp-accent) !important; }

/* Compact cells so wide pivot tables (many item columns) stay readable.
   Do NOT force white-space here -- that overrides each Dataframe's own
   `wrap` setting and, combined with narrow auto-sized columns, stacks
   short headers into a single letter per line. Let `wrap` control it. */
.gradio-container table td,
.gradio-container table th {
    padding: 4px 8px !important;
    font-size: 0.82rem !important;
    line-height: 1.3 !important;
}
"""


# ---------------------------------------------------------------------------
# Report file parsing (.xls -> DataFrame)
# ---------------------------------------------------------------------------


def text_value(value: object) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\.0$", "", str(value).strip())


def hcode_value(value: object) -> str:
    value = text_value(value)
    return value.zfill(5) if value.isdigit() else value


def money_value(value: object) -> float:
    number = pd.to_numeric(value, errors="coerce")
    return 0.0 if pd.isna(number) else float(number)


def find_column(header: pd.Series, label: str) -> int:
    matches = [index for index, value in enumerate(header) if text_value(value) == label]
    if not matches:
        raise ValueError(f"ไม่พบคอลัมน์ {label}")
    return matches[0]


def parse_report(path: str) -> pd.DataFrame:
    sheet = pd.read_excel(path, header=None, dtype=object)
    mask = sheet.apply(lambda row: row.map(text_value).eq("HCODE").any(), axis=1)
    matches = mask[mask].index
    if len(matches) == 0:
        raise ValueError("ไม่พบหัวตาราง HCODE")

    header_row = int(matches[0])
    header = sheet.iloc[header_row].where(sheet.iloc[header_row].notna(), sheet.iloc[header_row - 1])
    columns = {label: find_column(header, label) for label in ["TRAN_ID", "PID", "ชื่อ-นามสกุล", "HCODE", "PP", "FS"]}
    date_col = find_column(header, "วันเข้ารักษา")
    rows = sheet.iloc[header_row + 2 :].copy()

    report_name = os.path.basename(path)
    report_code = re.search(r"(\d{4})_OP_\d{2}", report_name)
    result = pd.DataFrame(
        {
            "TRAN_ID": rows.iloc[:, columns["TRAN_ID"]].map(text_value),
            "PID": rows.iloc[:, columns["PID"]].map(text_value),
            "ชื่อ-นามสกุล": rows.iloc[:, columns["ชื่อ-นามสกุล"]].map(text_value),
            "HCODE": rows.iloc[:, columns["HCODE"]].map(hcode_value),
            "วันเข้ารักษา": pd.to_datetime(rows.iloc[:, date_col], errors="coerce").dt.date.astype("string"),
            "PP": rows.iloc[:, columns["PP"]].map(money_value),
            "FS": rows.iloc[:, columns["FS"]].map(money_value),
        }
    )
    result = result[(result["HCODE"] != "") & (result["HCODE"].str.lower() != "hcode")].copy()
    result["ไฟล์ต้นทาง"] = report_name
    result["รอบรายงาน"] = report_code.group(1) if report_code else report_name
    result["ยอดรวม"] = result["PP"] + result["FS"]
    result["รหัสรายการ"] = result.apply(
        lambda row: hashlib.sha256(
            "|".join(str(row[key]) for key in ["รอบรายงาน", "TRAN_ID", "PID", "HCODE", "วันเข้ารักษา", "PP", "FS"]).encode()
        ).hexdigest()[:16],
        axis=1,
    )
    return result


def export_csv(frame: pd.DataFrame, name: str) -> str:
    path = os.path.join(tempfile.gettempdir(), f"{name}_{datetime.now():%Y%m%d_%H%M%S}.csv")
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def export_excel(frame: pd.DataFrame | None, name: str):
    """Excel-download handler for a Dataframe component's current value."""
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    path = os.path.join(tempfile.gettempdir(), f"{name}_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
    frame.to_excel(path, index=False)
    return path


def export_excel_sheets(name: str, **sheets: pd.DataFrame | None):
    """Excel-download handler that writes multiple tables as separate sheets."""
    usable = {label: df for label, df in sheets.items() if isinstance(df, pd.DataFrame) and not df.empty}
    if not usable:
        return None
    path = os.path.join(tempfile.gettempdir(), f"{name}_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
    with pd.ExcelWriter(path) as writer:
        for label, df in usable.items():
            df.to_excel(writer, sheet_name=label[:31], index=False)
    return path


# ---------------------------------------------------------------------------
# Login (hidden admin panel)
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def login(username: str, password: str):
    if not ADMIN_USERNAME or not ADMIN_PASSWORD_HASH:
        return "viewer", "⚠️ เซิร์ฟเวอร์ยังไม่ได้ตั้งค่า OPPP_ADMIN_USERNAME / OPPP_ADMIN_PASSWORD_HASH"
    if username.strip() == ADMIN_USERNAME and password and hash_password(password) == ADMIN_PASSWORD_HASH:
        return "admin", "✅ เข้าสู่ระบบสำเร็จ: เปิดหน้าผู้ดูแลระบบแล้ว"
    return "viewer", "❌ ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"


def logout():
    return "viewer", "ออกจากระบบแล้ว"


def toggle_admin(role: str):
    return gr.update(visible=(role == "admin"))


# ---------------------------------------------------------------------------
# Executive dashboard (public, no login required)
# ---------------------------------------------------------------------------

RANKING_COLUMNS = ["HCODE", "รายการ", "PP", "FS", "ยอดรวม"]


def format_ranking_table(ranking: pd.DataFrame) -> pd.DataFrame:
    if ranking.empty:
        return ranking
    display = ranking.copy()
    display["HCODE"] = display["HCODE"].map(hcode_label)
    display["รายการ"] = display["รายการ"].map(lambda v: f"{int(v):,}")
    for col in ("PP", "FS", "ยอดรวม"):
        display[col] = display[col].map(lambda v: f"{float(v):,.2f}")
    return display


def refresh_dashboard():
    try:
        totals = db.get_overall_totals()
        ranking = db.get_summary_by_hcode()
        error = None
    except Exception as exc:  # noqa: BLE001 - surface any DB issue to the UI instead of crashing
        totals = {}
        ranking = pd.DataFrame(columns=RANKING_COLUMNS)
        error = str(exc)

    count = int(totals.get("count") or 0)
    if error:
        updated = f"⚠️ เชื่อมต่อฐานข้อมูลไม่ได้: {error}"
    else:
        updated = f"🟢 อัปเดตล่าสุด {datetime.now():%d/%m/%Y %H:%M:%S} น. · ข้อมูลสะสม {count:,} รายการ"

    top10 = ranking.head(10) if not ranking.empty else ranking

    return (
        f"{float(totals.get('total') or 0):,.2f} บาท",
        f"{float(totals.get('pp') or 0):,.2f} บาท",
        f"{float(totals.get('fs') or 0):,.2f} บาท",
        f"{count:,} รายการ",
        f"{int(totals.get('hcode_count') or 0):,} แห่ง",
        str(totals.get("latest_period") or "-"),
        top10,
        format_ranking_table(ranking),
        updated,
    )


# ---------------------------------------------------------------------------
# Facility drill-down (public, no login required -- amounts/services only,
# never names/PID)
# ---------------------------------------------------------------------------

BREAKDOWN_COLUMNS = ["รายการบริการ", "จำนวนครั้ง", "ยอดรวม (บาท)", "สถานะ"]
HCODE_PREFIX_RE = re.compile(r"^(\d{5})")


def build_service_breakdown(hcode: str) -> pd.DataFrame:
    empty = pd.DataFrame(columns=BREAKDOWN_COLUMNS)
    try:
        records = db.get_records_for_hcode(hcode)
        allocations = db.get_allocations_for_hcode(hcode)
    except Exception:  # noqa: BLE001
        return empty
    if records.empty:
        return empty

    allocated_by_record: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for row in allocations.itertuples():
        allocated_by_record[(row.record_code, row.money_type)].append((row.service, float(row.amount)))

    buckets: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"count": 0, "amount": 0.0})

    def add(label: str, status: str, amount: float) -> None:
        entry = buckets[(label, status)]
        entry["count"] += 1
        entry["amount"] += amount

    for row in records.itertuples():
        for money_type, total in (("PP", float(row.pp)), ("FS", float(row.fs))):
            if total <= 0:
                continue
            allocated = allocated_by_record.get((row.record_code, money_type), [])
            for service, amount in allocated:
                add(service, "✅ ยืนยันแล้ว", amount)

            remaining = round(total - sum(amount for _, amount in allocated), 2)
            if remaining <= 0.01:
                continue
            candidates = service_matching.match_candidates(remaining)
            if len(candidates) == 1:
                add(candidates[0], "🟢 คาดการณ์", remaining)
            elif len(candidates) > 1:
                add("อาจเป็น: " + " / ".join(candidates), "🟡 ไม่แน่ชัด", remaining)
            else:
                add("ไม่พบรายการที่ตรงกัน", "🔴 ไม่ระบุ", remaining)

    if not buckets:
        return empty

    rows = [
        {"รายการบริการ": label, "จำนวนครั้ง": data["count"], "ยอดรวม (บาท)": data["amount"], "สถานะ": status}
        for (label, status), data in buckets.items()
    ]
    breakdown = pd.DataFrame(rows).sort_values("ยอดรวม (บาท)", ascending=False).reset_index(drop=True)
    breakdown["จำนวนครั้ง"] = breakdown["จำนวนครั้ง"].map(lambda v: f"{int(v):,}")
    breakdown["ยอดรวม (บาท)"] = breakdown["ยอดรวม (บาท)"].map(lambda v: f"{float(v):,.2f}")
    return breakdown[BREAKDOWN_COLUMNS]


def on_select_facility(evt: gr.SelectData):
    row = evt.row_value
    if not row:
        return "คลิกแถวในตารางด้านบนเพื่อดูรายละเอียดบริการของหน่วยนั้น", pd.DataFrame(columns=BREAKDOWN_COLUMNS)

    hcode_display = str(row[0])
    match = HCODE_PREFIX_RE.match(hcode_display)
    if not match:
        return "ไม่พบรหัสหน่วยบริการในแถวที่เลือก", pd.DataFrame(columns=BREAKDOWN_COLUMNS)

    label = f"### 🔍 รายละเอียดบริการ: {hcode_display}"
    return label, build_service_breakdown(match.group(1))


# ---------------------------------------------------------------------------
# Facility service-reconciliation pipeline (admin only -- has PID/name)
# ---------------------------------------------------------------------------


def analyze_facility_ui(hcode_choice: str | None):
    empty = (
        pd.DataFrame(columns=service_analysis.PEOPLE_COLUMNS),
        pd.DataFrame(columns=service_analysis.PREDICTION_COLUMNS),
        pd.DataFrame(columns=service_analysis.COUNT_COLUMNS),
        pd.DataFrame(columns=service_analysis.RECONCILE_COLUMNS),
    )
    if not hcode_choice:
        return empty
    code = hcode_choice.split(" ", 1)[0].strip()
    try:
        return service_analysis.analyze_hcode(code)
    except Exception:  # noqa: BLE001
        return empty


def build_all_facilities_summary():
    try:
        pivot = service_analysis.build_all_facilities_pivot(HCODE_NAMES)
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), f"⚠️ สรุปไม่สำเร็จ: {exc}"
    if pivot.empty:
        return pd.DataFrame(), "ไม่มีข้อมูล"
    updated = f"🟢 คำนวณล่าสุด {datetime.now():%d/%m/%Y %H:%M:%S} น."
    return service_analysis.format_all_facilities_pivot(pivot), updated


# ---------------------------------------------------------------------------
# Developer console (hidden, admin-only)
# ---------------------------------------------------------------------------


def process_upload(files: list[str] | None, uploader: str):
    if not files:
        return "กรุณาเลือกไฟล์ .xls อย่างน้อย 1 ไฟล์"
    if not uploader or not uploader.strip():
        return "กรุณาระบุชื่อผู้บันทึกก่อนอัปโหลด"

    lines = []
    for path in files:
        name = os.path.basename(path)
        try:
            frame = parse_report(path)
        except Exception as exc:  # noqa: BLE001
            lines.append(f"❌ {name}: อ่านไฟล์ไม่สำเร็จ ({exc})")
            continue

        before = len(frame)
        frame = frame.drop_duplicates("รหัสรายการ", keep="first")
        internal_duplicate = before - len(frame)
        report_period = frame["รอบรายงาน"].iloc[0] if not frame.empty else name

        try:
            outcome = db.insert_batch(report_period, name, uploader.strip(), frame)
        except Exception as exc:  # noqa: BLE001
            lines.append(f"❌ {name}: บันทึกฐานข้อมูลไม่สำเร็จ ({exc})")
            continue

        skipped = outcome["duplicate_count"] + internal_duplicate
        line = f"✅ {name} (รอบ {report_period}): บันทึกใหม่ {outcome['inserted_count']:,} รายการ"
        if skipped:
            line += f" · ข้ามรายการซ้ำ {skipped:,} รายการ"
        lines.append(line)

    return "\n".join(lines)


def refresh_batches():
    try:
        batches = db.list_batches()
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), gr.update(choices=[], value=None), f"⚠️ โหลดประวัติไม่สำเร็จ: {exc}"

    choices = [
        f"{row.รหัสชุดข้อมูล} | {row.รอบรายงาน} | {row.ไฟล์ต้นทาง} | {row.สถานะ}"
        for row in batches.itertuples()
    ]
    return batches, gr.update(choices=choices, value=None), ""


def rollback_selected(choice: str | None):
    if not choice:
        return "กรุณาเลือกรายการก่อน"
    batch_id = choice.split(" | ", 1)[0].strip()
    try:
        db.set_batch_status(batch_id, "rolled_back")
    except Exception as exc:  # noqa: BLE001
        return f"ย้อนกลับไม่สำเร็จ: {exc}"
    return "↩️ ย้อนกลับไฟล์นี้แล้ว ข้อมูลจะไม่ถูกนับในสรุปอีกต่อไป (กู้คืนได้ภายหลัง)"


def restore_selected(choice: str | None):
    if not choice:
        return "กรุณาเลือกรายการก่อน"
    batch_id = choice.split(" | ", 1)[0].strip()
    try:
        db.set_batch_status(batch_id, "active")
    except Exception as exc:  # noqa: BLE001
        return f"กู้คืนไม่สำเร็จ: {exc}"
    return "♻️ กู้คืนไฟล์นี้กลับมาใช้งานแล้ว"


def predict_service_label(remaining: float) -> str:
    if remaining is None or remaining <= 0.01:
        return "✅ จัดสรรครบแล้ว"
    return service_matching.predict_label(remaining)


def refresh_admin_views(role: str):
    empty_choices = gr.update(choices=[], value=None)
    if role != "admin":
        return pd.DataFrame(), pd.DataFrame(), None, pd.DataFrame(), empty_choices, pd.DataFrame()
    try:
        people = db.get_people_summary()
        raw = db.get_raw_records()
        raw_path = export_csv(raw, "ข้อมูล_OPPP_ตรวจแล้ว") if not raw.empty else None
        ledger = db.get_allocation_ledger()
        choices = db.get_record_choices()
        alloc_summary = db.get_allocation_summary()
        if not alloc_summary.empty:
            alloc_summary["คาดการณ์บริการ"] = alloc_summary["คงเหลือ"].map(predict_service_label)
    except Exception:  # noqa: BLE001
        return pd.DataFrame(), pd.DataFrame(), None, pd.DataFrame(), empty_choices, pd.DataFrame()
    return people, raw, raw_path, ledger, gr.update(choices=choices, value=None), alloc_summary


def add_allocation_db(
    role: str,
    code_choice: str | None,
    money_type: str,
    service: str,
    amount: float | None,
    note: str,
    recorder: str,
):
    if role != "admin":
        return "กรุณาเข้าสู่ระบบก่อน"
    if not code_choice:
        return "กรุณาเลือกรหัสรายการที่ต้องการจัดสรร"
    if not service or not service.strip():
        return "กรุณาระบุชื่อบริการ"
    if not recorder or not recorder.strip():
        return "กรุณาระบุผู้บันทึก"
    if amount is None or amount <= 0:
        return "จำนวนเงินต้องมากกว่า 0"

    code = code_choice.split(" | ", 1)[0].strip()
    try:
        original = db.get_record_amount(code, money_type)
        if original is None:
            return "ไม่พบรหัสรายการนี้ในฐานข้อมูล"
        already = db.get_allocated_amount(code, money_type)
        remaining = original - already
        db.add_allocation(code, money_type, service.strip(), float(amount), note.strip() if note else "", recorder.strip())
    except Exception as exc:  # noqa: BLE001
        return f"บันทึกไม่สำเร็จ: {exc}"

    if amount > remaining:
        return f"⚠️ บันทึกแล้ว แต่จัดสรรเกินยอดคงเหลือ {remaining:,.2f} บาท (เกินไป {amount - remaining:,.2f} บาท)"
    return f"บันทึกการจัดสรรแล้ว คงเหลือหลังจัดสรร {remaining - amount:,.2f} บาท"


def export_ledger_csv():
    try:
        ledger = db.get_allocation_ledger()
    except Exception:  # noqa: BLE001
        return None
    if ledger.empty:
        return None
    return export_csv(ledger, "สมุดจัดสรรบริการ")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

with gr.Blocks(title="OPPP Compensation Dashboard") as demo:
    role_state = gr.State("viewer")

    with gr.Accordion("🔒 สำหรับผู้ดูแลระบบ", open=False, elem_classes="admin-toggle"):
        with gr.Row():
            username_box = gr.Textbox(label="ชื่อผู้ใช้", scale=1)
            password_box = gr.Textbox(label="รหัสผ่าน", type="password", scale=1)
        with gr.Row():
            login_btn = gr.Button("เข้าสู่ระบบ", variant="primary", scale=1)
            logout_btn = gr.Button("ออกจากระบบ", scale=1)
        login_status = gr.Markdown(elem_classes="login-status")

    _header_icon = (
        f'<img src="{LOGO_DATA_URI}" alt="กระทรวงสาธารณสุข" />'
        if LOGO_DATA_URI
        else "🏛️"
    )
    gr.HTML(
        f"""
        <div class="oppp-header">
            <div class="icon">{_header_icon}</div>
            <div>
                <h1>ระบบติดตามเงินชดเชย OPPP</h1>
                <p>สรุปยอด PP และ FS ตามหน่วยบริการ HCODE 5 หลัก — ภาพรวมผลการดำเนินงานสะสม</p>
            </div>
        </div>
        """
    )

    updated_badge = gr.Markdown("กำลังโหลดข้อมูล...")

    with gr.Row(elem_classes="kpi-row"):
        with gr.Group(elem_classes="kpi-card"):
            kpi_total = gr.Textbox(label="💰 ยอดชดเชยสะสมทั้งหมด", interactive=False)
        with gr.Group(elem_classes="kpi-card"):
            kpi_pp = gr.Textbox(label="💵 ยอด PP สะสม", interactive=False)
        with gr.Group(elem_classes="kpi-card"):
            kpi_fs = gr.Textbox(label="🩺 ยอด FS สะสม", interactive=False)
    with gr.Row(elem_classes="kpi-row"):
        with gr.Group(elem_classes="kpi-card gold"):
            kpi_count = gr.Textbox(label="🧾 จำนวนรายการสะสม", interactive=False)
        with gr.Group(elem_classes="kpi-card gold"):
            kpi_hcode = gr.Textbox(label="🏥 จำนวนหน่วยบริการ", interactive=False)
        with gr.Group(elem_classes="kpi-card gold"):
            kpi_latest = gr.Textbox(label="📅 รอบข้อมูลล่าสุด", interactive=False)

    with gr.Group(elem_classes="card"):
        gr.Markdown("### 🏆 อันดับหน่วยบริการตามยอดชดเชย (Top 10)", elem_classes="section-title")
        top_hcode_plot = gr.BarPlot(
            value=pd.DataFrame(columns=RANKING_COLUMNS),
            x="HCODE", y="ยอดรวม",
            title=None, height=280, show_label=False,
        )

    with gr.Group(elem_classes="card"):
        gr.Markdown("### 📊 สรุปยอดชดเชยรายหน่วยบริการ (ทั้งหมด)", elem_classes="section-title")
        gr.Markdown("คลิกแถวหน่วยบริการเพื่อดูรายละเอียดบริการด้านล่าง", elem_classes="hint-text")
        ranking_table = gr.Dataframe(value=pd.DataFrame(columns=RANKING_COLUMNS), interactive=False, wrap=True)
        ranking_excel_btn = gr.Button("📥 ดาวน์โหลด Excel")
        ranking_excel_file = gr.File(label="ไฟล์ Excel", visible=True)

    with gr.Group(elem_classes="card"):
        breakdown_label = gr.Markdown("### 🔍 รายละเอียดบริการ\nคลิกแถวในตารางด้านบนเพื่อดูรายละเอียดบริการของหน่วยนั้น")
        breakdown_table = gr.Dataframe(value=pd.DataFrame(columns=BREAKDOWN_COLUMNS), interactive=False)

    refresh_timer = gr.Timer(30)

    dashboard_outputs = [
        kpi_total, kpi_pp, kpi_fs, kpi_count, kpi_hcode, kpi_latest,
        top_hcode_plot, ranking_table, updated_badge,
    ]

    # -----------------------------------------------------------------
    # Developer console (hidden until admin login)
    # -----------------------------------------------------------------
    with gr.Group(visible=False) as admin_section:
        gr.Markdown("## 🛠️ หน้าผู้ดูแลระบบ / Developer")

        with gr.Group(elem_classes="card dev-card"):
            gr.Markdown("### 📤 อัปโหลดรายงานเดือนใหม่", elem_classes="section-title")
            files = gr.File(label="ไฟล์รายงาน OPPP (.xls) — เลือกได้หลายไฟล์", file_count="multiple", file_types=[".xls"], type="filepath")
            uploader_name = gr.Textbox(label="ผู้บันทึก", placeholder="ชื่อผู้อัปโหลด")
            run = gr.Button("⚙️ ประมวลผลและบันทึกลงฐานข้อมูล", variant="primary")
            gr.Markdown(
                "⚠️ อัปโหลดไฟล์ของรอบใหม่ได้เรื่อยๆ ระบบจะรวมกับข้อมูลเดิมอัตโนมัติ และข้ามรายการที่ซ้ำกับที่มีอยู่แล้วให้เอง",
                elem_classes="hint-text",
            )
            upload_status = gr.Markdown()

        with gr.Group(elem_classes="card dev-card"):
            gr.Markdown("### 🕒 ประวัติการอัปโหลด (ย้อนกลับได้หากอัปผิดไฟล์)", elem_classes="section-title")
            batch_table = gr.Dataframe(interactive=False)
            batch_dropdown = gr.Dropdown(label="เลือกไฟล์ที่ต้องการย้อนกลับ/กู้คืน", choices=[])
            with gr.Row():
                rollback_btn = gr.Button("↩️ ย้อนกลับไฟล์นี้")
                restore_btn = gr.Button("♻️ กู้คืนไฟล์นี้")
            batch_status = gr.Markdown()

        with gr.Tab("🧑‍⚕️ ตรวจสอบรายบุคคล"):
            people_table = gr.Dataframe(interactive=False, wrap=True)
            people_excel_btn = gr.Button("📥 ดาวน์โหลด Excel")
            people_excel_file = gr.File(label="ไฟล์ Excel")

        with gr.Tab("🗂️ ข้อมูลต้นทาง"):
            raw_table = gr.Dataframe(interactive=False, wrap=True)
            raw_download = gr.File(label="ดาวน์โหลด CSV ข้อมูลตรวจแล้ว")
            raw_excel_btn = gr.Button("📥 ดาวน์โหลด Excel")
            raw_excel_file = gr.File(label="ไฟล์ Excel")

        with gr.Tab("📊 วิเคราะห์รายบริการ"):
            gr.Markdown(
                "เลือกหน่วยบริการเพื่อไล่ดูทีละขั้น: 1) รายชื่อผู้รับบริการ 2) คาดการณ์บริการรายคน "
                "(รวมหลายรายการเข้าด้วยกันจนตรงยอด) 3) สรุปจำนวนรายการทั้ง 9 รายการของหน่วยนี้ "
                "4) เทียบยอดที่สปสช.ชดเชยเต็มอัตรา กับยอดที่ได้รับจัดสรรจริงตามข้อตกลงจังหวัด "
                "— คาดการณ์แยก PP และ FS ต่างหากจากกัน เพราะรายการอ้างอิงเป็น PP Fee เป็นหลัก",
                elem_classes="hint-text",
            )
            facility_dropdown = gr.Dropdown(
                label="เลือกหน่วยบริการ",
                choices=[hcode_label(code) for code in sorted(HCODE_NAMES)],
            )

            gr.Markdown("#### 1️⃣ รายชื่อผู้รับบริการ", elem_classes="section-title")
            facility_people_table = gr.Dataframe(interactive=False, wrap=True)

            gr.Markdown("#### 2️⃣ คาดการณ์บริการรายรายการ", elem_classes="section-title")
            facility_prediction_table = gr.Dataframe(interactive=False, wrap=True)

            gr.Markdown("#### 3️⃣ สรุปจำนวนรายการ (9 รายการ)", elem_classes="section-title")
            facility_count_table = gr.Dataframe(interactive=False, wrap=True)

            gr.Markdown("#### 4️⃣ เปรียบเทียบยอดสปสช. vs ยอดจัดสรรจริง", elem_classes="section-title")
            facility_reconcile_table = gr.Dataframe(interactive=False, wrap=True)

            facility_excel_btn = gr.Button("📥 ดาวน์โหลด Excel (ทุกตารางในหน้านี้)")
            facility_excel_file = gr.File(label="ไฟล์ Excel")

        with gr.Tab("📋 สรุปทุกหน่วยบริการ"):
            gr.Markdown(
                "ตารางสรุปทุกหน่วยบริการพร้อมกันในหน้าเดียว — แทนที่สเปรดชีตที่เจ้าหน้าที่ต้องนั่งกรอกเอง "
                "แต่ละรายการมี 2 คอลัมน์ (ครั้ง / บาท ตามอัตราเต็มสปสช.) นับเฉพาะรายการที่คาดการณ์ชัดเจน (🟢 หรือ 🟠 ใกล้เคียง) "
                "ส่วนที่ยังไม่แน่ชัดหรือไม่พบจะรวมอยู่ใน 'ยอดที่ยังไม่จัดประเภท' ท้ายตาราง — กดคำนวณใหม่หลังอัปโหลดข้อมูลเพิ่ม "
                "หัวคอลัมน์ใช้รหัสย่อ ดูความหมายได้จากคำอธิบายด้านล่าง",
                elem_classes="hint-text",
            )
            summary_refresh_btn = gr.Button("🔄 คำนวณสรุปทุกหน่วยบริการ", variant="primary")
            summary_status = gr.Markdown()
            all_facilities_table = gr.Dataframe(interactive=False, wrap=False, min_width=90)
            summary_legend = gr.Markdown(service_analysis.build_item_legend(), elem_classes="hint-text")
            summary_excel_btn = gr.Button("📥 ดาวน์โหลด Excel")
            summary_excel_file = gr.File(label="ไฟล์ Excel")

        with gr.Tab("🧮 จัดสรรบริการ"):
            gr.Markdown(
                "จัดสรรยอด PP/FS ของรายการที่ไม่แจกแจงบริการ เช่น ตรวจหลังคลอด, ตรวจฟัน "
                "— คอลัมน์ 'คาดการณ์บริการ' ในตารางยอดคงเหลือด้านล่างช่วยเดารายการจากยอดเงินคงเหลือ "
                "โดยจับคู่กับอัตราตามข้อตกลงจังหวัด (🟢 ตรงรายการเดียว 🟡 ตรงได้หลายรายการ 🔴 ไม่พบ) "
                "เป็นเพียงข้อเสนอแนะ ผู้บันทึกต้องตรวจสอบก่อนกรอกจริงเสมอ",
                elem_classes="hint-text",
            )
            code_dropdown = gr.Dropdown(label="รหัสรายการ (HCODE | ชื่อ | PP/FS ตั้งต้น)", choices=[])
            with gr.Row():
                money_type_radio = gr.Radio(["PP", "FS"], label="ประเภทเงิน", value="PP")
                service_box = gr.Textbox(label="บริการ", placeholder="เช่น ตรวจหลังคลอด")
                amount_box = gr.Number(label="จำนวนเงิน", precision=2)
            with gr.Row():
                note_box = gr.Textbox(label="หมายเหตุ")
                recorder_box = gr.Textbox(label="ผู้บันทึก")
            add_btn = gr.Button("➕ เพิ่มรายการจัดสรร", variant="primary")
            allocation_status = gr.Markdown(elem_classes="login-status")
            allocation_table = gr.Dataframe(label="สมุดจัดสรรบริการ", interactive=False, wrap=True)
            remaining_table = gr.Dataframe(label="ยอดคงเหลือต่อรายการ", interactive=False, wrap=True)
            ledger_export_btn = gr.Button("ดาวน์โหลดสมุดจัดสรร (CSV)")
            ledger_download = gr.File(label="ไฟล์สมุดจัดสรร")
            allocation_excel_btn = gr.Button("📥 ดาวน์โหลด Excel (สมุดจัดสรร + ยอดคงเหลือ)")
            allocation_excel_file = gr.File(label="ไฟล์ Excel")

    admin_view_outputs = [people_table, raw_table, raw_download, allocation_table, code_dropdown, remaining_table]

    # -----------------------------------------------------------------
    # Wiring
    # -----------------------------------------------------------------

    demo.load(refresh_dashboard, outputs=dashboard_outputs).then(
        refresh_batches, outputs=[batch_table, batch_dropdown, batch_status]
    )
    refresh_timer.tick(refresh_dashboard, outputs=dashboard_outputs)

    ranking_table.select(on_select_facility, outputs=[breakdown_label, breakdown_table])

    facility_dropdown.change(
        analyze_facility_ui,
        inputs=facility_dropdown,
        outputs=[facility_people_table, facility_prediction_table, facility_count_table, facility_reconcile_table],
    )

    summary_refresh_btn.click(
        build_all_facilities_summary,
        outputs=[all_facilities_table, summary_status],
    )

    login_btn.click(login, inputs=[username_box, password_box], outputs=[role_state, login_status]).then(
        toggle_admin, inputs=role_state, outputs=admin_section
    ).then(
        refresh_admin_views, inputs=role_state, outputs=admin_view_outputs
    ).then(
        refresh_batches, outputs=[batch_table, batch_dropdown, batch_status]
    ).then(lambda: "", outputs=password_box)

    logout_btn.click(logout, outputs=[role_state, login_status]).then(
        toggle_admin, inputs=role_state, outputs=admin_section
    )

    run.click(
        process_upload, inputs=[files, uploader_name], outputs=upload_status
    ).then(
        refresh_dashboard, outputs=dashboard_outputs
    ).then(
        refresh_batches, outputs=[batch_table, batch_dropdown, batch_status]
    ).then(
        refresh_admin_views, inputs=role_state, outputs=admin_view_outputs
    )

    rollback_btn.click(rollback_selected, inputs=batch_dropdown, outputs=batch_status).then(
        refresh_batches, outputs=[batch_table, batch_dropdown, batch_status]
    ).then(refresh_dashboard, outputs=dashboard_outputs).then(
        refresh_admin_views, inputs=role_state, outputs=admin_view_outputs
    )

    restore_btn.click(restore_selected, inputs=batch_dropdown, outputs=batch_status).then(
        refresh_batches, outputs=[batch_table, batch_dropdown, batch_status]
    ).then(refresh_dashboard, outputs=dashboard_outputs).then(
        refresh_admin_views, inputs=role_state, outputs=admin_view_outputs
    )

    add_btn.click(
        add_allocation_db,
        inputs=[role_state, code_dropdown, money_type_radio, service_box, amount_box, note_box, recorder_box],
        outputs=allocation_status,
    ).then(refresh_admin_views, inputs=role_state, outputs=admin_view_outputs)

    ledger_export_btn.click(export_ledger_csv, outputs=ledger_download)

    ranking_excel_btn.click(
        lambda df: export_excel(df, "สรุปยอดชดเชยรายหน่วยบริการ"), inputs=ranking_table, outputs=ranking_excel_file
    )
    people_excel_btn.click(
        lambda df: export_excel(df, "ตรวจสอบรายบุคคล"), inputs=people_table, outputs=people_excel_file
    )
    raw_excel_btn.click(
        lambda df: export_excel(df, "ข้อมูลต้นทาง"), inputs=raw_table, outputs=raw_excel_file
    )
    facility_excel_btn.click(
        lambda a, b, c, d: export_excel_sheets(
            "วิเคราะห์รายบริการ",
            รายชื่อผู้รับบริการ=a, คาดการณ์บริการ=b, สรุปจำนวนรายการ=c, เปรียบเทียบยอด=d,
        ),
        inputs=[facility_people_table, facility_prediction_table, facility_count_table, facility_reconcile_table],
        outputs=facility_excel_file,
    )
    summary_excel_btn.click(
        lambda df: export_excel(df, "สรุปทุกหน่วยบริการ"), inputs=all_facilities_table, outputs=summary_excel_file
    )
    allocation_excel_btn.click(
        lambda a, b: export_excel_sheets("จัดสรรบริการ", สมุดจัดสรรบริการ=a, ยอดคงเหลือต่อรายการ=b),
        inputs=[allocation_table, remaining_table],
        outputs=allocation_excel_file,
    )


if __name__ == "__main__":
    try:
        db.init_db()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] เชื่อมต่อฐานข้อมูลไม่สำเร็จตอนเริ่มระบบ: {exc}")

    demo.launch(
        theme=THEME,
        css=CUSTOM_CSS,
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 7860)),
    )
