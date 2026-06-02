"""
utils.py
--------
Shared utility functions used across the parser pipeline.
Handles date normalization, amount parsing, and null safety.
"""

import re
from typing import Optional


# ── Date normalization ──────────────────────────────────────────────────────

# Patterns we expect to see in Indian bank statements.
# Each entry is (regex_pattern, mode) where mode is either "dd_mm" (day-first)
# or "already_iso" (already YYYY-MM-DD, return as-is).
_DATE_PATTERNS = [
    (r"(\d{2})[\/\-](\d{2})[\/\-](\d{4})", "dd_mm"),       # DD/MM/YYYY or DD-MM-YYYY
    (r"(\d{2})[\/\-](\d{2})[\/\-](\d{2})",  "dd_mm"),       # DD/MM/YY
    (r"(\d{4})[\/\-](\d{2})[\/\-](\d{2})", "already_iso"),  # already YYYY-MM-DD
]

def normalize_date(raw: str) -> Optional[str]:
    """
    Convert any common Indian bank date format to YYYY-MM-DD.
    Returns None if the input cannot be parsed.
    """
    if not raw:
        return None

    raw = raw.strip()

    for pattern, mode in _DATE_PATTERNS:
        m = re.match(pattern, raw)
        if m:
            if mode == "already_iso":
                parts = m.groups()
                year, month, day = parts[0], parts[1], parts[2]
                try:
                    if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
                        continue
                    return f"{year}-{month}-{day}"
                except ValueError:
                    continue

            # mode == "dd_mm": groups are (day, month, year)
            parts = m.groups()
            day   = parts[0].zfill(2)
            month = parts[1].zfill(2)
            year  = parts[2]

            # Handle 2-digit year: 24 → 2024, 99 → 1999
            if len(year) == 2:
                year = "20" + year if int(year) <= 30 else "19" + year

            try:
                # Basic validation: month 1-12, day 1-31
                if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
                    continue
                return f"{year}-{month}-{day}"
            except ValueError:
                continue

    return None


# ── Amount parsing ──────────────────────────────────────────────────────────

def parse_amount(raw: str) -> Optional[float]:
    """
    Convert a raw amount string like '1,23,456.78' or '50000.00' to float.
    Returns None for empty or non-numeric strings.
    """
    if not raw:
        return None

    raw = raw.strip()

    # Remove currency symbols and commas
    cleaned = re.sub(r"[₹,\s]", "", raw)

    # Remove trailing Dr/Cr labels if present (some banks suffix amounts)
    cleaned = re.sub(r"(?i)(dr|cr)$", "", cleaned).strip()

    if not cleaned:
        return None

    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


# ── String cleaning ─────────────────────────────────────────────────────────

def clean_text(raw: str) -> str:
    """
    Normalize whitespace and remove null bytes from extracted PDF text.
    Does NOT truncate or summarize — preserves full narration.
    """
    if not raw:
        return ""
    # Collapse multiple spaces/tabs into one space
    cleaned = re.sub(r"[ \t]+", " ", raw)
    # Remove null bytes that pdfplumber occasionally produces
    cleaned = cleaned.replace("\x00", "")
    return cleaned.strip()


def parse_amount_or_null(raw: str) -> Optional[float]:
    """
    Same as parse_amount but treats 0.00 as None.
    Use this for withdrawal/deposit fields where 0.00 means the column was empty.
    Do NOT use for balance — a zero balance is a valid value.
    """
    result = parse_amount(raw)
    if result == 0.0:
        return None
    return result


def safe_str(value) -> Optional[str]:
    """Return stripped string or None if empty."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None
