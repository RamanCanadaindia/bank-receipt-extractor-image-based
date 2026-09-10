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

# Ensure parent directory is in path since we are in pages/
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth

# Set page config
st.set_page_config(
    page_title="PDF Form Filler",
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

COMMON_FIELDS = {
    "first_name": [r"first\s*name"],
    "last_name": [r"last\s*name", r"surname"],
    "full_name": [r"(?:full\s*)?name"],
    "date_of_birth": [r"date\s*of\s*birth", r"\bdob\b"],
    "email": [r"e-?mail"],
    "phone": [r"phone", r"telephone", r"mobile"],
    "address": [r"street\s*address", r"address"],
    "city": [r"city"],
    "state": [r"state|province"],
    "postal_code": [r"zip|postal\s*code"],
    "company": [r"company|organization|employer"],
    "date": [r"\bdate\b"],
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
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
            for table in page.extract_tables() or []:
                cleaned = [[(cell or "").strip() for cell in row] for row in table]
                if cleaned:
                    tables.append(cleaned)
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


def find_labeled_value(text: str, labels: list[str]) -> str:
    for label in labels:
        pattern = rf"(?im)^\s*(?:{label})\s*[:#-]?\s*([^\n]{{1,120}})$"
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip(" _.-")
            if value:
                return value
    return ""


def extract_fields(text: str) -> dict[str, str]:
    fields = {key: find_labeled_value(text, labels) for key, labels in COMMON_FIELDS.items()}
    email = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.I)
    phone = re.search(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}", text)
    if not fields["email"] and email:
        fields["email"] = email.group(0)
    if not fields["phone"] and phone:
        fields["phone"] = phone.group(0)
    return {key: value for key, value in fields.items() if value}


def get_pdf_fields(pdf_bytes: bytes) -> dict[str, dict[str, Any]]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    raw = reader.get_fields() or {}
    result: dict[str, dict[str, Any]] = {}
    for name, info in raw.items():
        result[name] = {
            "type": str(info.get("/FT", "")),
            "current_value": str(info.get("/V", "") or ""),
        }
    return result


def suggest_mapping(pdf_fields: list[str], data_fields: list[str]) -> dict[str, str]:
    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    mapping: dict[str, str] = {}
    for pdf_field in pdf_fields:
        target = normalize(pdf_field)
        exact = next((f for f in data_fields if normalize(f) == target), None)
        partial = next((f for f in data_fields if normalize(f) in target or target in normalize(f)), None)
        mapping[pdf_field] = exact or partial or "— Do not fill —"
    return mapping


def fill_pdf(pdf_bytes: bytes, values: dict[str, str]) -> bytes:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    for page in writer.pages:
        writer.update_page_form_field_values(page, values, auto_regenerate=True)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def validate_output(pdf_bytes: bytes, expected: dict[str, str]) -> dict[str, Any]:
    actual_fields = get_pdf_fields(pdf_bytes)
    checks = []
    for field, expected_value in expected.items():
        actual = actual_fields.get(field, {}).get("current_value", "")
        checks.append(
            {
                "pdf_field": field,
                "expected": expected_value,
                "actual": actual,
                "status": "PASS" if str(actual) == str(expected_value) else "FAIL",
            }
        )
    passed = sum(item["status"] == "PASS" for item in checks)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"total": len(checks), "passed": passed, "failed": len(checks) - passed},
        "checks": checks,
    }


def _amount(value: str) -> str:
    cleaned = value.replace("$", "").replace(" ", "").strip().rstrip(".")
    if cleaned.endswith("%"):
        return cleaned
    return cleaned


def _section(text: str, start: str, ends: list[str]) -> str:
    match = re.search(start, text, re.I)
    if not match:
        return ""
    tail = text[match.end():]
    positions = [m.start() for end in ends if (m := re.search(end, tail, re.I))]
    return tail[:min(positions)] if positions else tail


def _last_number(block: str) -> str:
    matches = re.findall(r"(?<![A-Za-z])(?:\$\s*)?-?\d[\d,]*(?:\.\d+)?%?", block)
    candidates = []
    for item in matches:
        value = _amount(item)
        bare = value.replace(",", "").replace("-", "").replace("%", "")
        if bare in {"2022", "2023", "2024", "2025", "2026", "20800"}:
            continue
        candidates.append(value)
    return candidates[-1] if candidates else ""


