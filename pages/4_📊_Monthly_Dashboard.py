import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import auth
import sheets_helper
from datetime import datetime

st.set_page_config(
    page_title="Monthly Financial Dashboard",
    page_icon="📊",
    layout="wide"
)

# Password Check
if not auth.check_password():
    st.stop()

# Design Styling
st.markdown("""
<style>
    .dashboard-header {
        text-align: center;
        padding: 30px 10px;
        background: linear-gradient(135deg, #2b5c8f 0%, #1f4268 100%);
        color: white;
        border-radius: 12px;
        margin-bottom: 25px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
    }
    .dashboard-title {
        font-size: 32px;
        font-weight: bold;
        margin-bottom: 5px;
    }
    .dashboard-subtitle {
        font-size: 16px;
        opacity: 0.9;
    }
    .metric-card {
        background-color: #ffffff;
        border: 1px solid #e9ecef;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.02);
    }
    .metric-value {
        font-size: 28px;
        font-weight: bold;
        margin-bottom: 5px;
    }
    .metric-label {
        font-size: 14px;
        color: #6c757d;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("""
<div class="dashboard-header">
    <div class="dashboard-title">📊 Monthly Cash Flow & Expense Analytics</div>
    <div class="dashboard-subtitle">Visualize income, expenses, and category distributions from your Google Sheets.</div>
</div>
""", unsafe_allow_html=True)

# Sidebar Configuration
st.sidebar.header("⚙️ Configuration")

# Get default spreadsheet ID from secrets
try:
    default_sheet_id = st.secrets.get("google_spreadsheet_id", "")
    if not default_sheet_id:
        default_sheet_id = st.secrets.get("google_sheets", {}).get("spreadsheet_id", "")
except Exception:
    default_sheet_id = ""

target_spreadsheet_id = st.sidebar.text_input(
    "Google Spreadsheet ID / URL",
    value=default_sheet_id,
    help="Paste the target Google Sheet's browser URL or its ID here."
)

if not target_spreadsheet_id:
    st.info("👈 Please enter your Google Spreadsheet ID or URL in the sidebar to load your transactions.")
    st.stop()

# Initialize Google Sheets Client
client = sheets_helper.get_gspread_client()
if not client:
    st.error("❌ Failed to initialize Google Sheets client. Please check your secrets.toml credentials.")
    st.stop()

spreadsheet = sheets_helper.get_spreadsheet(client, target_spreadsheet_id)
if not spreadsheet:
    st.stop()

# Fetch all available worksheets
try:
    worksheets = spreadsheet.worksheets()
    sheet_names = [w.title for w in worksheets]
except Exception as e:
    st.error(f"❌ Failed to retrieve tabs from spreadsheet: {e}")
    st.stop()

# Let user choose worksheets to load
st.sidebar.markdown("### 🗂️ Data Sources")
selected_tabs = st.sidebar.multiselect(
    "Select Sheets/Tabs to Analyze",
    options=sheet_names,
    default=[t for t in ["Bank Transactions", "Credit Card", "Bank Single Column"] if t in sheet_names] or (sheet_names[:1] if sheet_names else [])
)

if not selected_tabs:
    st.warning("⚠️ Please select at least one tab in the sidebar to load data.")
    st.stop()

# Load and Combine Data
@st.cache_data(ttl=60)  # cache for 1 minute to allow quick updates without hitting API limits
def load_consolidated_data(spreadsheet_id, tabs):
    # Retrieve spreadsheet again inside cached function to avoid unhashable gspread objects
    gc = sheets_helper.get_gspread_client()
    sh = sheets_helper.get_spreadsheet(gc, spreadsheet_id)
    all_dfs = []
    
    for tab in tabs:
        try:
            wks = sh.worksheet(tab)
            records = wks.get_all_records()
            if not records:
                continue
            df = pd.DataFrame(records)
            df['_source_tab'] = tab
            all_dfs.append(df)
        except Exception as e:
            st.sidebar.error(f"Failed to load '{tab}': {e}")
            
    if not all_dfs:
        return pd.DataFrame()
        
    # Consolidate
    return pd.concat(all_dfs, ignore_index=True)

with st.spinner("⏳ Loading transactions from Google Sheets..."):
    df_raw = load_consolidated_data(target_spreadsheet_id, selected_tabs)

if df_raw.empty:
    st.info("ℹ️ No transaction data found in the selected worksheets. Make sure you have uploaded statements first!")
    st.stop()

# Auto-detect and standardize columns
date_col = None
amount_col = None
category_col = None

# Search for Date column
for col in ['transaction_date', 'date', 'Date', 'Transaction Date']:
    if col in df_raw.columns:
        date_col = col
        break

# Search for Amount column
for col in ['amount', 'Amount', 'Value', 'Net Amount']:
    if col in df_raw.columns:
        amount_col = col
        break

# Search for Category column
for col in ['category', 'Category', 'GIFI Category', 'suggested_category']:
    if col in df_raw.columns:
        category_col = col
        break

# Fallback column detection if names differ
if not date_col:
    # Find column with date-like names
    cols = [c for c in df_raw.columns if 'date' in c.lower()]
    if cols:
        date_col = cols[0]
if not amount_col:
    cols = [c for c in df_raw.columns if 'amount' in c.lower() or 'val' in c.lower()]
    if cols:
        amount_col = cols[0]
if not category_col:
    cols = [c for c in df_raw.columns if 'cat' in c.lower()]
    if cols:
        category_col = cols[0]

# Check if we found the basic columns
missing_cols = []
if not date_col: missing_cols.append("Date (e.g. 'transaction_date')")
if not amount_col:
    # If debit and credit exist instead of single amount
    if 'debit' in df_raw.columns and 'credit' in df_raw.columns:
        pass
    else:
        missing_cols.append("Amount (e.g. 'amount')")
if not category_col: missing_cols.append("Category (e.g. 'category')")

if missing_cols:
    st.error(f"❌ Could not automatically detect all required columns. Missing: {', '.join(missing_cols)}")
    st.markdown("### Preview of Loaded Data:")
    st.dataframe(df_raw.head())
    st.stop()

# Prepare clean dataframe
df_clean = pd.DataFrame()

# Parse Date
df_clean['date'] = pd.to_datetime(df_raw[date_col], errors='coerce')
df_clean = df_clean.dropna(subset=['date'])

# Parse Amount
if amount_col in df_raw.columns:
    df_clean['amount'] = pd.to_numeric(df_raw[amount_col], errors='coerce').fillna(0.0)
else:
    # Reconstruct from debit/credit
    debit = pd.to_numeric(df_raw['debit'], errors='coerce').fillna(0.0)
    credit = pd.to_numeric(df_raw['credit'], errors='coerce').fillna(0.0)
    # Debits are expenses (negative), Credits are income (positive)
    df_clean['amount'] = credit - debit

# Parse Category & Description
df_clean['category'] = df_raw[category_col].astype(str).str.strip().replace("", "Uncategorized")
df_clean['description'] = df_raw['description'] if 'description' in df_raw.columns else (df_raw['Description'] if 'Description' in df_raw.columns else "")
df_clean['description'] = df_clean['description'].astype(str).str.strip()

# Add metadata columns if they exist
for optional_col in ['account_name', 'institution', '_source_tab']:
    if optional_col in df_raw.columns:
        df_clean[optional_col] = df_raw[optional_col]
    else:
        df_clean[optional_col] = "N/A"

# Filter out zero amounts
df_clean = df_clean[df_clean['amount'] != 0.0]

# Add Month and Year columns
df_clean['month_period'] = df_clean['date'].dt.to_period('M')
df_clean['month_str'] = df_clean['date'].dt.strftime('%Y-%m')

# Classify Income vs Expense
df_clean['type'] = np.where(df_clean['amount'] > 0, 'Income', 'Expense')
df_clean['abs_amount'] = df_clean['amount'].abs()

# Range selection filters
min_date = df_clean['date'].min()
max_date = df_clean['date'].max()

st.sidebar.markdown("### 📅 Date Range Filter")
start_date = st.sidebar.date_input("Start Date", min_date.date() if pd.notna(min_date) else datetime(2025, 1, 1))
end_date = st.sidebar.date_input("End Date", max_date.date() if pd.notna(max_date) else datetime.now().date())

# Filter data by date range
df_filtered = df_clean[(df_clean['date'].dt.date >= start_date) & (df_clean['date'].dt.date <= end_date)].copy()

if df_filtered.empty:
    st.warning("⚠️ No transactions found in the selected date range.")
    st.stop()

# Additional sidebar filters (Account/Institution)
institutions = sorted(df_filtered['institution'].unique())
selected_inst = st.sidebar.multiselect("Filter by Institution", options=institutions, default=institutions)

accounts = sorted(df_filtered['account_name'].unique())
selected_acct = st.sidebar.multiselect("Filter by Account", options=accounts, default=accounts)

# Apply filters
df_filtered = df_filtered[
    (df_filtered['institution'].isin(selected_inst)) & 
    (df_filtered['account_name'].isin(selected_acct))
]

if df_filtered.empty:
    st.warning("⚠️ No transactions match the selected filters.")
    st.stop()

# Calculate Summary Metrics
total_income = df_filtered[df_filtered['type'] == 'Income']['amount'].sum()
total_expense = df_filtered[df_filtered['type'] == 'Expense']['abs_amount'].sum()
net_cash_flow = total_income - total_expense
savings_rate = (net_cash_flow / total_income * 100) if total_income > 0 else 0.0

# Display Metric Cards
m_col1, m_col2, m_col3, m_col4 = st.columns(4)

with m_col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value" style="color: #2e7d32;">${total_income:,.2f}</div>
        <div class="metric-label">Total Deposits (Income)</div>
    </div>
    """, unsafe_allow_html=True)

