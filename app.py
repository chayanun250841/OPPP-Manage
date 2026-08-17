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

/* The theme variables are applied to every element, not just the root.
   Gradio re-declares them partway down the tree (main.contain resolved back
   to the dark palette), so plain inheritance from .gradio-container silently
   lost the light theme below that point. */
:root, .dark, .gradio-container, .gradio-container * {
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
    --oppp-overlay: rgba(2, 5, 4, 0.78);
}

/* Light theme -- toggled by the ☀/🌙 button in the header, which flips this
   class on the container and remembers the choice in localStorage. Same
   element-wide application as the dark defaults above, one specificity step
   higher so it wins everywhere. */
html.oppp-light, html.oppp-light * {
    --oppp-bg: #f4f7f5;
    --oppp-panel: #ffffff;
    --oppp-panel-alt: #eef4f0;
    --oppp-input: #ffffff;
    --oppp-border: #d3e0d7;
    --oppp-text: #1b2b22;
    --oppp-text-dim: #5b7566;
    --oppp-accent: #0f7a42;
    --oppp-accent-dark: #0a5c31;
    --oppp-accent-text: #ffffff;
    --oppp-shadow: 0 1px 2px rgba(23, 43, 32, 0.06), 0 4px 16px rgba(23, 43, 32, 0.07);
    --oppp-overlay: rgba(28, 42, 34, 0.42);
    color-scheme: light !important;
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
    font-size: 16px !important;
    max-width: 100% !important;
    width: 100% !important;
    padding: 18px 26px 28px !important;
}
html.oppp-light .gradio-container { color-scheme: light !important; }
/* Gradio paints its own background on these wrappers; without this the page
   keeps a dark frame around a light body (and vice versa). The inner wrappers
   go transparent rather than re-resolving the variable -- Gradio re-declares
   the palette on main.contain, so a var() there would read the wrong theme. */
body, gradio-app { background: var(--oppp-bg) !important; color: var(--oppp-text) !important; }
.gradio-container .main,
.gradio-container .wrap,
.gradio-container main.contain,
main.contain { background: transparent !important; }
/* Readable body copy -- the old 0.8rem sizing was too small to scan. */
.gradio-container p,
.gradio-container li,
.gradio-container label,
.gradio-container .prose,
.gradio-container button { font-size: 0.98rem !important; }
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

/* ---------- Header: brand on the left, actions on the right, one bar ------ */
.oppp-header-row {
    display: flex !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
    justify-content: space-between !important;
    gap: 18px !important;
    background: var(--oppp-panel) !important;
    padding: 18px 24px !important;
    border: 1px solid var(--oppp-border) !important;
    border-radius: 14px !important;
    box-shadow: var(--oppp-shadow);
    margin-bottom: 20px !important;
    position: relative;
    overflow: hidden;
}
/* A thin accent bar along the top edge, instead of the old left border */
.oppp-header-row::before {
    content: "";
    position: absolute;
    inset: 0 0 auto 0;
    height: 3px;
    background: linear-gradient(90deg, var(--oppp-accent), transparent 75%);
}
.oppp-header-row > .html-container,
.oppp-header-row > div:first-child { flex: 1 1 auto !important; min-width: 0 !important; }
.oppp-header {
    position: relative;
    display: flex;
    align-items: center;
    gap: 18px;
    color: var(--oppp-text);
    background: transparent;
}
/* Coin: a slow 3D spin about the vertical axis. The wrapper owns the
   perspective so the rotation reads as depth rather than a flat squash. */
.oppp-header .icon {
    font-size: 3.4rem;
    line-height: 1;
    width: 104px; height: 104px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    perspective: 700px;
}
.oppp-header .icon img {
    width: 100%; height: 100%;
    object-fit: contain;
    transform-style: preserve-3d;
    animation: oppp-coin-spin 9s linear infinite;
    filter: drop-shadow(0 4px 10px rgba(0, 0, 0, 0.45));
}
@keyframes oppp-coin-spin {
    from { transform: rotateY(0deg); }
    to   { transform: rotateY(360deg); }
}
@media (prefers-reduced-motion: reduce) {
    .oppp-header .icon img { animation: none; }
}
.oppp-header .titles { min-width: 0; }
.oppp-header h1 {
    margin: 0; font-size: 1.6rem; font-weight: 700; letter-spacing: 0.2px;
    color: var(--oppp-accent);
    line-height: 1.25;
}
.oppp-header p {
    margin: 5px 0 0; opacity: 0.9; font-size: 0.92rem; color: var(--oppp-text-dim);
    line-height: 1.45;
}
@media (max-width: 900px) {
    .oppp-header-row { flex-wrap: wrap !important; }
    .oppp-header p { display: none; }
}
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
    border-radius: 14px !important;
    padding: 20px 22px !important;
    box-shadow: var(--oppp-shadow);
    margin-bottom: 18px !important;
}
.dev-card { border-left: 3px solid var(--oppp-accent) !important; }