def _parse_numbered_lines(section: str, line_numbers: list[int]) -> dict[int, str]:
    found: dict[int, str] = {}
    for index, number in enumerate(line_numbers):
        next_numbers = line_numbers[index + 1:]
        end = "|".join(rf"(?:^|\n)\s*Line\s+{n}\b" for n in next_numbers)
        pattern = rf"(?:^|\n)\s*Line\s+{number}\b(.*?)(?={end or r'\Z'})"
        match = re.search(pattern, section, re.I | re.S)
        if match:
            value = _last_number(match.group(1))
            if value:
                found[number] = value
    return found


def parse_ai_instructions(text: str) -> dict[str, str]:
    """Parse common ChatGPT/Perplexity T1-OVP prose into reviewable values."""
    values: dict[str, str] = {}
    step2 = _section(text, r"Step\s*2", [r"Part\s*A"])
    for line, value in _parse_numbered_lines(step2, [1, 2, 3]).items():
        values[f"step2_line{line}"] = value

    part_a = _section(text, r"Part\s*A", [r"Part\s*B"])
    summary = re.search(r"(?:per month|Part A values).*?(?=Part\s*B|\Z)", part_a, re.I | re.S)
    summary_text = summary.group(0) if summary else part_a
    summary_rows = dict(re.findall(r"(?m)^\s*(?:Line\s*)?(1[01]|[1-9])\s*:\s*\$?\s*(-?[\d,]+(?:\.\d+)?)", summary_text))
    if summary_rows:
        for line, value in summary_rows.items():
            values[f"part_a_line{line}"] = _amount(value)
    else:
        for line, value in _parse_numbered_lines(part_a, list(range(1, 12))).items():
            values[f"part_a_line{line}"] = value

    part_c = _section(text, r"Part\s*C", [r"Step\s*3"])
    for line, value in _parse_numbered_lines(part_c, [19, 20]).items():
        values[f"part_c_line{line}"] = value
    monthly_excess = re.search(r"Monthly excess[^:\n]*:\s*\$?\s*([\d,]+(?:\.\d+)?)", part_c, re.I)
    if monthly_excess:
        values["part_c_line20"] = _amount(monthly_excess.group(1))

    step3 = _section(text, r"Step\s*3", [])
    for line, value in _parse_numbered_lines(step3, [4, 5, 6]).items():
        values[f"step3_line{line}"] = value

    year_total = re.search(r"(?:Year total|total for the year).*?(?:=|→)\s*\$?\s*([\d,]+(?:\.\d+)?)", text, re.I | re.S)
    if year_total:
        values["step3_line4"] = _amount(year_total.group(1))
    tax = re.search(r"(?:Balance owing|Tax on RRSP excess contributions).*?(?:=|→)\s*\$?\s*([\d,]+\.\d{2})", text, re.I | re.S)
    if tax:
        values["step3_line6"] = _amount(tax.group(1))
    values.setdefault("step3_line5", "1%")

    if re.search(r"Lines?\s*12\s*[–-]\s*18.*?(?:0|blank)", text, re.I | re.S):
        for line in range(12, 19):
            values[f"part_b_line{line}"] = "0"

    # Optional concise Note 1 syntax: note1_row1_year, note1_row1_a ...
    note = _section(text, r"Note\s*1", [r"Step\s*2", r"Part\s*A"])
    year = re.search(r"Year\s*:\s*(20\d{2})", note, re.I)
    if year:
        values["note1_row1_year"] = year.group(1)
        for column, label in (("a", "Column A"), ("b", "Column B"), ("c", "Column C"), ("d", "Column D"), ("e", "Column E")):
            block = _section(note, label, [rf"Column\s+{chr(ord(column.upper()) + 1)}", r"Step\s*2"])
            amount = _last_number(block)
            if amount:
                values[f"note1_row1_{column}"] = amount
    return values


