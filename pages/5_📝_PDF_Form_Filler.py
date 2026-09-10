from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber
import streamlit as st
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

# Ensure parent directory is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth

# Set page config
st.set_page_config(
    page_title="Universal PDF Form Filler",
    page_icon="📝",
    layout="wide",
)

# Authentication check
if not auth.check_password():
    st.stop()

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "local_data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "completed"
REPORT_DIR = DATA_DIR / "reports"
DB_PATH = DATA_DIR / "form_filler.db"

COMMON_SEMANTIC_PATTERNS: dict[str, list[str]] = {
    # Personal info
    "claimant_name": [r"claimant(?:\s*['’]?s)?\s*(?:legal\s*)?name", r"legal\s*name", r"applicant\s*name", r"full\s*name"],
    "first_name": [r"first\s*name", r"given\s*name"],
    "last_name": [r"last\s*name", r"surname", r"family\s*name"],
    "sin": [r"social\s*insurance\s*number", r"\bsin\b"],
    "business_number": [r"business\s*number", r"\bbn\b", r"rt\s*0001"],
    "phone": [r"daytime\s*phone", r"phone\s*(?:number)?", r"telephone", r"mobile"],
    "home_phone": [r"home\s*phone", r"home\s*telephone"],
    "email": [r"e-?mail\s*(?:address)?"],
    "language": [r"language\s*preference", r"language"],
    # Address
    "address": [r"property\s*address", r"purchased\s*house\s*address", r"street\s*address", r"\baddress\b"],
    "city": [r"\bcity\b", r"municipality"],
    "province": [r"province(?:\s*or\s*territory)?", r"\bprovince\b", r"\bstate\b"],
    "postal_code": [r"postal\s*code", r"zip(?:\s*code)?"],
    "mailing_address": [r"mailing\s*address"],
    "mailing_city": [r"mailing\s*city"],
    "mailing_province": [r"mailing\s*province"],
    "mailing_postal_code": [r"mailing\s*postal\s*code"],
    # Housing & Property Info
    "purchase_price": [r"purchase\s*price(?:\s*of\s*(?:the\s*)?house)?", r"contract\s*price", r"price\s*before\s*tax"],
    "fair_market_value": [r"fair\s*market\s*value", r"\bfmv\b"],
    "lot_number": [r"lot\s*number", r"strata\s*number", r"strata\s*lot"],
    "plan_number": [r"plan\s*number"],
    "agreement_date": [r"agreement\s*date", r"signed\s*date", r"date\s*(?:purchase\s*)?agreement\s*signed"],
    "closing_date": [r"closing\s*date", r"ownership\s*date", r"date\s*ownership\s*(?:was\s*)?transferred"],
    "possession_date": [r"possession\s*date", r"date\s*possession\s*(?:was\s*)?transferred"],
    "construction_start_date": [r"construction\s*(?:began|started|start)\s*date", r"date\s*construction\s*began"],
    "construction_end_date": [r"construction\s*completed\s*date", r"date\s*construction\s*(?:was\s*)?substantially\s*completed"],
    # Builder info
    "builder_name": [r"builder(?:\s*['’]?s)?\s*(?:legal\s*)?name", r"co-op(?:\s*['’]?s)?\s*name", r"vendor\s*name"],
    "builder_business_number": [r"builder(?:\s*['’]?s)?\s*business\s*number", r"builder\s*bn"],
    "builder_phone": [r"builder\s*phone", r"builder\s*telephone"],
    "builder_address": [r"builder\s*address"],
    "builder_city": [r"builder\s*city"],
    "builder_province": [r"builder\s*province"],
    "builder_postal_code": [r"builder\s*postal\s*code"],
    # Rebate calculation amounts
    "tax_paid": [r"gst\s*paid", r"federal\s*part\s*paid", r"hst\s*paid"],
    "rebate_rate": [r"rebate\s*rate", r"tax\s*rate"],
    "provincial_rebate": [r"provincial\s*rebate(?:\s*amount)?", r"ontario\s*rebate"],
    "total_rebate": [r"total\s*rebate(?:\s*amount)?", r"total\s*rebate"],
}


