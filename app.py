"""OPPP compensation dashboard for Hugging Face Gradio Spaces."""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import datetime

import gradio as gr
import pandas as pd


DISPLAY_COLUMNS = ["รอบรายงาน", "HCODE", "PID", "ชื่อ-นามสกุล", "วันเข้ารักษา", "PP", "FS", "ยอดรวม", "ไฟล์ต้นทาง"]
LEDGER_COLUMNS = ["รหัสรายการ", "ประเภทเงิน", "บริการ", "จำนวนเงิน", "หมายเหตุ", "ผู้บันทึก", "เวลา"]

ADMIN_PASSWORD_HASH = os.environ.get("OPPP_ADMIN_PASSWORD_HASH", "").strip().lower()

THEME = gr.themes.Soft(
    primary_hue="blue",
    secondary_hue="emerald",
    neutral_hue="slate",
    font=[gr.themes.GoogleFont("Sarabun"), "sans-serif"],
)

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@400;500;600;700&display=swap');

.gradio-container, .gradio-container * {
    font-family: 'Sarabun', 'Noto Sans Thai', sans-serif !important;
}
.gradio-container { background: linear-gradient(180deg, #f4f8fb 0%, #eef2f7 100%) !important; }

.oppp-header {
    display: flex;
    align-items: center;
    gap: 16px;
    background: linear-gradient(120deg, #2563eb 0%, #16a34a 100%);
    color: #ffffff;
    padding: 20px 28px;
    border-radius: 16px;
    margin-bottom: 18px;
    box-shadow: 0 8px 24px rgba(37, 99, 235, 0.25);
}
.oppp-header .icon { font-size: 2.4rem; line-height: 1; }
.oppp-header h1 { margin: 0; font-size: 1.5rem; font-weight: 700; color: #ffffff; }
.oppp-header p { margin: 4px 0 0; opacity: 0.92; font-size: 0.95rem; }

.card {
    background: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 14px !important;
    padding: 16px 18px !important;
    box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
    margin-bottom: 14px !important;
}
.login-card { border-left: 4px solid #2563eb !important; }
.allocation-card { border-left: 4px solid #7c3aed !important; }

.hint-text { color: #b45309 !important; font-size: 0.85rem !important; }
.status-line { font-weight: 600 !important; }

.kpi-row { gap: 12px !important; margin-bottom: 16px !important; }
.kpi-card {
    border-radius: 14px !important;
    padding: 6px 10px !important;
    box-shadow: 0 2px 10px rgba(15, 23, 42, 0.05);
    border: 1px solid transparent !important;
}
.kpi-pp { background: #eff6ff !important; border-color: #bfdbfe !important; }
.kpi-fs { background: #ecfdf5 !important; border-color: #a7f3d0 !important; }
.kpi-total { background: #f5f3ff !important; border-color: #ddd6fe !important; }
.kpi-count { background: #fff7ed !important; border-color: #fed7aa !important; }
.kpi-card textarea, .kpi-card input {
    font-size: 1.3rem !important;
    font-weight: 700 !important;
    color: #0f172a !important;
}

.footer-note { text-align: center !important; color: #94a3b8 !important; font-size: 0.8rem !important; margin-top: 12px !important; }
"""


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


def empty_outputs(message: str):
    empty = pd.DataFrame()
    return message, "-", "-", "-", "-", empty, None, None


def process_reports(files: list[str] | None):
    if not files:
        return empty_outputs("กรุณาเลือกไฟล์ .xls อย่างน้อย 1 ไฟล์")
    parsed, errors = [], []
    for path in files:
        try:
            parsed.append(parse_report(path))
        except Exception as exc:
            errors.append(f"{os.path.basename(path)}: {exc}")
    if not parsed:
        return empty_outputs("อ่านไฟล์ไม่สำเร็จ: " + "; ".join(errors))

    records = pd.concat(parsed, ignore_index=True)
    duplicate_count = int(records.duplicated("รหัสรายการ", keep="first").sum())
    records = records.drop_duplicates("รหัสรายการ", keep="first")
    summary = records.groupby("HCODE", as_index=False).agg(รายการ=("รหัสรายการ", "size"), PP=("PP", "sum"), FS=("FS", "sum"), ยอดรวม=("ยอดรวม", "sum")).sort_values(["ยอดรวม", "HCODE"], ascending=[False, True])
    status = f"อ่านแล้ว {len(records):,} รายการ จาก {len(parsed)} ไฟล์"
    if duplicate_count:
        status += f" · ตัดรายการซ้ำ {duplicate_count:,} รายการ"
    if errors:
        status += " · ไฟล์ที่อ่านไม่สำเร็จ: " + "; ".join(errors)
    return (
        status,
        f"{records['PP'].sum():,.2f} บาท",
        f"{records['FS'].sum():,.2f} บาท",
        f"{records['ยอดรวม'].sum():,.2f} บาท",
        f"{len(records):,}",
        summary,
        export_csv(summary, "สรุปยอดตาม_HCODE"),
        records,
    )


# ---------------------------------------------------------------------------
# Login / role-based access
#
# ผู้ที่ยังไม่เข้าสู่ระบบ (role = "viewer") เห็นเฉพาะยอดสรุปตาม HCODE
# ผู้เข้าสู่ระบบด้วยรหัสผ่านที่ถูกต้อง (role = "admin") จึงจะเห็น PID/ชื่อ/ข้อมูลดิบ/เครื่องมือจัดสรร
# ข้อมูลรายบุคคลจะถูกคำนวณและส่งไปยังฝั่ง client ก็ต่อเมื่อ role เป็น admin เท่านั้น
# เพื่อไม่ให้ข้อมูลหลุดผ่าน DOM ของแท็บที่ถูกซ่อนไว้
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def login(password: str, _role: str):
    if not ADMIN_PASSWORD_HASH:
        return "viewer", "⚠️ ยังไม่ได้ตั้งค่า OPPP_ADMIN_PASSWORD_HASH ใน Hugging Face Secrets จึงเข้าสู่ระบบไม่ได้"
    if password and hash_password(password) == ADMIN_PASSWORD_HASH:
        return "admin", "✅ เข้าสู่ระบบสำเร็จ: เห็นข้อมูลรายบุคคลและเครื่องมือจัดสรร"
    return "viewer", "❌ รหัสผ่านไม่ถูกต้อง: เห็นเฉพาะยอดสรุปตาม HCODE"


def logout():
    return "viewer", "ออกจากระบบแล้ว: เห็นเฉพาะยอดสรุปตาม HCODE"


def render_details(records: pd.DataFrame | None, role: str):
    is_admin = role == "admin"
    code_choices: list[str] = []
    if isinstance(records, pd.DataFrame) and not records.empty and is_admin:
        people = records.groupby(["รอบรายงาน", "HCODE", "PID", "ชื่อ-นามสกุล"], as_index=False).agg(
            รายการ=("รหัสรายการ", "size"), PP=("PP", "sum"), FS=("FS", "sum"), ยอดรวม=("ยอดรวม", "sum")
        ).sort_values("ยอดรวม", ascending=False)
        raw = records[DISPLAY_COLUMNS + ["รหัสรายการ"]].sort_values(["รอบรายงาน", "HCODE", "ชื่อ-นามสกุล"])
        raw_path = export_csv(records, "ข้อมูล_OPPP_ตรวจแล้ว")
        code_choices = [
            f"{row['รหัสรายการ']} | {row['HCODE']} | {row['ชื่อ-นามสกุล']} | PP {row['PP']:.2f} FS {row['FS']:.2f}"
            for _, row in records.sort_values(["รอบรายงาน", "HCODE"]).iterrows()
        ]
    else:
        people, raw, raw_path = pd.DataFrame(), pd.DataFrame(), None

    return (
        people,
        raw,
        raw_path,
        gr.update(visible=is_admin),
        gr.update(visible=is_admin),
        gr.update(visible=is_admin),
        gr.update(choices=code_choices, value=None),
    )


# ---------------------------------------------------------------------------
# Allocation ledger ("จัดสรรบริการ")
# ---------------------------------------------------------------------------


def empty_ledger() -> pd.DataFrame:
    return pd.DataFrame(columns=LEDGER_COLUMNS)


def allocation_summary(records: pd.DataFrame | None, ledger: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(records, pd.DataFrame) or records.empty:
        return pd.DataFrame()
    source = records.melt(
        id_vars=["รหัสรายการ", "HCODE", "PID", "ชื่อ-นามสกุล"],
        value_vars=["PP", "FS"],
        var_name="ประเภทเงิน",
        value_name="ยอดต้นทาง",
    )
    if ledger is None or ledger.empty:
        allocated = pd.DataFrame(columns=["รหัสรายการ", "ประเภทเงิน", "ยอดจัดสรรแล้ว"])
    else:
        allocated = ledger.groupby(["รหัสรายการ", "ประเภทเงิน"], as_index=False)["จำนวนเงิน"].sum().rename(
            columns={"จำนวนเงิน": "ยอดจัดสรรแล้ว"}
        )
    merged = source.merge(allocated, on=["รหัสรายการ", "ประเภทเงิน"], how="left")
    merged["ยอดจัดสรรแล้ว"] = merged["ยอดจัดสรรแล้ว"].fillna(0.0)
    merged["คงเหลือ"] = merged["ยอดต้นทาง"] - merged["ยอดจัดสรรแล้ว"]
    merged = merged[merged["ยอดต้นทาง"] != 0].sort_values(["HCODE", "ชื่อ-นามสกุล", "ประเภทเงิน"])
    return merged


def add_allocation(
    records: pd.DataFrame | None,
    ledger: pd.DataFrame | None,
    code_choice: str | None,
    money_type: str,
    service: str,
    amount: float | None,
    note: str,
    recorder: str,
):
    ledger = ledger if isinstance(ledger, pd.DataFrame) else empty_ledger()
    if not isinstance(records, pd.DataFrame) or records.empty:
        return ledger, pd.DataFrame(), "กรุณาประมวลผลรายงานก่อน", None
    if not code_choice:
        return ledger, allocation_summary(records, ledger), "กรุณาเลือกรหัสรายการที่ต้องการจัดสรร", None
    if not service or not service.strip():
        return ledger, allocation_summary(records, ledger), "กรุณาระบุชื่อบริการ", None
    if not recorder or not recorder.strip():
        return ledger, allocation_summary(records, ledger), "กรุณาระบุผู้บันทึก", None
    if amount is None or amount <= 0:
        return ledger, allocation_summary(records, ledger), "จำนวนเงินต้องมากกว่า 0", None

    code = code_choice.split(" | ", 1)[0].strip()
    row = records.loc[records["รหัสรายการ"] == code]
    if row.empty:
        return ledger, allocation_summary(records, ledger), "ไม่พบรหัสรายการนี้ในรายงานที่ประมวลผลแล้ว", None

    original = float(row.iloc[0][money_type])
    already = 0.0
    if not ledger.empty:
        already = float(
            ledger.loc[(ledger["รหัสรายการ"] == code) & (ledger["ประเภทเงิน"] == money_type), "จำนวนเงิน"].sum()
        )
    remaining = original - already

    new_row = pd.DataFrame(
        [
            {
                "รหัสรายการ": code,
                "ประเภทเงิน": money_type,
                "บริการ": service.strip(),
                "จำนวนเงิน": float(amount),
                "หมายเหตุ": note.strip() if note else "",
                "ผู้บันทึก": recorder.strip(),
                "เวลา": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ]
    )
    ledger = pd.concat([ledger, new_row], ignore_index=True)

    if amount > remaining:
        message = f"⚠️ บันทึกแล้ว แต่จัดสรรเกินยอดคงเหลือ {remaining:,.2f} บาท (เกินไป {amount - remaining:,.2f} บาท)"
    else:
        message = f"บันทึกการจัดสรรแล้ว คงเหลือหลังจัดสรร {remaining - amount:,.2f} บาท"

    return ledger, allocation_summary(records, ledger), message, export_csv(ledger, "สมุดจัดสรรบริการ")


def export_ledger(ledger: pd.DataFrame | None):
    ledger = ledger if isinstance(ledger, pd.DataFrame) else empty_ledger()
    if ledger.empty:
        return None, "ยังไม่มีรายการจัดสรรให้ดาวน์โหลด"
    return export_csv(ledger, "สมุดจัดสรรบริการ"), f"ดาวน์โหลดสมุดจัดสรร {len(ledger):,} รายการแล้ว"


def import_ledger(path: str | None, records: pd.DataFrame | None):
    if not path:
        return empty_ledger(), pd.DataFrame(), "กรุณาเลือกไฟล์ CSV สมุดจัดสรรที่เคยดาวน์โหลดไว้"
    try:
        loaded = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:
        return empty_ledger(), pd.DataFrame(), f"อ่านไฟล์ไม่สำเร็จ: {exc}"
    missing = [col for col in LEDGER_COLUMNS if col not in loaded.columns]
    if missing:
        return empty_ledger(), pd.DataFrame(), f"ไฟล์นี้ไม่ใช่สมุดจัดสรรบริการ (ขาดคอลัมน์ {', '.join(missing)})"
    loaded = loaded[LEDGER_COLUMNS]
    return loaded, allocation_summary(records, loaded), f"นำเข้าสมุดจัดสรร {len(loaded):,} รายการแล้ว"


with gr.Blocks(title="OPPP Compensation Dashboard") as demo:
    gr.HTML(
        """
        <div class="oppp-header">
            <div class="icon">💰</div>
            <div>
                <h1>OPPP Compensation Dashboard</h1>
                <p>สรุปยอด PP และ FS ตามหน่วยบริการ HCODE 5 หลัก</p>
            </div>
        </div>
        """
    )

    role_state = gr.State("viewer")
    records_state = gr.State(pd.DataFrame())
    ledger_state = gr.State(empty_ledger())

    with gr.Group(elem_classes="card login-card"):
        gr.Markdown("### 🔐 เข้าสู่ระบบผู้ดูแล")
        with gr.Row():
            password_box = gr.Textbox(label="รหัสผ่านผู้ดูแล", type="password", scale=2)
            login_btn = gr.Button("เข้าสู่ระบบ", scale=1, variant="primary")
            logout_btn = gr.Button("ออกจากระบบ", scale=1)
        login_status = gr.Markdown("ยังไม่ได้เข้าสู่ระบบ: เห็นเฉพาะยอดสรุปตาม HCODE", elem_classes="status-line")

    with gr.Group(elem_classes="card"):
        gr.Markdown("### 📤 อัปโหลดรายงาน")
        with gr.Row():
            files = gr.File(label="อัปโหลดรายงาน OPPP (.xls)", file_count="multiple", file_types=[".xls"], type="filepath", scale=3)
            run = gr.Button("⚙️ ประมวลผลรายงาน", variant="primary", scale=1)
        gr.Markdown(
            "⚠️ อัปโหลดเฉพาะไฟล์ของรอบที่ต้องการสรุป และอย่าใส่ชุด 'รวมทุกเดือน' ร่วมกับไฟล์รายเดือนเดียวกัน",
            elem_classes="hint-text",
        )
        status = gr.Markdown()

    with gr.Row(elem_classes="kpi-row"):
        with gr.Group(elem_classes="kpi-card kpi-pp"):
            pp_total = gr.Textbox(label="💵 ยอด PP", interactive=False)
        with gr.Group(elem_classes="kpi-card kpi-fs"):
            fs_total = gr.Textbox(label="🩺 ยอด FS", interactive=False)
        with gr.Group(elem_classes="kpi-card kpi-total"):
            all_total = gr.Textbox(label="📈 ยอดรวม", interactive=False)
        with gr.Group(elem_classes="kpi-card kpi-count"):
            count_total = gr.Textbox(label="🧾 จำนวนรายการ", interactive=False)

    with gr.Tab("📊 สรุปตาม HCODE"):
        summary_table = gr.Dataframe(label="ยอดชดเชยรายหน่วยบริการ", interactive=False)
        summary_download = gr.File(label="ดาวน์โหลด CSV สรุป HCODE")

    with gr.Tab("🧑‍⚕️ ตรวจสอบรายบุคคล", visible=False) as people_tab:
        people_table = gr.Dataframe(label="ยอดรวมรายบุคคล", interactive=False)

    with gr.Tab("🗂️ ข้อมูลต้นทาง", visible=False) as raw_tab:
        raw_table = gr.Dataframe(label="ข้อมูลหลังกันซ้ำ", interactive=False)
        raw_download = gr.File(label="ดาวน์โหลด CSV ข้อมูลตรวจแล้ว")

    with gr.Tab("🧮 จัดสรรบริการ", visible=False) as allocation_tab:
        with gr.Group(elem_classes="card allocation-card"):
            gr.Markdown("### 🧮 จัดสรรบริการ\nจัดสรรยอด PP/FS ของรายการที่ไม่แจกแจงบริการ เช่น ตรวจหลังคลอด, ตรวจฟัน")
            code_dropdown = gr.Dropdown(label="รหัสรายการ (HCODE | ชื่อ | PP/FS ตั้งต้น)", choices=[])
            with gr.Row():
                money_type_radio = gr.Radio(["PP", "FS"], label="ประเภทเงิน", value="PP")
                service_box = gr.Textbox(label="บริการ", placeholder="เช่น ตรวจหลังคลอด")
                amount_box = gr.Number(label="จำนวนเงิน", precision=2)
            with gr.Row():
                note_box = gr.Textbox(label="หมายเหตุ")
                recorder_box = gr.Textbox(label="ผู้บันทึก")
            add_btn = gr.Button("➕ เพิ่มรายการจัดสรร", variant="primary")
            allocation_status = gr.Markdown(elem_classes="status-line")
        allocation_table = gr.Dataframe(label="สมุดจัดสรรบริการ", interactive=False)
        remaining_table = gr.Dataframe(label="ยอดคงเหลือต่อรายการ", interactive=False)
        with gr.Row():
            ledger_download = gr.File(label="ดาวน์โหลดสมุดจัดสรร (CSV)")
            ledger_upload = gr.File(label="นำเข้าสมุดจัดสรรเดิม (CSV)", file_types=[".csv"], type="filepath")
        gr.Markdown(
            "Hugging Face Space ไม่เก็บข้อมูลถาวร กรุณาดาวน์โหลดสมุดจัดสรรหลังทำงานทุกครั้ง แล้วนำเข้ากลับมาในครั้งถัดไป",
            elem_classes="footer-note",
        )

    detail_outputs = [people_table, raw_table, raw_download, people_tab, raw_tab, allocation_tab, code_dropdown]

    run.click(
        process_reports,
        inputs=files,
        outputs=[status, pp_total, fs_total, all_total, count_total, summary_table, summary_download, records_state],
    ).then(render_details, inputs=[records_state, role_state], outputs=detail_outputs)

    login_btn.click(login, inputs=[password_box, role_state], outputs=[role_state, login_status]).then(
        render_details, inputs=[records_state, role_state], outputs=detail_outputs
    ).then(lambda: "", outputs=password_box)

    logout_btn.click(logout, outputs=[role_state, login_status]).then(
        render_details, inputs=[records_state, role_state], outputs=detail_outputs
    )

    add_btn.click(
        add_allocation,
        inputs=[records_state, ledger_state, code_dropdown, money_type_radio, service_box, amount_box, note_box, recorder_box],
        outputs=[ledger_state, remaining_table, allocation_status, ledger_download],
    ).then(lambda ledger: ledger, inputs=ledger_state, outputs=allocation_table)

    ledger_upload.upload(
        import_ledger, inputs=[ledger_upload, records_state], outputs=[ledger_state, remaining_table, allocation_status]
    ).then(lambda ledger: ledger, inputs=ledger_state, outputs=allocation_table)


if __name__ == "__main__":
    demo.launch(theme=THEME, css=CUSTOM_CSS)
