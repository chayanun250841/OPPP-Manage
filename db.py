"""Persistent storage layer for the OPPP dashboard, backed by Supabase Postgres."""
from __future__ import annotations

import os
import uuid

import pandas as pd
import psycopg2
import psycopg2.extras

SCHEMA = """
CREATE TABLE IF NOT EXISTS upload_batches (
    batch_id TEXT PRIMARY KEY,
    report_period TEXT NOT NULL,
    source_file TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    record_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    pp_total NUMERIC NOT NULL DEFAULT 0,
    fs_total NUMERIC NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS records (
    record_code TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES upload_batches(batch_id) ON DELETE CASCADE,
    report_period TEXT NOT NULL,
    tran_id TEXT,
    pid TEXT,
    full_name TEXT,
    hcode TEXT NOT NULL,
    visit_date TEXT,
    pp NUMERIC NOT NULL DEFAULT 0,
    fs NUMERIC NOT NULL DEFAULT 0,
    total NUMERIC NOT NULL DEFAULT 0,
    grand_total NUMERIC NOT NULL DEFAULT 0,
    source_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- grand_total = คอลัมน์สุดท้าย 'ยอดชดเชยทั้งสิ้น' ของแฟ้มต้นทาง (อาจมากกว่า pp+fs
-- เมื่อแถวนั้นได้เงินจากกองทุนอื่นด้วย) เพิ่มทีหลังจึงต้อง ALTER สำหรับฐานเดิม
ALTER TABLE records ADD COLUMN IF NOT EXISTS grand_total NUMERIC NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_records_hcode ON records(hcode);
CREATE INDEX IF NOT EXISTS idx_records_batch ON records(batch_id);
CREATE INDEX IF NOT EXISTS idx_records_period ON records(report_period);
CREATE INDEX IF NOT EXISTS idx_records_tran ON records(tran_id);

CREATE TABLE IF NOT EXISTS allocations (
    id SERIAL PRIMARY KEY,
    record_code TEXT NOT NULL,
    money_type TEXT NOT NULL,
    service TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    note TEXT,
    recorder TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def get_connection():
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("ยังไม่ได้ตั้งค่า DATABASE_URL")
    return psycopg2.connect(dsn)


def init_db() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        conn.commit()


def insert_batch(report_period: str, source_file: str, uploaded_by: str, frame: pd.DataFrame) -> dict:
    """Insert a new upload batch and its records.

    Deduplication is by TRAN_ID across the whole table (any batch, any month) --
    TRAN_ID is the transaction identity in the OPPP report, so the same claim
    appearing in two files must only ever be counted once. `record_code` stays
    the primary key and acts as a second safety net against byte-identical rows.
    """
    batch_id = str(uuid.uuid4())
    submitted = len(frame)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO upload_batches (batch_id, report_period, source_file, uploaded_by, record_count)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (batch_id, report_period, source_file, uploaded_by, submitted),
            )
            tran_ids = [t for t in frame["TRAN_ID"].astype(str).tolist() if t]
            if tran_ids:
                cur.execute("SELECT tran_id FROM records WHERE tran_id = ANY(%s)", (tran_ids,))
                existing = {row[0] for row in cur.fetchall()}
            else:
                existing = set()
            fresh = frame[~frame["TRAN_ID"].astype(str).isin(existing)]

            rows = [
                (
                    row["รหัสรายการ"],
                    batch_id,
                    row["รอบรายงาน"],
                    row["TRAN_ID"],
                    row["PID"],
                    row["ชื่อ-นามสกุล"],
                    row["HCODE"],
                    row["วันเข้ารักษา"],
                    float(row["PP"]),
                    float(row["FS"]),
                    float(row["ยอดรวม"]),
                    float(row["ยอดชดเชยทั้งสิ้น"]),
                    row["ไฟล์ต้นทาง"],
                )
                for _, row in fresh.iterrows()
            ]
            if rows:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO records
                        (record_code, batch_id, report_period, tran_id, pid, full_name, hcode, visit_date, pp, fs, total, grand_total, source_file)
                    VALUES %s
                    ON CONFLICT (record_code) DO NOTHING
                    """,
                    rows,
                )
            cur.execute(
                "SELECT COUNT(*), COALESCE(SUM(pp), 0), COALESCE(SUM(fs), 0) FROM records WHERE batch_id = %s",
                (batch_id,),
            )
            inserted_count, pp_total, fs_total = cur.fetchone()
            duplicate_count = submitted - inserted_count
            cur.execute(
                """
                UPDATE upload_batches
                SET inserted_count = %s, duplicate_count = %s, pp_total = %s, fs_total = %s
                WHERE batch_id = %s
                """,
                (inserted_count, duplicate_count, pp_total, fs_total, batch_id),
            )
        conn.commit()
    return {"batch_id": batch_id, "inserted_count": int(inserted_count), "duplicate_count": int(duplicate_count)}


