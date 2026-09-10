from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
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
    page_title="CRA Housing Rebate & Form Auto-Filler",
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
    # Part A - Claimant
    "claimant_name": [r"claimant(?:\s*['’]?s)?\s*(?:legal\s*)?name", r"legal\s*name", r"applicant\s*name", r"full\s*name", r"\bbuyer\b"],
    "business_number": [r"business\s*number", r"\bbn\b", r"rt\s*0001", r"gst_number"],
    "sin": [r"social\s*insurance\s*number", r"\bsin\b"],
    "daytime_phone": [r"daytime\s*(?:telephone|phone)", r"telephone\s*number", r"phone\s*(?:number)?", r"day_phone"],
    "extension": [r"\bext(?:ension)?\b", r"phone_ext"],
    "home_phone": [r"home\s*(?:telephone|phone)", r"evening\s*phone", r"home_tel"],
    "language": [r"language\s*preference", r"\blanguage\b"],
    "other_purchasers": [r"other\s*purchaser", r"co-?buyer", r"joint\s*buyer", r"second\s*purchaser"],
    "property_address": [r"property\s*address", r"purchased\s*house\s*address", r"street\s*address", r"\baddress\b", r"\bproperty\b"],
    "city": [r"\bcity\b", r"municipality"],
    "province": [r"province(?:\s*or\s*territory)?", r"\bprovince\b", r"\bstate\b"],
    "postal_code": [r"postal\s*code", r"zip(?:\s*code)?"],
    "mailing_address": [r"mailing\s*address", r"claimant\s*mailing\s*address"],
    "mailing_city": [r"mailing\s*city"],
    "mailing_province": [r"mailing\s*province", r"mailing\s*state"],
    "mailing_postal_code": [r"mailing\s*postal\s*code", r"mailing\s*zip"],
    "mailing_country": [r"mailing\s*country", r"\bcountry\b"],
    # Part B - House & Legal
    "primary_residence": [r"primary\s*(?:place\s*of\s*)?residence", r"main_residence"],
    "first_to_occupy": [r"first\s*to\s*occupy", r"occupant"],
    "agreement_date": [r"agreement\s*date", r"signed\s*date", r"date\s*(?:purchase\s*)?agreement\s*signed"],
    "closing_date": [r"completion\s*date", r"closing\s*date", r"ownership\s*date", r"date\s*ownership\s*(?:was\s*)?transferred"],
    "possession_date": [r"possession\s*date", r"adjustment\s*date", r"date\s*possession\s*(?:was\s*)?transferred"],
    "construction_start_date": [r"construction\s*(?:began|start)", r"date\s*construction\s*began"],
    "construction_end_date": [r"construction\s*(?:completed|ended)", r"date\s*construction\s*(?:was\s*)?substantially\s*completed"],
    "lot_number": [r"lot\s*(?:number|#)", r"strata\s*number", r"strata\s*lot", r"\blot\b"],
    "plan_number": [r"plan\s*(?:number|#)", r"\bplan\b"],
    "pid": [r"\bpid\b", r"parcel\s*identifier"],
    "legal_description": [r"legal\s*description", r"\blegal\b"],
    # Part C & D - Builder
    "builder_name": [r"builder(?:\s*['’]?s)?\s*(?:legal\s*)?name", r"seller\s*name", r"\bseller\b", r"\bvendor\b"],
    "builder_business_number": [r"builder(?:\s*['’]?s)?\s*business\s*number", r"builder\s*bn"],
    "builder_phone": [r"builder\s*phone", r"builder\s*telephone"],
    "builder_address": [r"builder\s*address"],
    "builder_city": [r"builder\s*city"],
    "builder_province": [r"builder\s*province"],
    "builder_postal_code": [r"builder\s*postal\s*code"],
    # Financial & Amounts
    "purchase_price": [r"purchase\s*price(?:\s*of\s*(?:the\s*)?house)?", r"contract\s*price", r"price\s*before\s*tax", r"\bprice\b"],
    "gst_paid": [r"gst\s*charged\s*on\s*price", r"gst\s*paid", r"federal\s*part\s*paid", r"total\s*gst", r"\bgst\b"],
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


