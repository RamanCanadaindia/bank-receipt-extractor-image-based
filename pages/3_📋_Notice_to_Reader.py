import streamlit as st
import os
import sys
import tempfile
import pandas as pd
import base64
import concurrent.futures
from datetime import datetime

# Ensure we can import helper modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth
import extract_statement
import gifi_extractor
import report_config

# Page authentication check
if not auth.check_password():
    st.stop()

st.set_page_config(
    page_title="Notice to Reader Compiler",
    page_icon="📋",
    layout="wide"
)

# Premium Page CSS
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 10px;
        padding: 15px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
    }
    .metric-value {
        font-size: 24px;
        font-weight: bold;
        color: #1f77b4;
    }
    .metric-label {
        font-size: 14px;
        color: #6d7278;
        margin-top: 5px;
    }
    
    /* Accounting Report Visual CSS (looks like a page on-screen) */
    .page-preview {
        background: #ffffff;
        border: 1px solid #d3d3d3;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        padding: 60px;
        width: 100%;
        max-width: 800px;
        margin: 20px auto;
        font-family: 'Times New Roman', Times, serif;
        color: #000000;
        line-height: 1.5;
    }
    .report-title {
        font-size: 28px;
        font-weight: bold;
        text-align: center;
        margin-top: 150px;
        text-transform: uppercase;
        letter-spacing: 2px;
    }
    .report-subtitle {
        font-size: 16px;
        text-align: center;
        margin-top: 40px;
    }
    .company-name {
        font-size: 22px;
        font-weight: bold;
        text-align: center;
        margin-top: 20px;
        text-transform: uppercase;
    }
    .date-title {
        font-size: 16px;
        text-align: center;
        margin-top: 150px;
    }
    .letter-text {
        font-size: 14px;
        text-align: justify;
        margin-bottom: 20px;
    }
    .report-table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 20px 0px;
        margin-top: 30px;
    }
    .report-table th {
        font-size: 14px;
        font-weight: bold;
        border-bottom: 1.5px solid #000;
        padding: 8px 0px;
        text-align: left;
    }
    .report-table td {
        font-size: 14px;
        padding: 6px 0px;
    }
    .num-col {
        text-align: right;
        width: 22%;
    }
    .single-under {
        border-top: 1.5px solid #000;
    }
    .double-under {
        border-top: 1.5px solid #000;
        border-bottom: 4px double #000;
    }
    .section-header {
        font-weight: bold;
        text-transform: uppercase;
        padding-top: 15px !important;
    }
    .subsection-header {
        font-weight: bold;
        padding-left: 10px;
    }
    .indented-td {
        padding-left: 20px !important;
    }
    
    .stButton>button {
        background-color: #1f4268;
        color: white;
        border-radius: 8px;
        font-weight: bold;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #152d47;
    }
