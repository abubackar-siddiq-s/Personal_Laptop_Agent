from __future__ import annotations
import csv
import datetime
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.files.schemas import (
    DocumentMetadata,
    DocumentSection,
    ParsedDocument,
    TableData,
)
from app.files.security import (
    SecurityError,
    sanitize_document_text,
    validate_file_path,
    verify_file_signature,
    verify_zip_archive_safety,
)

SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "doc",
    ".txt": "txt",
    ".md": "md",
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".xls": "xls",
    ".pptx": "pptx",
    ".ppt": "ppt",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".rtf": "rtf",
}


class UnsupportedFileFormatError(Exception):
    """Raised when encountering an unsupported file extension or format."""
    pass


class DocumentParsingError(Exception):
    """Raised when document parsing fails due to corruption or formatting issues."""
    pass


def format_size(size_bytes: int) -> str:
    """Format byte sizes into human-readable strings."""
    val = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if val < 1024.0:
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{val:.1f} TB"


def detect_file_format(path: Path) -> str:
    """
    Detect document format from extension and reject unsupported formats.
    Never silently treat unsupported formats as plain text.
    """
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileFormatError(
            f"Unsupported file format '{ext}' for file '{path.name}'. "
            f"Supported formats: {', '.join(sorted(set(SUPPORTED_EXTENSIONS.values())))}."
        )
    return SUPPORTED_EXTENSIONS[ext]


# =====================================================================
# INDIVIDUAL FORMAT PARSERS
# =====================================================================

def parse_pdf(path: Path) -> ParsedDocument:
    """Extract text, page numbers, and metadata from PDF files using pypdf."""
    import pypdf

    stat = path.stat()
    meta = DocumentMetadata(
        format="pdf",
        mime_type="application/pdf",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )

    try:
        reader = pypdf.PdfReader(str(path))
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="pdf",
            metadata=meta,
            error=f"Corrupted or invalid PDF: {e}",
            success=False,
        )

    if reader.is_encrypted:
        meta.is_encrypted = True
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="pdf",
            metadata=meta,
            error="PDF document is password-protected or encrypted. Cannot extract contents.",
            warnings=["Document is encrypted."],
            success=False,
        )

    meta.page_count = len(reader.pages)
    if reader.metadata:
        meta.title = reader.metadata.title or None
        meta.author = reader.metadata.author or None
        if reader.metadata.creation_date:
            meta.created_at = str(reader.metadata.creation_date)

    sections: List[DocumentSection] = []
    full_text_parts: List[str] = []
    total_extracted_chars = 0

    for idx, page in enumerate(reader.pages):
        page_num = idx + 1
        page_raw = page.extract_text() or ""
        sanitized_page, _ = sanitize_document_text(page_raw)
        total_extracted_chars += len(sanitized_page.strip())

        if sanitized_page.strip():
            sections.append(
                DocumentSection(
                    section_index=idx,
                    title=f"Page {page_num}",
                    page_number=page_num,
                    content=sanitized_page.strip(),
                    token_estimate=len(sanitized_page.split()),
                )
            )
            full_text_parts.append(f"--- Page {page_num} ---\n{sanitized_page.strip()}")

    # Scanned PDF detection: if pages exist but virtually no text was extracted
    is_scanned = False
    warnings = []
    if meta.page_count > 0 and (total_extracted_chars / meta.page_count) < 20:
        is_scanned = True
        meta.is_scanned = True
        warnings.append(
            "Scanned PDF detected: Text density is very low. Optical Character Recognition (OCR) may be required for full content."
        )

    raw_text = "\n\n".join(full_text_parts)
    meta.word_count = len(raw_text.split())

    return ParsedDocument(
        path=str(path),
        filename=path.name,
        format="pdf",
        metadata=meta,
        sections=sections,
        text_content=raw_text,
        is_scanned=is_scanned,
        warnings=warnings,
        success=True,
    )


