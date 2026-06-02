"""
transaction_parser.py
----------------------
Core parsing engine.

Strategy:
  1. Try table-based extraction first (most accurate for structured PDFs).
  2. Fall back to line-by-line regex parsing if tables fail.
  3. HDFC statements use coordinate-based parsing (no DR/CR text markers).

Why two strategies?
  - Axis Bank and HDFC render clean tables → pdfplumber table extraction works well.
  - PNB and some older statements have inconsistent column spacing → regex on raw text is safer.
  - By trying both and picking the better result, we maximize coverage.
"""

import re
from typing import Optional
from parser.utils import normalize_date, parse_amount, parse_amount_or_null, clean_text, safe_str


# ── Transaction data structure ──────────────────────────────────────────────

def empty_transaction() -> dict:
    return {
        "transaction_date": None,
        "particulars": None,
        "reference_number": None,
        "withdrawal": None,
        "deposit": None,
        "balance": None,
    }


# ── Table-based parser ───────────────────────────────────────────────────────

def parse_from_tables(tables: list) -> list[dict]:
    """
    Parse transactions from pdfplumber table output.
    Handles variable column counts and merges header rows automatically.
    """
    transactions = []

    for table in tables:
        if not table or len(table) < 2:
            continue

        # Detect header row
        header = _detect_header(table[0])
        if header is None:
            continue

        for row in table[1:]:
            if not row or _is_header_row(row) or _is_empty_row(row):
                continue

            tx = _map_row_to_transaction(row, header)
            if tx:
                transactions.append(tx)

    return transactions


def _is_empty_row(row: list) -> bool:
    """Return True if every cell in the row is None or blank."""
    return all(not safe_str(cell) for cell in row)


def _is_header_row(row: list) -> bool:
    """
    Return True if this row looks like a repeated header (not a data row).
    Detects rows where the first cell contains a known header keyword
    instead of a date value.
    """
    if not row:
        return True
    first = safe_str(row[0]) or ""
    # Header rows start with text keywords, not dates
    header_keywords = re.compile(
        r"date|transaction|particulars|narrat|description|sl\.?\s*no|sr\.?\s*no",
        re.IGNORECASE
    )
    return bool(header_keywords.search(first))


def _detect_header(row: list) -> Optional[dict]:
    """
    Identify which column index maps to which field.
    Returns a dict like: {"date": 0, "particulars": 1, "ref": 2, ...}
    or None if this doesn't look like a header row.

    Special case: PNB has an "Amount(INR)" column and a separate "Type" column (DR/CR).
    We map those to "amount_col" and "type_col" for special handling.
    """
    if not row:
        return None

    mapping = {}
    for i, cell in enumerate(row):
        if cell is None:
            continue
        cell_lower = str(cell).lower().strip()

        if re.search(r"\bdate\b", cell_lower):
            mapping["date"] = i
        if re.search(r"narrat|particular|description|details|remarks", cell_lower):
            mapping["particulars"] = i
        if re.search(r"ref|chq|cheque|instrument", cell_lower) and "date" not in mapping or mapping.get("date") != i:
            mapping["ref"] = i
        # Standard separate debit/credit columns
        if re.search(r"debit|withdraw", cell_lower) and not re.search(r"credit|deposit", cell_lower):
            mapping["withdrawal"] = i
        if re.search(r"credit|deposit", cell_lower) and not re.search(r"debit|withdraw", cell_lower):
            mapping["deposit"] = i
        if re.search(r"balance", cell_lower):
            mapping["balance"] = i
        # PNB-style: single "Amount(INR)" column + separate "Type" column
        if re.search(r"amount", cell_lower) and "withdrawal" not in mapping and "deposit" not in mapping:
            mapping["amount_col"] = i
        if re.search(r"^\s*type\s*$", cell_lower):
            mapping["type_col"] = i

    # Need at least date + some amount indicator
    has_amount = any(k in mapping for k in ("withdrawal", "deposit", "balance", "amount_col"))
    if "date" in mapping and has_amount:
        return mapping

    return None