/* ---------- KPI cards ---------- */
.kpi-row { gap: 16px !important; margin-bottom: 16px !important; }
.kpi-card {
    position: relative;
    border-radius: 14px !important;
    padding: 14px 18px !important;
    background: var(--oppp-panel) !important;
    border: 1px solid var(--oppp-border) !important;
    border-left: 3px solid var(--oppp-accent) !important;
    box-shadow: var(--oppp-shadow);
    transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.kpi-card:hover { transform: translateY(-2px); }
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

/* ---------- Header actions (theme toggle, login, console, logout) -------- */
.topbar {
    display: flex !important;
    flex: 0 0 auto !important;
    flex-wrap: nowrap !important;
    width: auto !important;
    align-items: center !important;
    justify-content: flex-end !important;
    gap: 10px !important;
    background: transparent !important;
    border: none !important;
    margin: 0 !important;
}
.topbar > * { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
/* `min-width: 0` on the button itself used to be here -- it let each button
   collapse to ~26px, stacking its label one character per line. */
.topbar button {
    white-space: nowrap !important;
    width: auto !important;
    padding: 10px 18px !important;
    border-radius: 999px !important;
    font-weight: 600 !important;
    line-height: 1.2 !important;
    box-shadow: none !important;
    transition: transform 0.12s ease, background 0.12s ease;
}
.topbar button:hover { transform: translateY(-1px); }
.topbar .icon-btn button, .topbar button.icon-btn {
    font-size: 1.2rem !important;
    padding: 9px 13px !important;
    line-height: 1 !important;
}

/* ---------- Modal overlay (login + developer console) ---------- */
.oppp-modal {
    position: fixed !important;
    inset: 0 !important;
    z-index: 3000 !important;
    background: var(--oppp-overlay) !important;
    backdrop-filter: blur(4px);
    display: flex !important;
    align-items: flex-start !important;
    justify-content: center !important;
    padding: 3vh 16px !important;
    overflow-y: auto !important;
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
}
/* Gradio wraps a Group's children in a `.styler` flex item that shrinks to
   its content -- without this the panel collapses to ~286px regardless of
   the width set on it. */
.oppp-modal .styler {
    flex: 1 1 auto !important;
    width: 100% !important;
    background: transparent !important;
    border: none !important;
}
.oppp-modal-panel {
    flex: 0 0 auto !important;
    /* margin auto centers regardless of the wrapper's flex-direction --
       justify-content alone does not, since Gradio stacks it as a column */
    margin: 0 auto !important;
    width: min(1200px, 100%) !important;
    background: var(--oppp-panel) !important;
    border: 1px solid var(--oppp-border) !important;
    border-top: 3px solid var(--oppp-accent) !important;
    border-radius: 10px !important;
    padding: 20px 24px 24px !important;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.55) !important;
}
.oppp-modal-panel.narrow { width: min(480px, 100%) !important; }
.modal-head { align-items: center !important; margin-bottom: 6px !important; }
.modal-title h3 {
    margin: 0 !important;
    border-bottom: none !important;
    padding-bottom: 0 !important;
    font-size: 1.1rem !important;
}
.modal-close button, button.modal-close { max-width: 46px !important; padding: 6px 10px !important; }

.login-status { font-weight: 600 !important; font-size: 0.95rem !important; color: var(--oppp-text) !important; }
.hint-text { color: var(--oppp-text-dim) !important; font-size: 0.9rem !important; line-height: 1.6 !important; }
.footer-note { text-align: center !important; color: var(--oppp-text-dim) !important; font-size: 0.85rem !important; margin-top: 18px !important; opacity: 0.85; }

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
button:not(.primary):hover { border-color: var(--oppp-accent) !important; }

/* ---------- Tabs: pill-style bar under the header ----------
   Do NOT lead these selectors with `.gradio-container`. Gradio rewrites custom
   CSS by prefixing `.gradio-container.gradio-container-X .contain `, so a
   self-prefixed selector becomes `... .contain .gradio-container ...`, which
   matches nothing -- and the surviving unprefixed copy then loses to Gradio's
   own prefixed `button:not(.primary)`. Starting from `.tab-container` lets the
   prefix do its job and outrank it. */
.tab-container {
    background: var(--oppp-panel) !important;
    border: 1px solid var(--oppp-border) !important;
    border-radius: 999px !important;
    padding: 5px !important;
    gap: 4px !important;
    display: inline-flex !important;
    margin-bottom: 16px !important;
    box-shadow: var(--oppp-shadow);
}
.tab-container.visually-hidden { display: none !important; }
.tab-container button[aria-selected] {
    border: none !important;
    border-radius: 999px !important;
    background: transparent !important;
    color: var(--oppp-text-dim) !important;
    padding: 8px 20px !important;
    font-weight: 600 !important;
    white-space: nowrap !important;
}
.tab-container button[aria-selected="true"] {
    background: var(--oppp-accent) !important;
    color: var(--oppp-accent-text) !important;
}
.tab-container button[aria-selected="false"]:hover {
    background: var(--oppp-panel-alt) !important;
    color: var(--oppp-text) !important;
}

/* ---------- Tables / plots ---------- */
table, thead, tbody, tr, td, th {
    background: var(--oppp-panel) !important;
    color: var(--oppp-text) !important;
    border-color: var(--oppp-border) !important;
}
thead th { color: var(--oppp-accent) !important; }

/* Do NOT force white-space on cells -- that overrides each Dataframe's own
   `wrap` setting and, combined with narrow auto-sized columns, stacks short
   headers into a single letter per line. Let `wrap` control it. */
table td, table th {
    padding: 8px 12px !important;
    font-size: 0.95rem !important;
    line-height: 1.45 !important;
}
/* Headers wrap between words but never inside one. `overflow-wrap: anywhere`
   shredded Thai headers a character per line ("ครั้" / "ง"); a min-width plus
   the table's own horizontal scroll keeps them readable instead. */
table th {
    white-space: normal !important;
    word-break: keep-all !important;
    overflow-wrap: normal !important;
    hyphens: none !important;
    vertical-align: bottom !important;
    font-weight: 700 !important;
    text-align: center !important;
}
table td { white-space: nowrap !important; }

/* ---------- All-facilities pivot: two-row grouped header ---------- */
.pivot-scroll { overflow-x: auto; border: 1px solid var(--oppp-border); border-radius: 12px; }
table.pivot {
    border-collapse: collapse !important;
    width: max-content;
    min-width: 100%;
    font-size: 0.92rem;
}
table.pivot th, table.pivot td {
    border: 1px solid var(--oppp-border) !important;
    padding: 7px 12px !important;
    white-space: nowrap !important;
    text-align: right;
}
table.pivot thead th {
    background: var(--oppp-panel-alt) !important;
    color: var(--oppp-accent) !important;
    text-align: center !important;
    font-weight: 700 !important;
    position: sticky;
    top: 0;
}
table.pivot th.grp { border-bottom: 2px solid var(--oppp-accent) !important; }
table.pivot th.sub { font-weight: 600 !important; font-size: 0.86rem; }
table.pivot th.lbl, table.pivot td.lbl { text-align: left !important; }
table.pivot tbody tr:nth-child(even) td { background: var(--oppp-panel-alt) !important; }
table.pivot tbody tr.total td {
    font-weight: 700 !important;
    color: var(--oppp-accent) !important;
    border-top: 2px solid var(--oppp-accent) !important;
}

/* ---------- Accordions used to collapse the long tables ---------- */
.label-wrap span { font-size: 1rem !important; font-weight: 600 !important; }
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


GRAND_TOTAL_LABEL = "ยอดชดเชยทั้งสิ้น"


def parse_report(path: str) -> tuple[pd.DataFrame, dict[str, int]]:
    """Read one OPPP report into the analysis frame.

    Scope rule (ตาม 'กติกาและสูตรรวม' ของแฟ้มอ้างอิง): เอาเฉพาะแถวที่มีเงินจริงใน
    PP หรือ FS เท่านั้น แถวที่ชดเชยมาจากกองทุนอื่น (HC, DRUG, AE ฯลฯ) ไม่เกี่ยวกับ
    การวิเคราะห์ PP/FS จึงถูกตัดทิ้งตั้งแต่ต้นทาง ไม่ให้ไปพองยอดในฐานข้อมูล

    เก็บคอลัมน์สุดท้าย `ยอดชดเชยทั้งสิ้น` ของแถวที่ผ่านเกณฑ์ไว้ด้วย เพราะเป็นตัวเลข
    เป้าหมายที่ต้องรายงาน ส่วน PP+FS เก็บแยกไว้ใช้จับคู่บริการ (สองค่านี้ไม่เท่ากัน
    เมื่อแถวเดียวกันมีเงินกองทุนอื่นปนมาด้วย)

    Returns the frame plus a stats dict for the upload log.
    """
    sheet = pd.read_excel(path, header=None, dtype=object)
    mask = sheet.apply(lambda row: row.map(text_value).eq("HCODE").any(), axis=1)
    matches = mask[mask].index
    if len(matches) == 0:
        raise ValueError("ไม่พบหัวตาราง HCODE")

    header_row = int(matches[0])
    header = sheet.iloc[header_row].where(sheet.iloc[header_row].notna(), sheet.iloc[header_row - 1])
    columns = {label: find_column(header, label) for label in ["TRAN_ID", "PID", "ชื่อ-นามสกุล", "HCODE", "PP", "FS"]}
    date_col = find_column(header, "วันเข้ารักษา")
    grand_col = find_column(header, GRAND_TOTAL_LABEL)
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
            GRAND_TOTAL_LABEL: rows.iloc[:, grand_col].map(money_value),
        }
    )
    result = result[(result["HCODE"] != "") & (result["HCODE"].str.lower() != "hcode")].copy()
    stats = {"อ่านได้": len(result)}

    result = result[(result["PP"] > 0) | (result["FS"] > 0)].copy()
    stats["ไม่มีเงิน PP/FS"] = stats["อ่านได้"] - len(result)

    before_tran = len(result)
    result = result[result["TRAN_ID"] != ""].copy()
    result = result.drop_duplicates("TRAN_ID", keep="first")
    stats["TRAN_ID ซ้ำ/ว่างในไฟล์"] = before_tran - len(result)

    result["ไฟล์ต้นทาง"] = report_name
    result["รอบรายงาน"] = report_code.group(1) if report_code else report_name
    result["ยอดรวม"] = result["PP"] + result["FS"]
    result["รหัสรายการ"] = result.apply(
        lambda row: hashlib.sha256(
            "|".join(str(row[key]) for key in ["รอบรายงาน", "TRAN_ID", "PID", "HCODE", "วันเข้ารักษา", "PP", "FS"]).encode()
        ).hexdigest()[:16],
        axis=1,
    )
    stats["นำเข้า"] = len(result)
    return result, stats