def list_batches() -> pd.DataFrame:
    query = """
        SELECT
            batch_id AS "รหัสชุดข้อมูล",
            report_period AS "รอบรายงาน",
            source_file AS "ไฟล์ต้นทาง",
            uploaded_by AS "ผู้บันทึก",
            uploaded_at AS "เวลาอัปโหลด",
            inserted_count AS "รายการที่บันทึก",
            duplicate_count AS "รายการซ้ำที่ข้าม",
            pp_total AS "PP",
            fs_total AS "FS",
            status AS "สถานะ"
        FROM upload_batches
        ORDER BY uploaded_at DESC
    """
    with get_connection() as conn:
        return pd.read_sql(query, conn)


def set_batch_status(batch_id: str, status: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE upload_batches SET status = %s WHERE batch_id = %s", (status, batch_id))
        conn.commit()


def reset_all_data() -> dict:
    """ลบข้อมูลทั้งหมดออกจากระบบ กลับไปเป็นฐานว่างเหมือนเพิ่งติดตั้งใหม่

    ต่างจาก rollback ตรงที่ rollback เป็น soft-delete (ข้อมูลยังอยู่ กู้คืนได้)
    แต่ฟังก์ชันนี้ลบจริงทั้ง allocations, records และ upload_batches
    **ย้อนกลับไม่ได้** ผู้เรียกต้องตรวจสิทธิ์ผู้ดูแลระบบและยืนยันรหัสผ่านก่อนเสมอ

    Returns the row counts that were removed, so the UI can report what it did.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            counts = {}
            for table in ("records", "upload_batches", "allocations"):
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = int(cur.fetchone()[0])
            # ตารางเดียวกันหมดในคำสั่งเดียว เพื่อไม่ให้ FK ของ records ขวาง
            cur.execute("TRUNCATE TABLE allocations, records, upload_batches RESTART IDENTITY")
        conn.commit()
    return counts


def get_overall_totals() -> dict:
    query = """
        SELECT
            COALESCE(SUM(r.pp), 0) AS pp,
            COALESCE(SUM(r.fs), 0) AS fs,
            COALESCE(SUM(r.total), 0) AS total,
            COALESCE(SUM(r.grand_total), 0) AS grand_total,
            COUNT(*) AS count,
            COUNT(DISTINCT r.hcode) AS hcode_count,
            COUNT(DISTINCT r.report_period) AS period_count,
            MAX(r.report_period) AS latest_period
        FROM records r
        JOIN upload_batches b ON b.batch_id = r.batch_id
        WHERE b.status = 'active'
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            columns = [desc[0] for desc in cur.description]
            row = cur.fetchone()
    return dict(zip(columns, row))


def get_monthly_trend() -> pd.DataFrame:
    query = """
        SELECT
            r.report_period AS "รอบรายงาน",
            SUM(r.pp) AS "PP",
            SUM(r.fs) AS "FS",
            SUM(r.total) AS "ยอดรวม"
        FROM records r
        JOIN upload_batches b ON b.batch_id = r.batch_id
        WHERE b.status = 'active'
        GROUP BY r.report_period
        ORDER BY r.report_period ASC
    """
    with get_connection() as conn:
        return pd.read_sql(query, conn)


def get_summary_by_hcode() -> pd.DataFrame:
    query = """
        SELECT
            r.hcode AS "HCODE",
            COUNT(*) AS "รายการ",
            SUM(r.pp) AS "PP",
            SUM(r.fs) AS "FS",
            SUM(r.total) AS "ยอดรวม",
            SUM(r.grand_total) AS "ยอดชดเชยทั้งสิ้น"
        FROM records r
        JOIN upload_batches b ON b.batch_id = r.batch_id
        WHERE b.status = 'active'
        GROUP BY r.hcode
        ORDER BY "ยอดชดเชยทั้งสิ้น" DESC, "HCODE" ASC
    """
    with get_connection() as conn:
        return pd.read_sql(query, conn)


def get_amount_frequency(limit: int = 30) -> pd.DataFrame:
    """ตัวเลข 'ยอดชดเชยทั้งสิ้น' ที่พบบ่อย เรียงตามจำนวนครั้ง -- ตรงกับแฟ้มอ้างอิง
    'ตัวเลขพบบ่อย' ที่ใช้ตีความว่าแต่ละยอดคือชุดบริการอะไร"""
    query = """
        SELECT
            r.grand_total AS "ยอดชดเชยทั้งสิ้น",
            COUNT(*) AS "จำนวนครั้ง",
            SUM(r.grand_total) AS "รวมเงิน"
        FROM records r
        JOIN upload_batches b ON b.batch_id = r.batch_id
        WHERE b.status = 'active' AND r.grand_total > 0
        GROUP BY r.grand_total
        ORDER BY "จำนวนครั้ง" DESC, "ยอดชดเชยทั้งสิ้น" DESC
        LIMIT %s
    """
    with get_connection() as conn:
        return pd.read_sql(query, conn, params=(limit,))


def get_records_for_hcode(hcode: str) -> pd.DataFrame:
    """Amounts only (no PID/name) for one facility -- safe for the public dashboard."""
    query = """
        SELECT r.record_code, r.pp, r.fs
        FROM records r
        JOIN upload_batches b ON b.batch_id = r.batch_id
        WHERE b.status = 'active' AND r.hcode = %s
    """
    with get_connection() as conn:
        return pd.read_sql(query, conn, params=(hcode,))


def get_people_records_for_hcode(hcode: str) -> pd.DataFrame:
    """Per-person records for one facility, including PID/name -- admin only."""
    query = """
        SELECT
            r.hcode AS "HCODE",
            r.pid AS "PID",
            r.full_name AS "ชื่อ-นามสกุล",
            r.pp AS "PP",
            r.fs AS "FS",
            r.total AS "ยอดรวม"
        FROM records r
        JOIN upload_batches b ON b.batch_id = r.batch_id
        WHERE b.status = 'active' AND r.hcode = %s
        ORDER BY r.full_name NULLS LAST, r.pid
    """
    with get_connection() as conn:
        return pd.read_sql(query, conn, params=(hcode,))


def get_allocations_for_hcode(hcode: str) -> pd.DataFrame:
    query = """
        SELECT a.record_code, a.money_type, a.service, a.amount
        FROM allocations a
        JOIN records r ON r.record_code = a.record_code
        JOIN upload_batches b ON b.batch_id = r.batch_id
        WHERE b.status = 'active' AND r.hcode = %s
    """
    with get_connection() as conn:
        return pd.read_sql(query, conn, params=(hcode,))


def get_people_summary() -> pd.DataFrame:
    query = """
        SELECT
            r.report_period AS "รอบรายงาน",
            r.hcode AS "HCODE",
            r.pid AS "PID",
            r.full_name AS "ชื่อ-นามสกุล",
            COUNT(*) AS "รายการ",
            SUM(r.pp) AS "PP",
            SUM(r.fs) AS "FS",
            SUM(r.total) AS "ยอดรวม"
        FROM records r
        JOIN upload_batches b ON b.batch_id = r.batch_id
        WHERE b.status = 'active'
        GROUP BY r.report_period, r.hcode, r.pid, r.full_name
        ORDER BY "ยอดรวม" DESC
    """
    with get_connection() as conn:
        return pd.read_sql(query, conn)


def get_raw_records() -> pd.DataFrame:
    query = """
        SELECT
            r.report_period AS "รอบรายงาน",
            r.hcode AS "HCODE",
            r.pid AS "PID",
            r.full_name AS "ชื่อ-นามสกุล",
            r.visit_date AS "วันเข้ารักษา",
            r.pp AS "PP",
            r.fs AS "FS",
            r.total AS "ยอดรวม",
            r.grand_total AS "ยอดชดเชยทั้งสิ้น",
            r.source_file AS "ไฟล์ต้นทาง",
            r.record_code AS "รหัสรายการ"
        FROM records r
        JOIN upload_batches b ON b.batch_id = r.batch_id
        WHERE b.status = 'active'
        ORDER BY r.report_period, r.hcode, r.full_name
    """
    with get_connection() as conn:
        return pd.read_sql(query, conn)


def get_record_choices() -> list[str]:
    query = """
        SELECT r.record_code, r.hcode, r.full_name, r.pp, r.fs
        FROM records r
        JOIN upload_batches b ON b.batch_id = r.batch_id
        WHERE b.status = 'active'
        ORDER BY r.report_period, r.hcode
    """
    with get_connection() as conn:
        df = pd.read_sql(query, conn)
    return [
        f"{row.record_code} | {row.hcode} | {row.full_name} | PP {row.pp:.2f} FS {row.fs:.2f}"
        for row in df.itertuples()
    ]


def get_record_amount(record_code: str, money_type: str) -> float | None:
    query = "SELECT CASE WHEN %s = 'PP' THEN pp ELSE fs END FROM records WHERE record_code = %s"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (money_type, record_code))
            row = cur.fetchone()
    return float(row[0]) if row else None