</style>
""", unsafe_allow_html=True)

# Initialize Session States
if "gifi_raw_items" not in st.session_state:
    st.session_state.gifi_raw_items = []
if "gifi_meta" not in st.session_state:
    st.session_state.gifi_meta = {
        "corporation_name": "1386371 B.C. LTD.",
        "business_number": "791178619",
        "tax_year_end": "2025-06-30"
    }

st.title("📋 Compilation Engagement & Notice to Reader Compiler")
st.markdown("""
Extract financial statement details from CRA GIFI condensed statement PDFs and instantly compile a formal, professional **Notice to Reader** or **CSRS 4200 Compilation Report** for your corporation.
""")

# Setup two-column layout
col_left, col_right = st.columns([5, 6])

with col_left:
    st.subheader("⚙️ Configuration & Controls")
    
    # 1. Sidebar-style configuration block
    config_card = st.container(border=True)
    with config_card:
        st.markdown("**Report Parameters**")
        include_preparer_details = st.checkbox("Include Business Number & Preparer Details", value=True)
        default_compiler = "RAMAN TAX & ACCOUNTING INC." if include_preparer_details else ""
        compiler_name = st.text_input("Accountant / Compiler Firm Name", value=default_compiler)
        compilation_date_str = st.text_input("Report Wording Date", value=datetime.today().strftime('%B %d, %Y'))
        
        # Defined statically to support backward-compatible PDF helper calls
        report_type = "Notice to Reader"
        basis_of_accounting = "Income Tax Basis"

    # 2. File Upload & Processing
    api_key = st.sidebar.text_input(
        "Google AI Studio API Key",
        type="password",
        value=os.environ.get("GEMINI_API_KEY", ""),
        help="Get a free key from https://aistudio.google.com/"
    )
    
    model = st.sidebar.selectbox(
        "Gemini OCR Model",
        ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"],
        index=0
    )

    uploaded_file = st.file_uploader("Upload GIFI PDF Statement", type=["pdf"])
    
    if uploaded_file is not None:
        process_btn = st.button("⚡ Extract GIFI Financial Data")
        
        if process_btn:
            if not api_key:
                st.error("🔑 Google AI Studio API Key is required. Please enter it in the sidebar.")
            else:
                with st.spinner("Processing GIFI PDF pages..."):
                    # Save to a temporary file locally
                    uploaded_file.seek(0)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                        tmp_file.write(uploaded_file.read())
                        tmp_pdf_path = tmp_file.name
                    
                    try:
                        base64_images = extract_statement.render_pdf_pages(tmp_pdf_path)
                    finally:
                        if os.path.exists(tmp_pdf_path):
                            os.remove(tmp_pdf_path)
                    
                    if base64_images:
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        status_text.text(f"Extracting {len(base64_images)} GIFI pages in parallel...")
                        
                        completed = 0
                        all_extracted_items = []
                        meta_info = {}
                        
                        # Call Gemini OCR in parallel
                        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                            futures = {
                                executor.submit(gifi_extractor.extract_gifi_data, api_key, model, img_b64, i+1): i+1
                                for i, img_b64 in enumerate(base64_images)
                            }
                            
                            for future in concurrent.futures.as_completed(futures):
                                page_num = futures[future]
                                try:
                                    page_data = future.result()
                                    if page_data:
                                        if "gifi_items" in page_data:
                                            all_extracted_items.extend(page_data["gifi_items"])
                                        # Capture company meta from first valid response
                                        if page_data.get("corporation_name") and not meta_info.get("corporation_name"):
                                            meta_info["corporation_name"] = page_data["corporation_name"]
                                            meta_info["business_number"] = page_data.get("business_number", "")
                                            meta_info["tax_year_end"] = page_data.get("tax_year_end", "")
                                    else:
                                        st.sidebar.error(f"⚠️ Page {page_num} extraction returned no data. Check console logs.")
                                except Exception as e:
                                    st.warning(f"Error extracting page {page_num}: {e}")
                                    
                                completed += 1
                                status_text.text(f"Finished page {page_num} ({completed}/{len(base64_images)} processed)...")
                                progress_bar.progress(completed / len(base64_images))
                        
                        progress_bar.empty()
                        status_text.empty()
                        
                        if all_extracted_items:
                            st.session_state.gifi_raw_items = all_extracted_items
                            if meta_info:
                                st.session_state.gifi_meta = meta_info
                            st.success("🎉 GIFI statement parsed successfully!")
                            st.rerun()
                        else:
                            st.error("Failed to extract items from PDF. Please check the file and try again.")

    # 3. Editable review panel
    if st.session_state.gifi_raw_items:
        st.subheader("🔍 Review & Edit Financial Items")
        
        # Meta info inputs
        meta = st.session_state.gifi_meta
        edit_corp = st.text_input("Corporation Name", value=meta.get("corporation_name", ""))
        edit_bn = st.text_input("Business Number", value=meta.get("business_number", ""))
        edit_year_end = st.text_input("Tax Year End (YYYY/MM/DD)", value=meta.get("tax_year_end", ""))
        
        # Update meta state
        st.session_state.gifi_meta = {
            "corporation_name": edit_corp,
            "business_number": edit_bn,
            "tax_year_end": edit_year_end
        }
        
        # Display tabbed form editing
        tab_bs, tab_is = st.tabs(["🏦 Balance Sheet Items", "📈 Income Statement Items"])
        
        # Pre-classify for inputs
        classified = gifi_extractor.classify_gifi_items(st.session_state.gifi_raw_items)
        
        # Keep a mapping for updates
        updated_items = []
        
        with tab_bs:
            st.markdown("### Assets")
            for item in classified["current_assets"] + classified["tangible_assets"] + classified["long_term_assets"]:
                col_desc, col_cur, col_pri = st.columns([5, 3, 3])
                with col_desc:
                    d_val = st.text_input(f"Desc ({item['gifi_code']})", value=item["description"], key=f"desc_{item['gifi_code']}")
                with col_cur:
                    c_val = st.number_input(f"Current ({item['gifi_code']})", value=float(item["current_year"]), step=1.0, key=f"cur_{item['gifi_code']}")
                with col_pri:
                    p_val = st.number_input(f"Prior ({item['gifi_code']})", value=float(item["prior_year"]), step=1.0, key=f"pri_{item['gifi_code']}")
                
                updated_items.append({
                    "gifi_code": item["gifi_code"],
                    "description": d_val,
                    "current_year": c_val,
                    "prior_year": p_val
                })
                
            st.markdown("### Liabilities & Equity")
            for item in classified["current_liabilities"] + classified["long_term_liabilities"] + classified["equity_shares"] + classified["retained_earnings"]:
                col_desc, col_cur, col_pri = st.columns([5, 3, 3])
                with col_desc:
                    d_val = st.text_input(f"Desc ({item['gifi_code']})", value=item["description"], key=f"desc_{item['gifi_code']}")
                with col_cur:
                    c_val = st.number_input(f"Current ({item['gifi_code']})", value=float(item["current_year"]), step=1.0, key=f"cur_{item['gifi_code']}")
                with col_pri:
                    p_val = st.number_input(f"Prior ({item['gifi_code']})", value=float(item["prior_year"]), step=1.0, key=f"pri_{item['gifi_code']}")
                
                updated_items.append({
                    "gifi_code": item["gifi_code"],
                    "description": d_val,
                    "current_year": c_val,
                    "prior_year": p_val
                })
                
        with tab_is:
            st.markdown("### Revenues & Expenses")
            for item in classified["revenues"] + classified["cost_of_sales"] + classified["expenses"]:
                col_desc, col_cur, col_pri = st.columns([5, 3, 3])
                with col_desc:
                    d_val = st.text_input(f"Desc ({item['gifi_code']})", value=item["description"], key=f"desc_{item['gifi_code']}")
                with col_cur:
                    c_val = st.number_input(f"Current ({item['gifi_code']})", value=float(item["current_year"]), step=1.0, key=f"cur_{item['gifi_code']}")
                with col_pri:
                    p_val = st.number_input(f"Prior ({item['gifi_code']})", value=float(item["prior_year"]), step=1.0, key=f"pri_{item['gifi_code']}")
                
                updated_items.append({
                    "gifi_code": item["gifi_code"],
                    "description": d_val,
                    "current_year": c_val,
                    "prior_year": p_val
                })
                
            if classified["current_income_taxes"]:
                st.markdown("### Income Taxes")
                item = classified["current_income_taxes"]
                col_desc, col_cur, col_pri = st.columns([5, 3, 3])
                with col_desc:
                    d_val = st.text_input(f"Desc ({item['gifi_code']})", value=item["description"], key=f"desc_{item['gifi_code']}")
                with col_cur:
                    c_val = st.number_input(f"Current ({item['gifi_code']})", value=float(item["current_year"]), step=1.0, key=f"cur_{item['gifi_code']}")
                with col_pri:
                    p_val = st.number_input(f"Prior ({item['gifi_code']})", value=float(item["prior_year"]), step=1.0, key=f"pri_{item['gifi_code']}")
                
                updated_items.append({
                    "gifi_code": item["gifi_code"],
                    "description": d_val,
                    "current_year": c_val,
                    "prior_year": p_val
                })
                
        # Write back updates to session state
        st.session_state.gifi_raw_items = updated_items

with col_right:
    st.subheader("📄 Compiled Report Preview")
    
    # Calculate financial totals based on current edits
    classified = gifi_extractor.classify_gifi_items(st.session_state.gifi_raw_items)
    meta = st.session_state.gifi_meta
    
    # Assets Totals
    cur_assets_sum_cur = sum(x["current_year"] for x in classified["current_assets"])
    cur_assets_sum_pri = sum(x["prior_year"] for x in classified["current_assets"])
    
    tang_assets_sum_cur = sum(x["current_year"] for x in classified["tangible_assets"])
    tang_assets_sum_pri = sum(x["prior_year"] for x in classified["tangible_assets"])
    
    # Check if motor vehicles accumulated amortization GIFI 1743/2009 is present and should subtract
    # We will adjust tangible assets calculation to respect amortization subtraction if code is standard accum amort (e.g. 1743 or 2009)
    tang_assets_net_cur = 0.0
    tang_assets_net_pri = 0.0
    for x in classified["tangible_assets"]:
        if "amort" in x["description"].lower() or "accumulated" in x["description"].lower() or x["gifi_code"] in (1743, 2009):
            # Subtract amortization
            # Make sure value is negative or subtract it
            val_cur = abs(x["current_year"])
            val_pri = abs(x["prior_year"])
            tang_assets_net_cur -= val_cur
            tang_assets_net_pri -= val_pri
        else:
            tang_assets_net_cur += x["current_year"]
            tang_assets_net_pri += x["prior_year"]
            
    long_assets_sum_cur = sum(x["current_year"] for x in classified["long_term_assets"])
    long_assets_sum_pri = sum(x["prior_year"] for x in classified["long_term_assets"])
    
    total_assets_calc_cur = cur_assets_sum_cur + tang_assets_net_cur + long_assets_sum_cur
    total_assets_calc_pri = cur_assets_sum_pri + tang_assets_net_pri + long_assets_sum_pri
    
    # Liabilities Totals
    cur_liab_sum_cur = sum(x["current_year"] for x in classified["current_liabilities"])
    cur_liab_sum_pri = sum(x["prior_year"] for x in classified["current_liabilities"])
    
    long_liab_sum_cur = sum(x["current_year"] for x in classified["long_term_liabilities"])
    long_liab_sum_pri = sum(x["prior_year"] for x in classified["long_term_liabilities"])
    
    total_liab_calc_cur = cur_liab_sum_cur + long_liab_sum_cur
    total_liab_calc_pri = cur_liab_sum_pri + long_liab_sum_pri
    
    # Equity Totals
    shares_sum_cur = sum(x["current_year"] for x in classified["equity_shares"])
    shares_sum_pri = sum(x["prior_year"] for x in classified["equity_shares"])
    
    # We find retained earnings starting and reconciliation
    re_curr = sum(x["current_year"] for x in classified["retained_earnings"] if x["gifi_code"] == 3600)
    re_prior = sum(x["prior_year"] for x in classified["retained_earnings"] if x["gifi_code"] == 3600)
    
    # Fallback to general calculations if not explicitly set
    if re_curr == 0.0 and len(classified["retained_earnings"]) > 0:
        re_curr = classified["retained_earnings"][0]["current_year"]
        re_prior = classified["retained_earnings"][0]["prior_year"]
        
    total_equity_calc_cur = shares_sum_cur + re_curr
    total_equity_calc_pri = shares_sum_pri + re_prior
    
    total_liab_equity_cur = total_liab_calc_cur + total_equity_calc_cur
    total_liab_equity_pri = total_liab_calc_pri + total_equity_calc_pri
    
    # Balance sheet validation warning
    if st.session_state.gifi_raw_items:
        balance_mismatch_cur = abs(total_assets_calc_cur - total_liab_equity_cur)
        if balance_mismatch_cur > 1.0:
            st.warning(f"⚠️ Balance Sheet Mismatch (Current Year): Assets = ${total_assets_calc_cur:,.2f}, Liabilities + Equity = ${total_liab_equity_cur:,.2f}. Mismatch = ${balance_mismatch_cur:,.2f}")
            
    def format_business_number(bn):
        if not bn:
            return ""
        clean = str(bn).replace(" ", "").strip()
        if "RC" in clean:
            parts = clean.split("RC")
            return f"{parts[0]} RC{parts[1]}"
        else:
            digits = "".join(filter(str.isdigit, clean))
            if digits:
                return f"{digits} RC0001"
            return clean

    # Format Tax Year End
    tax_year_end_formatted = meta.get("tax_year_end", "")
    try:
        dt_ye = datetime.strptime(tax_year_end_formatted.replace("/", "-"), "%Y-%m-%d")
        tax_year_end_display = dt_ye.strftime("%B %d, %Y")
    except Exception:
        tax_year_end_display = tax_year_end_formatted

    # Select Letter Wording dynamically from config
    report_title_header = "NOTICE TO READER"
    letter_body = report_config.NOTICE_TO_READER_TEXT
    if include_preparer_details:
        signature_block_html = f"""
        Business Number: 793344540<br/><br/>
        Prepared by:<br/>
        <strong>RAMAN TAX & ACCOUNTING INC.</strong><br/>
        Phone: 604-440-9885<br/>
        Email: beedhtaxservices@outlook.com<br/>
        Date: {compilation_date_str}
        """
    else:
        signature_block_html = f"""
        {f"<strong>{compiler_name}</strong><br/>" if compiler_name else ""}
        {compilation_date_str}
        """
    note_text = report_config.NOTE_1_TEXT

    # Render Preview Pages inside Container tabs
    tab_p1, tab_p2, tab_p3, tab_p4, tab_p5 = st.tabs(["📄 Cover Page", "✉️ Letter", "⚖️ Balance Sheet", "📊 Income Statement", "📝 Notes"])
    
    with tab_p1:
        st.markdown(f"""
        <div class="page-preview">
            <div class="report-title">Financial Statements</div>
            <div class="company-name">{meta.get('corporation_name', '[Company Name]')}</div>
            <div class="date-title">For the year ended<br/><strong>{tax_year_end_display}</strong><br/>(Unaudited)</div>
        </div>
        """, unsafe_allow_html=True)
        
    with tab_p2:
        st.markdown(f"""
        <div class="page-preview">
            <div style="font-size: 16px; font-weight: bold; text-align: center; margin-bottom: 30px;">{report_title_header}</div>
            <div class="letter-text" style="white-space: pre-line;">{letter_body}</div>
            <div class="letter-text" style="margin-top: 50px;">
                {signature_block_html}
            </div>
        </div>
        """, unsafe_allow_html=True)
        
    with tab_p3:
        # Build balance sheet rows
        bs_rows_html = ""
        
        # Assets Header
        bs_rows_html += '<tr><td class="section-header">ASSETS</td><td></td><td></td></tr>'
        
        # Current Assets
        if classified["current_assets"]:
            bs_rows_html += '<tr><td class="subsection-header">Current Assets</td><td></td><td></td></tr>'
            for x in classified["current_assets"]:
                bs_rows_html += f'<tr><td class="indented-td">{x["description"]}</td><td class="num-col">${x["current_year"]:,.2f}</td><td class="num-col">${x["prior_year"]:,.2f}</td></tr>'
            bs_rows_html += f'<tr><td class="indented-td" style="font-weight: bold;">Total Current Assets</td><td class="num-col single-under" style="font-weight: bold;">${cur_assets_sum_cur:,.2f}</td><td class="num-col single-under" style="font-weight: bold;">${cur_assets_sum_pri:,.2f}</td></tr>'
            
        # Tangible Capital Assets
        if classified["tangible_assets"]:
            bs_rows_html += '<tr><td class="subsection-header">Tangible Capital Assets</td><td></td><td></td></tr>'
            for x in classified["tangible_assets"]:
                desc_str = x["description"]
                # Prefix with less for amortization
                if "amort" in desc_str.lower() or "accumulated" in desc_str.lower() or x["gifi_code"] in (1743, 2009):
                    bs_rows_html += f'<tr><td class="indented-td" style="font-style: italic;">Less: {desc_str}</td><td class="num-col">(${abs(x["current_year"]):,.2f})</td><td class="num-col">(${abs(x["prior_year"]):,.2f})</td></tr>'
                else:
                    bs_rows_html += f'<tr><td class="indented-td">{desc_str}</td><td class="num-col">${x["current_year"]:,.2f}</td><td class="num-col">${x["prior_year"]:,.2f}</td></tr>'
            bs_rows_html += f'<tr><td class="indented-td" style="font-weight: bold;">Net Tangible Assets</td><td class="num-col single-under" style="font-weight: bold;">${tang_assets_net_cur:,.2f}</td><td class="num-col single-under" style="font-weight: bold;">${tang_assets_net_pri:,.2f}</td></tr>'
            
        # Long Term Assets
        if classified["long_term_assets"]:
            bs_rows_html += '<tr><td class="subsection-header">Long Term Assets</td><td></td><td></td></tr>'
            for x in classified["long_term_assets"]:
                bs_rows_html += f'<tr><td class="indented-td">{x["description"]}</td><td class="num-col">${x["current_year"]:,.2f}</td><td class="num-col">${x["prior_year"]:,.2f}</td></tr>'
            bs_rows_html += f'<tr><td class="indented-td" style="font-weight: bold;">Total Long Term Assets</td><td class="num-col single-under" style="font-weight: bold;">${long_assets_sum_cur:,.2f}</td><td class="num-col single-under" style="font-weight: bold;">${long_assets_sum_pri:,.2f}</td></tr>'
            
        # Total Assets
        bs_rows_html += f'<tr><td class="section-header" style="font-weight: bold;">TOTAL ASSETS</td><td class="num-col double-under" style="font-weight: bold;">${total_assets_calc_cur:,.2f}</td><td class="num-col double-under" style="font-weight: bold;">${total_assets_calc_pri:,.2f}</td></tr>'
        
        # Liabilities Header
        bs_rows_html += '<tr><td class="section-header">LIABILITIES</td><td></td><td></td></tr>'
        
        # Current Liabilities
        if classified["current_liabilities"]:
            bs_rows_html += '<tr><td class="subsection-header">Current Liabilities</td><td></td><td></td></tr>'
            for x in classified["current_liabilities"]:
                bs_rows_html += f'<tr><td class="indented-td">{x["description"]}</td><td class="num-col">${x["current_year"]:,.2f}</td><td class="num-col">${x["prior_year"]:,.2f}</td></tr>'
            bs_rows_html += f'<tr><td class="indented-td" style="font-weight: bold;">Total Current Liabilities</td><td class="num-col single-under" style="font-weight: bold;">${cur_liab_sum_cur:,.2f}</td><td class="num-col single-under" style="font-weight: bold;">${cur_liab_sum_pri:,.2f}</td></tr>'
            
        # Long-Term Liabilities
        if classified["long_term_liabilities"]:
            bs_rows_html += '<tr><td class="subsection-header">Long-Term Liabilities</td><td></td><td></td></tr>'
            for x in classified["long_term_liabilities"]:
                bs_rows_html += f'<tr><td class="indented-td">{x["description"]}</td><td class="num-col">${x["current_year"]:,.2f}</td><td class="num-col">${x["prior_year"]:,.2f}</td></tr>'
            bs_rows_html += f'<tr><td class="indented-td" style="font-weight: bold;">Total Long-Term Liabilities</td><td class="num-col single-under" style="font-weight: bold;">${long_liab_sum_cur:,.2f}</td><td class="num-col single-under" style="font-weight: bold;">${long_liab_sum_pri:,.2f}</td></tr>'
            
        # Shareholder Equity
        bs_rows_html += '<tr><td class="section-header">SHAREHOLDER EQUITY</td><td></td><td></td></tr>'
        for x in classified["equity_shares"]:
            bs_rows_html += f'<tr><td class="indented-td">{x["description"]}</td><td class="num-col">${x["current_year"]:,.2f}</td><td class="num-col">${x["prior_year"]:,.2f}</td></tr>'
        bs_rows_html += f'<tr><td class="indented-td">Retained Earnings (Deficit)</td><td class="num-col">${re_curr:,.2f}</td><td class="num-col">${re_prior:,.2f}</td></tr>'
        bs_rows_html += f'<tr><td class="indented-td" style="font-weight: bold;">Total Shareholder Equity</td><td class="num-col single-under" style="font-weight: bold;">${total_equity_calc_cur:,.2f}</td><td class="num-col single-under" style="font-weight: bold;">${total_equity_calc_pri:,.2f}</td></tr>'
        
        # Total Liabilities & Equity
        bs_rows_html += f'<tr><td class="section-header" style="font-weight: bold;">TOTAL LIABILITIES & EQUITY</td><td class="num-col double-under" style="font-weight: bold;">${total_liab_equity_cur:,.2f}</td><td class="num-col double-under" style="font-weight: bold;">${total_liab_equity_pri:,.2f}</td></tr>'

        st.markdown(f"""
        <div class="page-preview">
            <div style="font-size: 16px; font-weight: bold; text-align: center; margin-bottom: 5px;">{meta.get('corporation_name', '[Company Name]')}</div>
            <div style="font-size: 14px; text-align: center; font-style: italic; margin-bottom: 20px;">Balance Sheet as at {tax_year_end_display}<br/>(Unaudited)</div>
            <table class="report-table">
                <thead>
                    <tr>
                        <th style="text-align: left;">Account Description</th>
                        <th class="num-col">Current Year</th>
                        <th class="num-col">Prior Year</th>
                    </tr>
                </thead>
                <tbody>
                    {bs_rows_html}
                </tbody>
            </table>
            <div style="margin-top: 30px; font-size: 11px; text-align: center;">See accompanying Notes to Financial Statements.</div>
        </div>
        """, unsafe_allow_html=True)
        
    with tab_p4:
        # Build income statement rows
        is_rows_html = ""
        
        total_rev_cur = sum(x["current_year"] for x in classified["revenues"])
        total_rev_pri = sum(x["prior_year"] for x in classified["revenues"])
        
        total_cogs_cur = sum(-x["current_year"] if x["gifi_code"] == 8500 else x["current_year"] for x in classified["cost_of_sales"])
        total_cogs_pri = sum(-x["prior_year"] if x["gifi_code"] == 8500 else x["prior_year"] for x in classified["cost_of_sales"])
        
        gross_profit_cur = total_rev_cur - total_cogs_cur
        gross_profit_pri = total_rev_pri - total_cogs_pri
        
        total_exp_cur = sum(x["current_year"] for x in classified["expenses"])
        total_exp_pri = sum(x["prior_year"] for x in classified["expenses"])
        
        net_income_before_tax_cur = gross_profit_cur - total_exp_cur
        net_income_before_tax_pri = gross_profit_pri - total_exp_pri
        
        tax_cur = sum(x["current_year"] for x in st.session_state.gifi_raw_items if x["gifi_code"] == 9990)
        tax_pri = sum(x["prior_year"] for x in st.session_state.gifi_raw_items if x["gifi_code"] == 9990)
        
        net_income_after_tax_cur = net_income_before_tax_cur - tax_cur
        net_income_after_tax_pri = net_income_before_tax_pri - tax_pri
        
        # Revenues
        is_rows_html += '<tr><td class="section-header">REVENUE</td><td></td><td></td></tr>'
        for x in classified["revenues"]:
            is_rows_html += f'<tr><td class="indented-td">{x["description"]}</td><td class="num-col">${x["current_year"]:,.2f}</td><td class="num-col">${x["prior_year"]:,.2f}</td></tr>'
        is_rows_html += f'<tr><td class="indented-td" style="font-weight: bold;">Total Revenue</td><td class="num-col single-under" style="font-weight: bold;">${total_rev_cur:,.2f}</td><td class="num-col single-under" style="font-weight: bold;">${total_rev_pri:,.2f}</td></tr>'
        
        # Cost of Sales
        if classified["cost_of_sales"]:
            is_rows_html += '<tr><td class="section-header">COST OF SALES</td><td></td><td></td></tr>'
            for x in classified["cost_of_sales"]:
                is_rows_html += f'<tr><td class="indented-td">{x["description"]}</td><td class="num-col">${x["current_year"]:,.2f}</td><td class="num-col">${x["prior_year"]:,.2f}</td></tr>'
            is_rows_html += f'<tr><td class="indented-td" style="font-weight: bold;">Total Cost of Sales</td><td class="num-col single-under" style="font-weight: bold;">${total_cogs_cur:,.2f}</td><td class="num-col single-under" style="font-weight: bold;">${total_cogs_pri:,.2f}</td></tr>'
            is_rows_html += f'<tr><td class="indented-td" style="font-weight: bold;">Gross Profit</td><td class="num-col single-under" style="font-weight: bold;">${gross_profit_cur:,.2f}</td><td class="num-col single-under" style="font-weight: bold;">${gross_profit_pri:,.2f}</td></tr>'
            
        # Expenses
        is_rows_html += '<tr><td class="section-header">OPERATING EXPENSES</td><td></td><td></td></tr>'
        for x in classified["expenses"]:
            is_rows_html += f'<tr><td class="indented-td">{x["description"]}</td><td class="num-col">${x["current_year"]:,.2f}</td><td class="num-col">${x["prior_year"]:,.2f}</td></tr>'
        is_rows_html += f'<tr><td class="indented-td" style="font-weight: bold;">Total Operating Expenses</td><td class="num-col single-under" style="font-weight: bold;">${total_exp_cur:,.2f}</td><td class="num-col single-under" style="font-weight: bold;">${total_exp_pri:,.2f}</td></tr>'
        
        # Net Income Before Tax
        is_rows_html += f'<tr><td class="section-header" style="font-weight: bold;">NET INCOME BEFORE INCOME TAXES</td><td class="num-col single-under" style="font-weight: bold;">${net_income_before_tax_cur:,.2f}</td><td class="num-col single-under" style="font-weight: bold;">${net_income_before_tax_pri:,.2f}</td></tr>'
        
        # Income Taxes
        is_rows_html += f'<tr><td class="indented-td">Current Income Taxes</td><td class="num-col">${tax_cur:,.2f}</td><td class="num-col">${tax_pri:,.2f}</td></tr>'
        
        # Net Income After Tax
        is_rows_html += f'<tr><td class="section-header" style="font-weight: bold;">NET INCOME (LOSS) FOR THE YEAR</td><td class="num-col double-under" style="font-weight: bold;">${net_income_after_tax_cur:,.2f}</td><td class="num-col double-under" style="font-weight: bold;">${net_income_after_tax_pri:,.2f}</td></tr>'

        st.markdown(f"""
        <div class="page-preview">
            <div style="font-size: 16px; font-weight: bold; text-align: center; margin-bottom: 5px;">{meta.get('corporation_name', '[Company Name]')}</div>
            <div style="font-size: 14px; text-align: center; font-style: italic; margin-bottom: 20px;">Income Statement<br/>For the year ended {tax_year_end_display}<br/>(Unaudited)</div>
            <table class="report-table">
                <thead>
                    <tr>
                        <th style="text-align: left;">Account Description</th>
                        <th class="num-col">Current Year</th>
                        <th class="num-col">Prior Year</th>
                    </tr>
                </thead>
                <tbody>
                    {is_rows_html}
                </tbody>
            </table>
            <div style="margin-top: 30px; font-size: 11px; text-align: center;">See accompanying Notes to Financial Statements.</div>
        </div>
        """, unsafe_allow_html=True)
        
    with tab_p5:
        st.markdown(f"""
        <div class="page-preview">
            <div style="font-size: 16px; font-weight: bold; text-align: center; margin-bottom: 40px;">{meta.get('corporation_name', '[Company Name]')}</div>
            <div style="font-size: 14px; text-align: center; font-style: italic; margin-bottom: 40px;">Notes to Financial Statements<br/>For the year ended {tax_year_end_display}<br/>(Unaudited)</div>
            <div style="font-size: 14px; font-weight: bold; margin-top: 20px;">NOTE 1: BASIS OF ACCOUNTING</div>
            <div style="font-size: 14px; text-align: justify; margin-top: 10px;">{note_text}</div>
        </div>
        """, unsafe_allow_html=True)

    # 4. Generate print-ready HTML file download
    html_report = f"""<!DOCTYPE html>
