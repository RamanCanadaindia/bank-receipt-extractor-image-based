import streamlit as st
import os
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
api_key = st.sidebar.text_input(
    "Google AI Studio API Key",
    type="password",
    value=os.environ.get("GEMINI_API_KEY", ""),
    help="Required for scanned/image-only PDFs. Get a free key at https://aistudio.google.com/"
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
    value=True,
    help="Sort transactions from oldest to newest. Uncheck this to keep the exact page/row order from the PDF statement."
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📋 Google Sheets Metadata")
client_name = st.sidebar.text_input("Client Name", value="Test Client")
account_name = st.sidebar.text_input("Account Name", value="Main Checking")
institution = st.sidebar.text_input("Financial Institution", value="RBC")

from datetime import datetime, date
default_start = date(2024, 1, 1)
default_end = date(2024, 12, 31)

statement_start = st.sidebar.date_input("Statement Start Date", value=default_start)
statement_end = st.sidebar.date_input("Statement End Date", value=default_end)
target_spreadsheet_id = st.sidebar.text_input(
    "Target Google Sheet ID / URL",
    value=st.secrets.get("google_sheets", {}).get("spreadsheet_id", ""),
    help="Paste the target Google Sheet's browser URL or its ID here. Ensure you've shared the Sheet with the service account email."
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
    btn_label = "⚡ Extract from Digital PDF(s) (Free)" if has_digital else "👁️ Extract via Gemini Vision OCR"
    run_extraction = st.button(btn_label)

    if run_extraction:
        all_combined_txs = []
        
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
            if is_digital:
                with st.spinner(f"Extracting digital text from {u_file.name}..."):
                    transactions = extract_statement.parse_digital_text(text_pages)
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
                    tx["institution"] = institution
                all_combined_txs.extend(validated_txs)
                
        progress_bar.progress(1.0)
        status_text.text("Finished processing all files!")
        
        if all_combined_txs:
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
                    df = df.reset_index(drop=True)
                df['date'] = df['date'].dt.strftime('%Y-%m-%d')
                
                # Ensure all columns exist and are ordered
                cols_order = ['source_tab', 'date', 'description', 'debit', 'credit', 'balance', 'category', 'gifi_code', 'gst_rate', 'source_file', 'institution']
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
        
        # Metrics Calculation
        total_debits = pd.to_numeric(df['debit'], errors='coerce').fillna(0).sum()
        total_credits = pd.to_numeric(df['credit'], errors='coerce').fillna(0).sum()
        opening_bal = pd.to_numeric(df.iloc[0]['balance'], errors='coerce') + pd.to_numeric(df.iloc[0]['debit'], errors='coerce').fillna(0) - pd.to_numeric(df.iloc[0]['credit'], errors='coerce').fillna(0) if (pd.notna(df.iloc[0]['debit']) or pd.notna(df.iloc[0]['credit'])) else pd.to_numeric(df.iloc[0]['balance'], errors='coerce')
        closing_bal = pd.to_numeric(df.iloc[-1]['balance'], errors='coerce')
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
                            "Telephone Expense", "Trade Sales", "Travel Expense", "Truck Loan", "Vehicle Asset",
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
                    )
                },
                disabled=["source_tab", "date", "description", "debit", "credit", "balance"],
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
            
        # Download CSV button
        csv_data = df_edited.to_csv(index=False)
        st.download_button(
            label="📥 Download Transactions as CSV",
            data=csv_data,
            file_name="extracted_bank_transactions.csv",
            mime="text/csv"
        )
        
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
                    
                    # Create normalized schema copy for upload
                    upload_df = pd.DataFrame()
                    upload_df['client_name'] = [client_name] * len(df_edited)
                    upload_df['account_name'] = [account_name] * len(df_edited)
                    upload_df['statement_start'] = [statement_start.isoformat()] * len(df_edited)
                    upload_df['statement_end'] = [statement_end.isoformat()] * len(df_edited)
                    upload_df['transaction_date'] = df_edited['date']
                    upload_df['description'] = df_edited['description']
                    
                    # Numeric amounts
                    debits = pd.to_numeric(df_edited['debit'], errors='coerce')
                    credits = pd.to_numeric(df_edited['credit'], errors='coerce')
                    
                    upload_df['amount'] = debits.fillna(0) + credits.fillna(0)
                    upload_df['debit_credit_flag'] = ['debit' if pd.notna(d) and d != "" else 'credit' for d in df_edited['debit']]
                    upload_df['running_balance'] = pd.to_numeric(df_edited['balance'], errors='coerce').fillna(0)
                    
                    # pre-populate user edits first
                    upload_df['category'] = df_edited['category']
                    upload_df['subcategory'] = "" # default
                    
                    # Apply Category Map for remaining empty categories
                    upload_df = sheets_helper.apply_category_map(upload_df, cat_map_df)
                    
                    # Other metadata
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
                    
                    # 3. Split clean and review rows
                    clean_df, review_df = sheets_helper.split_clean_and_review(new_df)
                    
                    review_count = len(review_df)
                    appended_count = len(clean_df)
                    
                    # 4. Append to worksheet tabs
                    success_clean = sheets_helper.append_rows_to_sheet(spreadsheet, "Raw_Transactions", clean_df)
                    success_review = sheets_helper.append_rows_to_sheet(spreadsheet, "Needs_Review", review_df)
                    
                    # 5. Log processing run
                    status = "SUCCESS" if (success_clean and success_review) else "PARTIAL_FAILURE"
                    summary_dict = {
                        "file_count": len(uploaded_files),
                        "row_count": extracted_count,
                        "duplicates_count": duplicate_count,
                        "review_count": review_count,
                        "status": status
                    }
                    sheets_helper.log_processing_run(spreadsheet, summary_dict)
                    
                    # 6. Display Processing Summary metrics
                    st.success("🎉 Direct Google Sheets Sync Completed Successfully!")
                    
                    sc1, sc2, sc3, sc4 = st.columns(4)
                    with sc1:
                        st.metric("Extracted", extracted_count)
                    with sc2:
                        st.metric("Duplicates Skipped", duplicate_count)
                    with sc3:
                        st.metric("Appended to Raw", appended_count)
                    with sc4:
                        st.metric("Sent to Review", review_count)
                        
                    # Previews
                    if not clean_df.empty:
                        with st.expander("📄 Preview Appended Clean Rows", expanded=False):
                            st.dataframe(clean_df, use_container_width=True)
                    if not review_df.empty:
                        with st.expander("⚠️ Preview Sent to Review Rows", expanded=True):
                            st.dataframe(review_df, use_container_width=True)

        # View Learned Rules expander
        st.write("")
        with st.expander("🧠 View Learned Rules (Saved Overrides)", expanded=False):
            user_rules = categorizer.get_user_rules()
            if user_rules:
                rules_data = []
                for desc, meta in user_rules.items():
                    rules_data.append({
                        "Merchant Description": desc,
                        "Saved Category": meta.get("category"),
                        "GIFI Code": meta.get("gifi_code"),
                        "GST Rate": meta.get("gst_rate")
                    })
                df_rules = pd.DataFrame(rules_data)
                st.dataframe(df_rules, use_container_width=True)
                
                # Option to clear rules
                col_del1, col_del2 = st.columns([3, 1])
                with col_del2:
                    clear_all = st.button("🗑️ Clear All Saved Rules", key="clear_all_rules_btn_bank")
                    if clear_all:
                        user_rules_path = os.path.join(os.path.dirname(os.path.abspath(categorizer.__file__)), "user_rules.json")
                        if os.path.exists(user_rules_path):
                            os.remove(user_rules_path)
                            st.success("All saved rules cleared! Refreshing...")
                            st.rerun()
            else:
                st.info("No custom overrides saved yet. Use the 'Remember Manual Category Changes' button above to save overrides.")
