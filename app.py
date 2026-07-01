import streamlit as st

st.set_page_config(
    page_title="Financial Document Automator",
    page_icon="📊",
    layout="wide"
)

# Custom Sleek CSS Styles
st.markdown("""
<style>
    .welcome-header {
        text-align: center;
        padding: 40px 10px;
        background: linear-gradient(135deg, #1f4268 0%, #2b5c8f 100%);
        color: white;
        border-radius: 12px;
        margin-bottom: 30px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
    }
    .welcome-title {
        font-size: 36px;
        font-weight: bold;
        margin-bottom: 10px;
    }
    .welcome-subtitle {
        font-size: 18px;
        opacity: 0.9;
    }
    .tool-card {
        background-color: #ffffff;
        border: 1px solid #e9ecef;
        border-radius: 12px;
        padding: 30px;
        height: 100%;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
    }
    .tool-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15);
    }
    .tool-icon {
        font-size: 50px;
        margin-bottom: 20px;
    }
    .tool-name {
        font-size: 22px;
        font-weight: bold;
        color: #1f4268;
        margin-bottom: 15px;
    }
    .tool-desc {
        color: #5c636a;
        font-size: 15px;
        line-height: 1.6;
        margin-bottom: 20px;
    }
    .nav-instruction {
        font-weight: bold;
        color: #2b5c8f;
        background-color: #eef2f7;
        padding: 8px 12px;
        border-radius: 6px;
        display: inline-block;
        font-size: 14px;
    }
</style>
""", unsafe_allow_html=True)

# Welcome Banner
st.markdown("""
<div class="welcome-header">
    <div class="welcome-title">📊 Financial Document Automator</div>
    <div class="welcome-subtitle">A professional, local-first automation platform powered by Gemini AI.</div>
</div>
""", unsafe_allow_html=True)

# Grid Layout
col_statements, col_receipts = st.columns(2)

with col_statements:
    st.markdown("""
    <div class="tool-card">
        <div class="tool-icon">🏦</div>
        <div class="tool-name">Bank Statement Extractor</div>
        <div class="tool-desc">
            Parse transaction tables from PDF bank statements (both digital and scanned). 
            Features chronological balance transition validation, auto-fixing of debit/credit swaps, 
            interactive balance history trend lines, and monthly cash flow charts.
        </div>
        <div class="nav-instruction">👈 Select "1 🏦 Bank Statement Extractor" in the sidebar</div>
    </div>
    """, unsafe_allow_html=True)

with col_receipts:
    st.markdown("""
    <div class="tool-card">
        <div class="tool-icon">🧾</div>
        <div class="tool-name">Receipt Expense Scanner</div>
        <div class="tool-desc">
            Scan purchase receipt images and invoice PDFs. Extracts vendor name, purchase date, 
            invoice number, total amount, tax, and GST components. Compiles invoices in parallel 
            into a consolidated Wave-compatible Excel/CSV sheet, replacing paid bookkeeping plans.
        </div>
        <div class="nav-instruction">👈 Select "2 🧾 Receipt Scanner" in the sidebar</div>
    </div>
    """, unsafe_allow_html=True)

st.write("")
st.write("")

# General Info
st.markdown("### 💡 Cloud Deployment Note")
st.info("""
When you upload this project folder to your GitHub and link it to **share.streamlit.io**, Streamlit Cloud will automatically build and render this multi-page dashboard. 
You can use the sidebar navigation on the left to switch between pages instantly on any device—no local python install needed!
""")