<html>
<head>
    <title>Financial Statements - {meta.get('corporation_name', 'Company')}</title>
    <style>
        body {{
            font-family: 'Times New Roman', Times, serif;
            color: #000;
            background: #fff;
            margin: 0;
            padding: 0;
        }}
        .page {{
            page-break-after: always;
            padding: 2.5cm;
            box-sizing: border-box;
        }}
        .page:last-child {{
            page-break-after: avoid;
        }}
        .report-title {{
            font-size: 28px;
            font-weight: bold;
            text-align: center;
            margin-top: 5cm;
            text-transform: uppercase;
            letter-spacing: 2px;
        }}
        .report-subtitle {{
            font-size: 16px;
            text-align: center;
            margin-top: 1cm;
        }}
        .company-name {{
            font-size: 22px;
            font-weight: bold;
            text-align: center;
            margin-top: 0.5cm;
            text-transform: uppercase;
        }}
        .date-title {{
            font-size: 16px;
            text-align: center;
            margin-top: 4cm;
        }}
        .letter-text {{
            font-size: 14px;
            text-align: justify;
            margin-bottom: 20px;
            line-height: 1.6;
        }}
        .report-table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 20px 0px;
            margin-top: 30px;
        }}
        .report-table th {{
            font-size: 14px;
            font-weight: bold;
            border-bottom: 1.5px solid #000;
            padding: 8px 0px;
            text-align: left;
        }}
        .report-table td {{
            font-size: 14px;
            padding: 6px 0px;
        }}
        .num-col {{
            text-align: right;
            width: 22%;
        }}
        .single-under {{
            border-top: 1.5px solid #000;
        }}
        .double-under {{
            border-top: 1.5px solid #000;
            border-bottom: 4px double #000;
        }}
        .section-header {{
            font-weight: bold;
            text-transform: uppercase;
            padding-top: 15px !important;
        }}
        .subsection-header {{
            font-weight: bold;
            padding-left: 10px;
        }}
        .indented-td {{
            padding-left: 20px !important;
        }}
    </style>
