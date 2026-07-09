import os
import pandas as pd
from openpyxl import load_workbook

def save_to_excel(data, sheet_name, file_path="output/results.xlsx"):
    """
    Saves a list of dictionaries (data) to a specific sheet in results.xlsx.
    Creates the directory and file if they do not exist.
    If the file exists, it updates or creates the specified sheet while keeping other sheets intact.
    """
    if not data:
        print(f"No data to save for sheet '{sheet_name}'.")
        return

    # Ensure output directory exists
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    # Convert data list of dicts to DataFrame
    df = pd.DataFrame(data)

    # If file doesn't exist, write fresh Excel file
    if not os.path.exists(file_path):
        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
        print(f"Created new Excel file at {file_path} and saved sheet '{sheet_name}'.")
    else:
        # Load existing workbook and write/update sheet
        try:
            # We use openpyxl engine with ExcelWriter in append mode
            with pd.ExcelWriter(file_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"Updated sheet '{sheet_name}' in existing Excel file {file_path}.")
        except Exception as e:
            # Fallback if append mode fails or is unsupported in some versions of openpyxl/pandas
            print(f"Error appending sheet to Excel: {e}. Attempting full rewrite fallback.")
            try:
                # Read all sheets, update/add the current one, and write back
                sheets = {}
                xls = pd.ExcelFile(file_path)
                for s_name in xls.sheet_names:
                    if s_name != sheet_name:
                        sheets[s_name] = pd.read_excel(file_path, sheet_name=s_name)
                sheets[sheet_name] = df
                
                with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
                    for s_name, s_df in sheets.items():
                        s_df.to_excel(writer, sheet_name=s_name, index=False)
                print(f"Successfully wrote Excel file with fallback method.")
            except Exception as ex:
                print(f"Failed to save Excel file: {ex}")
                raise ex
