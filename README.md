# Bank Statement Extractor

A robust tool designed to extract bank statement transaction histories (specifically formatted for TD Bank and similar layouts) directly into structured CSV files. 

It provides:
1. **Command-Line Interface (CLI)**: For quick file conversions.
2. **Interactive Streamlit Web App**: For a graphical, web-based dashboard featuring file uploads, verification stats, transaction tables, and account visual analytics (monthly flows and balance trends).

---

## Features
*   **Digital PDFs**: Automatically extracts text using PDF layout parsing. It's fast, completely free, and doesn't require cloud services.
*   **Scanned PDFs / Images**: Converts PDF pages into images and runs OCR via the Gemini API, returning structured JSON directly.
*   **Double-Entry Math Verification**: Validates the extracted transaction history by sorting them chronologically and ensuring that `previous_balance - debit + credit = current_balance` for every single entry, auto-correcting debit/credit swaps and flagging errors.

---

## Installation

### 1. Prerequisites
You need Python 3 installed. Install the required libraries:

```bash
pip install pypdfium2 pillow pypdf pdfplumber streamlit pandas matplotlib seaborn
```

- `pypdfium2`: Fast, zero-dependency PDF rendering to convert scanned PDF pages into images.
- `pillow`: For image handling.
- `pypdf` & `pdfplumber`: For digital PDF text extraction.
- `streamlit`, `pandas`, `matplotlib`, `seaborn`: For the web application and interactive visual analytics.

### 2. Get a Gemini API Key
To parse scanned PDFs, you'll need a free or paid Gemini API key:
1. Get a key from the [Google AI Studio](https://aistudio.google.com/).
2. Set it as an environment variable (optional, as you can also input it directly in the web app sidebar):
   - **Windows (cmd)**: `set GEMINI_API_KEY=your_api_key_here`
   - **Windows (PowerShell)**: `$env:GEMINI_API_KEY="your_api_key_here"`
   - **Linux/macOS**: `export GEMINI_API_KEY="your_api_key_here"`

---

## How to Run

### 1. Bank Statement Extractor

#### Method A: Streamlit Web Dashboard (Easiest & Visual)
To launch the interactive dashboard in your browser:

```bash
python -m streamlit run app.py
```
*(If your terminal policies block direct streamlit execution, use the `python -m` prefix as shown above).*

#### Method B: Command-Line Interface (CLI)
To run directly from your terminal:

```bash
python extract_statement.py path/to/your/statement.pdf
```

#### CLI Options:
*   `-o`, `--output`: Specify the output CSV filename (default: `extracted_transactions.csv`).
*   `--api-key`: Pass the Gemini API Key directly in the command.
*   `--model`: Select the Gemini model (default: `gemini-2.5-flash`).
*   `--force-ocr`: Force OCR mode using Gemini, even if the PDF contains extractable digital text.

---

### 2. Receipt Expense Extractor (Wave Replacer)

To launch the interactive receipt scanning dashboard:

```bash
python -m streamlit run receipt_app.py
```

This dashboard lets you:
*   Upload photos or PDF receipts (PNG, JPG, PDF).
*   Extract merchant, date, items, tax, and total instantly via Gemini.
*   Edit/verify the parsed results and click **Add to Expense Log**.
*   Download a consolidated, Wave-compatible CSV of all processed receipts.

---

## Verification Logic
Once the transactions are extracted, the tool automatically verifies that the math flows correctly:
1. It sorts the transactions chronologically.
2. It tracks the running balance.
3. If a transaction's balance doesn't match `previous_balance - debit + credit`:
   - It checks if swapping the debit and credit amount fixes the math. If so, it **auto-corrects** the swap (a common OCR issue).
   - If the error remains, it flags the row with a warning so you can inspect it manually.

