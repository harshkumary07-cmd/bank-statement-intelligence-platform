# Bank Statement Intelligence Platform

A Python application that converts bank statement PDFs into structured, machine-readable JSON. Built as an internship project demonstrating PDF parsing, data extraction, and web application development with Streamlit.

---

## Project Overview

Banks issue PDF statements that are difficult to process programmatically. This tool extracts every transaction from those PDFs, classifies each as a withdrawal or deposit, normalises dates, and outputs clean JSON — ready for analysis, storage, or further processing.

---

## Features

- Upload any supported bank statement PDF and receive structured JSON output
- Automatic bank detection (HDFC, Axis, PNB, IndusInd)
- Correct withdrawal / deposit classification with per-bank DR/CR handling
- Date normalisation to ISO 8601 (`YYYY-MM-DD`)
- Summary dashboard: transactions, pages processed, total withdrawals, total deposits, closing balance
- One-click JSON download with auto-generated filename
- Raw text view per page for verification and debugging
- 34 automated unit tests covering parsing edge cases

---

## Supported Banks

| Bank | Statement Type | Parser Strategy |
|------|---------------|-----------------|
| HDFC Bank | Savings account (digitally generated) | Coordinate-based — no DR/CR text markers; horizontal x-position of each amount determines column |
| Axis Bank | Current / savings account | Text regex — explicit `DR`/`CR` marker on each line |
| Punjab National Bank (PNB) | Savings account | Table parser — `Amount(INR)` + `Type` (DR/CR) columns |
| IndusInd Bank | Savings account | Text regex — explicit `DR`/`CR` marker on each line |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Web UI | Streamlit |
| PDF extraction | pdfplumber |
| Data manipulation | pandas |
| Language | Python 3.11 |
| Testing | pytest |

---

## Project Architecture

```
bank-statement-platform/
│
├── app.py                          # Streamlit UI, orchestration, bank detection
│
├── parser/
│   ├── __init__.py
│   ├── extractor.py                # PDF reading layer
│   │   ├── extract_pdf()           # → raw text per page
│   │   ├── extract_tables()        # → structured table rows
│   │   └── extract_words_by_page() # → word-level coordinates (HDFC only)
│   │
│   ├── transaction_parser.py       # Parsing engine
│   │   ├── parse_from_tables()     # PNB table-based path
│   │   ├── parse_from_hdfc_words() # HDFC coordinate-based path
│   │   ├── parse_from_text()       # Axis / IndusInd text path
│   │   └── parse_transactions()    # Master entry point
│   │
│   └── utils.py                    # Shared helpers
│       ├── normalize_date()        # Any date format → YYYY-MM-DD
│       ├── parse_amount()          # String → float
│       └── parse_amount_or_null()  # 0.00 treated as null (empty column)
│
├── tests/
│   ├── test_utils.py               # Date/amount utility tests
│   └── test_parser_fixes.py        # DR/CR classification tests
│
├── requirements.txt
├── runtime.txt                     # Python 3.11 for Streamlit Cloud
└── README.md
```

---

## How It Works

### Parsing Strategy

Three distinct strategies are selected automatically per bank:

**1. Coordinate-based (HDFC)**
HDFC PDFs have no `DR`/`CR` text on each row. The only reliable way to distinguish withdrawals from deposits is the horizontal position (`x0` coordinate) of each amount word on the page. Column boundaries were measured from actual HDFC PDFs:
- Withdrawal column: `x0` 395–455
- Deposit column: `x0` 458–535
- Balance column: `x0` ≥ 548

**2. Table-based (PNB)**
PNB statements produce well-structured tables with a dedicated `Type` column (`DR`/`CR`) and a single `Amount(INR)` column. The parser maps these columns and assigns amounts accordingly.

**3. Text-based (Axis, IndusInd, fallback)**
Statements where raw extracted text includes `DR` or `CR` on each transaction line. A regex parser extracts amounts and classifies them using the marker.

The master function `parse_transactions()` runs all applicable strategies and returns the result with the highest transaction count.

---

## Installation

**Requirements:** Python 3.11+

```bash
git clone https://github.com/YOUR_USERNAME/bank-statement-platform.git
cd bank-statement-platform

pip install -r requirements.txt
```

---

## Running Locally

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

### Running Tests

```bash
python -m pytest tests/ -v
```

All 34 tests should pass.

---

## Example Workflow

1. Upload a bank statement PDF (e.g. HDFC savings account)
2. Platform detects the bank automatically
3. Transactions are extracted and displayed in a table
4. Summary dashboard shows total withdrawals, deposits and closing balance
5. Switch to the JSON tab to review or download the structured output
6. Use the Raw Extraction tab to verify what pdfplumber read from each page

---

## JSON Output Format

```json
{
  "bank_details": {
    "bank_name": "HDFC Bank",
    "source_file": "statement.pdf",
    "extracted_at": "2025-01-15 14:30:00",
    "total_pages": 12,
    "total_transactions": 243,
    "total_withdrawals": 185420.50,
    "total_deposits": 210000.00,
    "closing_balance": 15173.25,
    "extraction_method": "automated",
    "verification_status": "manual verification recommended"
  },
  "transactions": [
    {
      "transaction_date": "2025-04-01",
      "particulars": "UPI-MERCHANT-REF@BANK-IFSC",
      "reference_number": "509146900613",
      "withdrawal": null,
      "deposit": 500.00,
      "balance": 515.20
    }
  ]
}
```

---

## Future Improvements

- OCR support for scanned PDFs (Tesseract integration)
- Additional banks: SBI, Kotak, ICICI, Bank of Baroda
- CSV and Excel export in addition to JSON
- Statement period auto-detection and date range filtering
- Multi-file batch processing
- Account summary: net cash flow, monthly breakdown

---

## Known Limitations

- Scanned or image-based PDFs are not supported (no OCR layer)
- Password-protected PDFs cannot be processed
- HDFC column boundaries are measured from a specific statement version; layout changes across statement versions may require adjusting constants in `transaction_parser.py`
- PNB amounts use one decimal place (`600.0`) rather than two — handled by the parser but worth noting if comparing raw values
- The Axis Bank balance column is prefixed with `-\n` in table output; this is stripped automatically

---

*Internship Project · 2024–2025*
