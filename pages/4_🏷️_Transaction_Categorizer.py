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
import importlib
importlib.reload(categorizer)

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
                
                # Sort chronologically to compute mathematically consistent balance flow
                try:
                    categorized_txs.sort(key=lambda x: pd.to_datetime(x["date"], errors="coerce"))
                except Exception:
                    pass
                    
                # Calculate Running Balance
                running_balance = 0.0
                for i, tx in enumerate(categorized_txs):
                    deb = tx.get("debit") if tx.get("debit") is not None else 0.0
                    cred = tx.get("credit") if tx.get("credit") is not None else 0.0
                    net_change = cred - deb
                    
                    if i == 0:
                        desc_lower = tx["description"].lower()
                        if "opening" in desc_lower and ("bal" in desc_lower or "blan" in desc_lower):
                            running_balance = net_change
                        else:
                            running_balance = net_change
                    else:
                        running_balance += net_change
                        
                    tx["balance"] = round(running_balance, 2)
                    
                # Convert to DataFrame
                df_proc = pd.DataFrame(categorized_txs)
                df_proc['date'] = pd.to_datetime(df_proc['date'], errors='coerce')
                df_proc = df_proc.dropna(subset=['date']).sort_values(by='date').reset_index(drop=True)
                df_proc['date'] = df_proc['date'].dt.strftime('%Y-%m-%d')
                
                # Ensure all columns exist and are ordered
                cols_order = ['date', 'description', 'debit', 'credit', 'balance', 'category', 'gifi_code', 'gst_rate']
                for col in cols_order:
                    if col not in df_proc.columns:
                        df_proc[col] = ""
                df_proc = df_proc[cols_order]
                
                st.session_state.categorizer_df = df_proc
                st.success("🎉 Processing and running balance calculation complete!")

        # Render Dashboard if processed dataframe exists
        if "categorizer_df" in st.session_state and st.session_state.categorizer_df is not None:
            df_proc = st.session_state.categorizer_df
            
            # Metrics
            total_spend = pd.to_numeric(df_proc['debit'], errors='coerce').fillna(0).sum()
            total_income = pd.to_numeric(df_proc['credit'], errors='coerce').fillna(0).sum()
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
                df_exp_only = df_proc[pd.to_numeric(df_proc['debit'], errors='coerce') > 0]
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
                
                df_edited = st.data_editor(
                    st.session_state.categorizer_df,
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
                                "Other Expenses", "Revenue / Deposits", "Uncategorized"
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
                            options=["0%", "5%", "7%", "12%", ""]
                        )
                    },
                    disabled=["date", "description", "debit", "credit", "balance"],
                    use_container_width=True,
                    key="cat_editor_key"
                )
                
                # Write back edits to keep editor state in sync
                st.session_state.categorizer_df = df_edited
                
                # Remember categories button
                st.write("")
                if st.button("💾 Remember Manual Category Changes (Learn for Future)", key="remember_btn_cat"):
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
                
            # Download actions
            csv_dl = df_edited.to_csv(index=False)
            st.download_button(
                label="📥 Download Categorized Transactions (CSV)",
                data=csv_dl,
                file_name=f"categorized_{uploaded_file.name.split('.')[0]}.csv",
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
                        clear_all = st.button("🗑️ Clear All Saved Rules", key="clear_all_rules_btn_cat")
                        if clear_all:
                            user_rules_path = os.path.join(os.path.dirname(os.path.abspath(categorizer.__file__)), "user_rules.json")
                            if os.path.exists(user_rules_path):
                                os.remove(user_rules_path)
                                st.success("All saved rules cleared! Refreshing...")
                                st.rerun()
                else:
                    st.info("No custom overrides saved yet. Use the 'Remember Manual Category Changes' button above to save overrides.")