with m_col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value" style="color: #c62828;">${total_expense:,.2f}</div>
        <div class="metric-label">Total Withdrawals (Expense)</div>
    </div>
    """, unsafe_allow_html=True)

with m_col3:
    flow_color = "#2e7d32" if net_cash_flow >= 0 else "#c62828"
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value" style="color: {flow_color};">${net_cash_flow:,.2f}</div>
        <div class="metric-label">Net Savings Flow</div>
    </div>
    """, unsafe_allow_html=True)

with m_col4:
    rate_color = "#2e7d32" if savings_rate >= 0 else "#c62828"
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value" style="color: {rate_color};">{savings_rate:.1f}%</div>
        <div class="metric-label">Savings Rate</div>
    </div>
    """, unsafe_allow_html=True)

st.write("")
st.write("")

# ----------------- Visualizations -----------------
# 1. Monthly Trends Chart
st.subheader("📈 Monthly Cash Flow Trends")

# Group by Month and Type
monthly_summary = df_filtered.groupby(['month_str', 'type'])['abs_amount'].sum().unstack(fill_value=0.0).reset_index()

# Ensure both columns exist
if 'Income' not in monthly_summary.columns:
    monthly_summary['Income'] = 0.0
if 'Expense' not in monthly_summary.columns:
    monthly_summary['Expense'] = 0.0

# Add Net Flow to summary
monthly_summary['Net Flow'] = monthly_summary['Income'] - monthly_summary['Expense']

# Plotting using matplotlib/seaborn
sns.set_theme(style="whitegrid")
fig_trend, ax_trend = plt.subplots(figsize=(12, 5))

# Create bar chart for Income and Expense
x_indices = np.arange(len(monthly_summary))
width = 0.35

ax_trend.bar(x_indices - width/2, monthly_summary['Income'], width, label='Income (Deposits)', color='#4caf50', alpha=0.9)
ax_trend.bar(x_indices + width/2, monthly_summary['Expense'], width, label='Expense (Withdrawals)', color='#f44336', alpha=0.9)

# Draw line for Net Cash Flow
ax_trend.plot(x_indices, monthly_summary['Net Flow'], color='#1f77b4', marker='o', linewidth=2.5, label='Net Savings Flow')

ax_trend.set_title("Income vs. Expense by Month", fontsize=14, fontweight='bold', pad=15)
ax_trend.set_xticks(x_indices)
ax_trend.set_xticklabels(monthly_summary['month_str'], rotation=30, ha='right')
ax_trend.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, loc: "{:,}".format(int(x))))
ax_trend.legend(frameon=True, facecolor='white', edgecolor='none')
plt.tight_layout()
st.pyplot(fig_trend)

st.write("")
st.write("")

# 2. Monthly Deep-Dive Breakdown
st.subheader("🔍 Monthly Breakdown & Category Distributions")

# Month selection for deep-dive
available_months = sorted(df_filtered['month_str'].unique(), reverse=True)
if not available_months:
    st.info("No months available to analyze.")
else:
    selected_month = st.selectbox("Select Month for Deep-Dive Analysis:", options=available_months)
    
    # Filter data for the specific month
    df_month = df_filtered[df_filtered['month_str'] == selected_month].copy()
    
    # Create columns for Expense and Income breakdown
    col_exp, col_inc = st.columns(2)
    
    with col_exp:
        st.markdown(f"#### 💸 Expenses (Withdrawals) for {selected_month}")
        df_month_exp = df_month[df_month['type'] == 'Expense']
        
        if df_month_exp.empty:
            st.info("No expenses found in this month.")
        else:
            # Group by Category
            cat_exp = df_month_exp.groupby('category')['abs_amount'].sum().sort_values(ascending=False).reset_index()
            
            # Show Bar Chart
            fig_exp, ax_exp = plt.subplots(figsize=(8, 5))
            sns.barplot(data=cat_exp, x='abs_amount', y='category', palette='Reds_r', ax=ax_exp)
            ax_exp.set_title("Expense by Category", fontsize=12, fontweight='bold')
            ax_exp.set_xlabel("Amount ($)")
            ax_exp.set_ylabel("Category")
            ax_exp.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, loc: "{:,}".format(int(x))))
            plt.tight_layout()
            st.pyplot(fig_exp)
            
            # Show Table
            st.dataframe(
                cat_exp.rename(columns={'category': 'Category', 'abs_amount': 'Total Expense ($)'}),
                use_container_width=True,
                hide_index=True
            )
            
    with col_inc:
        st.markdown(f"#### 💰 Income (Deposits) for {selected_month}")
        df_month_inc = df_month[df_month['type'] == 'Income']
        
        if df_month_inc.empty:
            st.info("No income deposits found in this month.")
        else:
            # Group by Category
            cat_inc = df_month_inc.groupby('category')['abs_amount'].sum().sort_values(ascending=False).reset_index()
            
            # Show Bar Chart
            fig_inc, ax_inc = plt.subplots(figsize=(8, 5))
            sns.barplot(data=cat_inc, x='abs_amount', y='category', palette='Greens_r', ax=ax_inc)
            ax_inc.set_title("Income by Category", fontsize=12, fontweight='bold')
            ax_inc.set_xlabel("Amount ($)")
            ax_inc.set_ylabel("Category")
            ax_inc.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, loc: "{:,}".format(int(x))))
            plt.tight_layout()
            st.pyplot(fig_inc)
            
            # Show Table
            st.dataframe(
                cat_inc.rename(columns={'category': 'Category', 'abs_amount': 'Total Income ($)'}),
                use_container_width=True,
                hide_index=True
            )

st.write("")
st.write("")

# 3. Searchable Transaction Database
st.subheader("📑 Transaction Explorer")
st.write("Browse, search, or filter the raw transactions list below.")

# Filter elements for Table
search_query = st.text_input("🔍 Search Description or Merchant", value="").strip().lower()
type_filter = st.selectbox("Transaction Type Filter", options=["All", "Income Only", "Expense Only"])
selected_category = st.multiselect("Filter by Specific Categories", options=sorted(df_filtered['category'].unique()))

# Apply filters
df_table = df_filtered.copy()

if search_query:
    df_table = df_table[df_table['description'].str.lower().str.contains(search_query)]

if type_filter == "Income Only":
    df_table = df_table[df_table['type'] == 'Income']
elif type_filter == "Expense Only":
    df_table = df_table[df_table['type'] == 'Expense']

if selected_category:
    df_table = df_table[df_table['category'].isin(selected_category)]

# Format columns for display
df_display = df_table[['date', 'description', 'category', 'amount', 'account_name', 'institution', '_source_tab']].copy()
df_display['date'] = df_display['date'].dt.strftime('%Y-%m-%d')
df_display['amount'] = df_display['amount'].map(lambda x: f"${x:,.2f}")
df_display.columns = ['Date', 'Description', 'Category', 'Amount', 'Account', 'Institution', 'Source Tab']

st.dataframe(
    df_display.sort_values(by='Date', ascending=False),
    use_container_width=True,
    hide_index=True
)
