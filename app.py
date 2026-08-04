"""OPPP compensation dashboard.

Run locally: streamlit run app.py
"""
from __future__ import annotations

import hashlib
import re
from io import BytesIO

import pandas as pd
import streamlit as st


st.set_page_config(page_title="OPPP Dashboard", page_icon="💰", layout="wide")


def text_value(value: object) -> str:
    """Normalize Excel identifiers without losing leading zeroes."""
    if pd.isna(value):
        return ""
    value = str(value).strip()
    return re.sub(r"\.0$", "", value)


def hcode_value(value: object) -> str:
    value = text_value(value)
    return value.zfill(5) if value.isdigit() else value


def money_value(value: object) -> float:
    number = pd.to_numeric(value, errors="coerce")
    return 0.0 if pd.isna(number) else float(number)


def col_at(header: pd.Series, label: str) -> int:
    matches = [i for i, value in enumerate(header) if text_value(value) == label]
    if not matches:
        raise ValueError(f"ไม่พบคอลัมน์ {label}")
    return matches[0]


def parse_report(raw: bytes, filename: str) -> pd.DataFrame:
    sheet = pd.read_excel(BytesIO(raw), header=None, dtype=object)
    header_mask = sheet.apply(lambda row: row.map(text_value).eq("HCODE").any(), axis=1)
    header_rows = header_mask[header_mask].index
    if len(header_rows) == 0:
        raise ValueError("ไม่พบแถวหัวตารางที่มีคำว่า HCODE")

    header_row = int(header_rows[0])
    # The report uses a two-level header: identifiers are on the row above,
    # while HCODE / PP / FS are on this row.
    header = sheet.iloc[header_row].where(sheet.iloc[header_row].notna(), sheet.iloc[header_row - 1])
    fields = {name: col_at(header, name) for name in ["TRAN_ID", "PID", "ชื่อ-นามสกุล", "HCODE", "PP", "FS"]}
    optional = {name: col_at(header, name) for name in ["วันเข้ารักษา"] if name in set(header.map(text_value))}

    data = sheet.iloc[header_row + 2 :].copy()
    result = pd.DataFrame(
        {
            "TRAN_ID": data.iloc[:, fields["TRAN_ID"]].map(text_value),
            "PID": data.iloc[:, fields["PID"]].map(text_value),
            "ชื่อ-นามสกุล": data.iloc[:, fields["ชื่อ-นามสกุล"]].map(text_value),
            "HCODE": data.iloc[:, fields["HCODE"]].map(hcode_value),
            "PP": data.iloc[:, fields["PP"]].map(money_value),
            "FS": data.iloc[:, fields["FS"]].map(money_value),
        }
    )
    result["วันเข้ารักษา"] = (
        pd.to_datetime(data.iloc[:, optional["วันเข้ารักษา"]], errors="coerce").dt.date.astype("string")
        if "วันเข้ารักษา" in optional
        else ""
    )
    result = result[(result["HCODE"] != "") & (result["HCODE"].str.lower() != "hcode")].copy()
    result["ไฟล์ต้นทาง"] = filename
    code = re.search(r"(\d{4})_OP_\d{2}", filename)
    result["รอบรายงาน"] = code.group(1) if code else filename
    result["ยอดรวม"] = result["PP"] + result["FS"]
    result["รหัสรายการ"] = result.apply(
        lambda row: hashlib.sha256(
            "|".join(str(row[c]) for c in ["รอบรายงาน", "TRAN_ID", "PID", "HCODE", "วันเข้ารักษา", "PP", "FS"]).encode()
        ).hexdigest()[:16],
        axis=1,
    )
    return result


def load_allocations(file) -> pd.DataFrame:
    fields = ["รหัสรายการ", "ประเภทเงิน", "บริการ", "จำนวนเงิน", "หมายเหตุ"]
    if file is None:
        return pd.DataFrame(columns=fields)
    allocation = pd.read_csv(file, dtype={"รหัสรายการ": str})
    missing = set(fields) - set(allocation.columns)
    if missing:
        raise ValueError("ไฟล์การจัดสรรขาดคอลัมน์: " + ", ".join(sorted(missing)))
    return allocation[fields]