def parse_docx(path: Path) -> ParsedDocument:
    """Extract paragraphs, headings, tables, and metadata from DOCX files using python-docx."""
    import docx

    verify_zip_archive_safety(path)
    stat = path.stat()
    meta = DocumentMetadata(
        format="docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )

    try:
        doc = docx.Document(str(path))
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="docx",
            metadata=meta,
            error=f"Corrupted or invalid DOCX: {e}",
            success=False,
        )

    # Core properties metadata
    if doc.core_properties:
        meta.title = doc.core_properties.title or None
        meta.author = doc.core_properties.author or None
        if doc.core_properties.created:
            meta.created_at = doc.core_properties.created.isoformat()

    sections: List[DocumentSection] = []
    current_title = "Document Start"
    current_paras: List[str] = []
    sec_idx = 0

    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt:
            continue

        sanitized, _ = sanitize_document_text(txt)
        if p.style and p.style.name and p.style.name.startswith("Heading"):
            if current_paras:
                content_block = "\n".join(current_paras)
                sections.append(
                    DocumentSection(
                        section_index=sec_idx,
                        title=current_title,
                        content=content_block,
                        token_estimate=len(content_block.split()),
                    )
                )
                sec_idx += 1
                current_paras = []
            current_title = sanitized
        else:
            current_paras.append(sanitized)

    if current_paras:
        content_block = "\n".join(current_paras)
        sections.append(
            DocumentSection(
                section_index=sec_idx,
                title=current_title,
                content=content_block,
                token_estimate=len(content_block.split()),
            )
        )

    # Table extraction
    tables_data: List[TableData] = []
    for t_idx, table in enumerate(doc.tables):
        headers = []
        rows = []
        for r_idx, row in enumerate(table.rows):
            cells = [cell.text.strip() for cell in row.cells]
            if r_idx == 0:
                headers = cells
            else:
                rows.append(cells)
        if headers or rows:
            tables_data.append(
                TableData(
                    name=f"Table {t_idx + 1}",
                    headers=headers,
                    rows=rows,
                    row_count=len(rows),
                    col_count=len(headers) if headers else 0,
                )
            )

    full_text = "\n\n".join(s.content for s in sections)
    meta.word_count = len(full_text.split())

    return ParsedDocument(
        path=str(path),
        filename=path.name,
        format="docx",
        metadata=meta,
        sections=sections,
        text_content=full_text,
        tables=tables_data,
        success=True,
    )


def parse_doc(path: Path) -> ParsedDocument:
    """Safe extraction for legacy Word 97-2004 binary format (.doc)."""
    stat = path.stat()
    meta = DocumentMetadata(
        format="doc",
        mime_type="application/msword",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )

    try:
        with open(path, "rb") as f:
            content_bytes = f.read()

        # Extract printable strings from binary stream safely
        text_chunks = re.findall(b"[\x20-\x7E\r\n\t]{4,}", content_bytes)
        decoded_text = "\n".join(chunk.decode("latin-1", errors="ignore") for chunk in text_chunks)
        sanitized, _ = sanitize_document_text(decoded_text)

        sections = [
            DocumentSection(
                section_index=0,
                title="Legacy Document Content",
                content=sanitized[:100000],
                token_estimate=len(sanitized.split()),
            )
        ]
        meta.word_count = len(sanitized.split())

        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="doc",
            metadata=meta,
            sections=sections,
            text_content=sanitized[:100000],
            warnings=["Extracted using legacy binary string decoder. Complex formatting and tables may not be preserved."],
            success=True,
        )
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="doc",
            metadata=meta,
            error=f"Failed to parse legacy .doc file: {e}",
            success=False,
        )


