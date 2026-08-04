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
    return message, "-", "-", "-", "-", empty, empty, empty, None, None


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
    people = records.groupby(["รอบรายงาน", "HCODE", "PID", "ชื่อ-นามสกุล"], as_index=False).agg(รายการ=("รหัสรายการ", "size"), PP=("PP", "sum"), FS=("FS", "sum"), ยอดรวม=("ยอดรวม", "sum")).sort_values("ยอดรวม", ascending=False)
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
        people,
        records[DISPLAY_COLUMNS].sort_values(["รอบรายงาน", "HCODE", "ชื่อ-นามสกุล"]),
        export_csv(summary, "สรุปยอดตาม_HCODE"),
        export_csv(records, "ข้อมูล_OPPP_ตรวจแล้ว"),
    )


with gr.Blocks(title="OPPP Compensation Dashboard") as demo:
    gr.Markdown("# 💰 OPPP Compensation Dashboard\nสรุปยอด PP และ FS ตามหน่วยบริการ HCODE 5 หลัก")
    with gr.Row():
        files = gr.File(label="อัปโหลดรายงาน OPPP (.xls)", file_count="multiple", file_types=[".xls"], type="filepath")
        run = gr.Button("ประมวลผลรายงาน", variant="primary")
    gr.Markdown("อัปโหลดเฉพาะไฟล์ของรอบที่ต้องการสรุป และอย่าใส่ชุด ‘รวมทุกเดือน’ ร่วมกับไฟล์รายเดือนเดียวกัน")
    status = gr.Markdown()
    with gr.Row():
        pp_total = gr.Textbox(label="ยอด PP", interactive=False)
        fs_total = gr.Textbox(label="ยอด FS", interactive=False)
        all_total = gr.Textbox(label="ยอดรวม", interactive=False)
        count_total = gr.Textbox(label="จำนวนรายการ", interactive=False)
    with gr.Tab("สรุปตาม HCODE"):
        summary_table = gr.Dataframe(label="ยอดชดเชยรายหน่วยบริการ", interactive=False)
        summary_download = gr.File(label="ดาวน์โหลด CSV สรุป HCODE")
    with gr.Tab("ตรวจสอบรายบุคคล"):
        people_table = gr.Dataframe(label="ยอดรวมรายบุคคล", interactive=False)
        gr.Markdown("ระบบ Login และการซ่อนข้อมูลส่วนบุคคลจะเพิ่มในขั้นถัดไปก่อนเปิด Space เป็นสาธารณะ")
    with gr.Tab("ข้อมูลต้นทาง"):
        raw_table = gr.Dataframe(label="ข้อมูลหลังกันซ้ำ", interactive=False)
        raw_download = gr.File(label="ดาวน์โหลด CSV ข้อมูลตรวจแล้ว")

    run.click(process_reports, inputs=files, outputs=[status, pp_total, fs_total, all_total, count_total, summary_table, people_table, raw_table, summary_download, raw_download])


if __name__ == "__main__":
    demo.launch()