def get_gemini_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    try:
        if not api_key and "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return api_key


def file_to_base64_parts(file_bytes: bytes, filename: str) -> list[dict[str, Any]]:
    parts = []
    lower_name = filename.lower()
    if lower_name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        mime = "image/png" if lower_name.endswith(".png") else "image/jpeg"
        parts.append({
            "inlineData": {
                "mimeType": mime,
                "data": base64.b64encode(file_bytes).decode("utf-8"),
            }
        })
    elif lower_name.endswith(".pdf"):
        try:
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            for page_num in range(min(len(doc), 4)):
                page = doc[page_num]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
                png_bytes = pix.tobytes(output="png")
                parts.append({
                    "inlineData": {
                        "mimeType": "image/png",
                        "data": base64.b64encode(png_bytes).decode("utf-8"),
                    }
                })
            doc.close()
        except Exception:
            pass
    return parts


def extract_soa_with_gemini(doc_parts: list[dict[str, Any]], api_key: str) -> dict[str, Any]:
    if not api_key or not doc_parts:
        return {}

    prompt = """You are an expert Canadian tax and real estate document extractor.
Analyze the provided Statement of Adjustments and/or Purchase and Sale Agreement.
Extract the following information and return ONLY a valid JSON object:
{
  "claimant_name": "Full legal name of the primary buyer (e.g. Felicia Ejembi)",
  "other_purchasers": "Name of any co-buyer / other purchasers (e.g. Emmanuel Ejembi)",
  "business_number": "Claimant business number if present, or null",
  "sin": "Claimant SIN if present, or null",
  "daytime_phone": "Phone number if present, or null",
  "extension": "Phone extension if present, or null",
  "home_phone": "Home phone if present, or null",
  "language": "English or French",
  "builder_name": "Name of the seller / builder company (e.g. 1335269 Bc Ltd.)",
  "builder_business_number": "Builder BN or GST number if present, or null",
  "property_address": "Street address of the property (e.g. 7629 197 Street)",
  "city": "City (e.g. Langley)",
  "province": "2-letter province code (e.g. BC or ON)",
  "postal_code": "Postal code (e.g. V2Y 3T4)",
  "legal_description": "Full legal description text from document",
  "lot_number": "Lot or strata number (e.g. 8)",
  "plan_number": "Plan number (e.g. EPP70176)",
  "pid": "Property PID (e.g. 031-242-910)",
  "purchase_price": "Numeric purchase price before taxes as float (e.g. 1202500.00)",
  "gst_paid": "Numeric GST charged/paid on price as float (e.g. 60125.00)",
  "completion_date": "Completion / closing date in YYYY-MM-DD format",
  "possession_date": "Possession date in YYYY-MM-DD format",
  "agreement_date": "Date purchase agreement signed in YYYY-MM-DD format or null"
}
Return only JSON."""

    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}] + doc_parts
                }
            ],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                candidates = res_json.get("candidates", [])
                if candidates:
                    text_out = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    return json.loads(text_out)
        except Exception:
            continue
    return {}