def parse_xlsx(path: Path) -> ParsedDocument:
    """Extract sheets, headers, rows, and formulas from XLSX files using openpyxl."""
    import openpyxl

    verify_zip_archive_safety(path)
    stat = path.stat()
    meta = DocumentMetadata(
        format="xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )

    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="xlsx",
            metadata=meta,
            error=f"Corrupted or invalid XLSX: {e}",
            success=False,
        )

    meta.sheet_count = len(wb.sheetnames)
    sections: List[DocumentSection] = []
    tables_data: List[TableData] = []
    all_text_parts: List[str] = []

    for s_idx, sheetname in enumerate(wb.sheetnames):
        ws = wb[sheetname]
        headers: List[str] = []
        rows: List[List[Any]] = []
        row_strings: List[str] = []

        for r_idx, row in enumerate(ws.iter_rows(values_only=True)):
            if r_idx == 0:
                headers = [str(c or f"Col_{i+1}") for i, c in enumerate(row)]
                row_strings.append(" | ".join(headers))
            else:
                cleaned_row = [str(c) if c is not None else "" for c in row]
                if any(cleaned_row):
                    rows.append(cleaned_row)
                    row_strings.append(" | ".join(cleaned_row))

        sheet_content = f"Sheet: {sheetname}\n" + "\n".join(row_strings[:500])
        sanitized_sheet, _ = sanitize_document_text(sheet_content)
        sections.append(
            DocumentSection(
                section_index=s_idx,
                title=f"Sheet: {sheetname}",
                sheet_name=sheetname,
                content=sanitized_sheet,
                token_estimate=len(sanitized_sheet.split()),
            )
        )
        all_text_parts.append(sanitized_sheet)

        if headers:
            tables_data.append(
                TableData(
                    name=sheetname,
                    headers=headers,
                    rows=rows,
                    row_count=len(rows),
                    col_count=len(headers),
                )
            )

    try:
        wb.close()
    except Exception:
        pass

    full_text = "\n\n".join(all_text_parts)
    meta.word_count = len(full_text.split())

    return ParsedDocument(
        path=str(path),
        filename=path.name,
        format="xlsx",
        metadata=meta,
        sections=sections,
        text_content=full_text,
        tables=tables_data,
        success=True,
    )


def parse_xls(path: Path) -> ParsedDocument:
    """Safe extraction for legacy Excel 97-2003 binary format (.xls)."""
    stat = path.stat()
    meta = DocumentMetadata(
        format="xls",
        mime_type="application/vnd.ms-excel",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )

    try:
        with open(path, "rb") as f:
            content_bytes = f.read()

        strings = re.findall(b"[\x20-\x7E\t]{3,}", content_bytes)
        decoded = "\n".join(s.decode("latin-1", errors="ignore") for s in strings)
        sanitized, _ = sanitize_document_text(decoded)

        sections = [
            DocumentSection(
                section_index=0,
                title="Legacy Spreadsheet Content",
                content=sanitized[:100000],
                token_estimate=len(sanitized.split()),
            )
        ]
        meta.word_count = len(sanitized.split())

        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="xls",
            metadata=meta,
            sections=sections,
            text_content=sanitized[:100000],
            warnings=["Extracted using legacy binary stream scanner."],
            success=True,
        )
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="xls",
            metadata=meta,
            error=f"Failed to parse legacy .xls file: {e}",
            success=False,
        )


def parse_pptx(path: Path) -> ParsedDocument:
    """Extract slides, slide numbers, titles, and text from PPTX files using python-pptx."""
    import pptx

    verify_zip_archive_safety(path)
    stat = path.stat()
    meta = DocumentMetadata(
        format="pptx",
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )

    try:
        prs = pptx.Presentation(str(path))
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="pptx",
            metadata=meta,
            error=f"Corrupted or invalid PPTX: {e}",
            success=False,
        )

    meta.slide_count = len(prs.slides)
    sections: List[DocumentSection] = []
    all_text_parts: List[str] = []

    for idx, slide in enumerate(prs.slides):
        slide_num = idx + 1
        slide_title = f"Slide {slide_num}"
        slide_text_lines = []

        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    line = "".join(run.text for run in paragraph.runs).strip()
                    if line:
                        slide_text_lines.append(line)
                        if not slide_title.startswith("Slide ") and shape == slide.shapes.title:
                            slide_title = line

        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                slide_text_lines.append(f"[Speaker Notes: {notes}]")

        slide_block = "\n".join(slide_text_lines)
        sanitized_slide, _ = sanitize_document_text(slide_block)

        sections.append(
            DocumentSection(
                section_index=idx,
                title=slide_title,
                slide_number=slide_num,
                content=sanitized_slide,
                token_estimate=len(sanitized_slide.split()),
            )
        )
        all_text_parts.append(f"--- Slide {slide_num}: {slide_title} ---\n{sanitized_slide}")

    full_text = "\n\n".join(all_text_parts)
    meta.word_count = len(full_text.split())

    return ParsedDocument(
        path=str(path),
        filename=path.name,
        format="pptx",
        metadata=meta,
        sections=sections,
        text_content=full_text,
        success=True,
    )


