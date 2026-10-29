"""PDF validation, text extraction and page-aware chunking."""
import io
import re
from dataclasses import dataclass
from typing import List

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.config import settings


class DocumentError(Exception):
    """A user-facing problem with an uploaded document."""

    def __init__(self, message: str, code: str = "invalid_document", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


@dataclass
class Page:
    number: int  # 1-based
    text: str


@dataclass
class Chunk:
    page: int
    ordinal: int
    text: str


def validate_and_extract(filename: str, data: bytes) -> List[Page]:
    """Enforce the size/type/page limits and return the text of each page."""
    if not filename.lower().endswith(".pdf"):
        raise DocumentError(f"'{filename}' is not a PDF. Only .pdf files are accepted.", "invalid_type")
    if len(data) == 0:
        raise DocumentError(f"'{filename}' is empty.", "empty_file")
    if len(data) > settings.MAX_PDF_BYTES:
        mb = len(data) / (1024 * 1024)
        raise DocumentError(
            f"'{filename}' is {mb:.1f} MB. The maximum size is {settings.MAX_PDF_BYTES // (1024 * 1024)} MB per PDF.",
            "file_too_large",
            413,
        )
    if not data.lstrip()[:5].startswith(b"%PDF-"):
        raise DocumentError(f"'{filename}' is not a valid PDF file (missing PDF header).", "invalid_pdf")

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentError(f"'{filename}' is password-protected. Please upload an unencrypted PDF.", "encrypted_pdf")
        page_count = len(reader.pages)
    except DocumentError:
        raise
    except (PdfReadError, Exception) as exc:  # pypdf raises a variety of errors on corrupt files
        raise DocumentError(f"'{filename}' could not be read as a PDF ({type(exc).__name__}).", "invalid_pdf") from exc

    if page_count == 0:
        raise DocumentError(f"'{filename}' has no pages.", "empty_pdf")
    if page_count > settings.MAX_PAGES_PER_PDF:
        raise DocumentError(
            f"'{filename}' has {page_count} pages. The maximum is {settings.MAX_PAGES_PER_PDF} pages per PDF.",
            "too_many_pages",
        )

    pages: List[Page] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append(Page(number=i, text=_clean(text)))

    _strip_running_lines(pages)
    if sum(len(p.text) for p in pages) < 20:
        raise DocumentError(
            f"No readable text was found in '{filename}'. Scanned/image-only PDFs are not supported yet (no OCR).",
            "no_text",
        )
    return pages


def _clean(text: str) -> str:
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(?m)^\s*(\d{1,2}[.)]|[•●▪-])\s*\n", r"\1 ", text)  # "1." alone on a line + item text on the next
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_running_lines(pages: List[Page]) -> None:
    """Remove running headers/footers: page-number lines and lines repeated on most pages."""
    def norm(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip().lower())

    def edges(text: str) -> List[str]:  # headers/footers live in the first/last two lines of a page
        lines = [l for l in text.split("\n") if l.strip()]
        return lines[:2] + lines[-2:]

    counts = {}
    for p in pages:
        for key in {norm(l) for l in edges(p.text)}:
            counts[key] = counts.get(key, 0) + 1
    repeated = {k for k, n in counts.items() if len(pages) >= 2 and n >= max(2, 0.6 * len(pages)) and len(k) < 120}
    for p in pages:
        edge = set(edges(p.text))
        kept = [l for l in p.text.split("\n")
                if not (l in edge and (norm(l) in repeated or re.fullmatch(r"(?i)\s*(.{0,80}[-–—|]\s*)?page\s+\d+(\s+of\s+\d+)?\s*", l)))]
        if any(l.strip() for l in kept):  # never strip a page down to nothing
            p.text = "\n".join(kept).strip()


def chunk_pages(pages: List[Page], size: int = None, overlap: int = None) -> List[Chunk]:
    """Split each page into overlapping word windows, never crossing page boundaries,
    so every chunk maps to exactly one page for citations. Paragraph boundaries are
    preferred split points."""
    size = size or settings.CHUNK_SIZE_WORDS
    overlap = overlap or settings.CHUNK_OVERLAP_WORDS
    chunks: List[Chunk] = []
    ordinal = 0
    for page in pages:
        if not page.text:
            continue
        # pypdf returns one line per visual line; lines are our smallest split unit.
        paragraphs = [line.strip() for line in page.text.split("\n") if line.strip()]
        buffer: List[str] = []
        for para in paragraphs:
            words = para.split()
            if buffer and len(buffer) + len(words) > size:
                chunks.append(Chunk(page.number, ordinal, _join(buffer)))
                ordinal += 1
                buffer = buffer[-overlap:] if overlap else []
            buffer.extend(words)
            buffer.append("\n")  # keep line structure (headings, list items, table rows)
            while len(buffer) > size * 1.5:  # very long paragraph
                chunks.append(Chunk(page.number, ordinal, _join(buffer[:size])))
                ordinal += 1
                buffer = buffer[size - overlap:]
        if buffer:
            chunks.append(Chunk(page.number, ordinal, _join(buffer)))
            ordinal += 1
    return chunks


def _join(tokens: List[str]) -> str:
    return re.sub(r" ?\n ?", "\n", " ".join(tokens)).strip()
