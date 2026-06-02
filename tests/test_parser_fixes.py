"""
tests/test_parser_fixes.py
---------------------------
Targeted tests for the 5 bugs fixed in transaction_parser.py and utils.py.

Run with:
    python -m pytest tests/ -v
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from parser.utils import parse_amount_or_null
from parser.transaction_parser import (
    _parse_transaction_line,
    _is_empty_row,
    _is_header_row,
    parse_from_tables,
)


# ── Fix 1: _is_empty_row and _is_header_row exist and work ───────────────────

def test_is_empty_row_all_none():
    assert _is_empty_row([None, None, None]) is True

def test_is_empty_row_all_blank():
    assert _is_empty_row(["", "  ", None]) is True

def test_is_empty_row_has_data():
    assert _is_empty_row(["01/06/2024", "UPI PAYMENT", "500.00"]) is False

def test_is_header_row_date_keyword():
    assert _is_header_row(["Date", "Particulars", "Debit", "Credit", "Balance"]) is True

def test_is_header_row_transaction_keyword():
    assert _is_header_row(["Transaction Date", "Description", "Amount"]) is True

def test_is_header_row_data_row():
    assert _is_header_row(["01/06/2024", "UPI-MERCHANT", "500.00"]) is False


# ── Fix 2: 3-amount branch never sets both withdrawal AND deposit ─────────────

def test_three_amounts_with_dr_marker():
    """HDFC/PNB: line with DR marker → withdrawal only, never deposit"""
    line = "01-06-2024 UPI-MERCHANT-ref@upi DR 500.00 49,730.50"
    tx = _parse_transaction_line(line)
    assert tx is not None
    assert tx["withdrawal"] is not None
    assert tx["deposit"] is None, "deposit must be None when DR marker is present"

def test_three_amounts_with_cr_marker():
    """HDFC/PNB: line with CR marker → deposit only, never withdrawal"""
    line = "01-06-2024 NEFT-SALARY-PAYMENT CR 50000.00 99,730.50"
    tx = _parse_transaction_line(line)
    assert tx is not None
    assert tx["deposit"] is not None
    assert tx["withdrawal"] is None, "withdrawal must be None when CR marker is present"

def test_never_both_withdrawal_and_deposit():
    """Core rule: a single transaction row can NEVER have both withdrawal and deposit set."""
    test_lines = [
        "01-06-2024 UPI PAYMENT DR 500.00 49730.50",
        "02-06-2024 NEFT CREDIT CR 25000.00 74730.50",
        "03-06-2024 ATM WITHDRAWAL 1000.00 73730.50",
    ]
    for line in test_lines:
        tx = _parse_transaction_line(line)
        if tx:
            both_set = tx["withdrawal"] is not None and tx["deposit"] is not None
            assert not both_set, f"Both withdrawal and deposit set on: {line}"


# ── Fix 3: 2-amount CR detection ─────────────────────────────────────────────

def test_two_amounts_cr_marker():
    line = "15-06-2024 SALARY CREDIT CR 45000.00 1,20,000.00"
    tx = _parse_transaction_line(line)
    assert tx is not None
    assert tx["deposit"] is not None
    assert tx["withdrawal"] is None

def test_two_amounts_dr_marker():
    line = "15-06-2024 ELECTRICITY BILL DR 2500.00 1,17,500.00"
    tx = _parse_transaction_line(line)
    assert tx is not None
    assert tx["withdrawal"] is not None
    assert tx["deposit"] is None


# ── Fix 5: parse_amount_or_null treats 0.00 as None ──────────────────────────

def test_parse_amount_or_null_zero():
    assert parse_amount_or_null("0.00") is None

def test_parse_amount_or_null_real_amount():
    assert parse_amount_or_null("5000.00") == 5000.00

def test_parse_amount_or_null_none_input():
    assert parse_amount_or_null(None) is None

def test_parse_amount_or_null_empty():
    assert parse_amount_or_null("") is None


# ── Table parser: no crash on empty/header rows ───────────────────────────────

def test_table_parser_handles_empty_rows():
    """Table parser must not crash when rows are empty or None."""
    tables = [
        [
            ["Date", "Particulars", "Debit", "Credit", "Balance"],  # header
            [None, None, None, None, None],                           # empty row
            ["01/06/2024", "UPI PAYMENT", "500.00", None, "49730.50"],  # data
        ]
    ]
    result = parse_from_tables(tables)
    assert isinstance(result, list)
    # Should get 1 transaction (the data row), not crash
    assert len(result) == 1

def test_table_parser_deposit_not_zero_null():
    """When credit column is '0.00', deposit must be None not 0.0."""
    tables = [
        [
            ["Date", "Particulars", "Debit", "Credit", "Balance"],
            ["01/06/2024", "ATM CASH", "2000.00", "0.00", "48000.00"],
        ]
    ]
    result = parse_from_tables(tables)
    assert len(result) == 1
    assert result[0]["deposit"] is None
    assert result[0]["withdrawal"] == 2000.00