# Downloads must live somewhere Gradio is willing to serve. Gradio 5+ blocks
# arbitrary paths, and a bare tempfile.gettempdir() path is outside the set it
# trusts -- the click then produced no file at all. This directory is passed to
# launch(allowed_paths=...) so every export below is served.
EXPORT_DIR = os.path.join(tempfile.gettempdir(), "oppp_exports")
os.makedirs(EXPORT_DIR, exist_ok=True)


def export_path(name: str, extension: str) -> str:
    safe = re.sub(r"[^\w฀-๿.-]+", "_", name).strip("_") or "export"
    return os.path.join(EXPORT_DIR, f"{safe}_{datetime.now():%Y%m%d_%H%M%S}.{extension}")


def export_csv(frame: pd.DataFrame, name: str) -> str:
    path = export_path(name, "csv")
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def as_frame(value: object) -> pd.DataFrame | None:
    """A gr.Dataframe hands its value back as a DataFrame, but an empty one can
    arrive as a dict/list depending on how it was last written. Normalise so a
    download never silently no-ops on a shape we did not expect."""
    if isinstance(value, pd.DataFrame):
        return value if not value.empty else None
    if isinstance(value, dict) and "data" in value:
        frame = pd.DataFrame(value["data"], columns=value.get("headers"))
        return frame if not frame.empty else None
    if isinstance(value, list) and value:
        return pd.DataFrame(value)
    return None


def export_excel(frame: object, name: str):
    """Excel-download handler for a Dataframe component's current value.
    Returns (ไฟล์, ข้อความสถานะ) so a failure is visible instead of silent."""
    data = as_frame(frame)
    if data is None:
        return None, "⚠️ ยังไม่มีข้อมูลในตารางนี้ให้ดาวน์โหลด"
    try:
        path = export_path(name, "xlsx")
        data.to_excel(path, index=False)
    except Exception as exc:  # noqa: BLE001
        return None, f"❌ สร้างไฟล์ Excel ไม่สำเร็จ: {exc}"
    return path, f"✅ พร้อมดาวน์โหลด · {len(data):,} แถว"


def export_excel_sheets(name: str, **sheets: object):
    """Excel-download handler that writes multiple tables as separate sheets."""
    usable = {label: df for label, df in ((k, as_frame(v)) for k, v in sheets.items()) if df is not None}
    if not usable:
        return None, "⚠️ ยังไม่มีข้อมูลในตารางเหล่านี้ให้ดาวน์โหลด"
    try:
        path = export_path(name, "xlsx")
        with pd.ExcelWriter(path) as writer:
            for label, df in usable.items():
                df.to_excel(writer, sheet_name=label[:31], index=False)
    except Exception as exc:  # noqa: BLE001
        return None, f"❌ สร้างไฟล์ Excel ไม่สำเร็จ: {exc}"
    return path, f"✅ พร้อมดาวน์โหลด · {len(usable)} ตาราง"


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


# ---------------------------------------------------------------------------
# Executive dashboard (public, no login required)
# ---------------------------------------------------------------------------

RANKING_COLUMNS = ["HCODE", "รายการ", "PP", "FS", "ยอดรวม", "ยอดชดเชยทั้งสิ้น"]


def format_ranking_table(ranking: pd.DataFrame) -> pd.DataFrame:
    if ranking.empty:
        return ranking
    display = ranking.copy()
    display["HCODE"] = display["HCODE"].map(hcode_label)
    display["รายการ"] = display["รายการ"].map(lambda v: f"{int(v):,}")
    for col in ("PP", "FS", "ยอดรวม", "ยอดชดเชยทั้งสิ้น"):
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

    return (
        f"{float(totals.get('grand_total') or 0):,.2f} บาท",
        f"{float(totals.get('pp') or 0):,.2f} บาท",
        f"{float(totals.get('fs') or 0):,.2f} บาท",
        f"{count:,} รายการ",
        f"{int(totals.get('hcode_count') or 0):,} แห่ง",
        str(totals.get("latest_period") or "-"),
        format_ranking_table(ranking),
        updated,
    )


