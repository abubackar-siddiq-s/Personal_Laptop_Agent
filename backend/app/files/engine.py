from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.security import audit
from app.files.indexer import (
    clear_document_index,
    get_index_status,
    index_directory,
    index_file,
    search_documents,
)
from app.files.organizer import (
    execute_file_organization,
    find_duplicates,
    preview_file_organization,
    rollback_file_organization,
)
from app.files.parsers import parse_document
from app.files.schemas import (
    DocumentCompareResult,
    DocumentQAResult,
    IndexStatus,
    ParsedDocument,
    SearchResponse,
    SpreadsheetProfile,
)
from app.files.security import is_emergency_stopped
from app.files.spreadsheet import profile_spreadsheet, query_spreadsheet
from app.files.understanding import (
    ask_document,
    compare_documents,
    summarize_document,
)


class FileIntelligenceEngine:
    """
    Central coordinator for Phase 6 Queue 3 Advanced File Intelligence.
    Provides unified access to document parsing, FTS5 semantic search,
    spreadsheet intelligence, document Q&A, and safe file organization.
    """

    def __init__(self):
        pass

    def extract_document(self, file_path: str | Path) -> ParsedDocument:
        """Extract text, sections, metadata, and tables from any supported document."""
        audit("files.document.extract", {"path": str(file_path)})
        return parse_document(file_path)

    def summarize_document(self, file_path: str | Path, max_sentences: int = 5) -> Dict[str, Any]:
        """Generate structured extract-based summary, key points, and classification."""
        audit("files.document.summarize", {"path": str(file_path)})
        return summarize_document(file_path, max_summary_sentences=max_sentences)

    def ask_document(self, file_path: str | Path, question: str) -> DocumentQAResult:
        """Answer questions about document text with verifiable page/sheet/slide citations."""
        audit("files.document.ask", {"path": str(file_path), "question": question})
        return ask_document(file_path, question)

    def compare_documents(self, file_a: str | Path, file_b: str | Path) -> DocumentCompareResult:
        """Compare two documents structurally and semantically."""
        audit("files.document.compare", {"file_a": str(file_a), "file_b": str(file_b)})
        return compare_documents(file_a, file_b)

    def search_index(self, query: str, limit: int = 10, format_filter: Optional[str] = None) -> SearchResponse:
        """Perform full-text search with BM25 ranking across all indexed document chunks."""
        audit("files.search.semantic", {"query": query, "limit": limit, "filter": format_filter})
        return search_documents(query, limit=limit, format_filter=format_filter)

    def get_index_status(self) -> IndexStatus:
        """Get total indexed documents, chunks, formats, and storage volume."""
        return get_index_status()

    def refresh_index(self, path: str | Path, recursive: bool = True, max_files: int = 100) -> Dict[str, Any]:
        """Index a single document or directory of documents incrementally."""
        audit("files.index.refresh", {"path": str(path), "recursive": recursive})
        p = Path(path)
        if p.is_file():
            res = index_file(p, force=True)
            return {"type": "file", "result": res}
        return index_directory(p, recursive=recursive, max_files=max_files)

    def clear_index(self) -> Dict[str, Any]:
        """Purge all indexed chunks and documents from SQLite."""
        audit("files.index.clear", {})
        return clear_document_index()

    def profile_spreadsheet(
        self,
        file_path: str | Path,
        sheet_name: Optional[str] = None,
        max_preview: int = 50,
    ) -> SpreadsheetProfile:
        """Analyze and profile XLSX/CSV spreadsheets with column statistics and chart datasets."""
        audit("files.spreadsheet.analyze", {"path": str(file_path), "sheet": sheet_name})
        return profile_spreadsheet(file_path, sheet_name=sheet_name, max_rows_preview=max_preview)

    def query_spreadsheet(
        self,
        file_path: str | Path,
        filter_col: Optional[str] = None,
        filter_val: Optional[str] = None,
        sort_by: Optional[str] = None,
        descending: bool = False,
        sheet_name: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Filter and sort tabular spreadsheet data safely in read-only mode."""
        audit("files.spreadsheet.query", {"path": str(file_path), "filter_col": filter_col})
        return query_spreadsheet(
            file_path,
            filter_column=filter_col,
            filter_value=filter_val,
            sort_by=sort_by,
            descending=descending,
            sheet_name=sheet_name,
            limit=limit,
        )

    def find_duplicates(self, folder_path: str | Path, max_files: int = 300) -> List[Any]:
        """Find duplicate files using SHA-256 hashes and calculate wasted disk space."""
        audit("files.duplicates.find", {"folder": str(folder_path)})
        return [g.model_dump() for g in find_duplicates(folder_path, max_files=max_files)]

    def preview_organization(self, folder_path: str | Path) -> Dict[str, Any]:
        """Generate read-only preview of proposed file organization and clean-up actions."""
        audit("files.organize.preview", {"folder": str(folder_path)})
        return preview_file_organization(folder_path).model_dump()

    def execute_organization(
        self,
        action_items: List[Dict[str, Any]],
        quarantine_root: Optional[str | Path] = None,
    ) -> Dict[str, Any]:
        """
        Execute proposed file reorganization safely.
        Requires explicit user approval (enforced via risk='approval').
        """
        audit("files.organize.execute", {"action_count": len(action_items)})
        res = execute_file_organization(action_items, quarantine_root=quarantine_root)
        return res.model_dump()

    def rollback_organization(self, rollback_token: str) -> Dict[str, Any]:
        """Roll back file organization actions to original paths."""
        audit("files.organize.rollback", {"token": rollback_token})
        return rollback_file_organization(rollback_token)


engine = FileIntelligenceEngine()