st.title("💰 OPPP Compensation Dashboard")
st.caption("สรุปยอด PP และ FS ตามหน่วยบริการ (HCODE 5 หลัก) พร้อมตรวจสอบและจัดสรรยอดรายบุคคล")

with st.sidebar:
    reports = st.file_uploader("อัปโหลดรายงาน OPPP (.xls)", type=["xls"], accept_multiple_files=True)
    allocation_file = st.file_uploader("ไฟล์การจัดสรรเดิม (.csv) — ถ้ามี", type=["csv"])
    st.info("อัปโหลดเฉพาะไฟล์ของรอบที่ต้องการสรุป และอย่าอัปโหลดชุด ‘รวมทุกเดือน’ พร้อมไฟล์รายเดือนเดียวกัน เพราะอาจเป็นข้อมูลซ้ำ")

if not reports:
    st.warning("เลือกไฟล์รายงานอย่างน้อย 1 ไฟล์จากแถบด้านซ้ายเพื่อเริ่มต้น")
    st.stop()

parsed, errors = [], []
for report in reports:
    try:
        parsed.append(parse_report(report.getvalue(), report.name))
    except Exception as exc:
        errors.append(f"{report.name}: {exc}")

if errors:
    st.error("อ่านบางไฟล์ไม่สำเร็จ\n\n" + "\n".join(f"- {error}" for error in errors))
if not parsed:
    st.stop()

records = pd.concat(parsed, ignore_index=True)
duplicate_mask = records.duplicated("รหัสรายการ", keep="first")
duplicate_count = int(duplicate_mask.sum())
records = records.loc[~duplicate_mask].copy()

try:
    allocations = load_allocations(allocation_file)
except Exception as exc:
    st.error(f"อ่านไฟล์การจัดสรรไม่สำเร็จ: {exc}")
    allocations = load_allocations(None)

if "allocations" not in st.session_state or allocation_file is not None:
    st.session_state.allocations = allocations

if duplicate_count:
    st.warning(f"ตัดรายการซ้ำแบบตรงกันทุกช่องออกแล้ว {duplicate_count:,} รายการ (ใช้ TRAN_ID, PID, HCODE, วันรับบริการ, PP และ FS ตรวจ)")

total_pp, total_fs = records["PP"].sum(), records["FS"].sum()
one, two, three, four = st.columns(4)
one.metric("ยอด PP", f"{total_pp:,.2f} บาท")
two.metric("ยอด FS", f"{total_fs:,.2f} บาท")
three.metric("ยอดรวม", f"{total_pp + total_fs:,.2f} บาท")
four.metric("รายการหลังกันซ้ำ", f"{len(records):,}")

tab_summary, tab_person, tab_allocate, tab_data = st.tabs(["สรุปตาม HCODE", "ตรวจสอบรายบุคคล", "จัดสรรบริการ", "ข้อมูลต้นทาง"])

with tab_summary:
    summary = records.groupby("HCODE", as_index=False).agg(รายการ=("รหัสรายการ", "size"), PP=("PP", "sum"), FS=("FS", "sum"), ยอดรวม=("ยอดรวม", "sum"))
    summary = summary.sort_values(["ยอดรวม", "HCODE"], ascending=[False, True])
    st.dataframe(summary, use_container_width=True, hide_index=True, column_config={"PP": st.column_config.NumberColumn(format="%.2f"), "FS": st.column_config.NumberColumn(format="%.2f"), "ยอดรวม": st.column_config.NumberColumn(format="%.2f")})
    st.download_button("ดาวน์โหลดสรุป HCODE (CSV)", summary.to_csv(index=False).encode("utf-8-sig"), "สรุปยอดตาม_HCODE.csv", "text/csv")

with tab_person:
    person = records.groupby(["รอบรายงาน", "HCODE", "PID", "ชื่อ-นามสกุล"], dropna=False, as_index=False).agg(รายการ=("รหัสรายการ", "size"), PP=("PP", "sum"), FS=("FS", "sum"), ยอดรวม=("ยอดรวม", "sum"))
    query = st.text_input("ค้นหา HCODE / PID / ชื่อ")
    if query:
        match = person.astype(str).apply(lambda col: col.str.contains(query, case=False, na=False)).any(axis=1)
        person = person[match]
    st.dataframe(person.sort_values("ยอดรวม", ascending=False), use_container_width=True, hide_index=True)

