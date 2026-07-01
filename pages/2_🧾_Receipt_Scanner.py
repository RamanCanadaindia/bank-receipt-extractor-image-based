import streamlit as st
import os
import base64
import tempfile
import pandas as pd
from PIL import Image
import io
import sys

# Import helper functions from receipt_extractor
# Ensure parent directory is in path since we are in pages/
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import receipt_extractor

# Page Config
st.set_page_config(
    page_title="Wave-Compatible Receipt OCR Extractor",
    page_icon="🧾",
    layout="wide"
)

# Custom Sleek CSS Styles
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
    .stButton>button {
        background-color: #2b5c8f;
        color: white;
        border-radius: 8px;
        font-weight: bold;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #1f4268;
        transform: translateY(-1px);
    }
</style>
""", unsafe_allow_html=True)

# Session State Setup
if "receipt_history" not in st.session_state:
    st.session_state.receipt_history = []

if "temp_extracted" not in st.session_state:
    st.session_state.temp_extracted = None

# Title
st.title("🧾 Wave-Compatible Receipt OCR Extractor")
st.markdown("""
Save **$11/month** by using your own Gemini-powered OCR system! Scan purchase receipts, review and edit details, and compile them into a running CSV ready to import directly into Wave Apps.
""")

# Sidebar config
st.sidebar.header("⚙️ Configuration")
api_key = st.sidebar.text_input(
    "Google AI Studio API Key",
    type="password",
    value=os.environ.get("GEMINI_API_KEY", ""),
    help="Get a free key from https://aistudio.google.com/"
)

model = st.sidebar.selectbox(
    "Gemini OCR Model",
    ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest", "gemini-2.5-pro"],
    index=0,
    help="gemini-2.5-flash is highly recommended for speed and table OCR accuracy."
)

st.sidebar.markdown("---")
st.sidebar.markdown("### How it works:")
st.sidebar.info("""
1. **Upload** an image or PDF of your store receipt.
2. The tool uses **Gemini Vision OCR** to extract the merchant name, date, total, tax, tip, payment method, and items.
3. **Verify and edit** the extracted data fields.
4. Click **Add to Expense Log** to append to your session sheet.
5. Download your merged receipt log as a **Wave-ready CSV**!
""")

# File Upload Section
uploaded_files = st.file_uploader("Upload Receipt Images or PDFs", type=["png", "jpg", "jpeg", "pdf"], accept_multiple_files=True)

if uploaded_files:
    if len(uploaded_files) == 1:
        uploaded_file = uploaded_files[0]
        col_preview, col_form = st.columns([1, 1])
        
        with col_preview:
            st.subheader("🖼️ Receipt Preview")
            # Visual rendering of uploaded file
            file_extension = uploaded_file.name.split(".")[-1].lower()
            
            if file_extension == "pdf":
                st.info("PDF document uploaded. Previewing first page...")
                try:
                    # Save to a temporary file locally so we can render it
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded_file.getvalue())
                        tmp_path = tmp.name
                    
                    try:
                        # Convert to base64
                        base64_image = receipt_extractor.convert_pdf_to_image_base64(tmp_path)
                        image_data = base64.b64decode(base64_image)
                        st.image(image_data, use_container_width=True)
                    finally:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                except Exception as e:
                    st.error(f"Error rendering PDF: {e}")
                    base64_image = None
            else:
                # Standard image file preview
                image = Image.open(uploaded_file)
                st.image(image, use_container_width=True)
                
                # Prepare image base64
                buffered = io.BytesIO()
                image.save(buffered, format="PNG")
                base64_image = base64.b64encode(buffered.getvalue()).decode("utf-8")
                
        with col_form:
            st.subheader("🔍 Extraction Details")
            
            # Analyze button
            analyze_btn = st.button("⚡ Extract Receipt Details")
            
            if analyze_btn:
                if not api_key:
                    st.error("🔑 Gemini API Key is required. Please enter it in the sidebar.")
                elif base64_image is None:
                    st.error("Failed to read the file. Please re-upload.")
                else:
                    with st.spinner("Analyzing receipt with Gemini Vision..."):
                        extracted_data = receipt_extractor.extract_receipt_data(api_key, model, base64_image)
                        if extracted_data:
                            st.session_state.temp_extracted = extracted_data
                            st.success("🎉 Receipt extracted successfully!")
                        else:
                            st.error("Failed to extract data from receipt. Try another model or check the terminal logs.")
            
            # Display editable form if data has been extracted
            if st.session_state.temp_extracted:
                ext = st.session_state.temp_extracted
                
                st.markdown("### Edit Parsed Fields")
                # Editable inputs
                edit_merchant = st.text_input("Merchant / Vendor", value=ext.get("merchant", ""))
                edit_date = st.text_input("Date (YYYY-MM-DD)", value=ext.get("date", "2026-01-01"))
                edit_invoice_num = st.text_input("Invoice / Receipt Number", value=ext.get("invoice_number", "") if ext.get("invoice_number") else "")
                edit_total = st.number_input("Total Amount ($)", value=float(ext.get("total", 0.0)), step=0.01)
                edit_tax = st.number_input("Tax ($)", value=float(ext.get("tax", 0.0)) if ext.get("tax") else 0.0, step=0.01)
                edit_gst = st.number_input("GST Amount ($)", value=float(ext.get("gst", 0.0)) if ext.get("gst") else 0.0, step=0.01)
                edit_tip = st.number_input("Tip ($)", value=float(ext.get("tip", 0.0)) if ext.get("tip") else 0.0, step=0.01)
                
                categories_list = [
                    "Meals & Entertainment", "Office Supplies", "Travel & Lodging", 
                    "Automobile Expenses", "Professional Services", "Utilities", "General Expenses"
                ]
                current_cat = ext.get("category", "General Expenses")
                if current_cat not in categories_list:
                    categories_list.append(current_cat)
                edit_category = st.selectbox("Wave Expense Category", categories_list, index=categories_list.index(current_cat))
                
                edit_payment = st.text_input("Payment Method (optional)", value=ext.get("payment_method", "") if ext.get("payment_method") else "")
                
                # Show itemized table
                items = ext.get("items", [])
                if items:
                    with st.expander("🛒 View Itemized Items"):
                        st.table(pd.DataFrame(items))
                        
                # Submit to log
                add_log = st.button("➕ Add to Expense Log")
                if add_log:
                    new_expense = {
                        "Date": edit_date,
                        "Invoice Number": edit_invoice_num,
                        "Description": edit_merchant,
                        "Category": edit_category,
                        "Amount": edit_total,
                        "Tax": edit_tax,
                        "GST": edit_gst,
                        "Tip": edit_tip,
                        "Payment Method": edit_payment
                    }
                    st.session_state.receipt_history.append(new_expense)
                    st.session_state.temp_extracted = None  # Reset form
                    st.success(f"Added expense for {edit_merchant} (${edit_total:,.2f}) to your log!")
                    st.rerun()
    else:
        # Multiple files mode!
        st.info(f"📁 {len(uploaded_files)} files uploaded. Ready to bulk extract.")
        
        with st.expander("📄 View Uploaded Files List"):
            for f in uploaded_files:
                st.write(f"- {f.name} ({f.size / 1024:.1f} KB)")
                
        bulk_btn = st.button("⚡ Bulk Extract Invoices")
        
        if bulk_btn:
            if not api_key:
                st.error("🔑 Gemini API Key is required. Please enter it in the sidebar.")
            else:
                import concurrent.futures
                
                # Render/encode helper for files
                def process_file_to_b64(u_file):
                    file_ext = u_file.name.split(".")[-1].lower()
                    if file_ext == "pdf":
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                            tmp.write(u_file.getvalue())
                            t_path = tmp.name
                        try:
                            return receipt_extractor.convert_pdf_to_image_base64(t_path)
                        finally:
                            if os.path.exists(t_path):
                                os.remove(t_path)
                    else:
                        img = Image.open(u_file)
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        return base64.b64encode(buf.getvalue()).decode("utf-8")
                
                # Render all files
                with st.spinner("Preparing files for processing..."):
                    base64_images = []
                    for f in uploaded_files:
                        try:
                            b64 = process_file_to_b64(f)
                            if b64:
                                base64_images.append((f.name, b64))
                        except Exception as e:
                            st.warning(f"Failed to load {f.name}: {e}")
                
                if base64_images:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    status_text.text(f"Extracting {len(base64_images)} invoices in parallel (concurrency=3)...")
                    
                    completed = 0
                    max_workers = 3
                    
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = {
                            executor.submit(receipt_extractor.extract_receipt_data, api_key, model, b64): name
                            for name, b64 in base64_images
                        }
                        
                        for future in concurrent.futures.as_completed(futures):
                            name = futures[future]
                            try:
                                data = future.result()
                                if data:
                                    new_expense = {
                                        "Date": data.get("date", "2026-01-01"),
                                        "Invoice Number": data.get("invoice_number", "") if data.get("invoice_number") else "",
                                        "Description": data.get("merchant", name),
                                        "Category": data.get("category", "General Expenses"),
                                        "Amount": float(data.get("total", 0.0)),
                                        "Tax": float(data.get("tax", 0.0)) if data.get("tax") else 0.0,
                                        "GST": float(data.get("gst", 0.0)) if data.get("gst") else 0.0,
                                        "Tip": float(data.get("tip", 0.0)) if data.get("tip") else 0.0,
                                        "Payment Method": data.get("payment_method", "") if data.get("payment_method") else ""
                                    }
                                    st.session_state.receipt_history.append(new_expense)
                            except Exception as e:
                                st.warning(f"Error extracting {name}: {e}")
                                
                            completed += 1
                            status_text.text(f"Finished {name} ({completed}/{len(base64_images)})...")
                            progress_bar.progress(completed / len(base64_images))
                            
                    progress_bar.empty()
                    status_text.empty()
                    st.success("🎉 Bulk extraction complete!")
                    st.rerun()

st.markdown("---")
# Session History Table
st.subheader("📋 Cumulative Expense Log")

if st.session_state.receipt_history:
    df_history = pd.DataFrame(st.session_state.receipt_history)
    
    # Render overall metrics
    total_spent = df_history["Amount"].sum()
    total_tax = df_history["Tax"].sum()
    total_gst = df_history["GST"].sum()
    total_tip = df_history["Tip"].sum()
    receipts_count = len(df_history)
    
    col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
    with col_m1:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{receipts_count}</div><div class="metric-label">Receipts Processed</div></div>', unsafe_allow_html=True)
    with col_m2:
        st.markdown(f'<div class="metric-card"><div class="metric-value" style="color: #2b5c8f;">${total_spent:,.2f}</div><div class="metric-label">Total Expenses</div></div>', unsafe_allow_html=True)
    with col_m3:
        st.markdown(f'<div class="metric-card"><div class="metric-value" style="color: #6d7278;">${total_tax:,.2f}</div><div class="metric-label">Total Tax Paid</div></div>', unsafe_allow_html=True)
    with col_m4:
        st.markdown(f'<div class="metric-card"><div class="metric-value" style="color: #e67e22;">${total_gst:,.2f}</div><div class="metric-label">Total GST Paid</div></div>', unsafe_allow_html=True)
    with col_m5:
        st.markdown(f'<div class="metric-card"><div class="metric-value" style="color: #34a853;">${total_tip:,.2f}</div><div class="metric-label">Total Tips Paid</div></div>', unsafe_allow_html=True)
        
    st.write("")
    
    # Display the cumulative log table
    st.dataframe(df_history, use_container_width=True)
    
    # CSV generation formatted for Wave Apps
    # We include all fields for detailed bookkeeping: Date, Invoice Number, Description, Category, Amount, Tax, GST, Tip, Payment Method
    wave_df = df_history[["Date", "Invoice Number", "Description", "Category", "Amount", "Tax", "GST", "Tip", "Payment Method"]].copy()
    
    csv_data = wave_df.to_csv(index=False)
    
    col_d1, col_d2, col_d3 = st.columns(3)
    with col_d1:
        st.download_button(
            label="📥 Download Wave-Ready CSV",
            data=csv_data,
            file_name="receipts_wave_import.csv",
            mime="text/csv"
        )
    with col_d2:
        # Excel generator
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            wave_df.to_excel(writer, index=False, sheet_name='Receipts')
        excel_data = excel_buffer.getvalue()
        
        st.download_button(
            label="📥 Download Excel (.xlsx)",
            data=excel_data,
            file_name="receipts_wave_import.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    with col_d3:
        clear_btn = st.button("🗑️ Clear Expense History")
        if clear_btn:
            st.session_state.receipt_history = []
            st.success("Expense log cleared successfully!")
            st.rerun()
else:
    st.info("No receipts have been processed in this session yet. Upload a receipt above and extract it to begin compiling your logs!")