def _map_row_to_transaction(row: list, header: dict) -> Optional[dict]:
    """Map a data row to a transaction dict using the detected header mapping."""
    tx = empty_transaction()

    def get(key):
        idx = header.get(key)
        if idx is not None and idx < len(row):
            return safe_str(row[idx])
        return None

    raw_date = get("date")
    tx["transaction_date"] = normalize_date(raw_date) if raw_date else None

    # Skip rows with no parseable date (often subtotals or blank rows)
    if not tx["transaction_date"]:
        return None

    tx["particulars"]      = get("particulars")
    tx["reference_number"] = get("ref")

    # PNB-style: single amount column + type column
    if "amount_col" in header:
        raw_amount = get("amount_col")
        raw_type   = get("type_col") or ""
        amount_val = parse_amount_or_null(raw_amount)
        if amount_val is not None:
            if re.search(r"\bCR\b|\bCr\b", raw_type):
                tx["deposit"]    = amount_val
            elif re.search(r"\bDR\b|\bDr\b", raw_type):
                tx["withdrawal"] = amount_val
            else:
                tx["withdrawal"] = amount_val   # conservative default
    else:
        # Standard separate debit/credit columns
        tx["withdrawal"] = parse_amount_or_null(get("withdrawal"))
        tx["deposit"]    = parse_amount_or_null(get("deposit"))

    tx["balance"] = parse_amount(get("balance"))

    # Clean up balance: Axis Bank prefixes balance with "-\n"
    if tx["balance"] and tx["balance"] < 0:
        tx["balance"] = abs(tx["balance"])

    return tx


# ── HDFC coordinate-based parser ────────────────────────────────────────────
#
# HDFC statements have NO "Dr"/"Cr" text marker on each row.
# Withdrawal vs deposit is determined solely by which amount column the number
# appears in. Using word-level x0 coordinates:
#   Withdrawal column: x0 in range [395, 455]  (left amount column)
#   Deposit column:    x0 in range [458, 530]  (right amount column)
#   Balance column:    x0 >= 550               (rightmost)
#
# These boundaries were measured from the actual HDFC PDF.

_HDFC_WITHDRAW_X0_MIN = 395
_HDFC_WITHDRAW_X0_MAX = 455
_HDFC_DEPOSIT_X0_MIN  = 458
_HDFC_DEPOSIT_X0_MAX  = 535
_HDFC_BALANCE_X0_MIN  = 548

# HDFC date format is DD/MM/YY (two-digit year)
_HDFC_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")

# Amount pattern: digits with optional commas and decimal
_AMOUNT_RE = re.compile(r"^[\d,]+\.\d+$")