with tab_allocate:
    st.write("บันทึกการแจกแจงยอดทีละรายการ เช่น ตรวจหลังคลอดหรือทันตกรรม โดยเลือกประเภทเงิน PP หรือ FS และตรวจยอดคงเหลือก่อนดาวน์โหลดไฟล์")
    options = records.sort_values(["ชื่อ-นามสกุล", "HCODE"])[["รหัสรายการ", "ชื่อ-นามสกุล", "PID", "HCODE", "PP", "FS", "ยอดรวม"]].copy()
    options["label"] = options.apply(lambda row: f"{row['ชื่อ-นามสกุล']} | PID {row['PID']} | HCODE {row['HCODE']} | PP {row['PP']:,.2f} / FS {row['FS']:,.2f}", axis=1)
    label_to_id = dict(zip(options["label"], options["รหัสรายการ"]))
    with st.form("allocation_form", clear_on_submit=True):
        selected = st.selectbox("รายการต้นทาง", options["label"])
        kind = st.selectbox("ประเภทเงิน", ["PP", "FS"])
        service = st.text_input("ชื่อบริการ", placeholder="เช่น ตรวจหลังคลอด")
        amount = st.number_input("จำนวนเงินที่จัดสรร", min_value=0.0, step=1.0, format="%.2f")
        note = st.text_input("หมายเหตุ")
        submitted = st.form_submit_button("เพิ่มรายการจัดสรร")
    if submitted:
        if not service.strip() or amount <= 0:
            st.error("ระบุชื่อบริการและจำนวนเงินที่มากกว่า 0")
        else:
            st.session_state.allocations = pd.concat([st.session_state.allocations, pd.DataFrame([[label_to_id[selected], kind, service.strip(), amount, note]], columns=st.session_state.allocations.columns)], ignore_index=True)
            st.success("เพิ่มรายการจัดสรรแล้ว")

    allocation_view = st.session_state.allocations.copy()
    if not allocation_view.empty:
        allocation_view["จำนวนเงิน"] = pd.to_numeric(allocation_view["จำนวนเงิน"], errors="coerce").fillna(0)
        assigned = allocation_view.pivot_table(index="รหัสรายการ", columns="ประเภทเงิน", values="จำนวนเงิน", aggfunc="sum", fill_value=0).reset_index()
        assigned = assigned.rename(columns={"PP": "PP จัดสรร", "FS": "FS จัดสรร"})
        reconciliation = options[["รหัสรายการ", "ชื่อ-นามสกุล", "PID", "HCODE", "PP", "FS"]].merge(assigned, on="รหัสรายการ", how="left").fillna({"PP จัดสรร": 0, "FS จัดสรร": 0})
        reconciliation["PP คงเหลือ"] = reconciliation["PP"] - reconciliation.get("PP จัดสรร", 0)
        reconciliation["FS คงเหลือ"] = reconciliation["FS"] - reconciliation.get("FS จัดสรร", 0)
        st.dataframe(allocation_view, use_container_width=True, hide_index=True)
        st.dataframe(reconciliation[["ชื่อ-นามสกุล", "PID", "HCODE", "PP คงเหลือ", "FS คงเหลือ"]].query('`PP คงเหลือ` != 0 or `FS คงเหลือ` != 0'), use_container_width=True, hide_index=True)
    st.download_button("ดาวน์โหลดสมุดจัดสรร (CSV)", st.session_state.allocations.to_csv(index=False).encode("utf-8-sig"), "สมุดจัดสรรบริการ.csv", "text/csv")

with tab_data:
    st.dataframe(records.sort_values(["รอบรายงาน", "HCODE", "ชื่อ-นามสกุล"]), use_container_width=True, hide_index=True)
    st.download_button("ดาวน์โหลดข้อมูลที่ผ่านการกันซ้ำ (CSV)", records.to_csv(index=False).encode("utf-8-sig"), "ข้อมูล_OPPP_ตรวจแล้ว.csv", "text/csv")
