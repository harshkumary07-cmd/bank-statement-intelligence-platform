"""
tests/test_utils.py
--------------------
Unit tests for parser/utils.py

Run with:
    python -m pytest tests/ -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from parser.utils import normalize_date, parse_amount, clean_text


# ── Date normalization tests ──────────────────────────────────────────────────

def test_date_dd_mm_yyyy_slash():
    assert normalize_date("15/06/2024") == "2024-06-15"

def test_date_dd_mm_yyyy_dash():
    assert normalize_date("15-06-2024") == "2024-06-15"

def test_date_dd_mm_yy():
    assert normalize_date("15/06/24") == "2024-06-15"

def test_date_already_normalized():
    assert normalize_date("2024-06-15") == "2024-06-15"

def test_date_empty():
    assert normalize_date("") is None

def test_date_invalid():
    assert normalize_date("not-a-date") is None

def test_date_invalid_month():
    assert normalize_date("15/13/2024") is None


# ── Amount parsing tests ──────────────────────────────────────────────────────

def test_amount_plain():
    assert parse_amount("1234.56") == 1234.56

def test_amount_with_commas():
    assert parse_amount("1,23,456.78") == 123456.78

def test_amount_with_rupee():
    assert parse_amount("₹50,000.00") == 50000.00

def test_amount_empty():
    assert parse_amount("") is None

def test_amount_none():
    assert parse_amount(None) is None

def test_amount_with_dr_suffix():
    assert parse_amount("5000.00Dr") == 5000.00


# ── Text cleaning tests ───────────────────────────────────────────────────────

def test_clean_text_collapses_spaces():
    assert clean_text("UPI  PAYMENT   TEST") == "UPI PAYMENT TEST"

def test_clean_text_strips():
    assert clean_text("  hello  ") == "hello"

def test_clean_text_empty():
    assert clean_text("") == ""

def test_clean_text_none():
    assert clean_text(None) == ""