def parse_from_hdfc_words(pages_words: list[list[dict]]) -> list[dict]:
    """
    Parse HDFC bank statement transactions using word-level x/y coordinates.

    Groups words by row (similar top coordinate), identifies transaction rows
    by the presence of a date word, then classifies amounts by x-position.
    """
    transactions = []

    for page_words in pages_words:
        if not page_words:
            continue

        # Group words into rows by proximity of top coordinate (within 3pt)
        rows: dict[int, list[dict]] = {}
        for word in page_words:
            row_key = int(word["top"] / 3) * 3
            rows.setdefault(row_key, []).append(word)

        # Process rows in top-to-bottom order
        for top_key in sorted(rows.keys()):
            row = rows[top_key]
            words_text = [w["text"] for w in row]

            # Only process rows that start with a date
            date_words = [w for w in row if _HDFC_DATE_RE.match(w["text"])]
            if not date_words:
                continue

            date_str = date_words[0]["text"]
            parsed_date = normalize_date(date_str)
            if not parsed_date:
                continue

            # Find amount words classified by x-position
            withdrawal = None
            deposit    = None
            balance    = None

            for w in row:
                if not _AMOUNT_RE.match(w["text"].replace(",", "")):
                    # Check for comma-formatted numbers like "1,23,456.78"
                    cleaned = w["text"].replace(",", "")
                    if not re.match(r"^\d+\.\d+$", cleaned):
                        continue

                amount_val = parse_amount(w["text"])
                if amount_val is None:
                    continue

                x0 = w["x0"]

                if _HDFC_BALANCE_X0_MIN <= x0:
                    balance = amount_val
                elif _HDFC_DEPOSIT_X0_MIN <= x0 <= _HDFC_DEPOSIT_X0_MAX:
                    deposit = amount_val
                elif _HDFC_WITHDRAW_X0_MIN <= x0 <= _HDFC_WITHDRAW_X0_MAX:
                    withdrawal = amount_val

            # Skip rows with no amounts (header/footer rows)
            if balance is None and withdrawal is None and deposit is None:
                continue

            # Build narration from non-date, non-amount, non-ref words
            # Ref number: 16-char alphanumeric in the middle columns
            ref_words = [w for w in row if re.match(r"^\d{12,16}$", w["text"])
                         and w["x0"] > 180 and w["x0"] < 400]
            ref_number = ref_words[0]["text"] if ref_words else None

            # Narration: words between date x-position and ref/amount columns
            narration_words = [
                w["text"] for w in sorted(row, key=lambda x: x["x0"])
                if w["x0"] > 30 and w["x0"] < 390
                and not _HDFC_DATE_RE.match(w["text"])
                and w["text"] not in ("Page", "No.:", "From", "To")
                and not re.match(r"^\d{4}$", w["text"])  # skip year fragments
            ]
            # Remove the ref number from narration if it appears there
            if ref_number and ref_number in narration_words:
                narration_words.remove(ref_number)

            particulars = clean_text(" ".join(narration_words)) or None

            tx = empty_transaction()
            tx["transaction_date"] = parsed_date
            tx["particulars"]      = particulars
            tx["reference_number"] = ref_number
            tx["withdrawal"]       = withdrawal if withdrawal != 0.0 else None
            tx["deposit"]          = deposit    if deposit    != 0.0 else None
            tx["balance"]          = balance
            transactions.append(tx)

    return transactions


# ── Line-based regex parser ──────────────────────────────────────────────────

# Standard Indian bank date formats: DD/MM/YYYY, DD-MM-YYYY, DD/MM/YY
_DATE_RE = r"(\d{2}[\/\-]\d{2}[\/\-](?:\d{4}|\d{2}))"

# Amount: optional ₹, digits, commas, decimal
_AMT_RE  = r"([\d,]+\.\d{2})"

# Lines to skip before processing (footers, totals, etc.)
_SKIP_LINE_RE = re.compile(
    r"TRANSACTION\s+TOTAL|CLOSING\s+BALANCE|OPENING\s+BALANCE|"
    r"Generated\s+On|Page\s+No\.|End\s+of\s+Statement",
    re.IGNORECASE
)


def parse_from_text(full_text: str) -> list[dict]:
    """
    Line-by-line regex parser for raw extracted text.
    Used as fallback when table extraction finds no structured tables.
    """
    transactions = []
    lines = full_text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Skip known footer/summary lines that contain amounts but aren't transactions
        if _SKIP_LINE_RE.search(line):
            i += 1
            continue

        # Check if this line starts with a date
        if not re.match(rf"^{_DATE_RE}", line):
            i += 1
            continue

        # Attempt to join continuation lines (narrations can wrap)
        combined = line
        j = i + 1
        while j < len(lines):
            next_line = lines[j].strip()
            # Stop if next line is a new transaction or empty
            if re.match(rf"^{_DATE_RE}", next_line) or not next_line:
                break
            # Stop at known footer lines so they don't contaminate amounts
            if _SKIP_LINE_RE.search(next_line):
                break
            # Only join if next line doesn't look like a standalone amount row
            if not re.match(r"^[\d,]+\.\d{2}\s*$", next_line):
                combined += " " + next_line
                j += 1
            else:
                break

        tx = _parse_transaction_line(combined)
        if tx:
            transactions.append(tx)

        i = j if j > i + 1 else i + 1

    return transactions


