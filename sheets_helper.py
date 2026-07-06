import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import pandas as pd
import hashlib
from datetime import datetime

# Define standard scopes for Google Sheets and Drive API
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_gspread_client():
    """
    Initializes and returns a gspread client using the service account credentials in st.secrets.
    """
    try:
        # Check if GCP service account secret is present
        if "gcp_service_account" not in st.secrets:
            raise KeyError("gcp_service_account key not found in Streamlit secrets.")
            
        credentials_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Failed to authenticate with Google Sheets: {e}")
        return None

def get_spreadsheet(client):
    """
    Retrieves the target spreadsheet from client using configured spreadsheet_id in secrets.
    """
    if "google_sheets" not in st.secrets or "spreadsheet_id" not in st.secrets["google_sheets"]:
        st.error("❌ google_sheets.spreadsheet_id not configured in secrets.")
        return None
    spreadsheet_id = st.secrets["google_sheets"]["spreadsheet_id"]
    try:
        return client.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound:
        # Try as a spreadsheet title
        try:
            return client.open(spreadsheet_id)
        except Exception:
            st.error(f"❌ Spreadsheet ID '{spreadsheet_id}' not found or inaccessible.")
            return None
    except Exception as e:
        st.error(f"❌ Error opening spreadsheet: {e}")
        return None

def generate_hash_key(account_name, transaction_date, description, amount):
    """
    Generates a deterministic MD5 hash key for duplicate detection.
    """
    raw_str = f"{str(account_name).strip()}|{str(transaction_date).strip()}|{str(description).strip()}|{str(amount).strip()}"
    return hashlib.md5(raw_str.encode('utf-8')).hexdigest()

def normalize_description(text):
    """
    Applies consistent whitespace and lowercase normalization to descriptions.
    """
    if not text:
        return ""
    return " ".join(str(text).split()).lower()

def load_category_map(spreadsheet):
    """
    Loads and returns the Category_Map worksheet as a pandas DataFrame.
    """
    try:
        wks = spreadsheet.worksheet("Category_Map")
        records = wks.get_all_records()
        return pd.DataFrame(records)
    except gspread.exceptions.WorksheetNotFound:
        st.warning("⚠️ 'Category_Map' worksheet not found in Google Sheet.")
        return pd.DataFrame(columns=["keyword", "merchant_normalized", "category", "subcategory"])
    except Exception as e:
        st.error(f"❌ Error loading Category_Map: {e}")
        return pd.DataFrame(columns=["keyword", "merchant_normalized", "category", "subcategory"])

def apply_category_map(df, category_map_df):
    """
    Pre-categorizes the DataFrame rows based on the category_map_df mapping rules.
    """
    if category_map_df.empty:
        return df
        
    # Standardize map columns
    req_cols = ["keyword", "merchant_normalized", "category", "subcategory"]
    for col in req_cols:
        if col not in category_map_df.columns:
            category_map_df[col] = ""
            
    # Compile mappings
    mappings = category_map_df.to_dict('records')
    
    for idx, row in df.iterrows():
        desc = str(row['description'])
        norm_desc = normalize_description(desc)
        
        matched = False
        # Phase 1: Exact Match on merchant_normalized or keyword
        for mapping in mappings:
            keyword = str(mapping.get("keyword", "")).strip()
            merchant = str(mapping.get("merchant_normalized", "")).strip()
            
            # Exact checks
            if merchant and norm_desc == normalize_description(merchant):
                df.at[idx, 'category'] = mapping.get("category", "")
                df.at[idx, 'subcategory'] = mapping.get("subcategory", "")
                matched = True
                break
            elif keyword and norm_desc == normalize_description(keyword):
                df.at[idx, 'category'] = mapping.get("category", "")
                df.at[idx, 'subcategory'] = mapping.get("subcategory", "")
                matched = True
                break
                
        # Phase 2: Keyword contains check (if not exact matched)
        if not matched:
            for mapping in mappings:
                keyword = str(mapping.get("keyword", "")).strip()
                if keyword and normalize_description(keyword) in norm_desc:
                    df.at[idx, 'category'] = mapping.get("category", "")
                    df.at[idx, 'subcategory'] = mapping.get("subcategory", "")
                    break
                    
    return df

def load_existing_hashes(spreadsheet):
    """
    Loads all existing hash keys from both Raw_Transactions and Needs_Review worksheets.
    """
    existing_hashes = set()
    for tab in ["Raw_Transactions", "Needs_Review"]:
        try:
            wks = spreadsheet.worksheet(tab)
            # Find hash_key column index
            headers = wks.row_values(1)
            if "hash_key" in headers:
                col_idx = headers.index("hash_key") + 1
                col_vals = wks.col_values(col_idx)
                # Skip header row
                for val in col_vals[1:]:
                    if val:
                        existing_hashes.add(val.strip())
        except gspread.exceptions.WorksheetNotFound:
            # OK if sheet doesn't exist yet
            pass
        except Exception as e:
            st.warning(f"⚠️ Failed to read hash keys from '{tab}': {e}")
    return existing_hashes

def split_clean_and_review(df):
    """
    Splits the normalized transaction DataFrame into clean and review subsets.
    Clean rows are those with review_flag = False or empty.
    """
    # Force review flags to be standard
    df['review_flag'] = df['review_flag'].fillna("False").astype(str).str.strip()
    
    clean_mask = (df['review_flag'] == "False") | (df['review_flag'] == "") | (df['review_flag'] == "None")
    clean_df = df[clean_mask].copy()
    review_df = df[~clean_mask].copy()
    
    return clean_df, review_df

def append_rows_to_sheet(spreadsheet, sheet_name, df):
    """
    Appends the rows of a DataFrame to the designated Google Sheet worksheet.
    Creates the worksheet with correct headers if it does not exist.
    """
    if df.empty:
        return True
        
    try:
        # Convert all columns to strings and fill NAs
        df_clean = df.fillna("").astype(str)
        rows_to_append = df_clean.values.tolist()
        
        try:
            wks = spreadsheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            # Create sheet if missing
            wks = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols=str(len(df.columns)))
            wks.append_row(list(df.columns))
            
        wks.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        st.error(f"❌ Failed to append data to worksheet '{sheet_name}': {e}")
        return False

def log_processing_run(spreadsheet, summary_dict):
    """
    Logs metadata about the batch processing run into the Processing_Log worksheet.
    """
    try:
        try:
            wks = spreadsheet.worksheet("Processing_Log")
        except gspread.exceptions.WorksheetNotFound:
            cols = ["timestamp", "file_count", "row_count", "duplicates_count", "review_count", "status"]
            wks = spreadsheet.add_worksheet(title="Processing_Log", rows="1000", cols=str(len(cols)))
            wks.append_row(cols)
            
        log_row = [
            datetime.now().isoformat(),
            str(summary_dict.get("file_count", 0)),
            str(summary_dict.get("row_count", 0)),
            str(summary_dict.get("duplicates_count", 0)),
            str(summary_dict.get("review_count", 0)),
            str(summary_dict.get("status", "SUCCESS"))
        ]
        wks.append_row(log_row, value_input_option="USER_ENTERED")
    except Exception as e:
        st.warning(f"⚠️ Failed to write to log sheet: {e}")
