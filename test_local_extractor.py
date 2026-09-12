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
        self.assertEqual(local_extractor.detect_bank("VCTY_91358035_20260721.pdf"), "Vancity")
        
        # Test filename fallback for VCTY abbreviation
        self.assertEqual(local_extractor.detect_bank("vcty_checking.pdf"), "Vancity")

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
        
        # BMO dot date and double date parsing
        parsed, month = local_extractor.parse_date("Jun. 26 Jun. 29", 2026, 6, 2026, 7)
        self.assertEqual(parsed, "2026-06-26")
        self.assertEqual(month, 6)

        # Some BMO digital statements encode the date as one token.
        parsed, month = local_extractor.parse_date("Jan02", 2025, 1, 2025, 1)
        self.assertEqual(parsed, "2025-01-02")
        self.assertEqual(month, 1)
        self.assertTrue(local_extractor.looks_like_date_word("Jan02"))

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

    def test_bmo_digital_parsing(self):
        """Test BMO digital statement parsing and reconciliation."""
        import extract_statement
        page1 = """Business Banking statement
For the period ending January 31, 2025
Summary of account
Account balance ($) debited ($) credited ($) Jan 31, 2025
Business Account # 0789 1984-032 167.10 1,207.77 1,171.51 130.84
Transaction details
Date Description Amounts debited from your account ($) Amounts credited to your account ($) Balance ($)
Jan 01 Opening balance 167.10
Jan 02 INTERAC e-Transfer Received 100.00 267.10
Jan 03 INTERAC e-Transfer Received 472.51 739.61
Jan 08 Cheque Processed By Branch 650.00 89.61
Jan 08 INTERAC e-Transfer Received 400.00 489.61
Jan 09 Debit Card Purchase, UNIWAY COMPUTER 274.40 215.21
Jan 20 INTERAC e-Transfer Sent 10.00 205.21
Jan 20 ABM Withdrawal, 7488 KING GEOR 200.00 5.21
Jan 20 Direct Deposit, INTUIT CANADA P AP /CC 84.00 89.21
Jan 20 Pre-Authorized Payment, INTUIT CANADA U AP /CC 2.69 86.52
Jan 23 Pre-Authorized Payment No Fee, BMO PAYMENT BPY/FAC 36.00 50.52"""

        page2 = """Transaction details (continued)
Date Description Amounts debited from your account ($) Amounts credited to your account ($) Balance ($)
Jan 23 Debit Card Purchase, NEWTN WAVE POOL 7.50 43.02
Jan 27 Debit Card Purchase, REAL CDN SUPERS 23.68 19.34
Jan 28 INTERAC e-Transfer Received 115.00 134.34
Jan 31 Transaction Fee, EXCESS ITEMS 01 AT $3.50 3.50 130.84
Jan 31 Closing totals 1,207.77 1,171.51"""

        txs = extract_statement.parse_digital_text([page1, page2])
        self.assertEqual(len(txs), 14)
        
        # Check first and last transaction
        self.assertEqual(txs[0]["date"], "2025-01-02")
        self.assertEqual(txs[0]["credit"], 100.0)
        self.assertEqual(txs[0]["balance"], 267.10)
        
        self.assertEqual(txs[-1]["date"], "2025-01-31")
        self.assertEqual(txs[-1]["debit"], 3.50)
        self.assertEqual(txs[-1]["balance"], 130.84)
        
        # Validate reconciliation
        reconciliation = local_extractor.reconcile_transactions(txs, 167.10)
        self.assertTrue(reconciliation["reconciled"])
        self.assertEqual(reconciliation["closing_balance"], 130.84)
        self.assertEqual(round(reconciliation["total_withdrawals"], 2), 1207.77)
        self.assertEqual(round(reconciliation["total_deposits"], 2), 1171.51)

    def test_bmo_footer_and_item_counts_exclusion(self):
        """Test that BMO footer item counts (spaced and unspaced) are excluded and genuine fees are preserved."""
        import extract_statement
        
        # Statement snippet with 5 false footer lines (spaced, unspaced, wrapped) + genuine fees and repeated charges
        statement_text = """Business Banking statement
For the period ending May 31, 2025
Summary of account
Account balance ($) debited ($) credited ($) May 31, 2025
Business Account # 0789 1984-032 1,462.78 10,500.72 10,518.50 1,480.56
Transaction details
Date Description Amounts debited from your account ($) Amounts credited to your account ($) Balance ($)
May 01 Opening balance 1,462.78
May 05 Direct Deposit, CLIENT PAYMENT 10,518.50 11,981.28
May 15 Cheque Processed By Branch 10,490.72 1,490.56
May 30 Monthly Account Fee 5.00 1,485.56
May 30 Transaction Fee, EXCESS ITEMS 01 AT $3.50 3.50 1,482.06
May 30 PARKING METER 1.50 1,480.56
May 30 Number of cheques or related items enclosed in your statement 1
May 31 Closing totals 10,500.72 10,518.50"""

        txs = extract_statement.parse_digital_text([statement_text])
        
        # Verify that the false footer transaction was completely excluded
        descriptions = [t["description"] for t in txs]
        self.assertNotIn("Number of cheques or related items enclosed in your statement", descriptions)
        self.assertNotIn("Numberofchequesorrelateditemsenclosedinyourstatement", descriptions)
        
        # Verify genuine bank fees and legitimate transactions are preserved
        self.assertIn("Monthly Account Fee", descriptions)
        self.assertIn("Transaction Fee, EXCESS ITEMS 01 AT $3.50", descriptions)
        self.assertIn("PARKING METER", descriptions)
        
        # Test unspaced metadata detector directly
        self.assertTrue(local_extractor.is_disclaimer_or_metadata("Number of cheques or related items enclosed in your statement"))
        self.assertTrue(local_extractor.is_disclaimer_or_metadata("Numberofchequesorrelateditemsenclosedinyourstatement"))
        self.assertTrue(local_extractor.is_disclaimer_or_metadata("Number of items processed"))
        self.assertTrue(local_extractor.is_disclaimer_or_metadata("Trade-marks of Bank of Montreal"))
        self.assertFalse(local_extractor.is_disclaimer_or_metadata("Monthly Account Fee"))
        self.assertFalse(local_extractor.is_disclaimer_or_metadata("Transaction Fee, EXCESS ITEMS 01 AT $3.50"))

    def test_same_date_transaction_ordering(self):
        """Test that same-date transactions preserve exact statement sequence."""
        raw_txs = [
            {"date": "2025-06-30", "description": "TX 1 - MORNING PURCHASE", "debit": 50.0, "credit": None, "balance": 950.0, "statement_order": 0, "page_num": 1, "row_idx": 1},
            {"date": "2025-06-30", "description": "TX 2 - LUNCH PAYMENT", "debit": 25.0, "credit": None, "balance": 925.0, "statement_order": 1, "page_num": 1, "row_idx": 2},
            {"date": "2025-06-30", "description": "TX 3 - AFTERNOON REFUND", "debit": None, "credit": 100.0, "balance": 1025.0, "statement_order": 2, "page_num": 1, "row_idx": 3},
            {"date": "2025-06-30", "description": "TX 4 - EVENING TRANSFER", "debit": 30.0, "credit": None, "balance": 995.0, "statement_order": 3, "page_num": 1, "row_idx": 4},
        ]
        
        df = pd.DataFrame(raw_txs)
        df['date_dt'] = pd.to_datetime(df['date'])
        
        sort_cols = ['date_dt']
        if 'statement_order' in df.columns:
            sort_cols.append('statement_order')
        df_sorted = df.sort_values(by=sort_cols, kind='stable').reset_index(drop=True)
        
        self.assertEqual(df_sorted.iloc[0]["description"], "TX 1 - MORNING PURCHASE")
        self.assertEqual(df_sorted.iloc[1]["description"], "TX 2 - LUNCH PAYMENT")
        self.assertEqual(df_sorted.iloc[2]["description"], "TX 3 - AFTERNOON REFUND")
        self.assertEqual(df_sorted.iloc[3]["description"], "TX 4 - EVENING TRANSFER")

    def test_validation_may_and_june_reconciliation(self):
        """
        Validate exact figures from user prompt:
        May: $1,462.78 + $10,518.50 - $10,500.72 = $1,480.56
        June: $1,480.56 + $10,995.24 - $12,229.34 = $246.46
        """
        # May validation
        may_txs = [
            {"date": "2025-05-05", "description": "CLIENT DEPOSIT", "debit": None, "credit": 10518.50, "balance": 11981.28},
            {"date": "2025-05-20", "description": "SUPPLIER PAYMENT", "debit": 10500.72, "credit": None, "balance": 1480.56},
        ]
        may_rec = local_extractor.reconcile_transactions(may_txs, 1462.78)
        self.assertTrue(may_rec["reconciled"])
        self.assertEqual(may_rec["opening_balance"], 1462.78)
        self.assertEqual(may_rec["total_deposits"], 10518.50)
        self.assertEqual(may_rec["total_withdrawals"], 10500.72)
        self.assertEqual(may_rec["closing_balance"], 1480.56)
        self.assertEqual(may_rec["difference"], 0.0)
        self.assertEqual(len(may_rec["running_discrepancies"]), 0)

        # June validation
        june_txs = [
            {"date": "2025-06-10", "description": "INVOICE REVENUE", "debit": None, "credit": 10995.24, "balance": 12475.80},
            {"date": "2025-06-25", "description": "OPERATING EXPENSES", "debit": 12229.34, "credit": None, "balance": 246.46},
        ]
        june_rec = local_extractor.reconcile_transactions(june_txs, 1480.56)
        self.assertTrue(june_rec["reconciled"])
        self.assertEqual(june_rec["opening_balance"], 1480.56)
        self.assertEqual(june_rec["total_deposits"], 10995.24)
        self.assertEqual(june_rec["total_withdrawals"], 12229.34)
        self.assertEqual(june_rec["closing_balance"], 246.46)
        self.assertEqual(june_rec["difference"], 0.0)
        self.assertEqual(len(june_rec["running_discrepancies"]), 0)

    def test_all_ten_bmo_months_opening_and_reconciliation(self):
        """Test reconciliation across all 10 statements with correct opening balances."""
        months_data = [
            ("03 31 2025", 49.27, 1012.58, 1061.85),
            ("04 30 2025", 1061.85, 400.93, 1462.78),
            ("05 30 2025", 1462.78, 17.78, 1480.56),
            ("06 30 2025", 1480.56, -1234.10, 246.46),
            ("07 31 2025", 246.46, -113.72, 132.74),
            ("08 29 2025", 132.74, -21.79, 110.95),
            ("09 29 2025", 110.95, -46.68, 64.27),
            ("10 31 2025", 64.27, -25.38, 38.89),
            ("11 28 2025", 38.89, -36.48, 2.41),
            ("12 31 2025", 2.41, 49.85, 52.26)
        ]
        for name, expected_op, net_flow, expected_cl in months_data:
            txs = []
            if net_flow >= 0:
                txs.append({"date": "2025-01-15", "description": "NET INFLOW", "debit": None, "credit": net_flow, "balance": expected_cl})
            else:
                txs.append({"date": "2025-01-15", "description": "NET OUTFLOW", "debit": abs(net_flow), "credit": None, "balance": expected_cl})
            
            rec = local_extractor.reconcile_transactions(txs, expected_op)
            self.assertTrue(rec["reconciled"], f"Failed for {name}")
            self.assertEqual(rec["opening_balance"], expected_op)
            self.assertEqual(rec["closing_balance"], expected_cl)
            self.assertEqual(rec["difference"], 0.0)

if __name__ == "__main__":
    unittest.main()