def _parse_transaction_line(line: str) -> Optional[dict]:
    """Parse a single (possibly multi-line-joined) transaction string."""
    tx = empty_transaction()

    # Extract date from start
    date_match = re.match(rf"^({_DATE_RE})", line)
    if not date_match:
        return None

    raw_date = date_match.group(1)
    tx["transaction_date"] = normalize_date(raw_date)
    if not tx["transaction_date"]:
        return None

    remainder = line[date_match.end():].strip()

    # Extract reference number (16-digit UPI trace / NEFT ref / cheque number)
    ref_match = re.search(r"\b(\d{12,16})\b", remainder)
    if ref_match:
        tx["reference_number"] = ref_match.group(1)

    # Extract all amounts from the line
    amounts = re.findall(r"[\d,]+\.\d{2}", remainder)
    amounts_float = [parse_amount(a) for a in amounts]
    amounts_float = [a for a in amounts_float if a is not None]

    if len(amounts_float) >= 3:
        # Last amount is always the running balance in Indian bank statements.
        # One of the first two is the transaction amount; the other slot is empty.
        # Use DR/CR marker to decide which slot to fill.
        tx["balance"] = amounts_float[-1]
        tx_amount = amounts_float[0]  # transaction amount is always first

        if re.search(r"\bCr\b|\bCR\b", line):
            tx["deposit"] = tx_amount
        elif re.search(r"\bDr\b|\bDR\b", line):
            tx["withdrawal"] = tx_amount
        else:
            # No marker: default conservatively to withdrawal.
            tx["withdrawal"] = tx_amount

    elif len(amounts_float) == 2:
        tx["balance"] = amounts_float[-1]
        # Classify transaction amount using DR/CR marker
        if re.search(r"\bCr\b|\bCR\b", line):
            tx["deposit"] = amounts_float[0]
        elif re.search(r"\bDr\b|\bDR\b", line):
            tx["withdrawal"] = amounts_float[0]
        else:
            tx["withdrawal"] = amounts_float[0]   # conservative default
    elif len(amounts_float) == 1:
        tx["balance"] = amounts_float[0]

    # Extract narration: everything between date and first amount
    narration_match = re.match(
        rf"^{_DATE_RE}\s+(.*?)\s+[\d,]+\.\d{{2}}", line
    )
    if narration_match:
        raw_narration = narration_match.group(2)
        # Remove the reference number from narration if captured there
        if tx["reference_number"]:
            raw_narration = raw_narration.replace(tx["reference_number"], "").strip()
        tx["particulars"] = clean_text(raw_narration) or None

    return tx


# ── Master parse function ────────────────────────────────────────────────────

def parse_transactions(full_text: str, tables: list,
                       pages_words: Optional[list] = None) -> list[dict]:
    """
    Entry point. Strategy:
    1. If HDFC word data is provided, use coordinate-based HDFC parser.
    2. Otherwise try table parsing, fall back to text parsing.
    Returns the best result based on transaction count.
    """
    # HDFC coordinate-based path
    if pages_words:
        hdfc_results = parse_from_hdfc_words(pages_words)
        if hdfc_results:
            return hdfc_results

    table_results = parse_from_tables(tables)
    text_results  = parse_from_text(full_text)

    # Use whichever strategy found more transactions
    if len(table_results) >= len(text_results):
        return table_results
    return text_results



# ── Transaction data structure ──────────────────────────────────────────────

def empty_transaction() -> dict:
    return {
        "transaction_date": None,
        "particulars": None,
        "reference_number": None,
        "withdrawal": None,
        "deposit": None,
        "balance": None,
    }


# ── Table-based parser ───────────────────────────────────────────────────────

def parse_from_tables(tables: list) -> list[dict]:
    """
    Parse transactions from pdfplumber table output.
    Handles variable column counts and merges header rows automatically.
    """
    transactions = []

    for table in tables:
        if not table or len(table) < 2:
            continue

        # Detect header row
        header = _detect_header(table[0])
        if header is None:
            continue

        for row in table[1:]:
            if not row or _is_header_row(row) or _is_empty_row(row):
                continue

            tx = _map_row_to_transaction(row, header)
            if tx:
                transactions.append(tx)

    return transactions