def extract_soa_with_heuristics(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if not text:
        return data

    seller_m = re.search(r"(?im)^\s*Seller\s*:\s*([^\n\r]+)", text)
    if seller_m:
        data["builder_name"] = seller_m.group(1).strip()

    buyer_m = re.search(r"(?im)^\s*Buyer\s*:\s*([^\n\r]+)", text)
    if buyer_m:
        buyers_str = buyer_m.group(1).strip()
        if " and " in buyers_str.lower():
            parts = re.split(r"\s+and\s+", buyers_str, flags=re.I)
            data["claimant_name"] = parts[0].strip()
            data["other_purchasers"] = ", ".join(parts[1:]).strip()
        else:
            data["claimant_name"] = buyers_str

    prop_m = re.search(r"(?im)^\s*Property\s*:\s*([^\n\r]+)", text)
    if prop_m:
        full_addr = prop_m.group(1).strip()
        data["property_address"] = full_addr
        m_parts = re.search(r"^(.*?),\s*([A-Za-z\s]+),\s*([A-Z]{2})\s+([A-Z0-9\s]{6,7})$", full_addr)
        if m_parts:
            data["property_address"] = m_parts.group(1).strip()
            data["city"] = m_parts.group(2).strip()
            data["province"] = m_parts.group(3).strip()
            data["postal_code"] = m_parts.group(4).strip()

    legal_m = re.search(r"(?im)^\s*Legal\s*:\s*([^\n\r]+)", text)
    if legal_m:
        leg_str = legal_m.group(1).strip()
        data["legal_description"] = leg_str
        pid_m = re.search(r"PID\s*:\s*([\d-]+)", leg_str, re.I)
        if pid_m:
            data["pid"] = pid_m.group(1).strip()
        lot_m = re.search(r"LOT\s*(\d+)", leg_str, re.I)
        if lot_m:
            data["lot_number"] = lot_m.group(1).strip()
        plan_m = re.search(r"PLAN\s*([A-Z0-9]+)", leg_str, re.I)
        if plan_m:
            data["plan_number"] = plan_m.group(1).strip()

    comp_m = re.search(r"(?im)Completion\s*Date\s*:\s*([^\n\r]+)", text)
    if comp_m:
        data["completion_date"] = comp_m.group(1).strip()
    poss_m = re.search(r"(?im)Possession\s*Date\s*:\s*([^\n\r]+)", text)
    if poss_m:
        data["possession_date"] = poss_m.group(1).strip()

    price_m = re.search(r"(?im)^\s*Price\s+\$?\s*([\d,]+(?:\.\d+)?)", text)
    if price_m:
        data["purchase_price"] = float(price_m.group(1).replace(",", ""))

    gst_m = re.search(r"(?im)GST\s*(?:Charged\s*on\s*Price|Paid)?[^$]*\$\s*([\d,]+(?:\.\d+)?)", text)
    if gst_m:
        data["gst_paid"] = float(gst_m.group(1).replace(",", ""))

    return data


def calculate_cra_rebate(price: float, gst_paid: float, is_fthb: bool = True, province: str = "BC") -> dict[str, Any]:
    s1_line1 = gst_paid
    s1_line2 = price
    s1_line3 = min(s1_line1 * 0.36, 6300.0)

    if s1_line2 <= 350000.0:
        s1_line4 = s1_line3
    elif s1_line2 >= 450000.0:
        s1_line4 = 0.0
    else:
        s1_line4 = ((450000.0 - s1_line2) / 100000.0) * s1_line3

    s4_line12 = gst_paid
    s4_line13 = price

    if s4_line13 <= 1000000.0:
        s4_line14 = min(50000.0, s4_line12)
    elif s4_line13 >= 1500000.0:
        s4_line14 = 0.0
    else:
        lesser_amount = min(50000.0, s4_line12)
        s4_line14 = ((1500000.0 - s4_line13) / 500000.0) * lesser_amount

    chosen_rebate = s4_line14 if is_fthb else s1_line4

    line_a = gst_paid
    line_b = price
    line_c = chosen_rebate
    line_d = 0.0
    line_x1 = 0.0
    line_x2 = 0.0
    line_x3 = 0.0
    line_e = line_c + line_d - (line_x1 + line_x2 + line_x3)

    return {
        "rc7190_line1": f"{s1_line1:,.2f}",
        "rc7190_line2": f"{s1_line2:,.2f}",
        "rc7190_line3": f"{s1_line3:,.2f}",
        "rc7190_line4": f"{s1_line4:,.2f}",
        "rc7190_line12": f"{s4_line12:,.2f}",
        "rc7190_line13": f"{s4_line13:,.2f}",
        "rc7190_line14": f"{s4_line14:,.2f}",
        "gst190_line_a": f"{line_a:,.2f}",
        "gst190_line_b": f"{line_b:,.2f}",
        "gst190_line_c": f"{line_c:,.2f}",
        "gst190_line_d": f"{line_d:,.2f}",
        "gst190_line_e": f"{line_e:,.2f}",
        "fthb_rebate_num": s4_line14,
        "standard_rebate_num": s1_line4,
        "total_rebate_num": line_e,
    }


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


def _clean_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key.strip().lower()).strip("_")


