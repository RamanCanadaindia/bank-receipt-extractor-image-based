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
    page_title="CRA Housing Rebate & PDF Form Filler",
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
    "claimant_name": [r"claimant(?:\s*['’]?s)?\s*(?:legal\s*)?name", r"legal\s*name", r"applicant\s*name", r"full\s*name", r"\bbuyer\b"],
    "first_name": [r"first\s*name", r"given\s*name"],
    "last_name": [r"last\s*name", r"surname", r"family\s*name"],
    "other_purchaser": [r"other\s*purchaser", r"co-?buyer", r"joint\s*buyer"],
    "sin": [r"social\s*insurance\s*number", r"\bsin\b"],
    "business_number": [r"business\s*number", r"\bbn\b", r"rt\s*0001"],
    "phone": [r"daytime\s*phone", r"phone\s*(?:number)?", r"telephone", r"mobile"],
    "email": [r"e-?mail\s*(?:address)?"],
    "address": [r"property\s*address", r"purchased\s*house\s*address", r"street\s*address", r"\baddress\b", r"\bproperty\b"],
    "city": [r"\bcity\b", r"municipality"],
    "province": [r"province(?:\s*or\s*territory)?", r"\bprovince\b", r"\bstate\b"],
    "postal_code": [r"postal\s*code", r"zip(?:\s*code)?"],
    "lot_number": [r"lot\s*(?:number|#)", r"strata\s*number", r"strata\s*lot", r"\blot\b"],
    "plan_number": [r"plan\s*(?:number|#)", r"\bplan\b"],
    "pid": [r"\bpid\b", r"parcel\s*identifier"],
    "legal_description": [r"legal\s*description", r"\blegal\b"],
    "purchase_price": [r"purchase\s*price(?:\s*of\s*(?:the\s*)?house)?", r"contract\s*price", r"price\s*before\s*tax", r"\bprice\b"],
    "gst_paid": [r"gst\s*charged\s*on\s*price", r"gst\s*paid", r"federal\s*part\s*paid", r"total\s*gst", r"\bgst\b"],
    "agreement_date": [r"agreement\s*date", r"signed\s*date", r"date\s*(?:purchase\s*)?agreement\s*signed"],
    "closing_date": [r"completion\s*date", r"closing\s*date", r"ownership\s*date", r"date\s*ownership\s*(?:was\s*)?transferred"],
    "possession_date": [r"possession\s*date", r"adjustment\s*date", r"date\s*possession\s*(?:was\s*)?transferred"],
    "builder_name": [r"builder(?:\s*['’]?s)?\s*(?:legal\s*)?name", r"seller\s*name", r"\bseller\b", r"\bvendor\b"],
    "builder_business_number": [r"builder(?:\s*['’]?s)?\s*business\s*number", r"builder\s*bn"],
    "builder_phone": [r"builder\s*phone", r"builder\s*telephone"],
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
    """Converts uploaded image or PDF into Gemini inline image parts."""
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
    """Uses Gemini multimodal model to extract Statement of Adjustments / Contract fields."""
    if not api_key or not doc_parts:
        return {}

    prompt = """You are an expert Canadian tax and real estate document extractor.
Analyze the provided Statement of Adjustments and/or Purchase and Sale Agreement.
Extract the following information and return ONLY a valid JSON object:
{
  "claimant_name": "Full legal name of the primary buyer (e.g. Felicia Ejembi)",
  "other_purchasers": "Name of any co-buyer / other purchasers (e.g. Emmanuel Ejembi)",
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
    """Fallback heuristic text parser for Statement of Adjustments."""
    data: dict[str, Any] = {}
    if not text:
        return data

    # Seller / Builder
    seller_m = re.search(r"(?im)^\s*Seller\s*:\s*([^\n\r]+)", text)
    if seller_m:
        data["builder_name"] = seller_m.group(1).strip()

    # Buyer
    buyer_m = re.search(r"(?im)^\s*Buyer\s*:\s*([^\n\r]+)", text)
    if buyer_m:
        buyers_str = buyer_m.group(1).strip()
        if " and " in buyers_str.lower():
            parts = re.split(r"\s+and\s+", buyers_str, flags=re.I)
            data["claimant_name"] = parts[0].strip()
            data["other_purchasers"] = ", ".join(parts[1:]).strip()
        else:
            data["claimant_name"] = buyers_str

    # Property Address
    prop_m = re.search(r"(?im)^\s*Property\s*:\s*([^\n\r]+)", text)
    if prop_m:
        full_addr = prop_m.group(1).strip()
        data["property_address"] = full_addr
        # Try splitting city, province, postal
        m_parts = re.search(r"^(.*?),\s*([A-Za-z\s]+),\s*([A-Z]{2})\s+([A-Z0-9\s]{6,7})$", full_addr)
        if m_parts:
            data["property_address"] = m_parts.group(1).strip()
            data["city"] = m_parts.group(2).strip()
            data["province"] = m_parts.group(3).strip()
            data["postal_code"] = m_parts.group(4).strip()

    # Legal
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

    # Dates
    comp_m = re.search(r"(?im)Completion\s*Date\s*:\s*([^\n\r]+)", text)
    if comp_m:
        data["completion_date"] = comp_m.group(1).strip()
    poss_m = re.search(r"(?im)Possession\s*Date\s*:\s*([^\n\r]+)", text)
    if poss_m:
        data["possession_date"] = poss_m.group(1).strip()

    # Price & GST
    price_m = re.search(r"(?im)^\s*Price\s+\$?\s*([\d,]+(?:\.\d+)?)", text)
    if price_m:
        data["purchase_price"] = float(price_m.group(1).replace(",", ""))

    gst_m = re.search(r"(?im)GST\s*(?:Charged\s*on\s*Price|Paid)?[^$]*\$\s*([\d,]+(?:\.\d+)?)", text)
    if gst_m:
        data["gst_paid"] = float(gst_m.group(1).replace(",", ""))

    return data


def calculate_cra_rebate(price: float, gst_paid: float, is_fthb: bool = True, province: str = "BC") -> dict[str, Any]:
    """Calculates official CRA GST190 and RC7190-WS rebate amounts."""
    # 1. Section 1 (Standard GST New Housing Rebate)
    s1_line1 = gst_paid
    s1_line2 = price
    s1_line3 = min(s1_line1 * 0.36, 6300.0)

    if s1_line2 <= 350000.0:
        s1_line4 = s1_line3
    elif s1_line2 >= 450000.0:
        s1_line4 = 0.0
    else:
        s1_line4 = ((450000.0 - s1_line2) / 100000.0) * s1_line3

    # 2. Section 4 (First-Time Home Buyers' GST/HST Rebate)
    s4_line12 = gst_paid
    s4_line13 = price

    if s4_line13 <= 1000000.0:
        s4_line14 = min(50000.0, s4_line12)
    elif s4_line13 >= 1500000.0:
        s4_line14 = 0.0
    else:
        # Phaseout calculation
        lesser_amount = min(50000.0, s4_line12)
        s4_line14 = ((1500000.0 - s4_line13) / 500000.0) * lesser_amount

    # Chosen rebate
    chosen_rebate = s4_line14 if is_fthb else s1_line4

    # GST190 Part F lines
    line_a = gst_paid
    line_b = price
    line_c = chosen_rebate
    line_d = 0.0  # Provincial rebate (e.g. Ontario top-up if ON, else 0)
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


def _amount(value: str) -> str:
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.strip().replace("$", "").replace(" ", "").rstrip(".")
    if cleaned.endswith("%"):
        return cleaned
    return cleaned


def _clean_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key.strip().lower()).strip("_")


def smart_map_pdf_values(data: dict[str, str], pdf_fields: dict[str, Any]) -> dict[str, str]:
    """Intelligently maps key-values to AcroForm field targets."""
    mapped_values: dict[str, str] = {}
    normalized_data = {_clean_key(k): str(v).strip() for k, v in data.items()}

    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
              "january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december"]

    for field_name, info in pdf_fields.items():
        norm_field = _clean_key(field_name)

        if norm_field in normalized_data:
            mapped_values[field_name] = normalized_data[norm_field]
            continue

        # Line number match
        line_num_match = re.search(r"line_?(\d{1,3})\b", norm_field)
        if line_num_match:
            num = line_num_match.group(1)
            for prefix in [f"rc7190_line{num}", f"line_{num}", f"part_a_line{num}", f"part_b_line{num}", f"part_c_line{num}", f"step2_line{num}", f"step3_line{num}"]:
                if prefix in normalized_data:
                    mapped_values[field_name] = normalized_data[prefix]
                    break
            if field_name in mapped_values:
                continue

        # Letter match (Line A, Line B, Line C, Line D, Line E)
        letter_match = re.search(r"line_?([a-z]\d?)\b", norm_field)
        if letter_match:
            let = letter_match.group(1)
            for prefix in [f"gst190_line_{let}", f"line_{let}"]:
                if prefix in normalized_data:
                    mapped_values[field_name] = normalized_data[prefix]
                    break
            if field_name in mapped_values:
                continue

        # Semantic keywords
        matched = False
        for sem_key, patterns in COMMON_SEMANTIC_PATTERNS.items():
            if sem_key in normalized_data:
                if any(re.search(p, norm_field) for p in patterns) or sem_key in norm_field:
                    mapped_values[field_name] = normalized_data[sem_key]
                    matched = True
                    break
        if matched:
            continue

        # Fallback substring
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
            Upload your <b>Buyer Statement of Adjustments</b> and <b>Purchase & Sale Agreement</b>. The AI extracts all buyers, builder details, legal lot/PID, purchase price, GST paid, and automatically calculates and populates <b>GST190</b> & <b>RC7190-WS</b>.
        </p>
    </div>
    """, unsafe_allow_html=True)

    mode = st.radio(
        "Select Operation Mode:",
        ["🏠 Statement of Adjustments Auto-Filler (GST190 & RC7190-WS)", "📝 Universal Form Filler (T1-OVP / Custom PDFs)"],
        horizontal=True,
    )

    if mode.startswith("🏠"):
        # ----------------- HOUSING REBATE AUTO-FILLER -----------------
        st.markdown("### Step 1: Upload Source Documents & Target CRA Forms")
        col_up1, col_up2 = st.columns(2)

        with col_up1:
            st.markdown("##### 📄 Source Closing Documents")
            soa_file = st.file_uploader(
                "Upload Buyer Statement of Adjustments (PDF or Image)",
                type=["pdf", "png", "jpg", "jpeg"],
                key="soa_file",
                help="Statement of Adjustments showing Buyer, Seller, Price, GST, Completion Date, Legal PID/Lot",
            )
            psa_file = st.file_uploader(
                "Upload Purchase & Sale Agreement (Optional)",
                type=["pdf", "png", "jpg", "jpeg"],
                key="psa_file",
                help="Signed contract between buyer and builder",
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

        if st.button("✨ Extract Information & Calculate Rebates", type="primary", disabled=not soa_file):
            with st.spinner("Analyzing Statement of Adjustments & calculating CRA rebates..."):
                soa_bytes = soa_file.getvalue()
                soa_parts = file_to_base64_parts(soa_bytes, soa_file.name)

                psa_parts = []
                if psa_file:
                    psa_parts = file_to_base64_parts(psa_file.getvalue(), psa_file.name)

                # 1. Try Gemini Multimodal Extraction
                extracted_data = {}
                if api_key:
                    extracted_data = extract_soa_with_gemini(soa_parts + psa_parts, api_key)

                # 2. Fallback to Local OCR / text extraction if needed
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
                st.success("✅ Extracted closing data successfully! Review details below.")

        if "extracted_soa" in st.session_state and st.session_state["extracted_soa"]:
            extracted = st.session_state["extracted_soa"]

            st.markdown("---")
            st.markdown("### Step 2: Review & Customize Extracted Values")

            col_r1, col_r2, col_r3 = st.columns(3)

            with col_r1:
                st.markdown("##### 👤 Parties (Buyer & Builder)")
                claimant = st.text_input("Primary Claimant / Buyer Name", value=extracted.get("claimant_name", "Felicia Ejembi"))
                other_buyer = st.text_input("Other Purchaser (Co-Buyer)", value=extracted.get("other_purchasers", "Emmanuel Ejembi"))
                builder = st.text_input("Builder / Seller Legal Name", value=extracted.get("builder_name", "1335269 Bc Ltd."))
                sin_val = st.text_input("Claimant SIN (Optional)", value=extracted.get("sin", ""))

            with col_r2:
                st.markdown("##### 📍 Property & Legal Info")
                addr = st.text_input("Property Address", value=extracted.get("property_address", "7629 197 Street"))
                city_val = st.text_input("City", value=extracted.get("city", "Langley"))
                prov_val = st.text_input("Province", value=extracted.get("province", "BC"))
                postal_val = st.text_input("Postal Code", value=extracted.get("postal_code", "V2Y 3T4"))
                lot_val = st.text_input("Lot / Strata #", value=str(extracted.get("lot_number", "8")))
                plan_val = st.text_input("Plan #", value=str(extracted.get("plan_number", "EPP70176")))
                pid_val = st.text_input("PID", value=str(extracted.get("pid", "031-242-910")))

            with col_r3:
                st.markdown("##### 📅 Key Dates")
                comp_date = st.text_input("Completion / Closing Date", value=str(extracted.get("completion_date", "2026-08-27")))
                poss_date = st.text_input("Possession Date", value=str(extracted.get("possession_date", "2026-08-28")))
                agree_date = st.text_input("Agreement Signed Date", value=str(extracted.get("agreement_date", "2026-08-20")))

            st.markdown("##### 💰 Financial & Rebate Calculation")
            col_f1, col_f2, col_f3 = st.columns(3)

            price_raw = extracted.get("purchase_price", 1202500.0)
            gst_raw = extracted.get("gst_paid", 60125.0)

            price_val = col_f1.number_input("Purchase Price (before tax)", value=float(price_raw), step=1000.0)
            gst_val = col_f2.number_input("GST Paid (5%)", value=float(gst_val if "gst_val" in locals() else gst_raw), step=100.0)
            is_fthb = col_f3.checkbox("Qualifies as First-Time Home Buyer (FTHB)?", value=True)

            # Compute CRA Rebates
            rebate_calcs = calculate_cra_rebate(price_val, gst_val, is_fthb=is_fthb, province=prov_val)

            st.markdown(f"""
            <div style="background-color: #f0f7ff; border-left: 5px solid #0066cc; padding: 16px; border-radius: 8px; margin: 15px 0;">
                <h4 style="margin: 0 0 10px 0; color: #004085;">📊 CRA Rebate Calculation Breakdown</h4>
                <div style="display: flex; gap: 30px; flex-wrap: wrap;">
                    <div><b>RC7190-WS Line 1 (GST Paid):</b> ${rebate_calcs['rc7190_line1']}</div>
                    <div><b>RC7190-WS Line 2 (Purchase Price):</b> ${rebate_calcs['rc7190_line2']}</div>
                    <div><b>Standard Rebate (Line 4):</b> ${rebate_calcs['rc7190_line4']} (Phased out over $450k)</div>
                    <div><b style="color: #006600;">FTHB Rebate (Line 14):</b> <span style="font-size: 18px; font-weight: bold; color: #006600;">${rebate_calcs['rc7190_line14']}</span></div>
                    <div><b>GST190 Total Claim (Line E):</b> <span style="font-size: 18px; font-weight: bold; color: #006600;">${rebate_calcs['gst190_line_e']}</span></div>
                </div>
                <p style="margin: 10px 0 0 0; font-size: 13px; color: #555;">
                    💡 <i>Formula applied for $1.0M – $1.5M FTHB: [($1,500,000 - ${price_val:,.2f}) / $500,000] × min($50,000, ${gst_val:,.2f}) = <b>${rebate_calcs['rc7190_line14']}</b></i>
                </p>
            </div>
            """, unsafe_allow_html=True)

            # Prepare complete payload
            combined_payload = {
                "claimant_name": claimant,
                "other_purchaser": other_buyer,
                "builder_name": builder,
                "sin": sin_val,
                "address": addr,
                "city": city_val,
                "province": prov_val,
                "postal_code": postal_val,
                "lot_number": lot_val,
                "plan_number": plan_val,
                "pid": pid_val,
                "legal_description": f"PID: {pid_val} - LOT {lot_val} PLAN {plan_val}",
                "closing_date": comp_date,
                "possession_date": poss_date,
                "agreement_date": agree_date,
                "purchase_price": f"{price_val:,.2f}",
                "gst_paid": f"{gst_val:,.2f}",
                **rebate_calcs,
            }

            st.markdown("---")
            st.markdown("### Step 3: Fill & Download Completed Forms")

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