def build_t1ovp_pdf_values(data: dict[str, str], pdf_fields: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
              "January", "February", "March", "April", "June", "July", "August", "September", "October", "November", "December"]
    for name, info in pdf_fields.items():
        if info.get("type") != "/Tx":
            continue
        for line in (1, 2, 3):
            if f"step2_line{line}" in data and f".Step2_content[0].line{line}[0]." in name:
                values[name] = data[f"step2_line{line}"]
        for line in range(1, 12):
            key = f"part_a_line{line}"
            if key in data and "Page2[0]" in name and f".line{line}[0]." in name and any(f".{m}[0]" in name for m in months):
                values[name] = data[key]
        for line in range(12, 19):
            key = f"part_b_line{line}"
            if key in data and "Page3[0]" in name and f".Line{line}[0]." in name:
                values[name] = data[key]
        for line in (19, 20):
            key = f"part_c_line{line}"
            if key in data and "Page3[0]" in name and f".line{line}[0]." in name:
                values[name] = data[key]
        if "step3_line4" in data and ".Step3_border[0].line4[0]." in name:
            values[name] = data["step3_line4"]
        if "step3_line5" in data and ".Step3_border[0].line5[0]." in name and info.get("type") == "/Tx":
            values[name] = data["step3_line5"]
        if "step3_line6" in data and ".Step3_border[0].line6[0]." in name:
            values[name] = data["step3_line6"]
        if "step3_line4" in data and "Page3[0]" in name and ".Total_amount[0]" in name:
            values[name] = data["step3_line4"]

    note_names = {
        "year": ["Date[0]"], "a": ["Unused_ColumnA[0]", "Unused_Contribution[0]"],
        "b": ["Contribution_Year[0]"], "c": ["PlanPayments[0]", "PlanPayment[0]"],
        "d": ["RowMath[0]"], "e": ["Contribution_Deducted[0]"],
    }
    for row in (1, 2, 3):
        for column, suffixes in note_names.items():
            key = f"note1_row{row}_{column}"
            if key not in data:
                continue
            for name in pdf_fields:
                if f".Row{row}[0]." in name and any(name.endswith(suffix) for suffix in suffixes):
                    values[name] = data[key]
    return values


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
    missing = sorted(set(values) - set(fields))
    if missing:
        raise ValueError(f"PDF fields were not found: {missing[:5]}")
    writer.update_page_form_field_values(None, values, auto_regenerate=False)
    editable_stream = io.BytesIO()
    writer.write(editable_stream)
    editable = editable_stream.getvalue()

    reader = PdfReader(io.BytesIO(editable))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    fields = writer.get_fields() or {}
    paint = {name: field.get("/V", "/Off" if field.get("/FT") == "/Btn" else "") for name, field in fields.items() if field.get("/FT") in ("/Tx", "/Btn", "/Ch") and field.get("/V") not in (None, "")}
    writer.update_page_form_field_values(None, paint, auto_regenerate=False, flatten=True)
    writer.remove_annotations(subtypes="/Widget")
    writer.root_object.pop(NameObject("/AcroForm"), None)
    flat_stream = io.BytesIO()
    writer.write(flat_stream)
    return editable, flat_stream.getvalue()


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


def init_state(file_hash: str, text: str, tables: list[list[list[str]]], fields: dict[str, str], pdf_fields: dict[str, Any]) -> None:
    if st.session_state.get("file_hash") == file_hash:
        return
    st.session_state.file_hash = file_hash
    st.session_state.extracted_text = text
    st.session_state.tables = tables
    st.session_state.field_rows = [{"field": key, "value": value} for key, value in fields.items()] or [{"field": "", "value": ""}]
    st.session_state.pdf_fields = pdf_fields
    st.session_state.mapping = suggest_mapping(list(pdf_fields), list(fields))
    st.session_state.ai_rows = []
    st.session_state.completed = None