def smart_map_pdf_values(data: dict[str, str], pdf_fields: dict[str, Any]) -> dict[str, str]:
    mapped_values: dict[str, str] = {}
    normalized_data = {_clean_key(k): str(v).strip() for k, v in data.items()}

    for field_name, info in pdf_fields.items():
        norm_field = _clean_key(field_name)

        if norm_field in normalized_data:
            mapped_values[field_name] = normalized_data[norm_field]
            continue

        line_num_match = re.search(r"line_?(\d{1,3})\b", norm_field)
        if line_num_match:
            num = line_num_match.group(1)
            for prefix in [f"rc7190_line{num}", f"line_{num}", f"part_a_line{num}", f"part_b_line{num}", f"part_c_line{num}", f"step2_line{num}", f"step3_line{num}"]:
                if prefix in normalized_data:
                    mapped_values[field_name] = normalized_data[prefix]
                    break
            if field_name in mapped_values:
                continue

        letter_match = re.search(r"line_?([a-z]\d?)\b", norm_field)
        if letter_match:
            let = letter_match.group(1)
            for prefix in [f"gst190_line_{let}", f"line_{let}"]:
                if prefix in normalized_data:
                    mapped_values[field_name] = normalized_data[prefix]
                    break
            if field_name in mapped_values:
                continue

        matched = False
        for sem_key, patterns in COMMON_SEMANTIC_PATTERNS.items():
            if sem_key in normalized_data:
                if any(re.search(p, norm_field) for p in patterns) or sem_key in norm_field:
                    mapped_values[field_name] = normalized_data[sem_key]
                    matched = True
                    break
        if matched:
            continue

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

    valid_values = {k: str(v) for k, v in values.items() if k in fields}
    writer.update_page_form_field_values(None, valid_values, auto_regenerate=True)
    editable_stream = io.BytesIO()
    writer.write(editable_stream)
    editable = editable_stream.getvalue()

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