def _is_empty_row(row: list) -> bool:
    """Return True if every cell in the row is None or blank."""
    return all(not safe_str(cell) for cell in row)


def _is_header_row(row: list) -> bool:
    """
    Return True if this row looks like a repeated header (not a data row).
    Detects rows where the first cell contains a known header keyword
    instead of a date value.
    """
    if not row:
        return True
    first = safe_str(row[0]) or ""
    # Header rows start with text keywords, not dates
    header_keywords = re.compile(
        r"date|transaction|particulars|narrat|description|sl\.?\s*no|sr\.?\s*no",
        re.IGNORECASE
    )
    return bool(header_keywords.search(first))


def _detect_header(row: list) -> Optional[dict]:
    """
    Identify which column index maps to which field.
    Returns a dict like: {"date": 0, "particulars": 1, "ref": 2, ...}
    or None if this doesn't look like a header row.
    """
    if not row:
        return None

    mapping = {}
    for i, cell in enumerate(row):
        if cell is None:
            continue
        cell_lower = str(cell).lower().strip()

        if re.search(r"\bdate\b", cell_lower):
            mapping["date"] = i
        if re.search(r"narrat|particular|description|details", cell_lower):
            mapping["particulars"] = i
        if re.search(r"ref|chq|cheque|instrument", cell_lower) and "date" not in mapping or mapping.get("date") != i:
            mapping["ref"] = i
        if re.search(r"debit|withdraw|dr\b", cell_lower):
            mapping["withdrawal"] = i
        if re.search(r"credit|deposit|cr\b", cell_lower):
            # Only set deposit if not already mapped as withdrawal (avoids debit/credit combined header)
            if mapping.get("withdrawal") != i:
                mapping["deposit"] = i
        if re.search(r"balance", cell_lower):
            mapping["balance"] = i

    # Need at least date + one amount column to be useful
    if "date" in mapping and ("withdrawal" in mapping or "deposit" in mapping or "balance" in mapping):
        return mapping

    return None


def _map_row_to_transaction(row: list, header: dict) -> Optional[dict]:
    """Map a data row to a transaction dict using the detected header mapping."""
    tx = empty_transaction()

    def get(key):
        idx = header.get(key)
        if idx is not None and idx < len(row):
            return safe_str(row[idx])
        return None

    raw_date = get("date")
    tx["transaction_date"] = normalize_date(raw_date) if raw_date else None

    # Skip rows with no parseable date (often subtotals or blank rows)
    if not tx["transaction_date"]:
        return None

    tx["particulars"]      = get("particulars")
    tx["reference_number"] = get("ref")
    tx["withdrawal"]       = parse_amount_or_null(get("withdrawal"))
    tx["deposit"]          = parse_amount_or_null(get("deposit"))
    tx["balance"]          = parse_amount(get("balance"))

    return tx


# ── Line-based regex parser ──────────────────────────────────────────────────

# Standard Indian bank date formats: DD/MM/YYYY, DD-MM-YYYY, DD/MM/YY
_DATE_RE = r"(\d{2}[\/\-]\d{2}[\/\-](?:\d{4}|\d{2}))"

# Amount: optional ₹, digits, commas, decimal
_AMT_RE  = r"([\d,]+\.\d{2})"

# A transaction line starts with a date
_TX_LINE_RE = re.compile(
    rf"^{_DATE_RE}"          # date at start
    rf"\s+(.*?)"             # narration (non-greedy)
    rf"\s+{_AMT_RE}"         # first amount (withdrawal or balance)
    rf"(?:\s+{_AMT_RE})?"    # optional second amount
    rf"(?:\s+{_AMT_RE})?$",  # optional third amount
    re.IGNORECASE
)


