import streamlit as st
import pandas as pd
import os
import sys
import tempfile
import matplotlib.pyplot as plt
import seaborn as sns

# Ensure parent directory is in path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth
import categorizer

# Try importing pdfplumber for digital PDF table extraction
try:
    import pdfplumber
except ImportError:
    pdfplumber = None

# Set page config
st.set_page_config(
    page_title="Transaction Categorizer",
    page_icon="🏷️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Auth check
if not auth.check_password():
    st.stop()

# Custom styles for visual premium consistency
st.markdown("""
<style>
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

st.title("🏷️ Bulk Transaction Categorizer")
st.markdown("""
Upload transactions already extracted in **CSV**, **Excel**, or **digital PDF table** format. 
This tool automatically applies your custom tax mapping rules (GIFI codes and GST/PST rates) and uses AI to classify any unseen merchants.
""")

# Sidebar config
st.sidebar.header("⚙️ Configuration")
api_key = st.sidebar.text_input(
    "Google AI Studio API Key",
    type="password",
    value=os.environ.get("GEMINI_API_KEY", ""),
    help="Optional: Used to intelligently categorize transaction descriptions not found in your custom rules."
)

st.sidebar.info("""
**Supported Formats:**
- **CSV** (.csv)
- **Excel** (.xlsx)
- **Digital PDF Tables** (.pdf)
""")

# File Uploader
uploaded_file = st.file_uploader("Upload Transaction File", type=["csv", "xlsx", "pdf"])

def extract_pdf_table(uploaded_file):
    """Extract tabular data from a digital PDF using pdfplumber."""
    if pdfplumber is None:
        st.error("pdfplumber library is not installed. Please run `pip install pdfplumber` to process PDF tables.")
        return None
        
    try:
        # Create a temp file to read since pdfplumber needs a file path or seekable buffer
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded_file.read())
            tmp_path = tmp.name
            
        rows = []
        with pdfplumber.open(tmp_path) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if table:
                    # Filter out completely empty rows
                    for r in table:
                        if any(cell is not None and str(cell).strip() for cell in r):
                            rows.append(r)
                            
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
            
        if not rows:
            return None
            
        # Treat first row as header if it contains text labels
        headers = [str(h).strip() for h in rows[0]]
        data = rows[1:]
        
        # Build DataFrame
        df = pd.DataFrame(data, columns=headers)
        return df
    except Exception as e:
        st.error(f"Error parsing PDF table: {e}")
        return None

if uploaded_file is not None:
    # Clear session state if file changes
    file_key = f"cat_{uploaded_file.name}_{uploaded_file.size}"
    if "current_cat_key" not in st.session_state or st.session_state.current_cat_key != file_key:
        st.session_state.categorizer_transactions = []
        st.session_state.current_cat_key = file_key

    # Step 1: Load file to raw dataframe
    df_raw = None
    file_ext = os.path.splitext(uploaded_file.name)[1].lower()
    
    if file_ext in (".xlsx", ".xls"):
        try:
            xl = pd.ExcelFile(uploaded_file)
            sheet_names = xl.sheet_names
            if len(sheet_names) > 1:
                selected_sheet = st.selectbox("📂 Select Excel Tab / Sheet", sheet_names)
            else:
                selected_sheet = sheet_names[0]
                
            with st.spinner(f"Reading sheet '{selected_sheet}'..."):
                df_raw = xl.parse(selected_sheet)
        except Exception as e:
            st.error(f"Error reading Excel file sheets: {e}")
    else:
        with st.spinner("Reading file..."):
            if file_ext == ".csv":
                try:
                    df_raw = pd.read_csv(uploaded_file)
                except Exception as e:
                    st.error(f"Error reading CSV: {e}")
            elif file_ext == ".pdf":
                df_raw = extract_pdf_table(uploaded_file)

    if df_raw is not None:
        st.success(f"Loaded file with {len(df_raw)} rows.")
        
        # Step 2: Column Selection Mapping
        st.subheader("Map columns to required fields")
        cols = list(df_raw.columns)
        
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            # Guess date column
            date_default = 0
            for i, c in enumerate(cols):
                if "date" in str(c).lower():
                    date_default = i
                    break
            date_col = st.selectbox("Date Column", cols, index=date_default)
            
        with col_m2:
            # Guess description column
            desc_default = 0
            for i, c in enumerate(cols):
                if any(x in str(c).lower() for x in ("desc", "memo", "particular", "merchant", "details")):
                    desc_default = i
                    break
            desc_col = st.selectbox("Description Column", cols, index=desc_default)
            
        with col_m3:
            # Guess amount column
            amount_default = 0
            for i, c in enumerate(cols):
                if any(x in str(c).lower() for x in ("amount", "value", "debit", "credit", "total")):
                    amount_default = i
                    break
            amount_col = st.selectbox("Amount Column", cols, index=amount_default)

        # Trigger Processing
        run_categorize = st.button("⚡ Auto-Categorize Transactions")
        
        if run_categorize:
            with st.spinner("Standardizing and processing transactions..."):
                standard_txs = []
                for _, row in df_raw.iterrows():
                    desc_val = str(row[desc_col]).strip()
                    if not desc_val or desc_val.lower() == 'nan':
                        continue
                        
                    # Standardize amount
                    amount_val = 0.0
                    try:
                        raw_amt = str(row[amount_col]).replace("$", "").replace(",", "").strip()
                        if raw_amt.startswith("(") and raw_amt.endswith(")"):
                            amount_val = -float(raw_amt[1:-1])
                        else:
                            amount_val = float(raw_amt)
                    except ValueError:
                        pass
                        
                    debit_val = abs(amount_val) if amount_val < 0 else None
                    credit_val = amount_val if amount_val > 0 else None
                    
                    # Formatting Date
                    date_val = str(row[date_col]).strip()
                    
                    standard_txs.append({
                        "date": date_val,
                        "description": desc_val,
                        "debit": debit_val,
                        "credit": credit_val,
                        "balance": 0.0 # Placeholder for bulk lists
                    })
                
                # Auto Categorize using hybrid engine
                categorized_txs = categorizer.categorize_transactions(api_key, standard_txs)
                st.session_state.categorizer_transactions = categorized_txs
                st.success("🎉 Processing complete!")

        # Render Dashboard if processed
        if "categorizer_transactions" in st.session_state and st.session_state.categorizer_transactions:
            df_proc = pd.DataFrame(st.session_state.categorizer_transactions)
            
            # Format and display
            df_proc['date'] = pd.to_datetime(df_proc['date'], errors='coerce')
            df_proc = df_proc.dropna(subset=['date']).sort_values(by='date').reset_index(drop=True)
            
            # Metrics
            total_spend = df_proc['debit'].fillna(0).sum()
            total_income = df_proc['credit'].fillna(0).sum()
            tx_count = len(df_proc)
            
            col_met1, col_met2, col_met3 = st.columns(3)
            with col_met1:
                st.markdown(f'<div class="metric-card"><div class="metric-value">{tx_count}</div><div class="metric-label">Total Transactions</div></div>', unsafe_allow_html=True)
            with col_met2:
                st.markdown(f'<div class="metric-card"><div class="metric-value" style="color: #ea4335;">${total_spend:,.2f}</div><div class="metric-label">Total Expense (Debits)</div></div>', unsafe_allow_html=True)
            with col_met3:
                st.markdown(f'<div class="metric-card"><div class="metric-value" style="color: #34a853;">${total_income:,.2f}</div><div class="metric-label">Total Revenue (Credits)</div></div>', unsafe_allow_html=True)
                
            st.write("")
            
            # Layout Visuals & Table Tabs
            tab_vis, tab_tbl = st.tabs(["📊 Spending Visuals", "📋 Transaction Editor"])
            
            with tab_vis:
                # Spend by category breakdown
                df_exp_only = df_proc[df_proc['debit'] > 0]
                if not df_exp_only.empty:
                    df_cat_summary = df_exp_only.groupby('category')['debit'].sum().reset_index()
                    df_cat_summary = df_cat_summary.sort_values(by='debit', ascending=False)
                    
                    fig, ax = plt.subplots(figsize=(10, 5))
                    sns.barplot(data=df_cat_summary, x='debit', y='category', ax=ax, palette='viridis')
                    ax.set_title("Total Spend per Category")
                    ax.set_xlabel("Spend ($)")
                    ax.set_ylabel("Category")
                    st.pyplot(fig)
                else:
                    st.info("No expense (debit) transactions found to display breakdown.")
                    
            with tab_tbl:
                st.subheader("Categorized Transaction List")
                st.markdown("*Adjust categories, GIFI codes, and GST rates directly in the grid. Changes will save automatically.*")
                
                df_editor_display = df_proc.copy()
                df_editor_display['date'] = df_editor_display['date'].dt.strftime('%Y-%m-%d')
                
                # Make clean columns order
                cols_order = ['date', 'description', 'debit', 'credit', 'category', 'gifi_code', 'gst_rate']
                for col in cols_order:
                    if col not in df_editor_display.columns:
                        df_editor_display[col] = ""
                df_editor_display = df_editor_display[cols_order]
                
                df_edited = st.data_editor(
                    df_editor_display,
                    column_config={
                        "category": st.column_config.SelectboxColumn(
                            "Category",
                            width="medium",
                            options=[
                                "Accounting Fees", "Advertising Expense", "Bank Charges", "Business taxes",
                                "CC Payment", "CRA Payment", "Due to individual shareholder", "Due to Related Party",
                                "Insurance expense", "Meal", "Office Expense", "Office Supplies", "Rent",
                                "Repairs and maintenance", "Salaries and wages", "Subcontract Expense",
                                "Telephone Expense", "Trade Sales", "Travel Expense", "Truck Loan", "Vehicle Asset",
                                "Vehicle Expense", "Equipment rental/lease", "Dumping Charges", "Utilities",
                                "Other Expenses", "Revenue / Deposits"
                            ],
                            required=True
                        ),
                        "gifi_code": st.column_config.TextColumn(
                            "GIFI Code",
                            width="small"
                        ),
                        "gst_rate": st.column_config.SelectboxColumn(
                            "GST/PST Rate",
                            width="small",
                            options=["0%", "5%", "12%", ""]
                        )
                    },
                    disabled=["date", "description", "debit", "credit"],
                    use_container_width=True,
                    key="cat_editor_key"
                )
                
                # Write back edits
                st.session_state.categorizer_transactions = df_edited.to_dict('records')
                
            # Download actions
            csv_dl = df_edited.to_csv(index=False)
            st.download_button(
                label="📥 Download Categorized Transactions (CSV)",
                data=csv_dl,
                file_name=f"categorized_{uploaded_file.name.split('.')[0]}.csv",
                mime="text/csv"
            )