# ---------------------------------------------------------------------------
# Frequent-amount table: the "ตัวเลขพบบ่อย" view from the reference workbook,
# rebuilt live from whatever is currently in the database.
# ---------------------------------------------------------------------------

FREQUENCY_COLUMNS = ["ยอดชดเชยทั้งสิ้น", "จำนวนครั้ง", "รวมเงิน", "ตีความตามกติกา", "สถานะ"]


def build_amount_frequency():
    try:
        frequency = db.get_amount_frequency()
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(columns=FREQUENCY_COLUMNS), f"⚠️ โหลดไม่สำเร็จ: {exc}"
    if frequency.empty:
        return pd.DataFrame(columns=FREQUENCY_COLUMNS), "ยังไม่มีข้อมูล"

    rows = []
    for rec in frequency.to_dict(orient="records"):
        amount = float(rec["ยอดชดเชยทั้งสิ้น"])
        status, label = service_matching.explain_amount(amount)
        rows.append(
            {
                "ยอดชดเชยทั้งสิ้น": f"{amount:,.2f}",
                "จำนวนครั้ง": f"{int(rec['จำนวนครั้ง']):,}",
                "รวมเงิน": f"{float(rec['รวมเงิน']):,.2f}",
                "ตีความตามกติกา": label,
                "สถานะ": status,
            }
        )
    covered = int(frequency["จำนวนครั้ง"].sum())
    covered_amount = float(frequency["รวมเงิน"].sum())
    note = f"แสดง {len(rows)} ยอดที่พบบ่อยที่สุด · ครอบคลุม {covered:,} รายการ · รวม {covered_amount:,.2f} บาท"
    return pd.DataFrame(rows, columns=FREQUENCY_COLUMNS), note


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
    """Returns (ตาราง HTML, สถานะ, ตารางดิบสำหรับส่งออก).

    The display table is HTML because its header spans two rows -- one service
    name over its จำนวนครั้ง and ยอดชดเชย columns -- which gr.Dataframe cannot
    express. The raw frame rides along in a State so the Excel export still has
    real data to write.
    """
    empty = pd.DataFrame()
    try:
        pivot = service_analysis.build_all_facilities_pivot(HCODE_NAMES)
    except Exception as exc:  # noqa: BLE001
        return "", f"⚠️ สรุปไม่สำเร็จ: {exc}", empty
    if pivot.empty:
        return service_analysis.render_all_facilities_html(pivot), "ไม่มีข้อมูล", empty
    updated = f"🟢 คำนวณล่าสุด {datetime.now():%d/%m/%Y %H:%M:%S} น."
    # The State keeps the raw frame, not a formatted one: the Excel writer
    # rebuilds the same grouped header from the "group | sub" column names and
    # writes real numbers rather than pre-formatted strings.
    return service_analysis.render_all_facilities_html(pivot), updated, pivot


# ---------------------------------------------------------------------------
# Developer console (hidden, admin-only)
# ---------------------------------------------------------------------------


def process_upload(files: list[str] | None, uploader: str, note: str):
    """Process one batch of report files, adding them on top of what is already
    stored -- uploading is always cumulative, never a replacement.

    Returns (สรุปผล, ล้างช่องเลือกไฟล์) so the picker empties after a successful
    run and the next batch can be dropped straight in. Without that the previous
    selection lingers and pressing the button again files an empty duplicate batch.
    """
    keep = gr.update()
    if not files:
        return "⚠️ กรุณาเลือกไฟล์ .xls อย่างน้อย 1 ไฟล์", keep
    if not uploader or not uploader.strip():
        return "⚠️ กรุณาระบุชื่อผู้บันทึกก่อนอัปโหลด", keep

    lines = []
    added = 0
    for path in files:
        name = os.path.basename(path)
        try:
            frame, stats = parse_report(path)
        except Exception as exc:  # noqa: BLE001
            lines.append(f"- ❌ **{name}** — อ่านไฟล์ไม่สำเร็จ ({exc})")
            continue

        report_period = frame["รอบรายงาน"].iloc[0] if not frame.empty else name

        try:
            outcome = db.insert_batch(report_period, name, uploader.strip(), frame, (note or "").strip())
        except Exception as exc:  # noqa: BLE001
            lines.append(f"- ❌ **{name}** — บันทึกฐานข้อมูลไม่สำเร็จ ({exc})")
            continue

        added += outcome["inserted_count"]
        lines.append(
            f"- ✅ **{name}** (รอบ {report_period}) — อ่าน {stats['อ่านได้']:,} แถว "
            f"· ตัดแถวไม่มีเงิน PP/FS {stats['ไม่มีเงิน PP/FS']:,} "
            f"· ตัด TRAN_ID ซ้ำในไฟล์ {stats['TRAN_ID ซ้ำ/ว่างในไฟล์']:,} "
            f"· เข้าเกณฑ์ {stats['นำเข้า']:,} → **บันทึกใหม่ {outcome['inserted_count']:,} รายการ** "
            f"(ซ้ำกับที่มีอยู่แล้ว {outcome['duplicate_count']:,})"
        )

    try:
        total = int(db.get_overall_totals().get("count") or 0)
        lines.append(f"\n**รวมรอบนี้เพิ่ม {added:,} รายการ · ตอนนี้ทั้งระบบมี {total:,} รายการ**")
    except Exception:  # noqa: BLE001
        pass

    return "\n".join(lines), gr.update(value=None)


def reset_system(role: str, password: str):
    """Wipe every uploaded record so a fresh set of files can be loaded.

    Two independent gates, both required: the caller must already hold an admin
    session, and must re-enter the admin password here. The session alone is not
    enough -- this is irreversible, unlike the per-batch rollback next to it.
    Returns (สถานะ, ล้างช่องรหัสผ่าน) so the password never lingers in the UI.
    """
    blank = gr.update(value="")
    if role != "admin":
        return "❌ ต้องเข้าสู่ระบบด้วยสิทธิ์ผู้ดูแลระบบก่อนจึงจะรีเซ็ตได้", blank
    if not ADMIN_PASSWORD_HASH:
        return "⚠️ เซิร์ฟเวอร์ยังไม่ได้ตั้งค่า OPPP_ADMIN_PASSWORD_HASH จึงรีเซ็ตไม่ได้", blank
    if not password or hash_password(password) != ADMIN_PASSWORD_HASH:
        return "❌ รหัสผ่านไม่ถูกต้อง — ระบบไม่ได้ลบข้อมูลใดๆ", blank

    try:
        removed = db.reset_all_data()
    except Exception as exc:  # noqa: BLE001
        return f"❌ รีเซ็ตไม่สำเร็จ: {exc}", blank

    return (
        f"✅ รีเซ็ตระบบเรียบร้อยเมื่อ {datetime.now():%d/%m/%Y %H:%M:%S} น. — "
        f"ลบรายการ {removed['records']:,} รายการ, ประวัติการอัปโหลด {removed['upload_batches']:,} ไฟล์, "
        f"สมุดจัดสรร {removed['allocations']:,} รายการ · ตอนนี้ระบบว่างเปล่า พร้อมอัปโหลดไฟล์ใหม่แล้ว",
        blank,
    )


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


