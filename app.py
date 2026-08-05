"""OPPP compensation dashboard: public executive view + hidden developer console."""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import datetime

import gradio as gr
import pandas as pd

import db

ADMIN_USERNAME = os.environ.get("OPPP_ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD_HASH = os.environ.get("OPPP_ADMIN_PASSWORD_HASH", "").strip().lower()

NAVY = gr.themes.Color(
    name="navy",
    c50="#eaf0f7", c100="#cdddec", c200="#a3c1db", c300="#6f9bc4",
    c400="#3f74a6", c500="#1f4e79", c600="#153a5c", c700="#102c46",
    c800="#0b2036", c900="#081727", c950="#050f1a",
)
GOLD = gr.themes.Color(
    name="gold",
    c50="#fbf7ec", c100="#f3e8c8", c200="#e8d296", c300="#d9b968",
    c400="#c9a24a", c500="#b8912f", c600="#9a7825", c700="#7a5f1e",
    c800="#5c4818", c900="#403212", c950="#26200b",
)

THEME = gr.themes.Soft(
    primary_hue=NAVY,
    secondary_hue=GOLD,
    neutral_hue="slate",
    font=[gr.themes.GoogleFont("Sarabun"), gr.themes.GoogleFont("Noto Sans Thai"), "sans-serif"],
)

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700;800&family=Noto+Sans+Thai:wght@400;500;600;700&display=swap');

:root, .dark, .gradio-container.dark {
    --oppp-navy: #0d2c4e;
    --oppp-navy-dark: #081b31;
    --oppp-navy-light: #1f4e79;
    --oppp-gold: #b8912f;
    --oppp-bg: #eef1f5;
    --oppp-surface: #ffffff;
    --oppp-border: #d7dde4;
    --oppp-text: #14213a;
    --oppp-text-dim: #5b677c;
    --oppp-shadow: 0 1px 3px rgba(13, 44, 78, 0.08), 0 1px 2px rgba(13, 44, 78, 0.06);
}

/* Force the light navy/white look regardless of the visitor's OS/browser
   dark-mode preference -- Gradio's built-in dark skin otherwise overrides
   input/textarea backgrounds independently of the vars above. */
.gradio-container, .gradio-container * {
    font-family: 'Sarabun', 'Noto Sans Thai', sans-serif !important;
}
.gradio-container, .gradio-container.dark {
    background: var(--oppp-bg) !important;
    color-scheme: light !important;
}
.gradio-container input,
.gradio-container textarea,
.gradio-container select,
.gradio-container .block,
.gradio-container .form,
.gradio-container .wrap {
    background: var(--oppp-surface);
    color: var(--oppp-text);
}

/* ---------- Header ---------- */
.oppp-header {
    position: relative;
    display: flex;
    align-items: center;
    gap: 18px;
    background: linear-gradient(180deg, var(--oppp-navy) 0%, var(--oppp-navy-dark) 100%);
    color: #ffffff;
    padding: 26px 32px;
    border-radius: 6px;
    margin-bottom: 22px;
    border-bottom: 4px solid var(--oppp-gold);
    box-shadow: var(--oppp-shadow);
}
.oppp-header .icon {
    font-size: 2.2rem;
    line-height: 1;
    width: 56px; height: 56px;
    display: flex; align-items: center; justify-content: center;
    background: rgba(255, 255, 255, 0.10);
    border-radius: 50%;
    border: 1px solid rgba(255,255,255,0.35);
    flex-shrink: 0;
}
.oppp-header h1 {
    margin: 0; font-size: 1.45rem; font-weight: 700; letter-spacing: 0.2px;
}
.oppp-header p { margin: 4px 0 0; opacity: 0.85; font-size: 0.85rem; }
.oppp-header .badge {
    margin-left: auto;
    text-align: right;
    font-size: 0.78rem;
    opacity: 0.9;
    line-height: 1.5;
}

/* ---------- Section titles ---------- */
.section-title h3 {
    display: inline-flex;
    align-items: center;
    font-size: 1rem !important;
    font-weight: 700 !important;
    color: var(--oppp-navy) !important;
    padding-bottom: 8px !important;
    margin-bottom: 12px !important;
    border-bottom: 2px solid var(--oppp-gold) !important;
}

/* ---------- Cards ---------- */
.card {
    background: var(--oppp-surface) !important;
    border: 1px solid var(--oppp-border) !important;
    border-top: 3px solid var(--oppp-navy) !important;
    border-radius: 8px !important;
    padding: 20px 22px !important;
    box-shadow: var(--oppp-shadow);
    margin-bottom: 18px !important;
}
.dev-card { border-top: 3px solid var(--oppp-gold) !important; }

/* ---------- KPI cards ---------- */
.kpi-row { gap: 16px !important; margin-bottom: 16px !important; }
.kpi-card {
    position: relative;
    border-radius: 8px !important;
    padding: 8px 16px !important;
    background: var(--oppp-surface) !important;
    border: 1px solid var(--oppp-border) !important;
    border-left: 4px solid var(--oppp-navy) !important;
    box-shadow: var(--oppp-shadow);
}
.kpi-card.gold { border-left: 4px solid var(--oppp-gold) !important; }
.kpi-card label span { color: var(--oppp-text-dim) !important; font-weight: 600 !important; }
.kpi-card .wrap, .kpi-card .block, .kpi-card .form {
    background: transparent !important;
}
.kpi-card textarea, .kpi-card input {
    font-size: 1.35rem !important;
    font-weight: 700 !important;
    color: var(--oppp-navy) !important;
    background: transparent !important;
    -webkit-text-fill-color: var(--oppp-navy) !important;
}

/* ---------- Misc ---------- */
.admin-toggle { max-width: 340px; margin: 0 0 10px auto !important; }
.admin-toggle .label-wrap {
    background: var(--oppp-surface) !important;
    border: 1px solid var(--oppp-border) !important;
    border-radius: 6px !important;
}
.admin-toggle .label-wrap span { font-size: 0.8rem !important; color: var(--oppp-text-dim) !important; }

.login-status { font-weight: 600 !important; font-size: 0.85rem !important; }
.hint-text { color: var(--oppp-navy-light) !important; font-size: 0.85rem !important; }
.footer-note { text-align: center !important; color: var(--oppp-text-dim) !important; font-size: 0.8rem !important; margin-top: 18px !important; opacity: 0.8; }

/* Buttons */
button.primary, .gr-button-primary {
    background: var(--oppp-navy) !important;
    border: none !important;
    box-shadow: var(--oppp-shadow) !important;
}
button.primary:hover, .gr-button-primary:hover {
    background: var(--oppp-navy-light) !important;
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

TREND_COLUMNS = ["รอบรายงาน", "PP", "FS", "ยอดรวม"]
RANKING_COLUMNS = ["HCODE", "รายการ", "PP", "FS", "ยอดรวม"]


def refresh_dashboard():
    try:
        totals = db.get_overall_totals()
        trend = db.get_monthly_trend()
        ranking = db.get_summary_by_hcode()
        error = None
    except Exception as exc:  # noqa: BLE001 - surface any DB issue to the UI instead of crashing
        totals = {}
        trend = pd.DataFrame(columns=TREND_COLUMNS)
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
        trend,
        top10,
        ranking,
        updated,
    )


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

    gr.HTML(
        """
        <div class="oppp-header">
            <div class="icon">🏛️</div>
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
        gr.Markdown("### 📈 แนวโน้มยอดชดเชยรายรอบ", elem_classes="section-title")
        trend_plot = gr.LinePlot(
            value=pd.DataFrame(columns=TREND_COLUMNS),
            x="รอบรายงาน", y="ยอดรวม",
            title=None, height=280, show_label=False,
        )

    with gr.Group(elem_classes="card"):
        gr.Markdown("### 🏆 อันดับหน่วยบริการตามยอดชดเชย (Top 10)", elem_classes="section-title")
        top_hcode_plot = gr.BarPlot(
            value=pd.DataFrame(columns=RANKING_COLUMNS),
            x="HCODE", y="ยอดรวม",
            title=None, height=280, show_label=False,
        )

    with gr.Group(elem_classes="card"):
        gr.Markdown("### 📊 สรุปยอดชดเชยรายหน่วยบริการ (ทั้งหมด)", elem_classes="section-title")
        ranking_table = gr.Dataframe(value=pd.DataFrame(columns=RANKING_COLUMNS), interactive=False)

    refresh_timer = gr.Timer(30)

    dashboard_outputs = [
        kpi_total, kpi_pp, kpi_fs, kpi_count, kpi_hcode, kpi_latest,
        trend_plot, top_hcode_plot, ranking_table, updated_badge,
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
            people_table = gr.Dataframe(interactive=False)

        with gr.Tab("🗂️ ข้อมูลต้นทาง"):
            raw_table = gr.Dataframe(interactive=False)
            raw_download = gr.File(label="ดาวน์โหลด CSV ข้อมูลตรวจแล้ว")

        with gr.Tab("🧮 จัดสรรบริการ"):
            gr.Markdown("จัดสรรยอด PP/FS ของรายการที่ไม่แจกแจงบริการ เช่น ตรวจหลังคลอด, ตรวจฟัน")
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
            allocation_table = gr.Dataframe(label="สมุดจัดสรรบริการ", interactive=False)
            remaining_table = gr.Dataframe(label="ยอดคงเหลือต่อรายการ", interactive=False)
            ledger_export_btn = gr.Button("ดาวน์โหลดสมุดจัดสรร (CSV)")
            ledger_download = gr.File(label="ไฟล์สมุดจัดสรร")

    admin_view_outputs = [people_table, raw_table, raw_download, allocation_table, code_dropdown, remaining_table]

    # -----------------------------------------------------------------
    # Wiring
    # -----------------------------------------------------------------

    demo.load(refresh_dashboard, outputs=dashboard_outputs).then(
        refresh_batches, outputs=[batch_table, batch_dropdown, batch_status]
    )
    refresh_timer.tick(refresh_dashboard, outputs=dashboard_outputs)

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