</head>
<body>
    <!-- Page 1: Cover Page -->
    <div class="page">
        <div class="report-title">Financial Statements</div>
        <div class="company-name">{meta.get('corporation_name', 'Company')}</div>
        <div class="date-title">For the year ended<br/><strong>{tax_year_end_display}</strong><br/>(Unaudited)</div>
    </div>
    
    <!-- Page 2: Letter -->
    <div class="page">
        <div style="font-size: 16px; font-weight: bold; text-align: center; margin-bottom: 40px;">{report_title_header}</div>
        <div class="letter-text" style="white-space: pre-line;">{letter_body}</div>
        <div class="letter-text" style="margin-top: 60px;">
            {signature_block_html}
        </div>
    </div>
    
    <!-- Page 3: Balance Sheet -->
    <div class="page">
        <div style="font-size: 16px; font-weight: bold; text-align: center; margin-bottom: 5px;">{meta.get('corporation_name', 'Company')}</div>
        <div style="font-size: 14px; text-align: center; font-style: italic; margin-bottom: 20px;">Balance Sheet as at {tax_year_end_display}<br/>(Unaudited)</div>
        <table class="report-table">
            <thead>
                <tr>
                    <th style="text-align: left;">Account Description</th>
                    <th class="num-col">Current Year</th>
                    <th class="num-col">Prior Year</th>
                </tr>
            </thead>
            <tbody>
                {bs_rows_html}
            </tbody>
        </table>
        <div style="margin-top: 40px; font-size: 11px; text-align: center;">See accompanying Notes to Financial Statements.</div>
    </div>
    
    <!-- Page 4: Income Statement -->
    <div class="page">
        <div style="font-size: 16px; font-weight: bold; text-align: center; margin-bottom: 5px;">{meta.get('corporation_name', 'Company')}</div>
        <div style="font-size: 14px; text-align: center; font-style: italic; margin-bottom: 20px;">Income Statement<br/>For the year ended {tax_year_end_display}<br/>(Unaudited)</div>
        <table class="report-table">
            <thead>
                <tr>
                    <th style="text-align: left;">Account Description</th>
                    <th class="num-col">Current Year</th>
                    <th class="num-col">Prior Year</th>
                </tr>
            </thead>
            <tbody>
                {is_rows_html}
            </tbody>
        </table>
        <div style="margin-top: 40px; font-size: 11px; text-align: center;">See accompanying Notes to Financial Statements.</div>
    </div>
    
    <!-- Page 5: Notes -->
    <div class="page">
        <div style="font-size: 16px; font-weight: bold; text-align: center; margin-bottom: 40px;">{meta.get('corporation_name', 'Company')}</div>
        <div style="font-size: 14px; text-align: center; font-style: italic; margin-bottom: 40px;">Notes to Financial Statements<br/>For the year ended {tax_year_end_display}<br/>(Unaudited)</div>
        <div style="font-size: 14px; font-weight: bold; margin-top: 20px;">NOTE 1: BASIS OF ACCOUNTING</div>
        <div style="font-size: 14px; text-align: justify; margin-top: 10px;">{note_text}</div>
    </div>