def main() -> None:
    ensure_storage()
    st.title("📝 PDF Form Filler")
    st.caption("Upload a form, paste instructions from ChatGPT or Perplexity, review, and fill it accurately.")

    uploaded = st.file_uploader("Upload a fillable PDF", type=["pdf"])
    if not uploaded:
        st.info("Upload a PDF to begin.")
        return
    pdf_bytes = uploaded.getvalue()
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    with st.spinner("Reading PDF fields and layout..."):
        native_text, tables = extract_native_text(pdf_bytes)
        pdf_fields = get_pdf_fields(pdf_bytes)
        init_state(file_hash, native_text, tables, {}, pdf_fields)

    st.success(f"Form ready — found {len(pdf_fields)} PDF fields.")
    if not pdf_fields:
        st.error("This PDF has no fillable fields. Use a fillable PDF template.")
        return

    tab_paste, tab_review, tab_generate, tab_source = st.tabs([
        "1. Paste AI instructions", "2. Review values", "3. Fill and download", "Form details"
    ])

    with tab_paste:
        instructions = st.text_area(
            "Paste the complete answer from ChatGPT or Perplexity",
            height=380,
            placeholder="Paste Step 2, Part A, Part B, Part C, Step 3, and optional Note 1 instructions here...",
            key=f"instructions_{file_hash}",
        )
        if st.button("Parse instructions", type="primary", disabled=not instructions.strip()):
            parsed = parse_ai_instructions(instructions)
            st.session_state.ai_rows = [{"field": key, "value": value} for key, value in parsed.items()]
            st.session_state.completed = None
            if parsed:
                st.success(f"Parsed {len(parsed)} review values. Open Review values and confirm them.")
            else:
                st.error("No recognizable T1-OVP values were found. Add them manually in Review values.")
        st.caption("Parsing runs securely. No PDF or pasted text is sent to an external service.")

    with tab_review:
        st.write("Verify every value. Correct rows, remove them, or add missing semantic fields.")
        rows = st.session_state.ai_rows or [{"field": "", "value": ""}]
        edited = st.data_editor(
            pd.DataFrame(rows), num_rows="dynamic", use_container_width=True, key=f"ai_editor_{file_hash}",
            column_config={
                "field": st.column_config.TextColumn("Form value", required=True),
                "value": st.column_config.TextColumn("Approved amount", required=True),
            },
        )
        st.session_state.ai_rows = edited.to_dict("records")
        approved = {str(row.get("field", "")).strip(): _amount(str(row.get("value", ""))) for row in st.session_state.ai_rows if str(row.get("field", "")).strip()}
        mapped_preview = build_t1ovp_pdf_values(approved, pdf_fields)
        col1, col2, col3 = st.columns(3)
        col1.metric("Reviewed values", len(approved))
        col2.metric("PDF fields to fill", len(mapped_preview))
        col3.metric("Total PDF fields", len(pdf_fields))
        required = ["step2_line1", "step2_line2", "step2_line3", "part_a_line1", "part_a_line11", "part_c_line20", "step3_line4", "step3_line6"]
        missing = [item for item in required if item not in approved]
        if missing:
            st.warning("Still missing key values: " + ", ".join(missing))
        with st.expander("Semantic field guide"):
            st.code(
                "step2_line1 ... step2_line3\n"
                "part_a_line1 ... part_a_line11\n"
                "part_b_line12 ... part_b_line18\n"
                "part_c_line19, part_c_line20\n"
                "step3_line4, step3_line5, step3_line6\n"
                "note1_row1_year, note1_row1_a ... note1_row1_e (rows 1-3 supported)"
            )

    with tab_generate:
        approved = {str(row.get("field", "")).strip(): _amount(str(row.get("value", ""))) for row in st.session_state.ai_rows if str(row.get("field", "")).strip()}
        selected = build_t1ovp_pdf_values(approved, pdf_fields)
        st.write(f"Ready to fill {len(selected)} exact fields from {len(approved)} reviewed values.")
        approval = st.checkbox("I reviewed the values and approve this PDF generation.")
        if st.button("Generate editable and viewer-safe PDFs", type="primary", disabled=not approval or not selected):
            try:
                editable_pdf, flat_pdf = fill_and_flatten_pdf(pdf_bytes, selected)
                report = validate_output(editable_pdf, selected)
                output_path, report_path = save_submission(uploaded.name, pdf_bytes, approved, selected, flat_pdf, report)
                editable_path = output_path.with_name(output_path.stem + "_editable.pdf")
                editable_path.write_bytes(editable_pdf)
                st.session_state.completed = {
                    "editable": editable_pdf, "flat": flat_pdf, "report": report,
                    "output_path": output_path, "editable_path": editable_path, "report_path": report_path,
                }
            except Exception as exc:
                st.exception(exc)

        if st.session_state.completed:
            result = st.session_state.completed
            summary = result["report"]["summary"]
            if summary["failed"]:
                st.error(f"Validation found {summary['failed']} mismatch(es).")
            else:
                st.success(f"Validation passed: {summary['passed']} of {summary['total']} filled fields match.")
            col1, col2, col3 = st.columns(3)
            stem = safe_stem(uploaded.name)
            col1.download_button("Download viewer-safe PDF", result["flat"], file_name=f"{stem}_completed.pdf", mime="application/pdf", use_container_width=True)
            col2.download_button("Download editable PDF", result["editable"], file_name=f"{stem}_editable.pdf", mime="application/pdf", use_container_width=True)
            col3.download_button("Download validation report", json.dumps(result["report"], indent=2), file_name=f"{stem}_validation.json", mime="application/json", use_container_width=True)
            st.caption(f"Saved: {result['output_path']} | {result['editable_path']} | {result['report_path']}")

    with tab_source:
        st.write(f"Detected {len(pdf_fields)} PDF fields and {len(tables)} extracted tables.")
        with st.expander("Extracted PDF text"):
            st.text_area("PDF text", st.session_state.extracted_text, height=300, disabled=True, label_visibility="collapsed")
        terminal = [{"PDF field": name, "Type": info["type"], "Current value": info["current_value"]} for name, info in pdf_fields.items() if info["type"]]
        st.dataframe(pd.DataFrame(terminal), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
