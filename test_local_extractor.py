import unittest
import os
import pandas as pd
from datetime import datetime
import local_extractor

class TestLocalExtractor(unittest.TestCase):

    def test_bank_detection(self):
        """Test keyword-based bank detection."""
        # Standard fallback bank detection tests
        self.assertEqual(local_extractor.detect_bank("bank_rbc_statement.pdf"), "RBC")
        self.assertEqual(local_extractor.detect_bank("td_statement.pdf"), "TD")
        self.assertEqual(local_extractor.detect_bank("bmo_client.pdf"), "BMO")
        self.assertEqual(local_extractor.detect_bank("cibc_checking.pdf"), "CIBC")
        self.assertEqual(local_extractor.detect_bank("tangerine_savings.pdf"), "Tangerine")
        self.assertEqual(local_extractor.detect_bank("vancity_visa.pdf"), "Vancity")

    def test_statement_year_range(self):
        """Test year context parser."""
        text = "Statement Period: Dec 15, 2024 to Jan 15, 2025"
        start, end = local_extractor.extract_statement_year_range(text)
        self.assertEqual(start, 2024)
        self.assertEqual(end, 2025)

        text_one_year = "Royal Bank Statement for Year 2026"
        start, end = local_extractor.extract_statement_year_range(text_one_year)
        self.assertEqual(start, 2026)
        self.assertEqual(end, 2026)

    def test_date_parsing_and_year_transition(self):
        """Test MM/DD parsing and December-to-January year transitions."""
        # Normal parsing (within same year, e.g. Jan 1 to Dec 31 2025)
        parsed, month = local_extractor.parse_date("Jan 15", 2025, 1, 2025, 12)
        self.assertEqual(parsed, "2025-01-15")
        self.assertEqual(month, 1)

        # December-to-January spanning year transition (Dec 2025 to Jan 2026)
        parsed, month = local_extractor.parse_date("Jan 05", 2025, 12, 2026, 1)
        self.assertEqual(parsed, "2026-01-05")
        self.assertEqual(month, 1)

    def test_reconciliation_math(self):
        """Test reconciliation checking and warning logic."""
        txs = [
            {"debit": 100.0, "credit": None, "balance": 400.0},
            {"debit": None, "credit": 200.0, "balance": 600.0}
        ]
        opening_bal = 500.0
        
        reconcile_result = local_extractor.reconcile_transactions(txs, opening_bal)
        self.assertTrue(reconcile_result["reconciled"])
        self.assertEqual(reconcile_result["difference"], 0.0)

        # Test mismatch / difference warnings
        txs_bad = [
            {"debit": 100.0, "credit": None, "balance": 400.0},
            {"debit": None, "credit": 150.0, "balance": 600.0} # balance says 600, math says 550
        ]
        reconcile_result_bad = local_extractor.reconcile_transactions(txs_bad, opening_bal)
        self.assertFalse(reconcile_result_bad["reconciled"])
        self.assertEqual(reconcile_result_bad["difference"], 50.0)

    def test_apply_category_map(self):
        """Test custom dynamic Excel category mapping applied to DataFrame."""
        # Mock DataFrame
        df = pd.DataFrame([
            {"description": "ESSO GAS STATION", "category": "Uncategorized", "gifi_code": "", "gst_rate": ""},
            {"description": "SUKH AUTO REPAIR", "category": "Uncategorized", "gifi_code": "", "gst_rate": ""}
        ])

        # Mock Excel Mapping DataFrame
        map_df = pd.DataFrame([
            {"keyword": "esso", "category name": "Vehicle Expense", "gifi code": "8810", "gst rate": "5%"},
            {"keyword": "sukh auto", "category name": "Repairs and maintenance", "gifi code": "8960", "gst rate": "12%"}
        ])
        
        # Save temp map excel
        temp_excel_path = "temp_category_map.xlsx"
        map_df.to_excel(temp_excel_path, index=False)
        
        try:
            df_mapped = local_extractor.apply_excel_category_map(df, temp_excel_path)
            self.assertEqual(df_mapped.iloc[0]["category"], "Vehicle Expense")
            self.assertEqual(df_mapped.iloc[0]["gifi_code"], "8810")
            self.assertEqual(df_mapped.iloc[0]["gst_rate"], "5%")
            
            self.assertEqual(df_mapped.iloc[1]["category"], "Repairs and maintenance")
            self.assertEqual(df_mapped.iloc[1]["gifi_code"], "8960")
            self.assertEqual(df_mapped.iloc[1]["gst_rate"], "12%")
        finally:
            if os.path.exists(temp_excel_path):
                os.remove(temp_excel_path)

if __name__ == "__main__":
    unittest.main()
