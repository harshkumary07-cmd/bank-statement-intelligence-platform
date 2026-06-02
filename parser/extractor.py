"""
extractor.py
------------
Responsible ONLY for reading a PDF and returning raw text.
No parsing logic lives here — separation of concerns.

Uses pdfplumber which handles:
  - digitally generated PDFs (best accuracy)
  - most text-layer PDFs from Indian banks
  - multi-column layouts better than PyPDF2
"""

from pathlib import Path
from typing import Optional, Union
import pdfplumber

from parser.utils import clean_text


class ExtractionResult:
    """Holds the output of a PDF extraction attempt."""

    def __init__(self):
        self.pages: list[str] = []          # raw text per page
        self.full_text: str = ""            # all pages joined
        self.page_count: int = 0
        self.success: bool = False
        self.error: Optional[str] = None


def extract_pdf(file_path: Union[str, Path]) -> ExtractionResult:
    """
    Open a PDF and extract text from every page using pdfplumber.

    Args:
        file_path: Path to the PDF file (str or Path object).

    Returns:
        ExtractionResult with pages list and full_text.
    """
    result = ExtractionResult()
    path = Path(file_path)

    if not path.exists():
        result.error = f"File not found: {path}"
        return result

    if path.suffix.lower() != ".pdf":
        result.error = "File must be a PDF (.pdf extension)."
        return result

    try:
        with pdfplumber.open(path) as pdf:
            result.page_count = len(pdf.pages)

            for page_num, page in enumerate(pdf.pages, start=1):
                raw = page.extract_text()

                if raw:
                    cleaned = clean_text(raw)
                    result.pages.append(cleaned)
                else:
                    # Page has no extractable text (scanned image)
                    result.pages.append(f"[Page {page_num}: No extractable text — may be scanned]")

            result.full_text = "\n\n".join(result.pages)
            result.success = True

    except Exception as e:
        result.error = f"PDF extraction failed: {str(e)}"

    return result


def extract_words_by_page(file_path: Union[str, Path]) -> list:
    """
    Extract word-level data with x/y coordinates for each page.
    Used by the HDFC parser to distinguish withdrawal vs deposit columns
    using horizontal position, since HDFC has no DR/CR text markers.

    Returns a list of pages, each page being a list of word dicts with
    keys: text, x0, x1, top (vertical position).
    """
    path = Path(file_path)
    pages_words = []

    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                words = page.extract_words()
                pages_words.append([
                    {"text": w["text"], "x0": w["x0"], "x1": w["x1"], "top": w["top"]}
                    for w in words
                ])
    except Exception:
        pass

    return pages_words


def extract_tables(file_path: Union[str, Path]) -> list:
    """
    Attempt table extraction using pdfplumber's table detection.
    More accurate than raw text for well-structured bank statements.

    Returns a flat list of tables, where each table is a list of rows,
    and each row is a list of cell strings.
    """
    path = Path(file_path)
    all_tables = []

    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                if tables:
                    all_tables.extend(tables)
    except Exception:
        pass  # Fall back gracefully to text extraction

    return all_tables