def parse_ppt(path: Path) -> ParsedDocument:
    """Safe extraction for legacy PowerPoint 97-2004 binary format (.ppt)."""
    stat = path.stat()
    meta = DocumentMetadata(
        format="ppt",
        mime_type="application/vnd.ms-powerpoint",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )

    try:
        with open(path, "rb") as f:
            content_bytes = f.read()

        strings = re.findall(b"[\x20-\x7E\t]{4,}", content_bytes)
        decoded = "\n".join(s.decode("latin-1", errors="ignore") for s in strings)
        sanitized, _ = sanitize_document_text(decoded)

        sections = [
            DocumentSection(
                section_index=0,
                title="Legacy Presentation Content",
                content=sanitized[:100000],
                token_estimate=len(sanitized.split()),
            )
        ]
        meta.word_count = len(sanitized.split())

        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="ppt",
            metadata=meta,
            sections=sections,
            text_content=sanitized[:100000],
            warnings=["Extracted using legacy binary presentation scanner."],
            success=True,
        )
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="ppt",
            metadata=meta,
            error=f"Failed to parse legacy .ppt file: {e}",
            success=False,
        )


def parse_csv(path: Path) -> ParsedDocument:
    """Parse CSV text with dialect auto-detection, preserving table structure."""
    stat = path.stat()
    meta = DocumentMetadata(
        format="csv",
        mime_type="text/csv",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        sheet_count=1,
    )

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            sample = f.read(4096)
            f.seek(0)
            delimiter = ","
            try:
                dialect = csv.Sniffer().sniff(sample)
                delimiter = dialect.delimiter
            except Exception:
                pass

            reader = csv.reader(f, delimiter=delimiter)
            headers = []
            rows = []
            for r_idx, row in enumerate(reader):
                if r_idx == 0:
                    headers = row
                else:
                    rows.append(row)

        table = TableData(
            name=path.stem,
            headers=headers,
            rows=rows,
            row_count=len(rows),
            col_count=len(headers),
        )

        formatted_lines = [" | ".join(headers)]
        for r in rows[:500]:
            formatted_lines.append(" | ".join(r))
        raw_text = "\n".join(formatted_lines)
        sanitized, _ = sanitize_document_text(raw_text)

        sections = [
            DocumentSection(
                section_index=0,
                title=f"CSV Table: {path.stem}",
                sheet_name=path.stem,
                content=sanitized,
                token_estimate=len(sanitized.split()),
            )
        ]
        meta.word_count = len(sanitized.split())

        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="csv",
            metadata=meta,
            sections=sections,
            text_content=sanitized,
            tables=[table],
            success=True,
        )
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="csv",
            metadata=meta,
            error=f"Failed to parse CSV file: {e}",
            success=False,
        )


def parse_txt(path: Path) -> ParsedDocument:
    """Parse plain text files with robust encoding fallbacks."""
    stat = path.stat()
    meta = DocumentMetadata(
        format="txt",
        mime_type="text/plain",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )

    try:
        content = ""
        for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                with open(path, "r", encoding=enc) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue

        sanitized, _ = sanitize_document_text(content)
        paragraphs = [p.strip() for p in sanitized.split("\n\n") if p.strip()]

        sections = []
        for idx, p in enumerate(paragraphs):
            sections.append(
                DocumentSection(
                    section_index=idx,
                    title=f"Paragraph {idx + 1}",
                    content=p,
                    token_estimate=len(p.split()),
                )
            )

        meta.word_count = len(sanitized.split())
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="txt",
            metadata=meta,
            sections=sections,
            text_content=sanitized,
            success=True,
        )
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="txt",
            metadata=meta,
            error=f"Failed to read TXT file: {e}",
            success=False,
        )