def parse_from_text(full_text: str) -> list[dict]:
    """
    Line-by-line regex parser for raw extracted text.
    Used as fallback when table extraction finds no structured tables.
    """
    transactions = []
    lines = full_text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Check if this line starts with a date
        if not re.match(rf"^{_DATE_RE}", line):
            i += 1
            continue

        # Attempt to join continuation lines (narrations can wrap)
        combined = line
        j = i + 1
        while j < len(lines):
            next_line = lines[j].strip()
            if re.match(rf"^{_DATE_RE}", next_line) or not next_line:
                break
            # Only join if next line doesn't look like a standalone amount row
            if not re.match(r"^[\d,]+\.\d{2}\s*$", next_line):
                combined += " " + next_line
                j += 1
            else:
                break

        tx = _parse_transaction_line(combined)
        if tx:
            transactions.append(tx)

        i = j if j > i + 1 else i + 1

    return transactions


def _parse_transaction_line(line: str) -> Optional[dict]:
    """Parse a single (possibly multi-line-joined) transaction string."""
    tx = empty_transaction()

    # Extract date from start
    date_match = re.match(rf"^({_DATE_RE})", line)
    if not date_match:
        return None

    raw_date = date_match.group(1)
    tx["transaction_date"] = normalize_date(raw_date)
    if not tx["transaction_date"]:
        return None

    remainder = line[date_match.end():].strip()

    # Extract reference number (16-digit UPI trace / NEFT ref / cheque number)
    ref_match = re.search(r"\b(\d{12,16})\b", remainder)
    if ref_match:
        tx["reference_number"] = ref_match.group(1)

    # Extract all amounts from the line — match 1+ decimal digits (PNB uses 600.0 not 600.00)
    amounts = re.findall(r"[\d,]+\.\d+", remainder)
    amounts_float = [parse_amount(a) for a in amounts]
    amounts_float = [a for a in amounts_float if a is not None]

    if len(amounts_float) >= 3:
        # Last amount is always the running balance in Indian bank statements.
        # One of the first two is the transaction amount; the other slot is empty.
        # Use DR/CR marker to decide which slot to fill.
        tx["balance"] = amounts_float[-1]
        tx_amount = amounts_float[0]  # transaction amount is always first

        if re.search(r"\bCr\b|\bCR\b", line):
            tx["deposit"] = tx_amount
        elif re.search(r"\bDr\b|\bDR\b", line):
            tx["withdrawal"] = tx_amount
        else:
            # No marker: use balance direction heuristic.
            # If balance went UP compared to previous amount, it was a deposit.
            # We don't have previous balance here, so default conservatively to withdrawal.
            # This will be partially wrong but is better than setting both.
            tx["withdrawal"] = tx_amount

    elif len(amounts_float) == 2:
        tx["balance"] = amounts_float[-1]
        # Classify transaction amount using DR/CR marker
        if re.search(r"\bCr\b|\bCR\b", line):
            tx["deposit"] = amounts_float[0]
        elif re.search(r"\bDr\b|\bDR\b", line):
            tx["withdrawal"] = amounts_float[0]
        else:
            tx["withdrawal"] = amounts_float[0]   # conservative default
    elif len(amounts_float) == 1:
        tx["balance"] = amounts_float[0]

    # Extract narration: everything between date and first amount (1+ decimals)
    narration_match = re.match(
        rf"^{_DATE_RE}\s+(.*?)\s+[\d,]+\.\d+", line
    )
    if narration_match:
        raw_narration = narration_match.group(2)
        # Remove the reference number from narration if captured there
        if tx["reference_number"]:
            raw_narration = raw_narration.replace(tx["reference_number"], "").strip()
        tx["particulars"] = clean_text(raw_narration) or None

    return tx


# ── Master parse function ────────────────────────────────────────────────────

def parse_transactions(full_text: str, tables: list,
                       pages_words: Optional[list] = None) -> list[dict]:
    """
    Entry point. Strategy:
    1. If HDFC word data is provided, use coordinate-based HDFC parser.
    2. Otherwise try table parsing, fall back to text parsing.
    Returns the best result based on transaction count.
    """
    # HDFC coordinate-based path
    if pages_words:
        hdfc_results = parse_from_hdfc_words(pages_words)
        if hdfc_results:
            return hdfc_results

    table_results = parse_from_tables(tables)
    text_results  = parse_from_text(full_text)

    # Use whichever strategy found more transactions
    if len(table_results) >= len(text_results):
        return table_results
    return text_results
