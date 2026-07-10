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
    Supports either the TOML structure under [gcp_service_account] or the raw JSON string under gcp_service_account_json.
    """
    import json
    try:
        if "gcp_service_account_json" in st.secrets:
            # strict=False allows literal newlines/control characters inside the JSON string
            credentials_dict = json.loads(st.secrets["gcp_service_account_json"], strict=False)
        elif "gcp_service_account" in st.secrets:
            credentials_dict = dict(st.secrets["gcp_service_account"])
        else:
            raise KeyError("Neither 'gcp_service_account' nor 'gcp_service_account_json' keys found in Streamlit secrets.")
            
        # Sanitize private key newlines
        if "private_key" in credentials_dict:
            credentials_dict["private_key"] = credentials_dict["private_key"].replace("\\n", "\n")
            
        creds = Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Failed to authenticate with Google Sheets: {e}")
        return None

def get_spreadsheet(client, spreadsheet_id):
    """
    Retrieves the target spreadsheet from client using a spreadsheet ID or URL.
    """
    if not spreadsheet_id:
        st.error("❌ Google Spreadsheet ID/URL is empty.")
        return None
        
    # If a full URL was pasted, parse out the ID automatically
    if "docs.google.com/spreadsheets" in str(spreadsheet_id):
        try:
            parts = str(spreadsheet_id).split("/d/")
            if len(parts) > 1:
                spreadsheet_id = parts[1].split("/")[0]
        except Exception:
            pass
            
    try:
        return client.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound:
        try:
            return client.open(spreadsheet_id)
        except Exception:
            st.error(f"❌ Spreadsheet ID/URL '{spreadsheet_id}' not found or inaccessible. Make sure you shared it with the service account email.")
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
        # Silently fail and return empty DataFrame if worksheet is not present
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
    Loads all existing hash keys from new and fallback worksheets to prevent duplicates.
    """
    existing_hashes = set()
    for tab in ["Bank Transactions", "Bank Single Column", "Credit Card", "Raw_Transactions", "Needs_Review"]:
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

def sync_property_listings(spreadsheet, df):
    """
    Syncs property listings to the 'Real Estate Listings' worksheet.
    Removes duplicates based on Address or Link URL before appending.
    """
    if df.empty:
        return True
    try:
        sheet_name = "Real Estate Listings"
        try:
            wks = spreadsheet.worksheet(sheet_name)
            # Fetch all values to check for duplicates
            existing_rows = wks.get_all_records()
            existing_links = {str(row.get("Link", "")).strip() for row in existing_rows}
            existing_addresses = {str(row.get("Address", "")).strip().lower() for row in existing_rows}
        except gspread.exceptions.WorksheetNotFound:
            # Create sheet if missing
            wks = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols=str(len(df.columns)))
            wks.append_row(list(df.columns))
            existing_links = set()
            existing_addresses = set()
            
        # Filter out rows that are already in sheet
        rows_to_append = []
        for _, row in df.iterrows():
            addr = str(row.get("Address", "")).strip().lower()
            link = str(row.get("Link", "")).strip()
            if link in existing_links or (addr and addr in existing_addresses):
                continue
            # Convert all values to strings and fill NA
            row_clean = row.fillna("").astype(str).tolist()
            rows_to_append.append(row_clean)
            
        if rows_to_append:
            wks.append_rows(rows_to_append, value_input_option="USER_ENTERED")
            st.success(f"✅ Successfully synced {len(rows_to_append)} new listings to Google Sheet!")
        else:
            st.info("ℹ️ All listings are already synced to the Google Sheet (no duplicates added).")
        return True
    except Exception as e:
        st.error(f"❌ Failed to sync property listings: {e}")
        return False