</body>
</html>"""

    # 5. Generate direct PDF using ReportLab
    import gifi_pdf_generator
    try:
        pdf_report_data = gifi_pdf_generator.generate_financial_pdf(
            meta, classified, compiler_name, compilation_date_str, report_type, basis_of_accounting,
            include_preparer_details=include_preparer_details
        )
    except Exception as pdf_err:
        pdf_report_data = None
        st.error(f"Error compiling PDF: {pdf_err}")
        st.exception(pdf_err)

    # Add HTML & PDF Download Actions
    st.markdown("---")
    col_dl1, col_dl2, col_dl3 = st.columns(3)
    with col_dl1:
        if pdf_report_data:
            st.download_button(
                label="📥 Download PDF Report",
                data=pdf_report_data,
                file_name=f"financial_statements_{meta.get('corporation_name', 'Company').replace(' ', '_')}.pdf",
                mime="application/pdf"
            )
        else:
            st.warning("⚠️ Direct PDF generation unavailable.")
    with col_dl2:
        st.download_button(
            label="📥 Download HTML Report (Print Ready)",
            data=html_report,
            file_name=f"financial_statements_{meta.get('corporation_name', 'Company').replace(' ', '_')}.html",
            mime="text/html"
        )
    with col_dl3:
        st.info("💡 **Which to choose?**: Use the **PDF** button for instant print-ready download, or use the **HTML** button for browser-native printing customization (`Ctrl + P`).")