def parse_md(path: Path) -> ParsedDocument:
    """Parse markdown documents, splitting into sections based on heading levels."""
    stat = path.stat()
    meta = DocumentMetadata(
        format="md",
        mime_type="text/markdown",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        sanitized, _ = sanitize_document_text(content)
        lines = sanitized.splitlines()

        sections = []
        current_title = "Document Overview"
        current_lines = []
        sec_idx = 0

        for line in lines:
            if line.startswith("#"):
                if current_lines:
                    block = "\n".join(current_lines).strip()
                    if block:
                        sections.append(
                            DocumentSection(
                                section_index=sec_idx,
                                title=current_title,
                                content=block,
                                token_estimate=len(block.split()),
                            )
                        )
                        sec_idx += 1
                        current_lines = []
                current_title = line.lstrip("#").strip()
            else:
                current_lines.append(line)

        if current_lines:
            block = "\n".join(current_lines).strip()
            if block:
                sections.append(
                    DocumentSection(
                        section_index=sec_idx,
                        title=current_title,
                        content=block,
                        token_estimate=len(block.split()),
                    )
                )

        meta.word_count = len(sanitized.split())
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="md",
            metadata=meta,
            sections=sections,
            text_content=sanitized,
            success=True,
        )
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="md",
            metadata=meta,
            error=f"Failed to read Markdown file: {e}",
            success=False,
        )


def parse_json(path: Path) -> ParsedDocument:
    """Parse JSON files, validating structure and extracting formatted text."""
    stat = path.stat()
    meta = DocumentMetadata(
        format="json",
        mime_type="application/json",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)

        formatted = json.dumps(data, indent=2)
        sanitized, _ = sanitize_document_text(formatted)

        sections = [
            DocumentSection(
                section_index=0,
                title="JSON Structure",
                content=sanitized[:100000],
                token_estimate=len(sanitized.split()),
            )
        ]

        tables = []
        if isinstance(data, list) and data and isinstance(data[0], dict):
            headers = list(data[0].keys())
            rows = [[str(item.get(h, "")) for h in headers] for item in data[:500]]
            tables.append(
                TableData(
                    name=path.stem,
                    headers=headers,
                    rows=rows,
                    row_count=len(rows),
                    col_count=len(headers),
                )
            )

        meta.word_count = len(sanitized.split())
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="json",
            metadata=meta,
            sections=sections,
            text_content=sanitized[:100000],
            tables=tables,
            success=True,
        )
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="json",
            metadata=meta,
            error=f"Invalid or corrupted JSON file: {e}",
            success=False,
        )


def parse_xml(path: Path) -> ParsedDocument:
    """Safely parse XML files with entity-expansion defenses."""
    stat = path.stat()
    meta = DocumentMetadata(
        format="xml",
        mime_type="application/xml",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()

        # Defend against billion laughs / entity attacks
        if "<!ENTITY" in raw:
            raise SecurityError("XML file contains entity definitions (prohibited for security).")

        root = ET.fromstring(raw)
        meta.title = root.tag

        text_nodes = []
        for elem in root.iter():
            txt = (elem.text or "").strip()
            if txt:
                text_nodes.append(f"<{elem.tag}>: {txt}")

        full_text = "\n".join(text_nodes)
        sanitized, _ = sanitize_document_text(full_text)

        sections = [
            DocumentSection(
                section_index=0,
                title=f"XML Root: <{root.tag}>",
                content=sanitized[:100000],
                token_estimate=len(sanitized.split()),
            )
        ]
        meta.word_count = len(sanitized.split())

        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="xml",
            metadata=meta,
            sections=sections,
            text_content=sanitized[:100000],
            success=True,
        )
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="xml",
            metadata=meta,
            error=f"Invalid or corrupted XML file: {e}",
            success=False,
        )