def get_allocated_amount(record_code: str, money_type: str) -> float:
    query = "SELECT COALESCE(SUM(amount), 0) FROM allocations WHERE record_code = %s AND money_type = %s"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (record_code, money_type))
            row = cur.fetchone()
    return float(row[0]) if row else 0.0


def add_allocation(record_code: str, money_type: str, service: str, amount: float, note: str, recorder: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO allocations (record_code, money_type, service, amount, note, recorder)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (record_code, money_type, service, amount, note, recorder),
            )
        conn.commit()


def get_allocation_ledger() -> pd.DataFrame:
    query = """
        SELECT
            record_code AS "รหัสรายการ",
            money_type AS "ประเภทเงิน",
            service AS "บริการ",
            amount AS "จำนวนเงิน",
            note AS "หมายเหตุ",
            recorder AS "ผู้บันทึก",
            recorded_at AS "เวลา"
        FROM allocations
        ORDER BY recorded_at DESC
    """
    with get_connection() as conn:
        return pd.read_sql(query, conn)


def get_allocation_summary() -> pd.DataFrame:
    query = """
        WITH source AS (
            SELECT r.record_code, r.hcode AS "HCODE", r.pid AS "PID", r.full_name AS "ชื่อ-นามสกุล",
                   'PP' AS "ประเภทเงิน", r.pp AS "ยอดต้นทาง"
            FROM records r
            JOIN upload_batches b ON b.batch_id = r.batch_id
            WHERE b.status = 'active' AND r.pp <> 0
            UNION ALL
            SELECT r.record_code, r.hcode AS "HCODE", r.pid AS "PID", r.full_name AS "ชื่อ-นามสกุล",
                   'FS' AS "ประเภทเงิน", r.fs AS "ยอดต้นทาง"
            FROM records r
            JOIN upload_batches b ON b.batch_id = r.batch_id
            WHERE b.status = 'active' AND r.fs <> 0
        ),
        allocated AS (
            SELECT record_code, money_type AS "ประเภทเงิน", SUM(amount) AS "ยอดจัดสรรแล้ว"
            FROM allocations
            GROUP BY record_code, money_type
        )
        SELECT
            s.record_code AS "รหัสรายการ",
            s."HCODE",
            s."PID",
            s."ชื่อ-นามสกุล",
            s."ประเภทเงิน",
            s."ยอดต้นทาง",
            COALESCE(a."ยอดจัดสรรแล้ว", 0) AS "ยอดจัดสรรแล้ว",
            s."ยอดต้นทาง" - COALESCE(a."ยอดจัดสรรแล้ว", 0) AS "คงเหลือ"
        FROM source s
        LEFT JOIN allocated a ON a.record_code = s.record_code AND a."ประเภทเงิน" = s."ประเภทเงิน"
        ORDER BY s."HCODE", s."ชื่อ-นามสกุล", s."ประเภทเงิน"
    """
    with get_connection() as conn:
        return pd.read_sql(query, conn)