def export_all_facilities_excel(pivot: object):
    """Excel for the all-facilities pivot, carrying the same two-row merged
    header as the table on screen."""
    if not isinstance(pivot, pd.DataFrame) or pivot.empty:
        return None, "⚠️ ยังไม่มีข้อมูล — กด 'คำนวณสรุปทุกหน่วยบริการ' ก่อน"
    try:
        path = export_path("สรุปทุกหน่วยบริการ", "xlsx")
        service_analysis.write_all_facilities_excel(pivot, path)
    except Exception as exc:  # noqa: BLE001
        return None, f"❌ สร้างไฟล์ Excel ไม่สำเร็จ: {exc}"
    return path, f"✅ พร้อมดาวน์โหลด · {len(pivot):,} แถว"


def export_ledger_csv():
    """Returns (ไฟล์, ข้อความสถานะ) to match the download-button wiring."""
    try:
        ledger = db.get_allocation_ledger()
    except Exception as exc:  # noqa: BLE001
        return None, f"❌ อ่านสมุดจัดสรรไม่สำเร็จ: {exc}"
    if ledger.empty:
        return None, "⚠️ สมุดจัดสรรยังว่างอยู่"
    return export_csv(ledger, "สมุดจัดสรรบริการ"), f"✅ พร้อมดาวน์โหลด · {len(ledger):,} แถว"


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