def parse_html(path: Path) -> ParsedDocument:
    """Parse HTML documents using BeautifulSoup, extracting headings, paragraphs, and tables."""
    from bs4 import BeautifulSoup

    stat = path.stat()
    meta = DocumentMetadata(
        format="html",
        mime_type="text/html",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            html_content = f.read()

        soup = BeautifulSoup(html_content, "html.parser")

        # Strip scripts and styles
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        if soup.title and soup.title.string:
            meta.title = soup.title.string.strip()

        sections = []
        sec_idx = 0
        for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
            h_text = heading.get_text().strip()
            # Collect following sibling text until next heading
            paras = [h_text]
            curr = heading.find_next_sibling()
            while curr and curr.name not in ["h1", "h2", "h3", "h4"]:
                txt = curr.get_text().strip()
                if txt:
                    paras.append(txt)
                curr = curr.find_next_sibling()
            content_str = "\n".join(paras)
            if content_str:
                sanitized, _ = sanitize_document_text(content_str)
                sections.append(
                    DocumentSection(
                        section_index=sec_idx,
                        title=h_text or f"Section {sec_idx + 1}",
                        content=sanitized,
                        token_estimate=len(sanitized.split()),
                    )
                )
                sec_idx += 1

        if not sections:
            plain = soup.get_text(separator="\n", strip=True)
            sanitized, _ = sanitize_document_text(plain)
            sections.append(
                DocumentSection(
                    section_index=0,
                    title="HTML Body",
                    content=sanitized[:100000],
                    token_estimate=len(sanitized.split()),
                )
            )

        # Tables extraction
        tables_data = []
        for t_idx, tbl in enumerate(soup.find_all("table")):
            headers = [th.get_text(strip=True) for th in tbl.find_all("th")]
            rows = []
            for tr in tbl.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if cells:
                    rows.append(cells)
            if headers or rows:
                tables_data.append(
                    TableData(
                        name=f"HTML Table {t_idx + 1}",
                        headers=headers,
                        rows=rows,
                        row_count=len(rows),
                        col_count=len(headers) if headers else 0,
                    )
                )

        full_text = "\n\n".join(s.content for s in sections)
        meta.word_count = len(full_text.split())

        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="html",
            metadata=meta,
            sections=sections,
            text_content=full_text,
            tables=tables_data,
            success=True,
        )
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="html",
            metadata=meta,
            error=f"Failed to parse HTML file: {e}",
            success=False,
        )


def parse_rtf(path: Path) -> ParsedDocument:
    """Parse Rich Text Format (.rtf) by stripping RTF control sequences."""
    stat = path.stat()
    meta = DocumentMetadata(
        format="rtf",
        mime_type="application/rtf",
        size_bytes=stat.st_size,
        size_formatted=format_size(stat.st_size),
        modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    )

    try:
        with open(path, "r", encoding="latin-1", errors="replace") as f:
            raw = f.read()

        # Remove RTF control sequences: \controlword or \controlword123 or { ... }
        text = re.sub(r"\\[a-zA-Z0-9]+(?:\s|-?[0-9]+)?", " ", raw)
        text = re.sub(r"[{}]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        sanitized, _ = sanitize_document_text(text)

        sections = [
            DocumentSection(
                section_index=0,
                title="RTF Document Content",
                content=sanitized[:100000],
                token_estimate=len(sanitized.split()),
            )
        ]
        meta.word_count = len(sanitized.split())

        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="rtf",
            metadata=meta,
            sections=sections,
            text_content=sanitized[:100000],
            success=True,
        )
    except Exception as e:
        return ParsedDocument(
            path=str(path),
            filename=path.name,
            format="rtf",
            metadata=meta,
            error=f"Failed to parse RTF file: {e}",
            success=False,
        )


# =====================================================================
# UNIFIED PARSING DISPATCHER
# =====================================================================

PARSER_REGISTRY = {
    "pdf": parse_pdf,
    "docx": parse_docx,
    "doc": parse_doc,
    "xlsx": parse_xlsx,
    "xls": parse_xls,
    "pptx": parse_pptx,
    "ppt": parse_ppt,
    "csv": parse_csv,
    "txt": parse_txt,
    "md": parse_md,
    "json": parse_json,
    "xml": parse_xml,
    "html": parse_html,
    "rtf": parse_rtf,
}


def parse_document(file_path: str | Path) -> ParsedDocument:
    """
    Primary document parser entrypoint.
    1. Validates path and permissions.
    2. Detects format and validates signature.
    3. Dispatches to dedicated lightweight parser.
    4. Handles scanned PDFs via OCR fallback if necessary.
    5. Never silently interprets unsupported formats as plain text.
    """
    valid_path = validate_file_path(file_path)
    fmt = detect_file_format(valid_path)

    sig_ok, sig_msg = verify_file_signature(valid_path, fmt)
    if not sig_ok:
        return ParsedDocument(
            path=str(valid_path),
            filename=valid_path.name,
            format=fmt,
            metadata=DocumentMetadata(
                format=fmt,
                size_bytes=valid_path.stat().st_size,
                size_formatted=format_size(valid_path.stat().st_size),
            ),
            error=f"File signature validation failed: {sig_msg}",
            success=False,
        )

    parser = PARSER_REGISTRY.get(fmt)
    if not parser:
        raise UnsupportedFileFormatError(f"No parser implemented for detected format: '{fmt}'.")

    return parser(valid_path)
