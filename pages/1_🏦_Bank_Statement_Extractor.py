import streamlit as st
import os
import json
import tempfile
import pandas as pd
import base64
from io import BytesIO
import matplotlib.pyplot as plt
import seaborn as sns
import sys

# Import helper functions from extract_statement
# Ensure parent directory is in path since we are in pages/
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import extract_statement
import auth
import categorizer
import importlib
importlib.reload(categorizer)

# Set page config for premium styling
st.set_page_config(
    page_title="Bank Statement Extractor",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Password Check
if not auth.check_password():
    st.stop()

# Custom CSS for rich aesthetics
st.markdown("""
<style>
    .reportview-container {
        background: #f0f2f6;
    }
    .metric-card {
        background-color: #ffffff;
        border: 1px solid #e6e9ef;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
        text-align: center;
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
    .stButton>button {
        background-color: #4CAF50;
        color: white;
        border-radius: 8px;
        font-weight: bold;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #45a049;
        transform: translateY(-2px);
    }
</style>
""", unsafe_allow_html=True)

# Main Title & Description
st.title("🏦 Bank Statement Transaction Extractor")
st.markdown("""
Extract transaction history from both **digital** and **scanned (image-only)** PDF statements.
This tool will automatically verify the mathematical integrity of the statement's balance flow and output a clean CSV file.
""")

# Sidebar settings
st.sidebar.header("⚙️ Configuration")

# API Key management
api_key_default = os.environ.get("GEMINI_API_KEY", "")
if not api_key_default and "GEMINI_API_KEY" in st.secrets:
    api_key_default = st.secrets["GEMINI_API_KEY"]
    
api_key = st.sidebar.text_input(
    "Google AI Studio API Key",
    type="password",
    value=api_key_default,
    help="Required for scanned/image-only PDFs. Get a free key at https://aistudio.google.com/"
)

extraction_engine = st.sidebar.radio(
    "Extraction Engine",
    ["Gemini AI Engine (Cloud OCR)", "Local Python Engine (Private & Offline)"],
    index=1,
    help="Select 'Local Python Engine' to parse digital text statements locally using custom layout rules, or 'Gemini AI Engine' to use Cloud OCR."
)

mapping_excel = None
if extraction_engine == "Local Python Engine (Private & Offline)":
    mapping_excel = st.sidebar.file_uploader(
        "Upload Custom Map sheet (Optional)",
        type=["xlsx", "xls"],
        help="Upload an Excel sheet containing columns: Keyword, Category Name, Excel Column Name, GST Rate, PST Rate, GIFI Code."
    )

model = st.sidebar.selectbox(
    "Gemini OCR Model",
    ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest", "gemini-2.5-pro"],
    index=0,
    help="Flash models are highly recommended for fast table extraction."
)

force_ocr = st.sidebar.checkbox(
    "Force OCR Mode",
    value=False,
    help="Force image-based OCR extraction even if the PDF contains digital text."
)

sort_chronologically = st.sidebar.checkbox(
    "Sort Output Chronologically",
    value=False,
    help="Sort transactions from oldest to newest. Uncheck this to keep the native statement order (Payments first, then Interest, then Charges)."
)

from datetime import datetime, date
client_name = ""
account_name = ""
institution = ""
statement_start = date(2024, 1, 1)
statement_end = date(2024, 12, 31)
target_spreadsheet_id = st.sidebar.text_input(
    "Target Google Sheet ID / URL",
    value=st.secrets.get("google_sheets", {}).get("spreadsheet_id", ""),
    help="Paste the target Google Sheet's browser URL or its ID here. Ensure you've shared the Sheet with the service account email."
)
dest_sheet_override = st.sidebar.selectbox(
    "Destination Sheet Tab",
    ["Create New Tab", "[Auto-detect based on file]", "Bank Transactions", "Bank Single Column", "Credit Card"],
    index=0,
    help="Select the target Google Sheet tab. 'Create New Tab' will dynamically create a new tab in your Google Sheet named after the statement filename."
)

st.sidebar.markdown("---")
st.sidebar.markdown("### How it works:")
st.sidebar.info("""
1. **Upload** your statement PDF(s).
2. The tool checks for **digital text** first (free).
3. If scanned, it renders pages using **pypdfium2** and uses **Gemini Vision OCR** to extract the rows.
4. It **mathematically validates** the transactions chronologically and flags errors.
""")

# File Uploader
uploaded_files = st.file_uploader("Upload your Bank Statement PDF(s)", type=["pdf"], accept_multiple_files=True)

if uploaded_files:
    # Clear session state if files change
    combined_key = "_".join([f"{f.name}_{f.size}" for f in uploaded_files])
    if "current_file_key" not in st.session_state or st.session_state.current_file_key != combined_key:
        st.session_state.bank_transactions = []
        st.session_state.current_file_key = combined_key

    # Check if there is digital PDF
    has_digital = False
    if not force_ocr:
        # Check first file as representative
        with st.spinner("Checking PDF type..."):
            test_pages = extract_statement.extract_digital_text(uploaded_files[0])
            if test_pages:
                has_digital = True

    # Action button
    if extraction_engine == "Local Python Engine (Private & Offline)":
        btn_label = "⚡ Process with Local Python Layout Engine (Offline)"
    else:
        btn_label = "⚡ Extract from Digital PDF(s) (Free)" if has_digital else "👁️ Extract via Gemini Vision OCR"
    run_extraction = st.button(btn_label)

    if run_extraction:
        all_combined_txs = []
        local_reconciliation_results = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for file_idx, u_file in enumerate(uploaded_files):
            status_text.text(f"Processing file {file_idx+1}/{len(uploaded_files)}: {u_file.name}...")
            progress_bar.progress(file_idx / len(uploaded_files))
            
            # Reset stream pointer
            u_file.seek(0)
            text_pages = []
            is_digital = False
            
            if not force_ocr:
                text_pages = extract_statement.extract_digital_text(u_file)
                if text_pages:
                    is_digital = True
            
            transactions = []
            detected_bank = "Standard"
            opening_bal = 0.0
            
            if extraction_engine == "Local Python Engine (Private & Offline)":
                import local_extractor
                if is_digital:
                    u_file.seek(0)
                    detected_bank = local_extractor.detect_bank(u_file)
                    st.info(f"📋 Detected Bank Layout for {u_file.name}: **{detected_bank}**")
                    
                    u_file.seek(0)
                    transactions, opening_bal = local_extractor.extract_digital_pdf(u_file, detected_bank)
                    
                    # Reconcile this statement
                    reconciliation = local_extractor.reconcile_transactions(transactions, opening_bal)
                    reconciliation["file_name"] = u_file.name
                    reconciliation["bank_name"] = detected_bank
                    local_reconciliation_results.append(reconciliation)
                else:
                    st.warning(f"⚠️ {u_file.name} appears to be a scanned statement. Local engine requires digital PDFs. Switch to Gemini AI Engine in the sidebar to process scanned statements.")
                    continue
            else:
                if is_digital:
                    with st.spinner(f"Extracting digital text from {u_file.name}..."):
                        transactions = extract_statement.parse_digital_text(text_pages)
                        if not transactions and api_key:
                            with st.spinner(f"No transactions matched local regex. Falling back to Gemini API Text-parsing..."):
                                full_text = "\n".join(text_pages)
                                transactions = extract_statement.call_gemini_api_for_text(api_key, model, full_text)
                else:
                    # Scanned statement - requires API Key
                    if not api_key:
                        st.error(f"🔑 Gemini API Key is required to process scanned statements. Skipped: {u_file.name}")
                        continue
                    else:
                        # Reset stream pointer
                        u_file.seek(0)
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                            tmp_file.write(u_file.read())
                            tmp_pdf_path = tmp_file.name
                        
                        try:
                            base64_images = extract_statement.render_pdf_pages(tmp_pdf_path)
                        except Exception as e:
                            st.error(f"Failed to render pages of {u_file.name}: {e}")
                            base64_images = []
                        finally:
                            if os.path.exists(tmp_pdf_path):
                                try:
                                    os.remove(tmp_pdf_path)
                                except Exception:
                                    pass
                                    
                        if base64_images:
                            import concurrent.futures
                            max_workers = 3
                            transactions_by_page = {}
                            
                            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                                futures = {
                                    executor.submit(extract_statement.call_gemini_api, api_key, model, img_b64, i+1): i+1
                                    for i, img_b64 in enumerate(base64_images)
                                }
                                
                                for future in concurrent.futures.as_completed(futures):
                                    page_num = futures[future]
                                    try:
                                        page_txs = future.result()
                                        transactions_by_page[page_num] = page_txs
                                    except Exception as e:
                                        st.warning(f"Error on page {page_num} of {u_file.name}: {e}")
                                        transactions_by_page[page_num] = []
                            
                            for page_num in sorted(transactions_by_page.keys()):
                                transactions.extend(transactions_by_page[page_num])
            
            if transactions:
                # Validate the flow for this statement
                with st.spinner(f"Validating balance flows for {u_file.name}..."):
                    validated_txs = extract_statement.validate_and_correct_transactions(
                        transactions, sort_chronologically=sort_chronologically
                    )
                for tx in validated_txs:
                    tx["source_file"] = u_file.name
                    tx["institution"] = detected_bank if extraction_engine == "Local Python Engine (Private & Offline)" else institution
                all_combined_txs.extend(validated_txs)
                
        progress_bar.progress(1.0)
        status_text.text("Finished processing all files!")
        
        # Save local reconciliation results to session state
        st.session_state.local_reconciliation_results = local_reconciliation_results
        
        if all_combined_txs:
            if extraction_engine == "Local Python Engine (Private & Offline)":
                df = pd.DataFrame(all_combined_txs)
                df['source_tab'] = "Bank"
                df['date'] = pd.to_datetime(df['date'], errors='coerce')
                if sort_chronologically:
                    df = df.sort_values(by='date').reset_index(drop=True)
                else:
                    is_cc = (df['is_credit_card'].any() if 'is_credit_card' in df.columns else False) or df['description'].str.lower().str.contains("payment thank you|paiement merci").any()
                    if is_cc:
                        # Group by Statement Sections (Payments -> Interest -> Charges)
                        payments = []
                        interest = []
                        charges = []
                        for _, row in df.iterrows():
                            desc = str(row.get('description', '')).lower()
                            cred = pd.to_numeric(row.get('credit'), errors='coerce')
                            is_payment = (pd.notna(cred) and cred > 0) or "payment thank you" in desc or "paiement merci" in desc
                            is_interest = "interest" in desc or "purchases 20.99%" in desc or "regular purchases" in desc
                            
                            if is_payment:
                                payments.append(row)
                            elif is_interest:
                                interest.append(row)
                            else:
                                charges.append(row)
                                
                        payments_df = pd.DataFrame(payments)
                        if not payments_df.empty:
                            payments_df = payments_df.sort_values(by='date', kind='mergesort')
                        interest_df = pd.DataFrame(interest)
                        if not interest_df.empty:
                            interest_df = interest_df.sort_values(by='date', kind='mergesort')
                        charges_df = pd.DataFrame(charges)
                        if not charges_df.empty:
                            charges_df = charges_df.sort_values(by='date', kind='mergesort')
                            
                        df = pd.concat([payments_df, interest_df, charges_df], ignore_index=True)
                    else:
                        df = df.reset_index(drop=True)
                df['date'] = df['date'].dt.strftime('%Y-%m-%d')
                
                # Pre-populate categories using saved rules database (learned overrides)
                updated_categories = []
                updated_suggested = []
                updated_gifi = []
                updated_gst = []
                for _, row in df.iterrows():
                    desc = row.get("description", "")
                    
                    # 1. Assigned Category (checks user overrides first)
                    d_cat, d_gifi, d_gst = categorizer.lookup_with_overrides(desc)
                    
                    # 2. Raw Suggested Category (checks static rules first)
                    ai_cat, _, _ = categorizer.lookup_by_rules(desc)
                    if not ai_cat:
                        ai_cat = "Uncategorized"
                        
                    # Standard default fallbacks for assigned category
                    if not d_cat:
                        d_cat = "Uncategorized"
                        d_gifi = ""
                        d_gst = ""
                        
                    updated_categories.append(d_cat)
                    updated_suggested.append(ai_cat)
                    updated_gifi.append(d_gifi)
                    updated_gst.append(d_gst)
                    
                df['category'] = updated_categories
                df['suggested_category'] = updated_suggested
                df['gifi_code'] = updated_gifi
                df['gst_rate'] = updated_gst
                
                # Apply custom map
                if mapping_excel:
                    with st.spinner("Applying custom Category Map from Excel..."):
                        import local_extractor
                        df = local_extractor.apply_excel_category_map(df, mapping_excel)
                
                # Ensure all columns exist and are ordered
                cols_order = ['source_tab', 'date', 'description', 'debit', 'credit', 'balance', 'category', 'suggested_category', 'gifi_code', 'gst_rate', 'source_file', 'institution', 'is_credit_card']
                for col in cols_order:
                    if col not in df.columns:
                        df[col] = ""
                df = df[cols_order]
                
                st.session_state.bank_df = df
                st.success(f"🎉 Successfully extracted {len(df)} transactions locally from {len(uploaded_files)} files!")
            else:
                with st.spinner("Auto-categorizing all extracted transactions..."):
                    # Run auto-categorization helper
                    categorized_txs = categorizer.categorize_transactions(api_key, all_combined_txs)
                    
                    # Convert to DataFrame
                    df = pd.DataFrame(categorized_txs)
                    df['source_tab'] = "Bank"
                    df['date'] = pd.to_datetime(df['date'], errors='coerce')
                    if sort_chronologically:
                        df = df.sort_values(by='date').reset_index(drop=True)
                    else:
                        is_cc = (df['is_credit_card'].any() if 'is_credit_card' in df.columns else False) or df['description'].str.lower().str.contains("payment thank you|paiement merci").any()
                        if is_cc:
                            # Group by Statement Sections (Payments -> Interest -> Charges)
                            payments = []
                            interest = []
                            charges = []
                            for _, row in df.iterrows():
                                desc = str(row.get('description', '')).lower()
                                cred = pd.to_numeric(row.get('credit'), errors='coerce')
                                is_payment = (pd.notna(cred) and cred > 0) or "payment thank you" in desc or "paiement merci" in desc
                                is_interest = "interest" in desc or "purchases 20.99%" in desc or "regular purchases" in desc
                                
                                if is_payment:
                                                                    payments.append(row)
                                elif is_interest:
                                                                    interest.append(row)
                                else:
                                                                    charges.append(row)
                                    
                            payments_df = pd.DataFrame(payments)
                            if not payments_df.empty:
                                                            payments_df = payments_df.sort_values(by='date', kind='mergesort')
                            interest_df = pd.DataFrame(interest)
                            if not interest_df.empty:
                                                            interest_df = interest_df.sort_values(by='date', kind='mergesort')
                            charges_df = pd.DataFrame(charges)
                            if not charges_df.empty:
                                                            charges_df = charges_df.sort_values(by='date', kind='mergesort')
                                
                            df = pd.concat([payments_df, interest_df, charges_df], ignore_index=True)
                        else:
                            df = df.reset_index(drop=True)
                    df['date'] = df['date'].dt.strftime('%Y-%m-%d')
                    
                    # Ensure all columns exist and are ordered
                    cols_order = ['source_tab', 'date', 'description', 'debit', 'credit', 'balance', 'category', 'suggested_category', 'gifi_code', 'gst_rate', 'source_file', 'institution', 'is_credit_card']
                    for col in cols_order:
                        if col not in df.columns:
                            df[col] = ""
                    df = df[cols_order]
                    
                    st.session_state.bank_df = df
                    st.success(f"🎉 Successfully extracted {len(df)} transactions from {len(uploaded_files)} files!")
        else:
            st.warning("⚠️ No transactions could be extracted from the uploaded files.")

    # Now render dashboard if transactions are loaded in session state
    if "bank_df" in st.session_state and st.session_state.bank_df is not None:
        df = st.session_state.bank_df
        
        # Display reconciliation warning if mismatch found in local extraction
        if "local_reconciliation_results" in st.session_state and st.session_state.local_reconciliation_results:
            st.subheader("📋 Offline Reconciliation Audit Log")
            for result in st.session_state.local_reconciliation_results:
                if not result["reconciled"]:
                    st.error(f"⚠️ **{result['file_name']} ({result['bank_name']}) Reconciliation Warning**: Difference of **${result['difference']:,.2f}** (Opening: ${result['opening_balance']:,.2f}, Calculated Closing: ${result['closing_balance'] - result['difference']:,.2f}, Actual: ${result['closing_balance']:,.2f})")
                else:
                    st.success(f"✅ **{result['file_name']} ({result['bank_name']}) Reconciled**: Opening ${result['opening_balance']:,.2f} matches transaction flow to Closing ${result['closing_balance']:,.2f}")
            st.write("")
        
        # Metrics Calculation
        total_debits = pd.to_numeric(df['debit'], errors='coerce').fillna(0).sum()
        total_credits = pd.to_numeric(df['credit'], errors='coerce').fillna(0).sum()
        # Ensure we read opening balance from local reconciliation if available
        first_op = None
        if "local_reconciliation_results" in st.session_state and st.session_state.local_reconciliation_results:
            first_op = st.session_state.local_reconciliation_results[0]["opening_balance"]
            
        if first_op is not None:
            opening_bal = first_op
        else:
            # Fallback calculation
            raw_bal = pd.to_numeric(df.iloc[0]['balance'], errors='coerce')
            raw_deb = pd.to_numeric(df.iloc[0]['debit'], errors='coerce')
            raw_cred = pd.to_numeric(df.iloc[0]['credit'], errors='coerce')
            
            val_bal = float(raw_bal) if pd.notna(raw_bal) else 0.0
            val_deb = float(raw_deb) if pd.notna(raw_deb) else 0.0
            val_cred = float(raw_cred) if pd.notna(raw_cred) else 0.0
            
            opening_bal = val_bal + val_deb - val_cred if (pd.notna(raw_deb) or pd.notna(raw_cred)) else val_bal
            
        closing_bal = pd.to_numeric(df.iloc[-1]['balance'], errors='coerce')
        closing_bal = float(closing_bal) if pd.notna(closing_bal) else 0.0
        net_flow = total_credits - total_debits
        
        # Layout metric cards
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.markdown(f'<div class="metric-card"><div class="metric-value">${opening_bal:,.2f}</div><div class="metric-label">Opening Balance</div></div>', unsafe_allow_html=True)
        with col2:
            st.markdown(f'<div class="metric-card"><div class="metric-value" style="color: #ea4335;">${total_debits:,.2f}</div><div class="metric-label">Total Withdrawals</div></div>', unsafe_allow_html=True)
        with col3:
            st.markdown(f'<div class="metric-card"><div class="metric-value" style="color: #34a853;">${total_credits:,.2f}</div><div class="metric-label">Total Deposits</div></div>', unsafe_allow_html=True)
        with col4:
            flow_color = "#34a853" if net_flow >= 0 else "#ea4335"
            st.markdown(f'<div class="metric-card"><div class="metric-value" style="color: {flow_color};">${net_flow:,.2f}</div><div class="metric-label">Net Monthly Flow</div></div>', unsafe_allow_html=True)
        with col5:
            st.markdown(f'<div class="metric-card"><div class="metric-value">${closing_bal:,.2f}</div><div class="metric-label">Closing Balance</div></div>', unsafe_allow_html=True)
        
        st.write("")
        
        # Layout visual tabs
        tab1, tab2, tab3 = st.tabs(["📊 Financial Visuals", "📋 Transaction Table", "📂 Transactions by Category"])
        
        with tab1:
            col_plot1, col_plot2 = st.columns(2)
            
            with col_plot1:
                st.subheader("Balance Trend Over Time")
                fig, ax = plt.subplots(figsize=(10, 5))
                sns.lineplot(data=df, x='date', y='balance', marker='o', ax=ax, color='#1f77b4', linewidth=2)
                ax.set_title("Running Account Balance History")
                ax.set_xlabel("Date")
                ax.set_ylabel("Balance ($)")
                plt.xticks(rotation=45)
                st.pyplot(fig)
                
            with col_plot2:
                st.subheader("Spending Breakdown by Category")
                # Group non-deposits by category
                df_expenses = df[pd.to_numeric(df["debit"], errors='coerce') > 0]
                if not df_expenses.empty:
                    df_cat = df_expenses.groupby("category")["debit"].sum().reset_index()
                    df_cat = df_cat.sort_values(by="debit", ascending=False)
                    fig, ax = plt.subplots(figsize=(10, 5))
                    sns.barplot(data=df_cat, x="debit", y="category", ax=ax, palette="viridis")
                    ax.set_title("Total Spend per Category")
                    ax.set_xlabel("Spend ($)")
                    ax.set_ylabel("Category")
                    st.pyplot(fig)
                else:
                    st.info("No expense (debit) transactions found to categorize.")
                    
        with tab2:
            st.subheader("Extracted Transaction History")
            st.markdown("*Double-click a category cell to edit/reassign categories directly!*")
            
            df_edited = st.data_editor(
                st.session_state.bank_df,
                column_config={
                    "category": st.column_config.SelectboxColumn(
                        "Category",
                        help="Select standard business tax category",
                        width="medium",
                        options=[
                            "Accounting Fees", "Advertising Expense", "Bank Charges", "Business taxes",
                            "CC Payment", "CRA Payment", "Due to individual shareholder", "Due to Related Party",
                            "Insurance expense", "Meal", "Office Expense", "Office Supplies", "Rent",
                            "Repairs and maintenance", "Salaries and wages", "Subcontract Expense",
                            "Telephone Expense", "Travel Expense", "Truck Loan", "Vehicle Asset",
                            "Vehicle Expense", "Equipment rental/lease", "Dumping Charges", "Utilities",
                            "Other Expenses", "Revenue / Deposits", "Uncategorized"
                        ],
                        required=True,
                    ),
                    "source_tab": st.column_config.TextColumn(
                        "Source Tab",
                        width="small"
                    ),
                    "gifi_code": st.column_config.TextColumn(
                        "GIFI Code",
                        help="GIFI taxonomy code",
                        width="small"
                    ),
                    "gst_rate": st.column_config.SelectboxColumn(
                        "GST/PST Rate",
                        help="Applicable GST or combined sales tax rate",
                        width="small",
                        options=["0%", "5%", "7%", "12%", ""]
                    ),
                    "suggested_category": st.column_config.TextColumn(
                        "AI Suggestion",
                        help="The original suggestion made by the AI or rules engine",
                        width="medium"
                    ),
                    "is_credit_card": None
                },
                disabled=["source_tab", "date", "description", "debit", "credit", "balance", "suggested_category", "is_credit_card"],
                use_container_width=True,
                key="editor_key"
            )
            
            # Write back edits to session state if changed
            st.session_state.bank_df = df_edited
            
            # Remember categories button
            st.write("")
            if st.button("💾 Remember Manual Category Changes (Learn for Future)", key="remember_btn_bank"):
                saved_count = 0
                for tx in df_edited.to_dict('records'):
                    desc = tx.get("description")
                    cat = tx.get("category")
                    gifi = tx.get("gifi_code", "")
                    gst = tx.get("gst_rate", "0%")
                    
                    # Check if this matches default rules
                    d_cat, d_gifi, d_gst = categorizer.lookup_by_rules(desc)
                    if d_cat == cat and d_gifi == gifi and d_gst == gst:
                        continue
                        
                    categorizer.save_user_rule(desc, cat, gifi, gst)
                    saved_count += 1
                    
                    if saved_count > 0:
                        st.success(f"🎉 Saved {saved_count} merchant rules! The app will remember these mappings in the future.")
                    else:
                        st.info("No manual changes detected. All transactions match current rules!")
            
        with tab3:
            view_type = st.radio("Report Layout", ["Grouped by Category (General Ledger)", "Single Category Filter"], horizontal=True, key="cat_report_view_type_bank")
            
            unique_cats_in_data = sorted(df['category'].dropna().unique())
            if not unique_cats_in_data:
                st.info("No categorized transactions available.")
            elif view_type == "Grouped by Category (General Ledger)":
                st.subheader("General Ledger by Category")
                for cat in unique_cats_in_data:
                    df_cat = df[df['category'] == cat]
                    if df_cat.empty:
                        continue
                    
                    # Calculate sums
                    cat_debit = pd.to_numeric(df_cat['debit'], errors='coerce').fillna(0).sum()
                    cat_credit = pd.to_numeric(df_cat['credit'], errors='coerce').fillna(0).sum()
                    cat_net = cat_credit - cat_debit
                    
                    # Prepare display DataFrame
                    df_cat_display = pd.DataFrame()
                    df_cat_display['Source Tab'] = df_cat['source_tab']
                    df_cat_display['Date'] = df_cat['date']
                    df_cat_display['Description'] = df_cat['description']
                    df_cat_display['Debit'] = pd.to_numeric(df_cat['debit'], errors='coerce')
                    df_cat_display['Credit'] = pd.to_numeric(df_cat['credit'], errors='coerce')
                    df_cat_display['Net Amount'] = pd.to_numeric(df_cat['credit'], errors='coerce').fillna(0) - pd.to_numeric(df_cat['debit'], errors='coerce').fillna(0)
                    
                    # Append TOTAL row
                    total_row = pd.DataFrame([{
                        'Source Tab': 'TOTAL',
                        'Date': '',
                        'Description': '',
                        'Debit': cat_debit,
                        'Credit': cat_credit,
                        'Net Amount': cat_net
                    }])
                    df_cat_display = pd.concat([df_cat_display, total_row], ignore_index=True)
                    
                    # Render category name and table
                    st.markdown(f"#### 📂 {cat}")
                    st.dataframe(df_cat_display, use_container_width=True, hide_index=True)
                    st.write("")
            else:
                # Single Category Filter
                st.subheader("Filter Transactions by Category")
                unique_options = ["All"] + unique_cats_in_data
                selected_filter_cat = st.selectbox(
                    "Select Category to View Details",
                    unique_options,
                    key="filter_cat_selector_bank"
                )
                if selected_filter_cat == "All":
                    df_filtered = df
                else:
                    df_filtered = df[df['category'] == selected_filter_cat]
                    
                cat_spend = pd.to_numeric(df_filtered['debit'], errors='coerce').fillna(0).sum()
                cat_income = pd.to_numeric(df_filtered['credit'], errors='coerce').fillna(0).sum()
                
                col_c1, col_c2, col_c3 = st.columns(3)
                with col_c1:
                    st.metric("Total Transactions", len(df_filtered))
                with col_c2:
                    st.metric("Total Spending (Debits)", f"${cat_spend:,.2f}")
                with col_c3:
                    st.metric("Total Deposits (Credits)", f"${cat_income:,.2f}")
                    
                st.dataframe(df_filtered[['source_tab', 'date', 'description', 'debit', 'credit', 'balance', 'gifi_code', 'gst_rate']], use_container_width=True)
            
        # Download Export Options
        st.write("")
        st.subheader("📥 Export Options")
        
        col_ex1, col_ex2, col_ex3 = st.columns(3)
        
        with col_ex1:
            csv_data = df_edited.to_csv(index=False)
            st.download_button(
                label="📥 Download as CSV",
                data=csv_data,
                file_name="extracted_bank_transactions.csv",
                mime="text/csv",
                key="download_csv_btn"
            )
            
        with col_ex2:
            try:
                import local_extractor
                # Convert df_edited back to transaction dict list
                txs_list = []
                for _, r in df_edited.iterrows():
                    txs_list.append({
                        "date": r["date"],
                        "description": r["description"],
                        "debit": float(r["debit"]) if pd.notna(r["debit"]) and r["debit"] != "" else None,
                        "credit": float(r["credit"]) if pd.notna(r["credit"]) and r["credit"] != "" else None,
                        "balance": float(r["balance"]) if pd.notna(r["balance"]) and r["balance"] != "" else None,
                        "category": r.get("category", ""),
                        "gifi_code": r.get("gifi_code", ""),
                        "gst_rate": r.get("gst_rate", "")
                    })
                
                # Reconcile full dataset
                first_opening = 0.0
                if "local_reconciliation_results" in st.session_state and st.session_state.local_reconciliation_results:
                    first_opening = st.session_state.local_reconciliation_results[0]["opening_balance"]
                
                full_reconcile = local_extractor.reconcile_transactions(txs_list, first_opening)
                bank_val = df_edited['institution'].iloc[0] if not df_edited.empty else "Standard"
                
                excel_bytes = local_extractor.generate_excel_report(
                    txs_list,
                    full_reconcile,
                    bank_val,
                    "extracted_statements.pdf"
                )
                
                st.download_button(
                    label="📊 Download as Excel (Styled)",
                    data=excel_bytes,
                    file_name="extracted_bank_statement.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_excel_btn"
                )
            except Exception as e:
                st.error(f"Excel error: {e}")
                
        with col_ex3:
            try:
                import local_extractor
                # Sort transactions chronologically
                df_sorted = df_edited.copy()
                df_sorted['date_dt'] = pd.to_datetime(df_sorted['date'], errors='coerce')
                df_sorted = df_sorted.sort_values(by='date_dt').reset_index(drop=True)
                
                first_op = 0.0
                if "local_reconciliation_results" in st.session_state and st.session_state.local_reconciliation_results:
                    first_op = st.session_state.local_reconciliation_results[0]["opening_balance"]
                    
                annual_bytes = local_extractor.generate_annual_workbook(df_sorted, first_op)
                
                st.download_button(
                    label="📅 Download Annual Workbook (Month Separators)",
                    data=annual_bytes,
                    file_name="annual_accounting_workbook.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_annual_excel_btn"
                )
            except Exception as e:
                st.error(f"Annual Excel error: {e}")
        
        # Google Sheets Sync Section
        st.markdown("---")
        st.subheader("📤 Google Sheets Integration")
        
        has_sheets_secrets = "gcp_service_account" in st.secrets or "gcp_service_account_json" in st.secrets
        if not has_sheets_secrets:
            st.warning("⚠️ Google Sheets credentials are not configured in secrets. Please configure secrets.toml or Streamlit Cloud Settings to enable sync.")
        else:
            st.info("💡 Google Sheets credentials detected. Press the button below to upload directly.")
            
        col_sh1, col_sh2 = st.columns([1, 1])
        with col_sh1:
            send_to_sheets = st.button("📤 Process & Send to Google Sheets", key="send_to_sheets_btn")
            
        if send_to_sheets and has_sheets_secrets:
            import sheets_helper
            with st.spinner("Connecting to Google Sheets..."):
                client = sheets_helper.get_gspread_client()
                spreadsheet = sheets_helper.get_spreadsheet(client, target_spreadsheet_id) if client else None
                
            if spreadsheet:
                with st.spinner("Performing pre-categorization, duplicate checking, and upload..."):
                    # 1. Load Category Map and apply pre-categorization
                    cat_map_df = sheets_helper.load_category_map(spreadsheet)
                    
                    # Create normalized schema copy for upload with exact requested column order
                    upload_df = pd.DataFrame()
                    
                    # 1. Date
                    upload_df['transaction_date'] = df_edited['date']
                    
                    # 2. Description
                    upload_df['description'] = df_edited['description']
                    
                    # 3. Amount (combine debit and credit for all sheets, debit is negative, credit is positive)
                    amounts = []
                    for idx, row in df_edited.iterrows():
                        deb = pd.to_numeric(row.get('debit'), errors='coerce')
                        cred = pd.to_numeric(row.get('credit'), errors='coerce')
                        val_deb = float(deb) if pd.notna(deb) else 0.0
                        val_cred = float(cred) if pd.notna(cred) else 0.0
                        
                        if val_cred != 0.0:
                            amounts.append(val_cred)
                        elif val_deb != 0.0:
                            amounts.append(-val_deb)
                        else:
                            amounts.append(0.0)
                    upload_df['amount'] = amounts
                    
                    # 4. Running Balance
                    upload_df['running_balance'] = pd.to_numeric(df_edited['balance'], errors='coerce').fillna(0)
                    
                    # 5. Category (pre-populate user edits first)
                    upload_df['category'] = df_edited['category']
                    
                    # Remaining columns (order does not matter)
                    upload_df['client_name'] = [client_name] * len(df_edited)
                    upload_df['account_name'] = [account_name] * len(df_edited)
                    upload_df['statement_start'] = [statement_start.isoformat()] * len(df_edited)
                    upload_df['statement_end'] = [statement_end.isoformat()] * len(df_edited)
                    upload_df['debit_credit_flag'] = ['debit' if pd.notna(d) and d != "" else 'credit' for d in df_edited['debit']]
                    upload_df['subcategory'] = ""
                    
                    # Apply Category Map for remaining empty categories
                    upload_df = sheets_helper.apply_category_map(upload_df, cat_map_df)
                    
                    upload_df['source_file'] = df_edited['source_file'] if 'source_file' in df_edited.columns else ""
                    upload_df['institution'] = df_edited['institution'] if 'institution' in df_edited.columns else institution
                    upload_df['upload_timestamp'] = datetime.now().isoformat()
                    
                    # Validation flags (Suspicious balance, missing date, missing amount)
                    review_flags = []
                    review_reasons = []
                    
                    # Balance discrepancy check: running balance vs calculated balance transitions
                    running_bal_list = upload_df['running_balance'].tolist()
                    debit_credit_list = upload_df['debit_credit_flag'].tolist()
                    amount_list = upload_df['amount'].tolist()
                    
                    for idx, row_up in upload_df.iterrows():
                        flag = "False"
                        reason = ""
                        
                        # Date validation
                        if pd.isna(row_up['transaction_date']) or not str(row_up['transaction_date']).strip():
                            flag = "True"
                            reason += "Missing transaction date; "
                            
                        # Amount validation
                        if pd.isna(row_up['amount']) or row_up['amount'] == 0:
                            flag = "True"
                            reason += "Missing or zero amount; "
                            
                        # Balance discrepancy check
                        if idx > 0:
                            prev_bal = running_bal_list[idx-1]
                            curr_bal = running_bal_list[idx]
                            curr_amt = amount_list[idx]
                            curr_flag = debit_credit_list[idx]
                            
                            expected_bal = prev_bal + curr_amt if curr_flag == 'credit' else prev_bal - curr_amt
                            if abs(expected_bal - curr_bal) > 0.05: # allow small float tolerance
                                flag = "True"
                                reason += f"Suspicious balance transition (expected {expected_bal:.2f}, got {curr_bal:.2f}); "
                                
                        review_flags.append(flag)
                        review_reasons.append(reason.strip("; "))
                        
                    upload_df['review_flag'] = review_flags
                    upload_df['review_reason'] = review_reasons
                    
                    # Generate deterministic hash key
                    hashes = []
                    for _, r_hash in upload_df.iterrows():
                        h_key = sheets_helper.generate_hash_key(
                            r_hash['account_name'],
                            r_hash['transaction_date'],
                            r_hash['description'],
                            r_hash['amount']
                        )
                        hashes.append(h_key)
                    upload_df['hash_key'] = hashes
                    
                    # 2. Duplicate Detection
                    existing_hashes = sheets_helper.load_existing_hashes(spreadsheet)
                    extracted_count = len(upload_df)
                    
                    # Filter out duplicates
                    dupe_mask = upload_df['hash_key'].isin(existing_hashes)
                    dupes_df = upload_df[dupe_mask]
                    new_df = upload_df[~dupe_mask]
                    
                    duplicate_count = len(dupes_df)
                    
                    # 3. Determine target tab routing and upload
                    target_tabs = []
                    for idx, row_up in new_df.iterrows():
                        if dest_sheet_override == "Create New Tab":
                            fn = str(row_up.get('source_file', 'New_Transactions'))
                            if fn.lower().endswith('.pdf'):
                                fn = fn[:-4]
                            # Sanitize Sheet worksheet name rules (limit 100 chars, no special chars)
                            fn = fn.replace(':', '_').replace('/', '_').replace('\\', '_').replace('?', '_').replace('*', '_').replace('[', '_').replace(']', '_')
                            target_tabs.append(fn[:100])
                        elif dest_sheet_override == "[Auto-detect based on file]":
                            fn = str(row_up.get('source_file', '')).lower()
                            bank = str(row_up.get('institution', '')).lower()
                            
                            is_cc_meta = str(row_up.get('is_credit_card', '')).lower() == 'true' or row_up.get('is_credit_card') == True
                            if is_cc_meta or any(x in fn for x in ["visa", "mastercard", "credit", "card", "cc"]) or "visa" in bank or "mastercard" in bank or "credit" in bank:
                                target_tabs.append("Credit Card")
                            elif "td" in bank or "tangerine" in bank:
                                target_tabs.append("Bank Single Column")
                            else:
                                target_tabs.append("Bank Transactions")
                        else:
                            target_tabs.append(dest_sheet_override)
                            
                    new_df['target_tab'] = target_tabs
                    
                    # Group and upload
                    success = True
                    uploaded_sheets = []
                    appended_count = len(new_df)
                    
                    if appended_count > 0:
                        for tab_name, group_df in new_df.groupby('target_tab'):
                            # Drop the temporary routing columns before upload
                            group_to_upload = group_df.drop(columns=['target_tab', 'is_credit_card'], errors='ignore')
                            success_group = sheets_helper.append_rows_to_sheet(spreadsheet, tab_name, group_to_upload)
                            if success_group:
                                uploaded_sheets.append(tab_name)
                            else:
                                success = False
                                
                    # 5. Log processing run
                    status = "SUCCESS" if success else "PARTIAL_FAILURE"
                    summary_dict = {
                        "file_count": len(uploaded_files),
                        "row_count": extracted_count,
                        "duplicates_count": duplicate_count,
                        "review_count": 0,
                        "status": status
                    }
                    sheets_helper.log_processing_run(spreadsheet, summary_dict)
                    
                    # 6. Display Processing Summary metrics
                    if success:
                        st.success(f"🎉 Direct Google Sheets Sync Completed Successfully!")
                    else:
                        st.warning("⚠️ Direct Google Sheets Sync completed with some errors.")
                        
                    sc1, sc2, sc3 = st.columns(3)
                    with sc1:
                        st.metric("Extracted", extracted_count)
                    with sc2:
                        st.metric("Duplicates Skipped", duplicate_count)
                    with sc3:
                        st.metric("Appended to Sheet", appended_count)
                        
                    if uploaded_sheets:
                        st.info(f"📁 Uploaded transactions directly to target worksheet tabs: **{', '.join(set(uploaded_sheets))}**")
                        
                    # Previews
                    if not new_df.empty:
                        with st.expander("📄 Preview Appended Transactions", expanded=False):
                            disp_df = new_df.drop(columns=['target_tab'], errors='ignore')
                            st.dataframe(disp_df, use_container_width=True)
                    if not dupes_df.empty:
                        with st.expander("⏭️ Preview Skipped Duplicates", expanded=False):
                            st.dataframe(dupes_df, use_container_width=True)

        # View Learned Rules expander
        st.write("")
        with st.expander("🧠 View Learned Rules (Saved Overrides)", expanded=False):
            user_rules = categorizer.get_user_rules()
            rules_data = []
            if user_rules:
                for desc, meta in user_rules.items():
                    rules_data.append({
                        "Merchant Description": desc,
                        "Saved Category": meta.get("category"),
                        "GIFI Code": meta.get("gifi_code"),
                        "GST Rate": meta.get("gst_rate")
                    })
            df_rules = pd.DataFrame(rules_data, columns=["Merchant Description", "Saved Category", "GIFI Code", "GST Rate"])
            df_rules = df_rules.sort_values(by=["Saved Category", "Merchant Description"])
            
            df_edited_rules = st.data_editor(
                df_rules,
                column_config={
                    "Saved Category": st.column_config.SelectboxColumn(
                        "Saved Category",
                        options=[
                            "Accounting Fees", "Advertising Expense", "Bank Charges", "Business taxes",
                            "CC Payment", "CRA Payment", "Due to individual shareholder", "Due to Related Party",
                            "Insurance expense", "Meal", "Office Expense", "Office Supplies", "Rent",
                            "Repairs and maintenance", "Salaries and wages", "Subcontract Expense",
                            "Telephone Expense", "Travel Expense", "Truck Loan", "Vehicle Asset",
                            "Vehicle Expense", "Equipment rental/lease", "Dumping Charges", "Utilities",
                            "Other Expenses", "Revenue / Deposits", "Uncategorized"
                        ],
                        required=True
                    ),
                    "GST Rate": st.column_config.SelectboxColumn(
                        "GST Rate",
                        options=["0%", "5%", "7%", "12%", ""]
                    )
                },
                num_rows="dynamic",
                use_container_width=True,
                key="rules_editor_key"
            )
            
            # Option to save edits
            save_edits = st.button("💾 Save Changes to Rules Database", key="save_rules_edits_btn")
            if save_edits:
                new_rules = {}
                for _, row in df_edited_rules.iterrows():
                    desc = str(row.get("Merchant Description", "")).strip()
                    cat = str(row.get("Saved Category", "")).strip()
                    gifi = str(row.get("GIFI Code", "")).strip()
                    gst = str(row.get("GST Rate", "")).strip()
                    if desc and cat:
                        new_rules[desc] = {
                            "category": cat,
                            "gifi_code": gifi,
                            "gst_rate": gst
                        }
                user_rules_path = os.path.join(os.path.dirname(os.path.abspath(categorizer.__file__)), "user_rules.json")
                try:
                    with open(user_rules_path, "w", encoding="utf-8") as f:
                        json.dump(new_rules, f, indent=4, ensure_ascii=False)
                    st.success("🎉 Rules database updated successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save changes: {e}")
                        
            # File Uploader to import custom rules directly to database
            st.markdown("---")
            st.markdown("### 📤 Import Rules from Excel/CSV Mappings File")
            import_file = st.file_uploader(
                "Upload a mappings file (Excel/CSV) to import directly to your rules database",
                type=["xlsx", "xls", "csv"],
                key="import_rules_uploader"
            )
            if import_file:
                try:
                    # Load the file
                    if import_file.name.lower().endswith(('.xlsx', '.xls')):
                        import pandas as pd
                        df_imp = pd.read_excel(import_file)
                    else:
                        import pandas as pd
                        df_imp = pd.read_csv(import_file)
                        
                    # Find correct columns
                    cols = df_imp.columns.tolist()
                    keyword_col = None
                    category_col = None
                    gifi_col = None
                    gst_col = None
                    
                    # Fuzzy match headers
                    for c in cols:
                        c_low = str(c).lower()
                        if "keyword" in c_low or "merchant" in c_low or "description" in c_low:
                            keyword_col = c
                        elif "category" in c_low:
                            category_col = c
                        elif "gifi" in c_low:
                            gifi_col = c
                        elif "gst" in c_low or "tax" in c_low or "pst" in c_low:
                            gst_col = c
                            
                    # Fallback to column index if not matched
                    if not keyword_col and len(cols) > 0:
                        keyword_col = cols[0]
                    if not category_col and len(cols) > 1:
                        category_col = cols[1]
                    if not gifi_col and len(cols) > 2:
                        gifi_col = cols[2]
                    if not gst_col and len(cols) > 3:
                        gst_col = cols[3]
                        
                    if keyword_col and category_col:
                        imported_rules = categorizer.get_user_rules() # existing rules
                        import_count = 0
                        for _, row_imp in df_imp.iterrows():
                            k_val = str(row_imp.get(keyword_col, "")).strip()
                            cat_val = str(row_imp.get(category_col, "")).strip()
                            gifi_val = str(row_imp.get(gifi_col, "")) if (gifi_col and pd.notna(row_imp.get(gifi_col))) else ""
                            gst_val = str(row_imp.get(gst_col, "0%")) if (gst_col and pd.notna(row_imp.get(gst_col))) else "0%"
                            
                            # Clean up and normalize nulls
                            if pd.isna(row_imp.get(keyword_col)) or not k_val:
                                continue
                            if pd.isna(row_imp.get(category_col)) or not cat_val:
                                continue
                                
                            imported_rules[k_val] = {
                                "category": cat_val,
                                "gifi_code": gifi_val,
                                "gst_rate": gst_val
                            }
                            import_count += 1
                            
                        # Save
                        user_rules_path = os.path.join(os.path.dirname(os.path.abspath(categorizer.__file__)), "user_rules.json")
                        with open(user_rules_path, "w", encoding="utf-8") as f:
                            json.dump(imported_rules, f, indent=4, ensure_ascii=False)
                            
                        st.success(f"🎉 Successfully imported {import_count} mapping rules to your database!")
                        st.rerun()
                    else:
                        st.error("Could not identify Keyword and Category columns in the uploaded file.")
                except Exception as e:
                    st.error(f"Failed to import rules: {e}")
                    
            # Copy-Paste Rules Area
            st.write("")
            st.markdown("### 📋 Bulk Paste Rules (From Excel/Spreadsheet)")
            st.markdown("Paste columns of keywords and categories directly from your spreadsheet below (one pair per line, separated by tabs or commas):")
            pasted_text = st.text_area(
                "Paste your mappings here (e.g. 'Rogers \\t Telephone Expense')",
                placeholder="Esso\tVehicle Expense\nRogers\tTelephone Expense",
                height=150,
                key="pasted_rules_textarea"
            )
            if st.button("📥 Import Pasted Rules", key="import_pasted_rules_btn"):
                if pasted_text.strip():
                    try:
                        imported_rules = categorizer.get_user_rules()
                        import_count = 0
                        lines = pasted_text.strip().split('\n')
                        for line in lines:
                            if not line.strip():
                                continue
                            
                            # Split by tab if present, else by comma
                            if '\t' in line:
                                parts = line.split('\t')
                            else:
                                parts = line.split(',')
                                
                            if len(parts) >= 2:
                                k_val = parts[0].strip()
                                cat_val = parts[1].strip()
                                # Clean quotes if present
                                k_val = k_val.strip('\'"').strip()
                                cat_val = cat_val.strip('\'"').strip()
                                
                                if k_val and cat_val:
                                    imported_rules[k_val] = {
                                        "category": cat_val,
                                        "gifi_code": "",
                                        "gst_rate": "0%"
                                    }
                                    import_count += 1
                        
                        if import_count > 0:
                            # Save
                            user_rules_path = os.path.join(os.path.dirname(os.path.abspath(categorizer.__file__)), "user_rules.json")
                            with open(user_rules_path, "w", encoding="utf-8") as f:
                                json.dump(imported_rules, f, indent=4, ensure_ascii=False)
                            st.success(f"🎉 Successfully imported {import_count} pasted rules!")
                            st.rerun()
                        else:
                            st.warning("No valid rules could be parsed from the pasted text. Make sure you have at least a keyword and category per line.")
                    except Exception as e:
                        st.error(f"Failed to import pasted rules: {e}")