with gr.Blocks(title="OPPP Compensation Dashboard") as demo:
    role_state = gr.State("viewer")

    _header_icon = (
        f'<img src="{LOGO_DATA_URI}" alt="กระทรวงสาธารณสุข" />'
        if LOGO_DATA_URI
        else "🏛️"
    )
    with gr.Row(elem_classes="oppp-header-row"):
        gr.HTML(
            f"""
            <div class="oppp-header">
                <div class="icon">{_header_icon}</div>
                <div class="titles">
                    <h1>ระบบติดตามเงินชดเชย OPPP</h1>
                    <p>สรุปยอดชดเชยทั้งสิ้นของรายการที่มีเงิน PP/FS ตามหน่วยบริการ HCODE 5 หลัก</p>
                </div>
            </div>
            """
        )
        with gr.Row(elem_classes="topbar"):
            theme_btn = gr.Button("🌙", elem_classes="icon-btn", scale=0, min_width=0)
            open_login_btn = gr.Button("🔑 เข้าสู่ระบบ", scale=0, min_width=0)
            open_admin_btn = gr.Button("🛠️ หน้าผู้ดูแลระบบ", variant="primary", visible=False, scale=0, min_width=0)
            logout_btn = gr.Button("🚪 ออกจากระบบ", visible=False, scale=0, min_width=0)

    # --- Login modal ---------------------------------------------------
    with gr.Group(visible=False, elem_classes="oppp-modal") as login_modal:
        with gr.Column(elem_classes="oppp-modal-panel narrow"):
            with gr.Row(elem_classes="modal-head"):
                gr.Markdown("### 🔐 เข้าสู่ระบบผู้ดูแล", elem_classes="modal-title")
                close_login_btn = gr.Button("✕", elem_classes="modal-close", scale=0, min_width=46)
            gr.Markdown("กรอกข้อมูลแล้วกด Enter ได้เลย", elem_classes="hint-text")
            # lines=max_lines=1 forces a real <input>; the default renders a
            # <textarea>, where Enter inserts a newline instead of submitting.
            username_box = gr.Textbox(label="ชื่อผู้ใช้", autofocus=True, lines=1, max_lines=1)
            password_box = gr.Textbox(label="รหัสผ่าน", type="password", lines=1, max_lines=1)
            login_btn = gr.Button("เข้าสู่ระบบ", variant="primary")
            login_status = gr.Markdown(elem_classes="login-status")

    updated_badge = gr.Markdown("กำลังโหลดข้อมูล...")

    with gr.Tabs():
        with gr.Tab("📈 ภาพรวม"):
            with gr.Row(elem_classes="kpi-row"):
                with gr.Group(elem_classes="kpi-card"):
                    kpi_total = gr.Textbox(label="💰 ยอดชดเชยทั้งสิ้นสะสม", interactive=False)
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

        with gr.Tab("📊 สรุปรายหน่วยบริการ"):
            with gr.Group(elem_classes="card"):
                gr.Markdown("คลิกแถวหน่วยบริการเพื่อดูรายละเอียดบริการด้านล่าง", elem_classes="hint-text")
                with gr.Accordion("📊 ตารางสรุปยอดชดเชยรายหน่วยบริการ (ทั้งหมด)", open=True):
                    ranking_table = gr.Dataframe(
                        value=pd.DataFrame(columns=RANKING_COLUMNS), interactive=False, wrap=True
                    )
                ranking_excel_btn = gr.DownloadButton("📥 ดาวน์โหลด Excel")
                ranking_excel_file = gr.File(label="ไฟล์ล่าสุด (สำรอง กดที่นี่ได้ถ้าไม่โหลดอัตโนมัติ)")
                ranking_excel_status = gr.Markdown(elem_classes="hint-text")

            with gr.Group(elem_classes="card"):
                breakdown_label = gr.Markdown("### 🔍 รายละเอียดบริการ\nคลิกแถวในตารางด้านบนเพื่อดูรายละเอียดบริการของหน่วยนั้น")
                with gr.Accordion("🔍 ตารางรายละเอียดบริการของหน่วยที่เลือก", open=True):
                    breakdown_table = gr.Dataframe(value=pd.DataFrame(columns=BREAKDOWN_COLUMNS), interactive=False, wrap=True)

        with gr.Tab("📋 สรุปทุกหน่วยบริการ"):
            gr.Markdown(
                "ตารางสรุปทุกหน่วยบริการพร้อมกันในหน้าเดียว — แทนที่สเปรดชีตที่เจ้าหน้าที่ต้องนั่งกรอกเอง "
                "แต่ละรายการมี 2 คอลัมน์ (ครั้ง / บาท ตามอัตราเต็มสปสช.) นับเฉพาะรายการที่คาดการณ์ชัดเจน (🟢 หรือ 🟠 ใกล้เคียง) "
                "ส่วนที่ยังไม่แน่ชัดหรือไม่พบจะรวมอยู่ใน 'ยอดที่ยังไม่จัดประเภท' ท้ายตาราง "
                "· คำนวณให้อัตโนมัติตั้งแต่เปิดหน้า และคำนวณซ้ำเองทุก 5 นาที รวมทั้งทันทีหลังอัปโหลดข้อมูลใหม่ "
                "· หัวคอลัมน์เป็นชื่อรายการแบบย่อ ดูชื่อเต็มตามประกาศได้ที่ 'คำอธิบายรายการ' ด้านล่าง "
                "· ตารางเลื่อนดูทางแนวนอนได้",
                elem_classes="hint-text",
            )
            summary_status = gr.Markdown("กำลังคำนวณ...")
            all_facilities_data = gr.State(pd.DataFrame())
            with gr.Accordion("📋 ตารางสรุปทุกหน่วยบริการ", open=True):
                all_facilities_table = gr.HTML()
            with gr.Accordion("📖 คำอธิบายรายการ (ชื่อย่อ → ชื่อเต็มตามประกาศ)", open=False):
                summary_legend = gr.Markdown(service_analysis.build_item_legend(), elem_classes="hint-text")
            summary_excel_btn = gr.DownloadButton("📥 ดาวน์โหลด Excel")
            summary_excel_file = gr.File(label="ไฟล์ล่าสุด (สำรอง)")
            summary_excel_status = gr.Markdown(elem_classes="hint-text")

        with gr.Tab("🔢 ยอดที่พบบ่อย"):
            with gr.Group(elem_classes="card"):
                gr.Markdown(
                    "นับเฉพาะรายการที่มีเงินใน PP หรือ FS และตัด TRAN_ID ซ้ำแล้ว "
                    "· คอลัมน์ 'ตีความตามกติกา' อ้างอิงแฟ้มกติกาที่ยืนยันไว้ ยอดที่ระบุว่ากำกวมต้องดูรหัสบริการประกอบ",
                    elem_classes="hint-text",
                )
                frequency_note = gr.Markdown("กำลังโหลดข้อมูล...")
                with gr.Accordion("🔢 ตารางยอดชดเชยที่พบบ่อย", open=True):
                    frequency_table = gr.Dataframe(
                        value=pd.DataFrame(columns=FREQUENCY_COLUMNS), interactive=False, wrap=True
                    )

    refresh_timer = gr.Timer(30)
    # The pivot is far heavier than the KPI queries -- one query per facility
    # plus combo matching over every record -- and it only changes when someone
    # uploads. Recomputing it on the 30s tick would keep the free instance busy
    # for nothing, so it gets its own slow timer and an immediate rerun after
    # each upload, where the change actually happens.
    summary_timer = gr.Timer(300)

    dashboard_outputs = [
        kpi_total, kpi_pp, kpi_fs, kpi_count, kpi_hcode, kpi_latest,
        ranking_table, updated_badge,
    ]
    frequency_outputs = [frequency_table, frequency_note]
    summary_outputs = [all_facilities_table, summary_status, all_facilities_data]

    # -----------------------------------------------------------------
    # Developer console -- a modal overlay, opened from the top bar and
    # closed with ✕. Closing only flips `visible`, so every field, table and
    # selection inside keeps its value for the next time it is opened.
    # -----------------------------------------------------------------
    with gr.Group(visible=False, elem_classes="oppp-modal") as admin_section:
      with gr.Column(elem_classes="oppp-modal-panel"):
        with gr.Row(elem_classes="modal-head"):
            gr.Markdown("### 🛠️ หน้าผู้ดูแลระบบ / Developer", elem_classes="modal-title")
            close_admin_btn = gr.Button("✕", elem_classes="modal-close", scale=0, min_width=46)

        with gr.Tab("📤 อัปโหลด"):
            files = gr.File(label="ไฟล์รายงาน OPPP (.xls) — เลือกได้หลายไฟล์", file_count="multiple", file_types=[".xls"], type="filepath")
            with gr.Row():
                uploader_name = gr.Textbox(label="ผู้บันทึก", placeholder="ชื่อผู้อัปโหลด")
                upload_note = gr.Textbox(
                    label="หมายเหตุ",
                    placeholder="เช่น ข้อมูล ต.ค. 2568 – ก.ค. 2569",
                )
            run = gr.Button("⚙️ ประมวลผลและบันทึกลงฐานข้อมูล", variant="primary")
            gr.Markdown(
                "⚠️ อัปโหลดไฟล์ของรอบใหม่ได้เรื่อยๆ ระบบจะรวมกับข้อมูลเดิมอัตโนมัติ และข้ามรายการที่ซ้ำกับที่มีอยู่แล้วให้เอง "
                "· หมายเหตุจะถูกบันทึกไว้กับไฟล์ชุดนี้และแสดงในประวัติการอัปโหลด",
                elem_classes="hint-text",
            )
            upload_status = gr.Markdown()

        with gr.Tab("🕒 ประวัติ / ย้อนกลับ"):
            with gr.Accordion("🕒 ตารางประวัติการอัปโหลด", open=True):
                batch_table = gr.Dataframe(interactive=False, wrap=True)
            batch_dropdown = gr.Dropdown(label="เลือกไฟล์ที่ต้องการย้อนกลับ/กู้คืน", choices=[])
            with gr.Row():
                rollback_btn = gr.Button("↩️ ย้อนกลับไฟล์นี้")
                restore_btn = gr.Button("♻️ กู้คืนไฟล์นี้")
            batch_status = gr.Markdown()

            with gr.Accordion("🧨 รีเซ็ตระบบกลับเป็นค่าเริ่มต้น", open=False):
                gr.Markdown(
                    "ลบข้อมูลที่อัปโหลดไว้**ทั้งหมด** (ทุกไฟล์ ทุกรอบ รวมถึงสมุดจัดสรรบริการ) "
                    "ให้ระบบว่างเปล่าเหมือนเพิ่งติดตั้งใหม่ เพื่อเริ่มอัปโหลดไฟล์ชุดใหม่\n\n"
                    "⚠️ **ย้อนกลับไม่ได้** — ต่างจากปุ่ม “ย้อนกลับไฟล์นี้” ด้านบนที่ยังกู้คืนได้ "
                    "ต้องมีสิทธิ์ผู้ดูแลระบบ **และ** กรอกรหัสผ่านยืนยันอีกครั้งจึงจะทำงาน",
                    elem_classes="hint-text",
                )
                reset_password = gr.Textbox(
                    label="ยืนยันรหัสผ่านผู้ดูแลระบบ",
                    type="password",
                    placeholder="กรอกรหัสผ่านเดิมอีกครั้งเพื่อยืนยัน",
                )
                reset_btn = gr.Button("🧨 ยืนยันรีเซ็ตระบบทั้งหมด", variant="stop")
                reset_status = gr.Markdown()

        with gr.Tab("🧑‍⚕️ ตรวจสอบรายบุคคล"):
            with gr.Accordion("🧑‍⚕️ ตารางตรวจสอบรายบุคคล", open=True):
                people_table = gr.Dataframe(interactive=False, wrap=True)
            people_excel_btn = gr.DownloadButton("📥 ดาวน์โหลด Excel")
            people_excel_file = gr.File(label="ไฟล์ล่าสุด (สำรอง)")
            people_excel_status = gr.Markdown(elem_classes="hint-text")

        with gr.Tab("🗂️ ข้อมูลต้นทาง"):
            with gr.Accordion("🗂️ ตารางข้อมูลต้นทาง", open=True):
                raw_table = gr.Dataframe(interactive=False, wrap=True)
            raw_download = gr.File(label="ดาวน์โหลด CSV ข้อมูลตรวจแล้ว")
            raw_excel_btn = gr.DownloadButton("📥 ดาวน์โหลด Excel")
            raw_excel_file = gr.File(label="ไฟล์ล่าสุด (สำรอง)")
            raw_excel_status = gr.Markdown(elem_classes="hint-text")

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

            with gr.Accordion("1️⃣ รายชื่อผู้รับบริการ", open=False):
                facility_people_table = gr.Dataframe(interactive=False, wrap=True)

            with gr.Accordion("2️⃣ คาดการณ์บริการรายรายการ", open=False):
                facility_prediction_table = gr.Dataframe(interactive=False, wrap=True)

            with gr.Accordion("3️⃣ สรุปจำนวนรายการ", open=True):
                facility_count_table = gr.Dataframe(interactive=False, wrap=True)

            with gr.Accordion("4️⃣ เปรียบเทียบยอดสปสช. vs ยอดจัดสรรจริง", open=True):
                facility_reconcile_table = gr.Dataframe(interactive=False, wrap=True)

            facility_excel_btn = gr.DownloadButton("📥 ดาวน์โหลด Excel (ทุกตารางในหน้านี้)")
            facility_excel_file = gr.File(label="ไฟล์ล่าสุด (สำรอง)")
            facility_excel_status = gr.Markdown(elem_classes="hint-text")

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
            with gr.Accordion("📒 สมุดจัดสรรบริการ", open=True):
                allocation_table = gr.Dataframe(label="สมุดจัดสรรบริการ", interactive=False, wrap=True)
            with gr.Accordion("💳 ยอดคงเหลือต่อรายการ", open=False):
                remaining_table = gr.Dataframe(label="ยอดคงเหลือต่อรายการ", interactive=False, wrap=True)
            ledger_export_btn = gr.DownloadButton("📥 ดาวน์โหลดสมุดจัดสรร (CSV)")
            ledger_download = gr.File(label="ไฟล์สมุดจัดสรรล่าสุด (สำรอง)")
            ledger_status = gr.Markdown(elem_classes="hint-text")
            allocation_excel_btn = gr.DownloadButton("📥 ดาวน์โหลด Excel (สมุดจัดสรร + ยอดคงเหลือ)")
            allocation_excel_file = gr.File(label="ไฟล์ล่าสุด (สำรอง)")
            allocation_excel_status = gr.Markdown(elem_classes="hint-text")

    admin_view_outputs = [people_table, raw_table, raw_download, allocation_table, code_dropdown, remaining_table]

    # -----------------------------------------------------------------
    # Wiring
    # -----------------------------------------------------------------

    # The KPIs land first, then the slower tables fill in behind them, so the
    # page is never blank waiting on the heaviest query.
    demo.load(refresh_dashboard, outputs=dashboard_outputs).then(
        build_amount_frequency, outputs=frequency_outputs
    ).then(
        refresh_batches, outputs=[batch_table, batch_dropdown, batch_status]
    ).then(
        build_all_facilities_summary, outputs=summary_outputs
    )
    refresh_timer.tick(refresh_dashboard, outputs=dashboard_outputs).then(
        build_amount_frequency, outputs=frequency_outputs
    )
    summary_timer.tick(build_all_facilities_summary, outputs=summary_outputs)

    ranking_table.select(on_select_facility, outputs=[breakdown_label, breakdown_table])

    facility_dropdown.change(
        analyze_facility_ui,
        inputs=facility_dropdown,
        outputs=[facility_people_table, facility_prediction_table, facility_count_table, facility_reconcile_table],
    )

    # --- Theme toggle: pure client-side so the choice survives reloads ---
    # The class goes on <html> so it also covers <body> and Gradio's own
    # wrappers, which sit outside .gradio-container and kept their dark
    # background when the class lived on the container.
    theme_btn.click(
        None, None, theme_btn,
        js="""() => {
            const light = document.documentElement.classList.toggle('oppp-light');
            localStorage.setItem('oppp-theme', light ? 'light' : 'dark');
            return light ? '☀️' : '🌙';
        }""",
    )
    demo.load(
        None, None, theme_btn,
        js="""() => {
            const light = localStorage.getItem('oppp-theme') === 'light';
            document.documentElement.classList.toggle('oppp-light', light);
            return light ? '☀️' : '🌙';
        }""",
    )

    # --- Modal open/close. Closing only hides the group, so everything
    #     inside keeps its value for the next time it is opened. ---
    open_login_btn.click(lambda: gr.update(visible=True), outputs=login_modal)
    close_login_btn.click(lambda: gr.update(visible=False), outputs=login_modal)
    open_admin_btn.click(lambda: gr.update(visible=True), outputs=admin_section)
    close_admin_btn.click(lambda: gr.update(visible=False), outputs=admin_section)

    def after_login(role: str):
        """On success: close the login modal, open the console, and reveal the
        admin-only buttons. On failure: keep the modal open showing the error."""
        is_admin = role == "admin"
        return (
            gr.update(visible=is_admin),      # open_admin_btn
            gr.update(visible=is_admin),      # logout_btn
            gr.update(visible=not is_admin),  # login_modal -- stays open on failure
            gr.update(visible=is_admin),      # admin_section
            gr.update(visible=not is_admin),  # open_login_btn
        )

    login_targets = [open_admin_btn, logout_btn, login_modal, admin_section, open_login_btn]
    for event in (
        login_btn.click(login, inputs=[username_box, password_box], outputs=[role_state, login_status]),
        username_box.submit(login, inputs=[username_box, password_box], outputs=[role_state, login_status]),
        password_box.submit(login, inputs=[username_box, password_box], outputs=[role_state, login_status]),
    ):
        event.then(
            after_login, inputs=role_state, outputs=login_targets
        ).then(
            refresh_admin_views, inputs=role_state, outputs=admin_view_outputs
        ).then(
            refresh_batches, outputs=[batch_table, batch_dropdown, batch_status]
        ).then(lambda: "", outputs=password_box)

    logout_btn.click(logout, outputs=[role_state, login_status]).then(
        lambda: (
            gr.update(visible=False),  # admin_section
            gr.update(visible=False),  # open_admin_btn
            gr.update(visible=False),  # logout_btn
            gr.update(visible=False),  # login_modal
            gr.update(visible=True),   # open_login_btn
        ),
        outputs=[admin_section, open_admin_btn, logout_btn, login_modal, open_login_btn],
    )

    run.click(
        process_upload, inputs=[files, uploader_name, upload_note], outputs=[upload_status, files]
    ).then(
        refresh_dashboard, outputs=dashboard_outputs
    ).then(
        build_amount_frequency, outputs=frequency_outputs
    ).then(
        refresh_batches, outputs=[batch_table, batch_dropdown, batch_status]
    ).then(
        refresh_admin_views, inputs=role_state, outputs=admin_view_outputs
    ).then(
        build_all_facilities_summary, outputs=summary_outputs
    )

    rollback_btn.click(rollback_selected, inputs=batch_dropdown, outputs=batch_status).then(
        refresh_batches, outputs=[batch_table, batch_dropdown, batch_status]
    ).then(refresh_dashboard, outputs=dashboard_outputs).then(
        build_amount_frequency, outputs=frequency_outputs
    ).then(
        refresh_admin_views, inputs=role_state, outputs=admin_view_outputs
    ).then(
        build_all_facilities_summary, outputs=summary_outputs
    )

    reset_btn.click(
        reset_system, inputs=[role_state, reset_password], outputs=[reset_status, reset_password]
    ).then(
        refresh_batches, outputs=[batch_table, batch_dropdown, batch_status]
    ).then(refresh_dashboard, outputs=dashboard_outputs).then(
        build_amount_frequency, outputs=frequency_outputs
    ).then(
        refresh_admin_views, inputs=role_state, outputs=admin_view_outputs
    ).then(
        build_all_facilities_summary, outputs=summary_outputs
    )

    restore_btn.click(restore_selected, inputs=batch_dropdown, outputs=batch_status).then(
        refresh_batches, outputs=[batch_table, batch_dropdown, batch_status]
    ).then(refresh_dashboard, outputs=dashboard_outputs).then(
        build_amount_frequency, outputs=frequency_outputs
    ).then(
        refresh_admin_views, inputs=role_state, outputs=admin_view_outputs
    ).then(
        build_all_facilities_summary, outputs=summary_outputs
    )

    add_btn.click(
        add_allocation_db,
        inputs=[role_state, code_dropdown, money_type_radio, service_box, amount_box, note_box, recorder_box],
        outputs=allocation_status,
    ).then(refresh_admin_views, inputs=role_state, outputs=admin_view_outputs)

    # Each handler writes the generated file back into the button that was
    # clicked. gr.DownloadButton's own frontend does not reliably turn that
    # value into a link, so a chained JS step reads the FileData the button now
    # holds and starts the download itself -- one click, one file, no second
    # link to hunt for. It must be `.then(...)`, not a separate `.click(...)`,
    # or it would run against the button's previous (stale) value.
    TRIGGER_DOWNLOAD_JS = """(f) => {
        if (!f || !f.url) return;
        const a = document.createElement('a');
        a.href = f.url;
        a.download = f.orig_name || '';
        document.body.appendChild(a);
        a.click();
        a.remove();
    }"""

    def wire_download(button, fn, inputs, file_box, status):
        """Generate the file, put it in both the button (which the JS step then
        downloads) and a visible File box.

        The box is the fallback: a browser that blocks the scripted download, or
        a user who simply misses it, still has something to click. Relying on
        the scripted download alone left nothing on screen at all.
        """

        def run(*args):
            path, message = fn(*args)
            return path, path, message

        button.click(run, inputs=inputs, outputs=[button, file_box, status]).then(
            None, inputs=button, outputs=None, js=TRIGGER_DOWNLOAD_JS
        )

    wire_download(
        ranking_excel_btn,
        lambda df: export_excel(df, "สรุปยอดชดเชยรายหน่วยบริการ"),
        ranking_table, ranking_excel_file, ranking_excel_status,
    )
    wire_download(
        people_excel_btn,
        lambda df: export_excel(df, "ตรวจสอบรายบุคคล"),
        people_table, people_excel_file, people_excel_status,
    )
    wire_download(
        raw_excel_btn,
        lambda df: export_excel(df, "ข้อมูลต้นทาง"),
        raw_table, raw_excel_file, raw_excel_status,
    )
    wire_download(
        facility_excel_btn,
        lambda a, b, c, d: export_excel_sheets(
            "วิเคราะห์รายบริการ",
            รายชื่อผู้รับบริการ=a, คาดการณ์บริการ=b, สรุปจำนวนรายการ=c, เปรียบเทียบยอด=d,
        ),
        [facility_people_table, facility_prediction_table, facility_count_table, facility_reconcile_table],
        facility_excel_file, facility_excel_status,
    )
    wire_download(
        summary_excel_btn,
        export_all_facilities_excel,
        all_facilities_data, summary_excel_file, summary_excel_status,
    )
    wire_download(
        allocation_excel_btn,
        lambda a, b: export_excel_sheets("จัดสรรบริการ", สมุดจัดสรรบริการ=a, ยอดคงเหลือต่อรายการ=b),
        [allocation_table, remaining_table], allocation_excel_file, allocation_excel_status,
    )
    wire_download(
        ledger_export_btn,
        export_ledger_csv,
        None, ledger_download, ledger_status,
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
        allowed_paths=[EXPORT_DIR],
    )