def main() -> None:
    ensure_storage()

    st.markdown("""
    <div style="background: linear-gradient(135deg, #1b3a57 0%, #2e5984 100%); color: white; padding: 22px; border-radius: 12px; margin-bottom: 25px;">
        <h2 style="margin: 0; color: white;">🏠 CRA Housing Rebate & Form Auto-Filler</h2>
        <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 15px;">
            Extract closing information from your <b>Statement of Adjustments</b> or enter it manually to generate completed CRA <b>GST190</b> & <b>RC7190-WS</b> forms.
        </p>
    </div>
    """, unsafe_allow_html=True)

    mode = st.radio(
        "Select Operation Mode:",
        ["🏠 Housing Rebate Form Filler (GST190 & RC7190-WS)", "📝 Universal Form Filler (T1-OVP / Custom PDFs)"],
        horizontal=True,
    )

    if mode.startswith("🏠"):
        # ----------------- HOUSING REBATE AUTO-FILLER -----------------
        st.markdown("### Step 1: Upload Source Documents & CRA Templates")
        col_up1, col_up2 = st.columns(2)

        with col_up1:
            st.markdown("##### 📄 Source Closing Documents *(Optional if entering manually)*")
            soa_file = st.file_uploader(
                "Upload Buyer Statement of Adjustments (PDF / Image)",
                type=["pdf", "png", "jpg", "jpeg"],
                key="soa_file",
                help="Upload Statement of Adjustments to auto-populate all fields below",
            )
            psa_file = st.file_uploader(
                "Upload Purchase & Sale Agreement (Optional)",
                type=["pdf", "png", "jpg", "jpeg"],
                key="psa_file",
            )

        with col_up2:
            st.markdown("##### 📋 Target Fillable CRA Forms")
            gst190_template = st.file_uploader(
                "Upload Fillable Form GST190 (PDF)",
                type=["pdf"],
                key="gst190_template",
                help="CRA GST190 New Housing Rebate Application PDF template",
            )
            rc7190_template = st.file_uploader(
                "Upload Fillable Form RC7190-WS (PDF)",
                type=["pdf"],
                key="rc7190_template",
                help="CRA RC7190-WS Calculation Worksheet PDF template",
            )

        api_key = get_gemini_api_key()

        if soa_file:
            if st.button("✨ Auto-Extract Information from Uploaded Documents", type="primary"):
                with st.spinner("Analyzing Statement of Adjustments & extracting values..."):
                    soa_bytes = soa_file.getvalue()
                    soa_parts = file_to_base64_parts(soa_bytes, soa_file.name)

                    psa_parts = []
                    if psa_file:
                        psa_parts = file_to_base64_parts(psa_file.getvalue(), psa_file.name)

                    extracted_data = {}
                    if api_key:
                        extracted_data = extract_soa_with_gemini(soa_parts + psa_parts, api_key)

                    if not extracted_data:
                        text_extracted, _ = extract_native_text(soa_bytes)
                        if not text_extracted:
                            try:
                                import fitz
                                import pytesseract
                                from PIL import Image
                                doc = fitz.open(stream=soa_bytes, filetype="pdf")
                                page_texts = []
                                for page in doc:
                                    pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
                                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                                    page_texts.append(pytesseract.image_to_string(img))
                                text_extracted = "\n".join(page_texts)
                            except Exception:
                                pass
                        extracted_data = extract_soa_with_heuristics(text_extracted)

                    st.session_state["extracted_soa"] = extracted_data
                    st.success("✅ Extracted closing data! Review and adjust all fields manually below.")

        extracted = st.session_state.get("extracted_soa", {})

        st.markdown("---")
        st.markdown("### Step 2: Review & Complete Form Information (Manual Entry & Edits)")

        tab_part_a, tab_part_b, tab_part_c_d, tab_part_f = st.tabs([
            "👤 Part A – Claimant Information",
            "🏠 Part B – House & Legal Description",
            "🏢 Parts C & D – Application & Builder",
            "💰 Part F & RC7190-WS – Calculations",
        ])

        with tab_part_a:
            st.markdown("##### 👤 Part A – Claimant Information")
            col_a1, col_a2 = st.columns(2)

            with col_a1:
                claimant = st.text_input(
                    "Claimant's Legal Name (Last name, First name, Initials)",
                    value=extracted.get("claimant_name", "Felicia Ejembi"),
                    help="Enter one name only, even if several individuals bought the house",
                )
                biz_num = st.text_input(
                    "Business Number (if applicable, 9 digits + RT + 4 digits)",
                    value=extracted.get("business_number", ""),
                    placeholder="e.g. 123456789 RT 0001",
                )
                sin_val = st.text_input(
                    "Claimant's Social Insurance Number (SIN)",
                    value=extracted.get("sin", ""),
                    placeholder="e.g. 123-456-789",
                )
                other_buyer = st.text_input(
                    "Other Purchaser Information (Co-buyers, if any)",
                    value=extracted.get("other_purchasers", "Emmanuel Ejembi"),
                    help="If more than one individual bought the house, list other purchasers",
                )

            with col_a2:
                col_p1, col_p2 = st.columns([3, 1])
                day_phone = col_p1.text_input("Daytime Telephone Number", value=extracted.get("daytime_phone", ""), placeholder="e.g. 604-555-0123")
                ext_val = col_p2.text_input("Extension", value=extracted.get("extension", ""), placeholder="101")
                home_phone = st.text_input("Home Telephone Number", value=extracted.get("home_phone", ""), placeholder="e.g. 604-555-0199")
                lang_pref = st.radio("Language Preference", ["English", "French"], horizontal=True)

            st.markdown("###### Eligibility & Program Declarations")
            col_dec1, col_dec2, col_dec3 = st.columns(3)
            is_fthb_claim = col_dec1.checkbox("Claiming First-Time Home Buyer (FTHB) Rebate?", value=True)
            is_enhr_claim = col_dec2.checkbox("Claiming Ontario Enhanced Rebate (ENHR)?", value=False)
            onhap_consent = col_dec3.checkbox("Consent to Share Info for ONHAP (Ontario)?", value=False)

            st.markdown("###### Address of Purchased House")
            col_addr1, col_addr2, col_addr3, col_addr4 = st.columns([3, 2, 1, 2])
            addr = col_addr1.text_input("Unit no. – Street no. Street name, RR", value=extracted.get("property_address", "7629 197 Street"))
            city_val = col_addr2.text_input("City", value=extracted.get("city", "Langley"))
            prov_val = col_addr3.text_input("Province", value=extracted.get("province", "BC"))
            postal_val = col_addr4.text_input("Postal Code", value=extracted.get("postal_code", "V2Y 3T4"))

            with st.expander("📬 Claimant Mailing Address (If different from purchased house)"):
                col_m1, col_m2, col_m3 = st.columns([3, 2, 2])
                mail_addr = col_m1.text_input("Mailing Unit & Street", value=extracted.get("mailing_address", ""))
                mail_city = col_m2.text_input("Mailing City", value=extracted.get("mailing_city", ""))
                mail_prov = col_m3.text_input("Mailing Province / State", value=extracted.get("mailing_province", ""))
                col_m4, col_m5 = st.columns(2)
                mail_postal = col_m4.text_input("Mailing Postal / ZIP", value=extracted.get("mailing_postal_code", ""))
                mail_country = col_m5.text_input("Mailing Country", value=extracted.get("mailing_country", "Canada"))

        with tab_part_b:
            st.markdown("##### 🏠 Part B – House Information & Dates")
            col_b1, col_b2, col_b3 = st.columns(3)
            primary_res = col_b1.selectbox("Purchased as Primary Place of Residence?", ["Yes", "No"], index=0)
            first_occ = col_b2.selectbox("First to Occupy the House?", ["Yes", "No"], index=0)
            housing_type_sel = col_b3.selectbox(
                "Type of Housing",
                ["House (including condominium unit / duplex)", "Mobile home", "Floating home", "Bed and breakfast", "Duplex"],
            )

            st.markdown("###### Critical Dates")
            col_dt1, col_dt2, col_dt3 = st.columns(3)
            agree_date = col_dt1.text_input("Purchase Agreement Signed Date", value=str(extracted.get("agreement_date", "2026-08-20")), placeholder="YYYY-MM-DD")
            comp_date = col_dt2.text_input("Ownership Transfer Date (Completion)", value=str(extracted.get("completion_date", "2026-08-27")), placeholder="YYYY-MM-DD")
            poss_date = col_dt3.text_input("Possession Transfer Date", value=str(extracted.get("possession_date", "2026-08-28")), placeholder="YYYY-MM-DD")

            st.markdown("###### Legal Description of Property")
            col_leg1, col_leg2, col_leg3 = st.columns(3)
            lot_val = col_leg1.text_input("Lot / Strata Number", value=str(extracted.get("lot_number", "8")))
            plan_val = col_leg2.text_input("Plan Number", value=str(extracted.get("plan_number", "EPP70176")))
            pid_val = col_leg3.text_input("PID / Other Description", value=str(extracted.get("pid", "031-242-910")))
            full_legal = st.text_area(
                "Full Legal Description (from Deed / Registry)",
                value=extracted.get("legal_description", "PID: 031-242-910 - LOT 8 SECTION 22 TOWNSHIP 8 NEW WESTMINSTER DISTRICT PLAN EPP70176"),
                height=70,
            )

        with tab_part_c_d:
            st.markdown("##### 🏢 Parts C & D – Application Type & Builder Information")
            col_c1, col_c2 = st.columns(2)

            with col_c1:
                st.markdown("###### Part C – Application Type")
                app_type = st.selectbox(
                    "Select Application Type:",
                    [
                        "Type 2 (Directly with CRA - Bought house & land from builder)",
                        "Type 1A (Filed by Builder - Builder credited rebate)",
                        "Type 1B (Filed by Builder - Lease land)",
                        "Type 3 (Directly with CRA - Co-op share)",
                        "Type 5 (Directly with CRA - Lease land)",
                    ],
                )

            with col_c2:
                st.markdown("###### Part D – Builder Information")
                builder = st.text_input("Builder's Legal Name", value=extracted.get("builder_name", "1335269 Bc Ltd."))
                builder_bn = st.text_input("Builder Business Number (RT)", value=extracted.get("builder_business_number", ""))
                builder_tel = st.text_input("Builder Telephone", value=extracted.get("builder_phone", ""))
                builder_addr = st.text_input("Builder Address", value=extracted.get("builder_address", ""))

        with tab_part_f:
            st.markdown("##### 💰 Part F & RC7190-WS – Calculation Breakdown")
            col_calc1, col_calc2 = st.columns(2)

            price_raw = extracted.get("purchase_price", 1202500.0)
            gst_raw = extracted.get("gst_paid", 60125.0)

            price_val = col_calc1.number_input("Purchase Price of House (before GST/HST)", value=float(price_raw), step=1000.0)
            gst_val = col_calc2.number_input("GST / Federal Tax Paid (5%)", value=float(gst_raw), step=100.0)

            rebate_calcs = calculate_cra_rebate(price_val, gst_val, is_fthb=is_fthb_claim, province=prov_val)

            st.markdown(f"""
            <div style="background-color: #f0f7ff; border: 1px solid #b8daff; border-left: 5px solid #0066cc; padding: 18px; border-radius: 8px; margin: 15px 0;">
                <h4 style="margin: 0 0 12px 0; color: #004085;">📊 Official CRA Calculation Summary</h4>
                <table style="width: 100%; font-size: 14px; border-collapse: collapse;">
                    <tr style="border-bottom: 1px solid #dee2e6;">
                        <td style="padding: 6px 0;"><b>RC7190-WS Line 1 / Line 12 (GST Paid):</b></td>
                        <td style="text-align: right; padding: 6px 0;">${rebate_calcs['rc7190_line1']}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #dee2e6;">
                        <td style="padding: 6px 0;"><b>RC7190-WS Line 2 / Line 13 (Purchase Price):</b></td>
                        <td style="text-align: right; padding: 6px 0;">${rebate_calcs['rc7190_line2']}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #dee2e6;">
                        <td style="padding: 6px 0;"><b>Standard Rebate (RC7190-WS Line 4):</b></td>
                        <td style="text-align: right; padding: 6px 0;">${rebate_calcs['rc7190_line4']} <i>(Phased out over $450k)</i></td>
                    </tr>
                    <tr style="border-bottom: 1px solid #dee2e6; background-color: #e8f5e9;">
                        <td style="padding: 8px 0; color: #1b5e20;"><b>First-Time Home Buyer Rebate (RC7190-WS Line 14):</b></td>
                        <td style="text-align: right; padding: 8px 0; font-size: 16px; font-weight: bold; color: #1b5e20;">${rebate_calcs['rc7190_line14']}</td>
                    </tr>
                    <tr style="background-color: #e3f2fd;">
                        <td style="padding: 10px 0; color: #0d47a1; font-size: 15px;"><b>GST190 Total Claim Amount (Line E):</b></td>
                        <td style="text-align: right; padding: 10px 0; font-size: 18px; font-weight: bold; color: #0d47a1;">${rebate_calcs['gst190_line_e']}</td>
                    </tr>
                </table>
            </div>
            """, unsafe_allow_html=True)

        # Assemble full payload from manual inputs
        combined_payload = {
            "claimant_name": claimant,
            "business_number": biz_num,
            "sin": sin_val,
            "other_purchaser": other_buyer,
            "other_purchasers": other_buyer,
            "daytime_phone": day_phone,
            "extension": ext_val,
            "home_phone": home_phone,
            "language": lang_pref,
            "property_address": addr,
            "address": addr,
            "city": city_val,
            "province": prov_val,
            "postal_code": postal_val,
            "mailing_address": mail_addr or addr,
            "mailing_city": mail_city or city_val,
            "mailing_province": mail_prov or prov_val,
            "mailing_postal_code": mail_postal or postal_val,
            "mailing_country": mail_country,
            "primary_residence": primary_res,
            "first_to_occupy": first_occ,
            "housing_type": housing_type_sel,
            "agreement_date": agree_date,
            "closing_date": comp_date,
            "possession_date": poss_date,
            "lot_number": lot_val,
            "plan_number": plan_val,
            "pid": pid_val,
            "legal_description": full_legal,
            "builder_name": builder,
            "builder_business_number": builder_bn,
            "builder_phone": builder_tel,
            "builder_address": builder_addr,
            "purchase_price": f"{price_val:,.2f}",
            "gst_paid": f"{gst_val:,.2f}",
            **rebate_calcs,
        }

        st.markdown("---")
        st.markdown("### Step 3: Generate & Download Completed Forms")

        col_gen1, col_gen2 = st.columns(2)

        with col_gen1:
            st.markdown("##### 📝 Generate Form GST190")
            if gst190_template:
                if st.button("🚀 Fill & Generate GST190 PDF", type="primary", key="btn_fill_gst190"):
                    t_bytes = gst190_template.getvalue()
                    fields = get_pdf_fields(t_bytes)
                    mapped = smart_map_pdf_values(combined_payload, fields)
                    editable_pdf, flat_pdf = fill_and_flatten_pdf(t_bytes, mapped)
                    st.download_button(
                        "📥 Download Completed GST190 PDF",
                        flat_pdf,
                        file_name=f"GST190_{safe_stem(claimant)}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
            else:
                st.info("Upload your fillable GST190 PDF template in Step 1 to generate.")

        with col_gen2:
            st.markdown("##### 📑 Generate Form RC7190-WS")
            if rc7190_template:
                if st.button("🚀 Fill & Generate RC7190-WS PDF", type="primary", key="btn_fill_rc7190"):
                    t_bytes = rc7190_template.getvalue()
                    fields = get_pdf_fields(t_bytes)
                    mapped = smart_map_pdf_values(combined_payload, fields)
                    editable_pdf, flat_pdf = fill_and_flatten_pdf(t_bytes, mapped)
                    st.download_button(
                        "📥 Download Completed RC7190-WS PDF",
                        flat_pdf,
                        file_name=f"RC7190_WS_{safe_stem(claimant)}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
            else:
                st.info("Upload your fillable RC7190-WS PDF template in Step 1 to generate.")

    else:
        # ----------------- UNIVERSAL FORM FILLER (T1-OVP / CUSTOM) -----------------
        st.markdown("### Universal CRA Form Filler (T1-OVP, Custom Forms)")
        uploaded = st.file_uploader("📂 Upload Fillable PDF Form", type=["pdf"], key="universal_pdf")
        if not uploaded:
            st.info("Upload a fillable PDF to begin.")
            return

        pdf_bytes = uploaded.getvalue()
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()
        pdf_fields = get_pdf_fields(pdf_bytes)

        st.success(f"✅ Form Loaded — Detected **{len(pdf_fields)} fillable fields**.")

        instructions = st.text_area(
            "Paste calculation text or instructions:",
            height=200,
            placeholder="Line 1: 5000\nLine 2: 25000\nClaimant Name: John Doe",
            key=f"univ_instr_{file_hash}",
        )

        if st.button("⚡ Parse & Fill Universal Form", type="primary", disabled=not instructions.strip()):
            parsed = {}
            for line in instructions.strip().split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    parsed[_clean_key(k)] = v.strip()
            mapped = smart_map_pdf_values(parsed, pdf_fields)
            editable_pdf, flat_pdf = fill_and_flatten_pdf(pdf_bytes, mapped)
            st.download_button(
                "📥 Download Filled PDF",
                flat_pdf,
                file_name=f"{safe_stem(uploaded.name)}_completed.pdf",
                mime="application/pdf",
                use_container_width=True,
            )


if __name__ == "__main__":
    main()
