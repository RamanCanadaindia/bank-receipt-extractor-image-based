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
st.sidebar.markdown("### How it works:")
st.sidebar.info("""
1. **Upload** your statement PDF.
2. The tool checks for **digital text** first (free).
3. If scanned, it renders pages using **pypdfium2** and uses **Gemini Vision OCR** to extract the rows.
4. It **mathematically validates** the transactions chronologically and flags errors.
""")

# File Uploader
uploaded_file = st.file_uploader("Upload your Bank Statement PDF", type=["pdf"])

if uploaded_file is not None:
    # Clear session state if file changes
    file_key = f"file_{uploaded_file.name}_{uploaded_file.size}"
    if "current_file_key" not in st.session_state or st.session_state.current_file_key != file_key:
        st.session_state.bank_transactions = []
        st.session_state.current_file_key = file_key

    # Determine extraction mode
    text_pages = []
    is_digital = False
    
    if not force_ocr:
        with st.spinner("Checking PDF type..."):
            text_pages = extract_statement.extract_digital_text(uploaded_file)
            if text_pages:
                is_digital = True
                
    # Action button
    btn_label = "⚡ Extract from Digital PDF (Free)" if is_digital else "👁️ Extract via Gemini Vision OCR"
    run_extraction = st.button(btn_label)
    
    if run_extraction:
        transactions = []
        
        if is_digital:
            with st.spinner("Extracting transaction text digitally..."):
                transactions = extract_statement.parse_digital_text(text_pages)
        else:
            # Scanned statement - requires API Key
            if not api_key:
                st.error("🔑 Gemini API Key is required to process scanned statements. Please enter it in the sidebar.")
            else:
                # Render pages to base64 images - requires a temporary file on disk for pypdfium2
                with st.spinner("Rendering PDF pages to image format..."):
                    # Reset the file stream pointer first
                    uploaded_file.seek(0)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                        tmp_file.write(uploaded_file.read())
                        tmp_pdf_path = tmp_file.name
                    
                    try:
                        base64_images = extract_statement.render_pdf_pages(tmp_pdf_path)
                    finally:
                        if os.path.exists(tmp_pdf_path):
                            try:
                                os.remove(tmp_pdf_path)
                            except Exception:
                                pass
                
                # API calls per page in parallel
                import concurrent.futures
                
                max_workers = 3
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                status_text.text(f"Processing {len(base64_images)} pages in parallel (concurrency={max_workers})...")
                
                completed = 0
                transactions_by_page = {}
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all tasks
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
                            st.warning(f"Error on page {page_num}: {e}")
                            transactions_by_page[page_num] = []
                            
                        completed += 1
                        status_text.text(f"Finished page {page_num} ({completed}/{len(base64_images)} pages processed)...")
                        progress_bar.progress(completed / len(base64_images))
                
                # Assemble in correct page order
                for page_num in sorted(transactions_by_page.keys()):
                    transactions.extend(transactions_by_page[page_num])
                    
                progress_bar.empty()
                status_text.empty()
        
        if transactions:
            # Validate the flow
            with st.spinner("Validating mathematical balance flows..."):
                validated_txs = extract_statement.validate_and_correct_transactions(
                    transactions, sort_chronologically=sort_chronologically
                )
            
            with st.spinner("Auto-categorizing transactions..."):
                # Run auto-categorization helper
                categorized_txs = categorizer.categorize_transactions(api_key, validated_txs)
                
                # Convert to DataFrame
                df = pd.DataFrame(categorized_txs)
                df['date'] = pd.to_datetime(df['date'])
                if sort_chronologically:
                    df = df.sort_values(by='date').reset_index(drop=True)
                else:
                    df = df.reset_index(drop=True)
                df['date'] = df['date'].dt.strftime('%Y-%m-%d')
                
                # Ensure all columns exist and are ordered
                cols_order = ['date', 'description', 'debit', 'credit', 'balance', 'category', 'gifi_code', 'gst_rate']
                for col in cols_order:
                    if col not in df.columns:
                        df[col] = ""
                df = df[cols_order]
                
                st.session_state.bank_df = df
                st.success("🎉 Extraction, validation, and categorization complete!")
        else:
            st.warning("⚠️ No transactions could be extracted from the file.")

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
        tab1, tab2 = st.tabs(["📊 Financial Visuals", "📋 Transaction Table"])
        
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
                disabled=["date", "description", "debit", "credit", "balance"],
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
            
        # Download CSV button
        csv_data = df_edited.to_csv(index=False)
        st.download_button(
            label="📥 Download Transactions as CSV",
            data=csv_data,
            file_name="extracted_bank_transactions.csv",
            mime="text/csv"
        )
        
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
