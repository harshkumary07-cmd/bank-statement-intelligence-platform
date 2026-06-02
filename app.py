"""
app.py
------
Bank Statement Intelligence Platform
Entry point for the Streamlit application.

Run with:
    streamlit run app.py
"""

import json
import tempfile
import re
from pathlib import Path
from datetime import datetime

import streamlit as st

from parser.extractor import extract_pdf, extract_tables, extract_words_by_page
from parser.transaction_parser import parse_transactions

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Bank Statement Intelligence Platform",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  .stApp { background-color: #0f1117; color: #e2e8f0; }

  #MainMenu, footer, header { visibility: hidden; }

  .main .block-container {
    padding: 2rem 3rem;
    max-width: 1100px;
  }

  /* Header area */
  .app-header {
    padding-bottom: 1.5rem;
    border-bottom: 1px solid #1e293b;
    margin-bottom: 1.75rem;
  }
  .app-title {
    margin: 0 0 4px 0;
    font-size: 1.5rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #f1f5f9;
  }
  .app-subtitle {
    margin: 0;
    font-size: 0.85rem;
    color: #64748b;
    line-height: 1.5;
  }

  /* Bank detection badge */
  .bank-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(59,130,246,0.1);
    border: 1px solid rgba(59,130,246,0.25);
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 0.78rem;
    font-weight: 600;
    color: #93c5fd;
    margin-top: 0.75rem;
    letter-spacing: 0.01em;
  }
  .bank-badge .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #3b82f6;
  }

  /* Metric cards */
  .metric-row {
    display: flex;
    gap: 12px;
    margin: 1.25rem 0;
    flex-wrap: wrap;
  }
  .metric-card {
    flex: 1;
    min-width: 130px;
    background: #111827;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 14px 16px;
  }
  .metric-label {
    font-size: 0.68rem;
    color: #475569;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    margin-bottom: 6px;
  }
  .metric-value {
    font-size: 1.35rem;
    font-weight: 700;
    color: #e2e8f0;
    font-family: 'JetBrains Mono', monospace;
    line-height: 1;
  }
  .metric-value.green { color: #34d399; }
  .metric-value.red   { color: #f87171; }
  .metric-value.blue  { color: #60a5fa; }

  /* Verification notice */
  .verify-notice {
    background: rgba(245,158,11,0.06);
    border: 1px solid rgba(245,158,11,0.2);
    border-left: 3px solid #f59e0b;
    border-radius: 6px;
    padding: 10px 14px;
    font-size: 0.8rem;
    color: #fbbf24;
    margin: 1rem 0;
    line-height: 1.5;
  }

  /* Download section */
  .download-section {
    background: #111827;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 1.25rem;
    margin-bottom: 1.25rem;
  }
  .download-label {
    font-size: 0.72rem;
    color: #475569;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    margin-bottom: 0.6rem;
  }

  /* Footer */
  .app-footer {
    border-top: 1px solid #1e293b;
    padding-top: 1rem;
    margin-top: 2rem;
    font-size: 0.75rem;
    color: #334155;
    line-height: 1.7;
    text-align: center;
  }

  /* Tab label cleanup */
  .stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    border-bottom: 1px solid #1e293b;
  }
  .stTabs [data-baseweb="tab"] {
    font-size: 0.82rem;
    padding: 6px 16px;
    color: #64748b;
  }
</style>
""", unsafe_allow_html=True)


# ── Bank detection helper ────────────────────────────────────────────────────

def detect_bank(text: str) -> str:
    """
    Identify which bank issued the statement from extracted text.
    Only inspects the first 800 characters (the header region) to avoid
    false matches from bank names appearing in transaction narrations.
    Returns a display name or 'Unknown Bank'.
    """
    header = text[:800]
    header_upper = header.upper()
    # Axis: check before HDFC — Axis narrations often contain "HDFC BANK"
    if "Axis Account No" in header or "UTIB0" in header or "AXIS BANK" in header_upper:
        return "Axis Bank"
    # HDFC: unique column headers or legal name in header block
    if "HDFC BANK LIMITED" in header or "WithdrawalAmt" in header or "DepositAmt" in header:
        return "HDFC Bank"
    if "PUNJAB NATIONAL BANK" in header_upper or "PUNB0" in header:
        return "Punjab National Bank"
    # IndusInd: match both "INDUSIND" and "INDUS IND" (space variant), plus IFSC prefix
    # IndusInd Bank
    if (
    "INDUSIND" in header_upper or "INDUS IND" in header_upper or "INDB0" in header_upper or "INDUS" in header_upper):
        return "IndusInd Bank"
    return "Unknown Bank"


# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="app-header">
  <h1 class="app-title">Bank Statement Intelligence Platform</h1>
  <p class="app-subtitle">
    Extract, analyse and convert bank statements into structured JSON.
    Supports multiple bank formats with automated transaction extraction.
  </p>
</div>
""", unsafe_allow_html=True)


# ── Upload section ────────────────────────────────────────────────────────────

st.markdown(
    "<p style='font-size:0.8rem; color:#475569; text-transform:uppercase; "
    "letter-spacing:0.09em; margin-bottom:0.5rem;'>UPLOAD STATEMENT</p>",
    unsafe_allow_html=True,
)

uploaded_file = st.file_uploader(
    label="Upload a bank statement PDF",
    type=["pdf"],
    label_visibility="collapsed",
    help="Supports digitally-generated PDF statements from HDFC, Axis, PNB and IndusInd. "
         "Scanned PDFs are not supported.",
)

if uploaded_file is None:
    st.markdown("""
    <div class="verify-notice">
      Upload a bank statement PDF to begin extraction.
      Supported banks: HDFC Bank, Axis Bank, Punjab National Bank, IndusInd Bank.
    </div>
    """, unsafe_allow_html=True)
    st.stop()


# ── Processing ────────────────────────────────────────────────────────────────

try:
    with st.spinner("Reading PDF…"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded_file.read())
            tmp_path = Path(tmp.name)

        extraction = extract_pdf(tmp_path)
        tables     = extract_tables(tmp_path)

        is_hdfc     = (
            "WithdrawalAmt" in extraction.full_text or
            "HDFC BANK LIMITED" in extraction.full_text
        )
        pages_words = extract_words_by_page(tmp_path) if is_hdfc else None

    if not extraction.success:
        st.error(f"Could not read the PDF: {extraction.error}")
        st.info("Please ensure the file is a digitally-generated (not scanned) PDF.")
        st.stop()

    with st.spinner("Parsing transactions…"):
        transactions = parse_transactions(extraction.full_text, tables, pages_words)

except Exception as e:
    st.error("An unexpected error occurred while processing the PDF.")
    st.caption(f"Technical detail: {type(e).__name__}: {e}")
    st.stop()
finally:
    # Always clean up the temp file, even if processing failed
    try:
        tmp_path.unlink(missing_ok=True)
    except Exception:
        pass

if not transactions:
    st.warning(
        "No transactions were found in this PDF. "
        "This may mean the PDF format is not yet supported, or the file is a scanned image. "
        "Check the Raw Extraction tab to inspect the extracted text."
    )
    # Still show the raw extraction tab so the user can debug
    st.divider()
    st.markdown("#### Raw Extraction")
    if extraction.pages:
        page_options = [f"Page {i+1}" for i in range(len(extraction.pages))]
        selected     = st.selectbox("Select page", page_options, label_visibility="collapsed")
        page_idx     = int(selected.split()[-1]) - 1
        st.code(extraction.pages[page_idx], language="text")
    st.stop()

# ── Bank detection badge ──────────────────────────────────────────────────────

detected_bank = detect_bank(extraction.full_text)
st.markdown(
    f'<div class="bank-badge"><span class="dot"></span>'
    f'Detected Bank: {detected_bank}</div>',
    unsafe_allow_html=True,
)

# ── Summary metrics ───────────────────────────────────────────────────────────

tx_count   = len(transactions)
pages      = extraction.page_count
debit_sum  = sum(t["withdrawal"] or 0 for t in transactions)
credit_sum = sum(t["deposit"]    or 0 for t in transactions)

# Closing balance: balance from the last transaction that has one
closing_balance = None
for t in reversed(transactions):
    if t.get("balance") is not None:
        closing_balance = t["balance"]
        break

def fmt_inr(amount: float) -> str:
    """Format a rupee amount with Indian comma grouping."""
    if amount >= 1_00_00_000:
        return f"₹{amount/1_00_00_000:.2f}Cr"
    if amount >= 1_00_000:
        return f"₹{amount/1_00_000:.1f}L"
    return f"₹{amount:,.0f}"

closing_display = fmt_inr(closing_balance) if closing_balance is not None else "—"

st.markdown(f"""
<div class="metric-row">
  <div class="metric-card">
    <div class="metric-label">Transactions</div>
    <div class="metric-value blue">{tx_count:,}</div>
  </div>
  <div class="metric-card">
    <div class="metric-label">Pages Processed</div>
    <div class="metric-value">{pages}</div>
  </div>
  <div class="metric-card">
    <div class="metric-label">Total Withdrawals</div>
    <div class="metric-value red">{fmt_inr(debit_sum)}</div>
  </div>
  <div class="metric-card">
    <div class="metric-label">Total Deposits</div>
    <div class="metric-value green">{fmt_inr(credit_sum)}</div>
  </div>
  <div class="metric-card">
    <div class="metric-label">Closing Balance</div>
    <div class="metric-value">{closing_display}</div>
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="verify-notice">
  <strong>Manual verification recommended.</strong>
  Automated extraction accuracy depends on PDF quality and structure.
  Always verify against the original statement before use in any financial workflow.
</div>
""", unsafe_allow_html=True)


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(["Transactions", "JSON Output", "Raw Extraction"])


# ── Tab 1: Transactions table ─────────────────────────────────────────────────
with tab1:
    if not transactions:
        st.warning("No transactions were parsed. Check the Raw Extraction tab to inspect the PDF text.")
    else:
        import pandas as pd

        df = pd.DataFrame(transactions)
        df_display = df.copy()

        # Use pd.notna() to safely handle NaN values that pandas introduces
        # when None appears in float columns. Plain `if x` treats NaN as truthy,
        # which would render "₹nan" in the table.
        df_display["withdrawal"] = df_display["withdrawal"].apply(
            lambda x: f"₹{x:,.2f}" if pd.notna(x) and x != 0 else ""
        )
        df_display["deposit"] = df_display["deposit"].apply(
            lambda x: f"₹{x:,.2f}" if pd.notna(x) and x != 0 else ""
        )
        df_display["balance"] = df_display["balance"].apply(
            lambda x: f"₹{x:,.2f}" if pd.notna(x) else ""
        )

        df_display.columns = ["Date", "Particulars", "Reference No.", "Withdrawal (₹)", "Deposit (₹)", "Balance (₹)"]
        df_display.index = range(1, len(df_display) + 1)

        st.dataframe(df_display, use_container_width=True, height=480)
        st.caption(f"{len(df_display):,} transactions  ·  Dates normalised to YYYY-MM-DD")


# ── Tab 2: JSON output + download ─────────────────────────────────────────────
with tab2:
    stem = Path(uploaded_file.name).stem
    safe_stem = re.sub(r"[^\w\-]", "_", stem)
    filename = f"{safe_stem}_extracted.json"

    output_json = {
        "bank_details": {
            "bank_name":           detected_bank,
            "source_file":         uploaded_file.name,
            "extracted_at":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_pages":         pages,
            "total_transactions":  tx_count,
            "total_withdrawals":   round(debit_sum, 2),
            "total_deposits":      round(credit_sum, 2),
            "closing_balance":     closing_balance,
            "extraction_method":   "automated",
            "verification_status": "manual verification recommended",
        },
        "transactions": transactions,
    }

    json_str = json.dumps(output_json, indent=2, ensure_ascii=False)

    st.markdown('<div class="download-section">', unsafe_allow_html=True)
    st.markdown('<p class="download-label">Download Extracted Data</p>', unsafe_allow_html=True)
    st.download_button(
        label="Download Extracted JSON",
        data=json_str,
        file_name=filename,
        mime="application/json",
        use_container_width=False,
    )
    st.markdown(
        f"<p style='font-size:0.75rem; color:#475569; margin-top:6px;'>"
        f"File: <code style='color:#94a3b8'>{filename}</code> &nbsp;·&nbsp; "
        f"{len(json_str):,} bytes &nbsp;·&nbsp; {tx_count:,} transactions</p>",
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)

    st.code(json_str, language="json")


# ── Tab 3: Raw extraction ─────────────────────────────────────────────────────
with tab3:
    st.markdown(
        "<p style='font-size:0.82rem; color:#64748b; margin-bottom:0.75rem;'>"
        "Raw text extracted by pdfplumber before parsing. "
        "Use this to verify extraction quality or debug parser issues.</p>",
        unsafe_allow_html=True,
    )

    page_options = [f"Page {i+1}" for i in range(len(extraction.pages))]
    selected     = st.selectbox("Select page", page_options, label_visibility="collapsed")
    page_idx     = int(selected.split()[-1]) - 1

    st.code(extraction.pages[page_idx], language="text")


# ── Footer ────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="app-footer">
  Built using Python, Streamlit and pdfplumber.<br>
  Supports automated extraction of structured transaction data from multiple bank statement formats.<br>
  Manual verification is recommended before financial use.
</div>
""", unsafe_allow_html=True)
