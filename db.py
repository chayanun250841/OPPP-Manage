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
    source_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_records_hcode ON records(hcode);
CREATE INDEX IF NOT EXISTS idx_records_batch ON records(batch_id);
CREATE INDEX IF NOT EXISTS idx_records_period ON records(report_period);

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
    """Insert a new upload batch and its records. Rows whose record_code already exists
    anywhere in the table (any batch, any time) are skipped so re-uploading the same
    file, or overlapping data across months, never double-counts."""
    batch_id = str(uuid.uuid4())
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO upload_batches (batch_id, report_period, source_file, uploaded_by, record_count)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (batch_id, report_period, source_file, uploaded_by, len(frame)),
            )
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
                    row["ไฟล์ต้นทาง"],
                )
                for _, row in frame.iterrows()
            ]
            if rows:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO records
                        (record_code, batch_id, report_period, tran_id, pid, full_name, hcode, visit_date, pp, fs, total, source_file)
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
            duplicate_count = len(frame) - inserted_count
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


def get_overall_totals() -> dict:
    query = """
        SELECT
            COALESCE(SUM(r.pp), 0) AS pp,
            COALESCE(SUM(r.fs), 0) AS fs,
            COALESCE(SUM(r.total), 0) AS total,
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
            SUM(r.total) AS "ยอดรวม"
        FROM records r
        JOIN upload_batches b ON b.batch_id = r.batch_id
        WHERE b.status = 'active'
        GROUP BY r.hcode
        ORDER BY "ยอดรวม" DESC, "HCODE" ASC
    """
    with get_connection() as conn:
        return pd.read_sql(query, conn)


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