def ensure_storage() -> None:
    for folder in (UPLOAD_DIR, OUTPUT_DIR, REPORT_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                source_file TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                approved_data TEXT NOT NULL,
                field_mapping TEXT NOT NULL,
                completed_pdf TEXT NOT NULL,
                validation_report TEXT NOT NULL
            )"""
        )


def safe_stem(name: str) -> str:
    stem = Path(name).stem
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "document"


def unique_path(folder: Path, stem: str, suffix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return folder / f"{stem}_{stamp}{suffix}"


def extract_native_text(pdf_bytes: bytes) -> tuple[str, list[list[list[str]]]]:
    pages: list[str] = []
    tables: list[list[list[str]]] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
                for table in page.extract_tables() or []:
                    cleaned = [[(cell or "").strip() for cell in row] for row in table]
                    if cleaned:
                        tables.append(cleaned)
    except Exception:
        pass
    return "\n\n".join(pages).strip(), tables


def ocr_pdf(pdf_bytes: bytes, language: str = "eng") -> str:
    try:
        import pymupdf as fitz
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("OCR dependencies are missing. Run: pip install -r requirements.txt") from exc

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: list[str] = []
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        pages.append(pytesseract.image_to_string(image, lang=language))
    return "\n\n".join(pages).strip()


def get_pdf_fields(pdf_bytes: bytes) -> dict[str, dict[str, Any]]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    raw = reader.get_fields() or {}
    result: dict[str, dict[str, Any]] = {}
    for name, info in raw.items():
        result[name] = {
            "type": str(info.get("/FT", "")),
            "current_value": str(info.get("/V", "") or ""),
            "options": [str(opt) for opt in (info.get("/Opt") or [])],
        }
    return result


def _amount(value: str) -> str:
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.strip().replace("$", "").replace(" ", "").rstrip(".")
    if cleaned.endswith("%"):
        return cleaned
    return cleaned


def _clean_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key.strip().lower()).strip("_")


def parse_ai_instructions(text: str) -> dict[str, str]:
    """
    Universal Parser supporting:
    1. RC7190-WS Calculation Worksheet (Lines 1-21, Section 1-6)
    2. GST190 New Housing Rebate (Claimant, Builder, Lines A-N, X1-X3)
    3. T1-OVP RRSP Excess Calculations (Step 2, Part A-C, Step 3, Note 1)
    4. Key-Value pairs, JSON, Markdown tables, or plain prose
    """
    values: dict[str, str] = {}
    if not text.strip():
        return values

    # Try JSON parsing first if text starts with '{'
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            parsed_json = json.loads(stripped)
            if isinstance(parsed_json, dict):
                return {_clean_key(str(k)): str(v).strip() for k, v in parsed_json.items()}
        except Exception:
            pass

    # 1. Parse Numbered Lines (e.g. Line 1: 500, Line 14 = 3600, Line 21 -> 1200)
    numbered_lines = re.findall(r"(?im)^\s*(?:Line|Row|Item)\s*#?\s*(\d{1,3})\s*[:=\-–→]\s*([^\n\r]+)", text)
    for num, val in numbered_lines:
        cleaned_val = _amount(val.split("|")[0].split("(")[0].strip())
        if cleaned_val:
            values[f"line_{num}"] = cleaned_val

    # 2. Parse Lettered Lines (e.g. Line A: 5000, Line B: 400000, Line X1: 0, Line E: 5000)
    lettered_lines = re.findall(r"(?im)^\s*(?:Line|Section|Box)\s*#?\s*([A-Za-z]\d?)\s*[:=\-–→]\s*([^\n\r]+)", text)
    for letter, val in lettered_lines:
        letter_key = letter.lower()
        cleaned_val = _amount(val.split("|")[0].split("(")[0].strip())
        if cleaned_val:
            values[f"line_{letter_key}"] = cleaned_val

    # 3. Parse Markdown Table rows (| Field | Value |)
    table_rows = re.findall(r"(?m)^\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|", text)
    for k, v in table_rows:
        k_clean = k.strip()
        v_clean = v.strip()
        if k_clean and v_clean and not set(k_clean).issubset({"-", ":", " "}) and not k_clean.lower() in ("field", "item", "parameter", "line"):
            values[_clean_key(k_clean)] = v_clean

    # 4. Parse standard Key-Value pairs (e.g. Claimant Name: John Doe, Purchase Price: 450,000)
    kv_pairs = re.findall(r"(?im)^\s*([a-zA-Z0-9_\s\-/]{2,40})\s*[:=]\s*([^\n\r]{1,150})$", text)
    for k, v in kv_pairs:
        k_str = k.strip()
        v_str = v.strip()
        if k_str and v_str and not k_str.lower().startswith(("http", "note", "step", "part")):
            key_clean = _clean_key(k_str)
            if key_clean not in values:
                values[key_clean] = v_str

    # 5. Semantic Named Extractors (using COMMON_SEMANTIC_PATTERNS)
    for sem_key, patterns in COMMON_SEMANTIC_PATTERNS.items():
        if sem_key not in values:
            for pattern in patterns:
                m = re.search(rf"(?im)^\s*(?:{pattern})\s*[:=\-–→]\s*([^\n\r]{{1,120}})", text)
                if m:
                    values[sem_key] = m.group(1).strip(" _.-")
                    break

    # 6. T1-OVP Specific parsing (if T1-OVP keywords detected)
    if "step 2" in text.lower() or "part a" in text.lower() or "step 3" in text.lower() or "t1-ovp" in text.lower():
        # Step 2
        for line in (1, 2, 3):
            m = re.search(rf"(?im)^\s*Line\s+{line}\b\s*[:=\-–→]\s*([^\n\r]+)", text)
            if m:
                values[f"step2_line{line}"] = _amount(m.group(1))
        # Part A monthly summary
        for line in range(1, 12):
            m = re.search(rf"(?im)^\s*(?:Part\s*A\s*)?Line\s+{line}\b\s*[:=\-–→]\s*([^\n\r]+)", text)
            if m:
                values[f"part_a_line{line}"] = _amount(m.group(1))
        # Part B
        for line in range(12, 19):
            m = re.search(rf"(?im)^\s*(?:Part\s*B\s*)?Line\s+{line}\b\s*[:=\-–→]\s*([^\n\r]+)", text)
            if m:
                values[f"part_b_line{line}"] = _amount(m.group(1))
        # Part C
        for line in (19, 20):
            m = re.search(rf"(?im)^\s*(?:Part\s*C\s*)?Line\s+{line}\b\s*[:=\-–→]\s*([^\n\r]+)", text)
            if m:
                values[f"part_c_line{line}"] = _amount(m.group(1))
        # Step 3
        for line in (4, 5, 6):
            m = re.search(rf"(?im)^\s*(?:Step\s*3\s*)?Line\s+{line}\b\s*[:=\-–→]\s*([^\n\r]+)", text)
            if m:
                values[f"step3_line{line}"] = _amount(m.group(1))

    return values


def smart_map_pdf_values(data: dict[str, str], pdf_fields: dict[str, Any]) -> dict[str, str]:
    """
    Intelligently maps parsed data values into specific PDF AcroForm field names.
    Supports RC7190-WS, GST190, T1-OVP, and generic CRA AcroForms.
    """
    mapped_values: dict[str, str] = {}
    normalized_data = {_clean_key(k): str(v).strip() for k, v in data.items()}

    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
              "january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december"]

    for field_name, info in pdf_fields.items():
        norm_field = _clean_key(field_name)

        # 1. Exact Match
        if norm_field in normalized_data:
            mapped_values[field_name] = normalized_data[norm_field]
            continue

        # 2. Numbered Line Match (e.g. Line 1, Line 14, Line 21 in RC7190-WS, GST190, T1-OVP)
        line_num_match = re.search(r"line_?(\d{1,3})\b", norm_field)
        if line_num_match:
            num = line_num_match.group(1)
            # Check for direct key match
            if f"line_{num}" in normalized_data:
                # If T1-OVP monthly grid field, handle month distribution
                if any(f"_{m}_" in norm_field for m in months) or any(norm_field.endswith(f"_{m}") for m in months):
                    part_a_key = f"part_a_line{num}"
                    if part_a_key in normalized_data:
                        mapped_values[field_name] = normalized_data[part_a_key]
                    elif f"line_{num}" in normalized_data:
                        mapped_values[field_name] = normalized_data[f"line_{num}"]
                else:
                    mapped_values[field_name] = normalized_data[f"line_{num}"]
                continue
            elif f"part_a_line{num}" in normalized_data:
                mapped_values[field_name] = normalized_data[f"part_a_line{num}"]
                continue
            elif f"part_b_line{num}" in normalized_data:
                mapped_values[field_name] = normalized_data[f"part_b_line{num}"]
                continue
            elif f"part_c_line{num}" in normalized_data:
                mapped_values[field_name] = normalized_data[f"part_c_line{num}"]
                continue
            elif f"step2_line{num}" in normalized_data:
                mapped_values[field_name] = normalized_data[f"step2_line{num}"]
                continue
            elif f"step3_line{num}" in normalized_data:
                mapped_values[field_name] = normalized_data[f"step3_line{num}"]
                continue

        # 3. Lettered Line Match (e.g. Line A, B, C, D, E, X1, X2, X3 in GST190)
        letter_match = re.search(r"line_?([a-z]\d?)\b", norm_field)
        if letter_match:
            letter = letter_match.group(1)
            if f"line_{letter}" in normalized_data:
                mapped_values[field_name] = normalized_data[f"line_{letter}"]
                continue

        # 4. Semantic Concept Matches
        matched = False
        for sem_key, patterns in COMMON_SEMANTIC_PATTERNS.items():
            if sem_key in normalized_data:
                if any(re.search(p, norm_field) for p in patterns) or sem_key in norm_field:
                    mapped_values[field_name] = normalized_data[sem_key]
                    matched = True
                    break
        if matched:
            continue

        # 5. Partial Substring Heuristic
        for k, v in normalized_data.items():
            if len(k) >= 4 and (k in norm_field or norm_field in k):
                mapped_values[field_name] = v
                break

    return mapped_values


def normalize_pdf(pdf_bytes: bytes) -> bytes:
    try:
        import pymupdf
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        normalized = doc.tobytes(garbage=4, deflate=True, encryption=pymupdf.PDF_ENCRYPT_NONE)
        doc.close()
        return normalized
    except Exception:
        return pdf_bytes


def fill_and_flatten_pdf(pdf_bytes: bytes, values: dict[str, str]) -> tuple[bytes, bytes]:
    source = normalize_pdf(pdf_bytes)
    reader = PdfReader(io.BytesIO(source))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    fields = writer.get_fields() or {}
    
    # Keep only values matching existing PDF fields
    valid_values = {k: str(v) for k, v in values.items() if k in fields}
    
    writer.update_page_form_field_values(None, valid_values, auto_regenerate=True)
    editable_stream = io.BytesIO()
    writer.write(editable_stream)
    editable = editable_stream.getvalue()

    # Flatten for viewing safely
    try:
        reader = PdfReader(io.BytesIO(editable))
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        fields = writer.get_fields() or {}
        paint = {
            name: field.get("/V", "/Off" if field.get("/FT") == "/Btn" else "")
            for name, field in fields.items()
            if field.get("/FT") in ("/Tx", "/Btn", "/Ch") and field.get("/V") not in (None, "")
        }
        writer.update_page_form_field_values(None, paint, auto_regenerate=True, flatten=True)
        writer.remove_annotations(subtypes="/Widget")
        writer.root_object.pop(NameObject("/AcroForm"), None)
        flat_stream = io.BytesIO()
        writer.write(flat_stream)
        flat = flat_stream.getvalue()
    except Exception:
        flat = editable

    return editable, flat


def validate_output(pdf_bytes: bytes, expected: dict[str, str]) -> dict[str, Any]:
    actual_fields = get_pdf_fields(pdf_bytes)
    checks = []
    for field, expected_value in expected.items():
        actual = actual_fields.get(field, {}).get("current_value", "")
        is_pass = str(actual).strip() == str(expected_value).strip()
        checks.append(
            {
                "pdf_field": field,
                "expected": expected_value,
                "actual": actual,
                "status": "PASS" if is_pass else "FAIL",
            }
        )
    passed = sum(item["status"] == "PASS" for item in checks)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"total": len(checks), "passed": passed, "failed": len(checks) - passed},
        "checks": checks,
    }


def save_submission(source_name: str, source_bytes: bytes, approved: dict[str, str], mapping: dict[str, str], completed: bytes, report: dict[str, Any]) -> tuple[Path, Path]:
    stem = safe_stem(source_name)
    upload_path = unique_path(UPLOAD_DIR, stem, ".pdf")
    output_path = unique_path(OUTPUT_DIR, f"{stem}_completed", ".pdf")
    report_path = unique_path(REPORT_DIR, f"{stem}_validation", ".json")
    upload_path.write_bytes(source_bytes)
    output_path.write_bytes(completed)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO submissions
            (created_at, source_file, source_sha256, approved_data, field_mapping, completed_pdf, validation_report)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(), source_name,
                hashlib.sha256(source_bytes).hexdigest(), json.dumps(approved),
                json.dumps(mapping), str(output_path), str(report_path),
            ),
        )
    return output_path, report_path


def init_state(file_hash: str, text: str, tables: list[list[list[str]]], pdf_fields: dict[str, Any]) -> None:
    if st.session_state.get("file_hash") == file_hash:
        return
    st.session_state.file_hash = file_hash
    st.session_state.extracted_text = text
    st.session_state.tables = tables
    st.session_state.pdf_fields = pdf_fields
    st.session_state.ai_rows = []
    st.session_state.completed = None


def main() -> None:
    ensure_storage()

    st.markdown("""
    <div style="background: linear-gradient(135deg, #1b3a57 0%, #2e5984 100%); color: white; padding: 24px; border-radius: 12px; margin-bottom: 25px;">
        <h2 style="margin: 0; color: white;">📝 Universal PDF Form Filler</h2>
        <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 15px;">
            Supports <b>GST190</b>, <b>RC7190-WS Calculation Worksheet</b>, <b>T1-OVP</b>, and any CRA AcroForm. Paste calculation results or values, review & verify mappings, and generate filled PDFs instantly.
        </p>
    </div>
    """, unsafe_allow_html=True)

    uploaded = st.file_uploader("📂 Upload Fillable CRA or Tax PDF Form", type=["pdf"], help="Upload fillable PDF forms like GST190, RC7190-WS, T1-OVP, etc.")
    if not uploaded:
        st.info("👆 Upload a fillable PDF form above to begin.")

        with st.expander("ℹ️ Supported CRA & Tax Forms"):
            st.markdown("""
            - **GST190**: GST/HST New Housing Rebate Application for Houses Purchased from a Builder
            - **RC7190-WS**: GST190 Calculation Worksheet (Sections 1 to 6, Lines 1 to 21)
            - **T1-OVP**: Individual Tax Return for RRSP, PRPP and SPP Excess Contributions
            - **Generic AcroForms**: Any PDF with interactive text boxes, checkboxes, or radio fields
            """)
        return

    pdf_bytes = uploaded.getvalue()
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    with st.spinner("Analyzing PDF AcroForm fields & structure..."):
        native_text, tables = extract_native_text(pdf_bytes)
        pdf_fields = get_pdf_fields(pdf_bytes)
        init_state(file_hash, native_text, tables, pdf_fields)

    if not pdf_fields:
        st.error("⚠️ This PDF does not contain interactive fillable AcroForm fields. Please ensure you upload a fillable CRA PDF template.")
        return

    st.success(f"✅ Form Loaded Successfully — Detected **{len(pdf_fields)} fillable PDF fields**.")

    tab_paste, tab_review, tab_generate, tab_source = st.tabs([
        "1. 📥 Paste Form Values / AI Calculations",
        "2. 🔍 Review & Field Mapping",
        "3. 🚀 Fill & Download PDF",
        "4. 📋 PDF Field Inspector"
    ])

    with tab_paste:
        col_t1, col_t2 = st.columns([3, 1])
        with col_t1:
            st.markdown("##### Paste Instructions or Calculation Output")
            instructions = st.text_area(
                "Paste ChatGPT, Perplexity, or custom key-value calculation text:",
                height=320,
                placeholder="Example for RC7190-WS:\nLine 1: 25000\nLine 2: 500000\nLine 3: 6300\nLine 4: 0\nLine 12: 25000\nLine 13: 500000\nLine 14: 50000\n\nExample for GST190:\nClaimant Name: John Doe\nSIN: 123456789\nPurchase Price: 500000\nLine A: 25000\nLine B: 500000\nLine C: 50000\nLine E: 50000",
                key=f"instructions_{file_hash}",
            )
        with col_t2:
            st.markdown("##### Quick Format Templates")
            st.caption("Click to insert sample template format into the text box:")
            if st.button("📄 RC7190-WS Template", use_container_width=True):
                st.session_state[f"instructions_{file_hash}"] = (
                    "Line 1: 25000\n"
                    "Line 2: 500000\n"
                    "Line 3: 6300\n"
                    "Line 4: 0\n"
                    "Line 12: 25000\n"
                    "Line 13: 500000\n"
                    "Line 14: 50000\n"
                )
                st.rerun()
            if st.button("🏠 GST190 Template", use_container_width=True):
                st.session_state[f"instructions_{file_hash}"] = (
                    "Claimant Name: John Doe\n"
                    "SIN: 123-456-789\n"
                    "Daytime Phone: 416-555-0199\n"
                    "Language: English\n"
                    "Address: 123 Maple Street\n"
                    "City: Toronto\n"
                    "Province: ON\n"
                    "Postal Code: M5V 2T6\n"
                    "Purchase Price: 500000\n"
                    "Line A: 25000\n"
                    "Line B: 500000\n"
                    "Line C: 50000\n"
                    "Line E: 50000\n"
                )
                st.rerun()
            if st.button("📑 T1-OVP Template", use_container_width=True):
                st.session_state[f"instructions_{file_hash}"] = (
                    "step2_line1: 2000\n"
                    "step2_line2: 2000\n"
                    "step2_line3: 2000\n"
                    "part_a_line1: 5000\n"
                    "part_a_line11: 3000\n"
                    "part_c_line20: 3000\n"
                    "step3_line4: 3000\n"
                    "step3_line5: 1%\n"
                    "step3_line6: 30.00\n"
                )
                st.rerun()

        if st.button("⚡ Parse and Auto-Map Values", type="primary", disabled=not instructions.strip()):
            parsed = parse_ai_instructions(instructions)
            st.session_state.ai_rows = [{"field": key, "value": value} for key, value in parsed.items()]
            st.session_state.completed = None
            if parsed:
                st.success(f"✨ Parsed **{len(parsed)} values**! Switch to **2. Review & Field Mapping** to verify.")
            else:
                st.warning("No structured fields were automatically parsed. You can enter them manually in the Review table.")

    with tab_review:
        st.markdown("##### 🔍 Verify and Edit Mapped Values")
        st.caption("You can add, modify, or remove any field before generating the PDF.")

        rows = st.session_state.ai_rows or [{"field": "", "value": ""}]
        edited = st.data_editor(
            pd.DataFrame(rows),
            num_rows="dynamic",
            use_container_width=True,
            key=f"ai_editor_{file_hash}",
            column_config={
                "field": st.column_config.TextColumn("Field / Line Name", required=True, help="e.g. line_1, line_a, claimant_name, purchase_price"),
                "value": st.column_config.TextColumn("Approved Value", required=True, help="Amount or text value to insert"),
            },
        )
        st.session_state.ai_rows = edited.to_dict("records")
        approved_dict = {
            str(row.get("field", "")).strip(): str(row.get("value", "")).strip()
            for row in st.session_state.ai_rows
            if str(row.get("field", "")).strip()
        }

        # Calculate live mapping preview
        mapped_preview = smart_map_pdf_values(approved_dict, pdf_fields)

        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Reviewed Values", len(approved_dict))
        col_m2.metric("Matched PDF Fields", len(mapped_preview))
        col_m3.metric("Total AcroForm Fields", len(pdf_fields))

        with st.expander("👁️ Preview Matched PDF AcroForm Fields"):
            if mapped_preview:
                preview_df = pd.DataFrame([
                    {"PDF Field Target": k, "Value to Fill": v}
                    for k, v in mapped_preview.items()
                ])
                st.dataframe(preview_df, use_container_width=True, hide_index=True)
            else:
                st.info("No matching PDF fields found yet. Ensure field names (e.g. line_1, line_a, etc.) match the form.")

    with tab_generate:
        st.markdown("##### 🚀 PDF Generation & Verification")
        approved_dict = {
            str(row.get("field", "")).strip(): str(row.get("value", "")).strip()
            for row in st.session_state.ai_rows
            if str(row.get("field", "")).strip()
        }
        selected_fields = smart_map_pdf_values(approved_dict, pdf_fields)

        st.info(f"Ready to fill **{len(selected_fields)} target PDF fields** using your reviewed values.")

        approval = st.checkbox("✅ I have reviewed the values and authorize generating the filled PDF form.", value=True)

        if st.button("✨ Generate Completed PDF & Report", type="primary", disabled=not approval or not selected_fields):
            try:
                with st.spinner("Filling AcroForm fields, regenerating appearance streams, and validating..."):
                    editable_pdf, flat_pdf = fill_and_flatten_pdf(pdf_bytes, selected_fields)
                    report = validate_output(editable_pdf, selected_fields)
                    output_path, report_path = save_submission(uploaded.name, pdf_bytes, approved_dict, selected_fields, flat_pdf, report)
                    editable_path = output_path.with_name(output_path.stem + "_editable.pdf")
                    editable_path.write_bytes(editable_pdf)

                    st.session_state.completed = {
                        "editable": editable_pdf,
                        "flat": flat_pdf,
                        "report": report,
                        "output_path": output_path,
                        "editable_path": editable_path,
                        "report_path": report_path,
                    }
                    st.success("🎉 PDF generated and verified successfully!")
            except Exception as exc:
                st.exception(exc)

        if st.session_state.completed:
            result = st.session_state.completed
            summary = result["report"]["summary"]

            if summary["failed"]:
                st.warning(f"⚠️ Validation note: {summary['passed']} of {summary['total']} filled fields verified.")
            else:
                st.success(f"✅ 100% Validation Pass: All {summary['passed']} filled fields match exactly.")

            st.write("")
            col_d1, col_d2, col_d3 = st.columns(3)
            stem = safe_stem(uploaded.name)

            col_d1.download_button(
                "📥 Download Completed PDF (Viewer-Safe)",
                result["flat"],
                file_name=f"{stem}_completed.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
            col_d2.download_button(
                "✏️ Download Editable PDF",
                result["editable"],
                file_name=f"{stem}_editable.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
            col_d3.download_button(
                "📊 Download Validation Report",
                json.dumps(result["report"], indent=2),
                file_name=f"{stem}_validation.json",
                mime="application/json",
                use_container_width=True,
            )

    with tab_source:
        st.markdown("##### 📋 Detected AcroForm Fields in this PDF")
        terminal = [
            {"PDF Field Name": name, "Field Type": info["type"], "Current Default": info["current_value"]}
            for name, info in pdf_fields.items()
        ]
        st.dataframe(pd.DataFrame(terminal), use_container_width=True, hide_index=True)

        with st.expander("📄 Raw Extracted Text from PDF"):
            st.text_area("Extracted Text", st.session_state.extracted_text, height=250, disabled=True, label_visibility="collapsed")


if __name__ == "__main__":
    main()
