"""Read supported test-basis documents into plain text."""

from pathlib import Path
from zipfile import BadZipFile


class TestBasisError(ValueError):
    """Raised when a test-basis document cannot provide readable text."""


def read_test_basis(path: Path) -> str:
    """Return readable text from a supported local test-basis document."""
    suffix = path.suffix.casefold()

    if suffix not in {".txt", ".md", ".pdf", ".docx"}:
        raise TestBasisError("Filformatet understøttes ikke.")

    try:
        if suffix in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8-sig")
        elif suffix == ".pdf":
            text = _read_pdf(path)
        else:
            text = _read_docx(path)
    except TestBasisError:
        raise
    except (OSError, UnicodeError, BadZipFile) as error:
        raise TestBasisError("Filen kan ikke læses.") from error

    if not text.strip():
        raise TestBasisError("Filen indeholder ingen læsbar tekst.")
    return text.strip()


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ModuleNotFoundError as error:
        raise TestBasisError(
            "Det nødvendige dokumentbibliotek er ikke installeret."
        ) from error

    try:
        reader = PdfReader(str(path))
    except PdfReadError as error:
        raise TestBasisError("Filen kan ikke læses.") from error
    if reader.is_encrypted:
        raise TestBasisError("PDF-filen er beskyttet.")
    try:
        return "\n\n".join(
            (page.extract_text() or "").strip() for page in reader.pages
        )
    except PdfReadError as error:
        raise TestBasisError("Filen kan ikke læses.") from error


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
        from docx.opc.exceptions import OpcError
        from docx.oxml.exceptions import InvalidXmlError
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        from lxml.etree import LxmlError
    except ModuleNotFoundError as error:
        raise TestBasisError(
            "Det nødvendige dokumentbibliotek er ikke installeret."
        ) from error

    def extract_content(container) -> str:
        blocks = []
        for item in container.iter_inner_content():
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if text:
                    blocks.append(text)
            elif isinstance(item, Table):
                for row in item.rows:
                    cells = [extract_content(cell) for cell in row.cells]
                    if any(cells):
                        blocks.append(" | ".join(cells))
        return "\n".join(blocks)

    try:
        document = Document(str(path))
        return extract_content(document)
    except (OpcError, InvalidXmlError, LxmlError, BadZipFile) as error:
        raise TestBasisError("Filen kan ikke læses.") from error
