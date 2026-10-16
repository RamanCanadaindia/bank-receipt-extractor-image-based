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

    def test_bmo_mastercard_extraction_and_reconciliation(self):
        """Test BMO MasterCard extraction, dates (spanning 2024 to 2025), and reconciliation."""
        import os
        uploaded_pdf = 'C:/Users/admin/.gemini/antigravity-ide/brain/2e063a42-16af-43e5-9710-ecd067f4343e/.user_uploaded/media_1789244866204.pdf'
        if os.path.exists(uploaded_pdf):
            txs, opening_bal = local_extractor.extract_digital_pdf(uploaded_pdf, 'BMO')
            self.assertEqual(len(txs), 28)
            self.assertEqual(opening_bal, 1539.97)
            self.assertEqual(txs[0]["date"], "2024-12-28")
            self.assertEqual(txs[1]["date"], "2025-01-01")
            self.assertEqual(txs[-1]["date"], "2025-01-28")
            
            recon = local_extractor.reconcile_transactions(txs, opening_bal)
            self.assertTrue(recon["reconciled"])
            self.assertEqual(recon["opening_balance"], 1539.97)
            self.assertEqual(recon["closing_balance"], 2323.51)
            self.assertEqual(recon["total_deposits"], 536.00)
            self.assertEqual(recon["total_withdrawals"], 1319.54)
            self.assertEqual(recon["difference"], 0.0)

    def test_all_twelve_bmo_mastercard_statements_reconcile(self):
        """Test that all 12 BMO Mastercard statements (01/2025 to 12/2025) extract and reconcile with 0.0 diff."""
        import os
        folder = 'H:/My Drive/Tax Return/RAMAN TAX & ACCOUNTING INC/2025/2025 Bank Statements/Master card'
        if os.path.exists(folder):
            for fname in sorted(os.listdir(folder)):
                if fname.endswith('.pdf'):
                    pdf_path = os.path.join(folder, fname)
                    txs, opening_bal = local_extractor.extract_digital_pdf(pdf_path, 'BMO')
                    recon = local_extractor.reconcile_transactions(txs, opening_bal)
                    self.assertTrue(recon["reconciled"], f"Failed reconciliation for {fname}: Diff={recon['difference']}")
                    self.assertAlmostEqual(recon["difference"], 0.0, places=2, msg=f"Non-zero diff for {fname}")

    def test_scotiabank_detection_and_date_parsing(self):
        """Test Scotiabank bank detection and MM/DD/YYYY date parsing."""
        self.assertEqual(local_extractor.detect_bank("scotiabank_business_statement.pdf"), "Scotiabank")
        self.assertEqual(local_extractor.detect_bank("scotia_chequing.pdf"), "Scotiabank")
        
        # Test full slash dates with 4-digit years
        parsed, m = local_extractor.parse_date("02/27/2026", 2026, 2, 2026, 3)
        self.assertEqual(parsed, "2026-02-27")
        self.assertEqual(m, 2)
        
        parsed, m = local_extractor.parse_date("03/03/2026", 2026, 2, 2026, 3)
        self.assertEqual(parsed, "2026-03-03")
        self.assertEqual(m, 3)

        parsed, m = local_extractor.parse_date("03/31/2026", 2026, 2, 2026, 3)
        self.assertEqual(parsed, "2026-03-31")
        self.assertEqual(m, 3)

    def test_scotiabank_digital_parsing_and_reconciliation(self):
        """Test Scotiabank digital text extraction and math reconciliation."""
        import extract_statement
        page1 = """Scotiabank
Statement Of: Business Account Account Number: 51060 02040 13 From: Feb 27 2026 To: Mar 31 2026
Account Summary for this Period:
No. of Debits Total Amount - Debits No. of Credits Total Amount - Credits
1 $10.00 8 $5,764.22
Account Details:
Date Description Withdrawals/Debits ($) Deposits/Credits ($) Balance ($)
02/27/2026 BALANCE FORWARD 886.50
03/03/2026 CREDIT MEMO SERVICE FEE REVERSAL 79.00 965.50
03/03/2026 CREDIT MEMO 03285816 FREE INTERAC E-TRANSFER 1050.00 2,015.50
03/10/2026 CREDIT MEMO 19595762 FREE INTERAC E-TRANSFER 840.00 2,855.50
03/12/2026 CREDIT MEMO 25528592 FREE INTERAC E-TRANSFER 1155.00 4,010.50
03/16/2026 CREDIT MEMO 34136459 FREE INTERAC E-TRANSFER 1550.22 5,560.72
03/25/2026 CREDIT MEMO 56306916 FREE INTERAC E-TRANSFER 600.00 6,160.72
03/30/2026 CREDIT MEMO 66617157 FREE INTERAC E-TRANSFER 375.00 6,535.72
03/30/2026 CREDIT MEMO 68114862 FREE INTERAC E-TRANSFER 115.00 6,650.72
03/31/2026 SERVICE CHARGE 10.00 6,640.72
No. of Debits Total Amount - Debits No. of Credits Total Amount - Credits
1 $10.00 8 $5,764.22
Uncollected fees and/or ODI owing: $0.00
Please examine this statement promptly.
"""
        txs = extract_statement.parse_digital_text([page1])
        self.assertEqual(len(txs), 9)
        
        # Verify first and last transaction
        self.assertEqual(txs[0]["date"], "2026-03-03")
        self.assertEqual(txs[0]["credit"], 79.00)
        self.assertEqual(txs[-1]["date"], "2026-03-31")
        self.assertEqual(txs[-1]["debit"], 10.00)
        
        # Verify reconciliation against opening balance $886.50
        opening_bal = 886.50
        recon = local_extractor.reconcile_transactions(txs, opening_bal)
        self.assertTrue(recon["reconciled"])
        self.assertEqual(recon["opening_balance"], 886.50)
        self.assertEqual(recon["total_deposits"], 5764.22)
        self.assertEqual(recon["total_withdrawals"], 10.00)
        self.assertEqual(recon["closing_balance"], 6640.72)
        self.assertEqual(recon["difference"], 0.0)

    def test_scotiabank_february_multiline_statement(self):
        """Test Scotiabank statement where transaction description and amounts span multiple lines."""
        import extract_statement
        page1 = """12040 NORDEL WAY 51060
SURREY BC V3W 1P6
501-7525
1 of 2
CLEAR EDGE GLASS AND SHOWER DO
12470 80 AVE
SURREY BC V3W3A5
Statement Of: Account Number: From: To:
Business Account 51060 02040 13 Feb 03 2026 Feb 27 2026
Account Summary for this Period:
No. of Debits Total Amount - Debits No. of Credits Total Amount - Credits
1 $7.25 2 $893.75
Account Details:
Date Description Withdrawals/Debits ($) Deposits/Credits ($) Balance ($)
02/03/2026 BALANCE FORWARD 0.00
02/03/2026 DEPOSIT 500.00 500.00
02/24/2026 CREDIT MEMO
 83544783
 FREE INTERAC E-TRANSFER
393.75 893.75
02/27/2026 SERVICE CHARGE 7.25 886.50
No. of Debits Total Amount - Debits No. of Credits Total Amount - Credits
1 $7.25 2 $893.75
Uncollected fees and/or ODI owing: $0.00
Please examine this statement promptly.
"""
        page2 = """Statement Of: Service Charge 51060 02040 13 Feb 03 2026 Feb 27 2026
Item Volume Rate Charge ($)
Transaction Fees Tier 1 2 1.25 2.50
Total Service Charges $7.25
"""
        txs = extract_statement.parse_digital_text([page1, page2])
        self.assertEqual(len(txs), 3)

        self.assertEqual(txs[0]["date"], "2026-02-03")
        self.assertEqual(txs[0]["credit"], 500.00)
        self.assertEqual(txs[0]["balance"], 500.00)

        self.assertEqual(txs[1]["date"], "2026-02-24")
        self.assertEqual(txs[1]["description"], "CREDIT MEMO 83544783 FREE INTERAC E-TRANSFER")
        self.assertEqual(txs[1]["credit"], 393.75)
        self.assertEqual(txs[1]["balance"], 893.75)

        self.assertEqual(txs[2]["date"], "2026-02-27")
        self.assertEqual(txs[2]["debit"], 7.25)
        self.assertEqual(txs[2]["balance"], 886.50)

        # Reconcile against opening balance 0.00
        recon = local_extractor.reconcile_transactions(txs, 0.00)
        self.assertTrue(recon["reconciled"])
        self.assertEqual(recon["opening_balance"], 0.00)
        self.assertEqual(recon["total_deposits"], 893.75)
        self.assertEqual(recon["total_withdrawals"], 7.25)
        self.assertEqual(recon["closing_balance"], 886.50)

    def test_local_extractor_multiline_raw_rows(self):
        """Test local_extractor raw_rows step 3 multiline merging and amount resolution."""
        raw_rows = [
            {"page_num": 1, "row_idx": 0, "statement_order": 0, "date_raw": "02/03/2026", "description": "BALANCE FORWARD", "debit_raw": "", "credit_raw": "", "balance_raw": "0.00"},
            {"page_num": 1, "row_idx": 1, "statement_order": 1, "date_raw": "02/03/2026", "description": "DEPOSIT", "debit_raw": "", "credit_raw": "500.00", "balance_raw": "500.00"},
            {"page_num": 1, "row_idx": 2, "statement_order": 2, "date_raw": "02/24/2026", "description": "CREDIT MEMO", "debit_raw": "", "credit_raw": "", "balance_raw": ""},
            {"page_num": 1, "row_idx": 3, "statement_order": 3, "date_raw": "", "description": "83544783", "debit_raw": "", "credit_raw": "", "balance_raw": ""},
            {"page_num": 1, "row_idx": 4, "statement_order": 4, "date_raw": "", "description": "FREE INTERAC E-TRANSFER", "debit_raw": "", "credit_raw": "", "balance_raw": ""},
            {"page_num": 1, "row_idx": 5, "statement_order": 5, "date_raw": "", "description": "", "debit_raw": "", "credit_raw": "393.75", "balance_raw": "893.75"},
            {"page_num": 1, "row_idx": 6, "statement_order": 6, "date_raw": "02/27/2026", "description": "SERVICE CHARGE", "debit_raw": "7.25", "credit_raw": "", "balance_raw": "886.50"},
        ]
        
        start_year, start_month, end_year, end_month = 2026, 2, 2026, 2
        is_credit_card = False
        transactions = []
        prev_date = None

        for r in raw_rows:
            date_raw = r["date_raw"]
            desc = r["description"]
            debit_raw = r["debit_raw"]
            credit_raw = r["credit_raw"]
            balance_raw = r["balance_raw"]
            
            desc_lower = desc.lower().strip()
            if "balance forward" in desc_lower:
                continue

            if not date_raw and not debit_raw and not credit_raw and not balance_raw:
                if transactions and desc and transactions[-1].get("page_num") == r["page_num"]:
                    transactions[-1]["description"] += " " + desc
                continue

            deb_clean = debit_raw.replace("$", "").replace(",", "").strip() if debit_raw else ""
            cred_clean = credit_raw.replace("$", "").replace(",", "").strip() if credit_raw else ""
            bal_clean = balance_raw.replace("$", "").replace(",", "").strip() if balance_raw else ""

            temp_debit = float(deb_clean) if deb_clean else None
            temp_credit = float(cred_clean) if cred_clean else None
            temp_balance = float(bal_clean) if bal_clean else None

            if not date_raw and (temp_debit is not None or temp_credit is not None or temp_balance is not None):
                if transactions and transactions[-1]["debit"] is None and transactions[-1]["credit"] is None and transactions[-1]["balance"] is None and transactions[-1].get("page_num") == r["page_num"]:
                    if desc:
                        transactions[-1]["description"] += " " + desc
                    transactions[-1]["debit"] = temp_debit
                    transactions[-1]["credit"] = temp_credit
                    transactions[-1]["balance"] = temp_balance
                    continue

            date_parsed = None
            if date_raw:
                date_parsed, month_num = local_extractor.parse_date(date_raw, start_year, start_month, end_year, end_month)
                if date_parsed:
                    prev_date = date_parsed
            else:
                if transactions and transactions[-1].get("page_num") == r.get("page_num"):
                    date_parsed = prev_date

            desc_cleaned = desc.strip()
            if date_parsed and desc_cleaned:
                transactions.append({
                    "date": date_parsed,
                    "description": desc_cleaned,
                    "debit": temp_debit,
                    "credit": temp_credit,
                    "balance": temp_balance,
                    "page_num": r.get("page_num", 1)
                })

        final_txs = [tx for tx in transactions if (tx["debit"] is not None or tx["credit"] is not None or tx["balance"] is not None)]
        self.assertEqual(len(final_txs), 3)
        self.assertEqual(final_txs[1]["description"], "CREDIT MEMO 83544783 FREE INTERAC E-TRANSFER")
        self.assertEqual(final_txs[1]["credit"], 393.75)
        self.assertEqual(final_txs[1]["balance"], 893.75)

    def test_scotiabank_visa_statement(self):
        """Test Scotiabank Momentum for business VISA card statement extraction."""
        import extract_statement
        page1 = """Scotia Momentum®
for business VISA* card
Statement Period Feb 3, 2026 - Feb 21, 2026
Statement Date Feb 21, 2026
Account # 4537 XXXX XXXX 5601
Previous balance, Feb 3/26 $0.00
Payments/credits - $0.00
Purchases/charges + $108.00
Account Balance‡‡ = $108.00 
Transactions since your last statement
REF.# TRANS. DATE POST DATE DETAILS AMOUNT($)
JUGRAJ SINGH JUGRAJSINGH - 4537 XXXX XXXX 5601 
001 Feb 21 Feb 21 ANNUAL FEE 79.00
002 Feb 21 Feb 21 ADDITIONAL CARD FEE 29.00
SUB-TOTAL CREDITS - 4537 XXXX XXXX 5601 $0.00
SUB-TOTAL DEBITS - 4537 XXXX XXXX 5601 $108.00
Interest charges posted on statement date
Cash advances/cheques $0.00
"""
        page2 = """INFORMATION ABOUT YOUR SCOTIABANK STATEMENT
1. PAYMENTS: The TOTAL MINIMUM PAYMENT on this statement includes your current minimum payment
"""
        page3 = """Special offers summary during this statement period
DESCRIPTION INTEREST CHARGED ENDING BALANCE PROMOTION EXPIRY
2.99% 6 MONS CA FEE $0.00 $0.00 Sep 2026
"""
        page4 = """Please do not write in this space
"""
        txs = extract_statement.parse_digital_text([page1, page2, page3, page4])
        self.assertEqual(len(txs), 2)
        self.assertEqual(txs[0]["date"], "2026-02-21")
        self.assertEqual(txs[0]["description"], "ANNUAL FEE")
        self.assertEqual(txs[0]["debit"], 79.00)
        self.assertEqual(txs[1]["date"], "2026-02-21")
        self.assertEqual(txs[1]["description"], "ADDITIONAL CARD FEE")
        self.assertEqual(txs[1]["debit"], 29.00)

        # Validate total charges
        total_charges = sum(t["debit"] for t in txs)
        self.assertEqual(total_charges, 108.00)

if __name__ == "__main__":
    unittest.main()


