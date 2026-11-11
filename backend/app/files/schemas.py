from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    created_at: Optional[str] = None
    modified_at: Optional[str] = None
    page_count: int = 0
    sheet_count: int = 0
    slide_count: int = 0
    word_count: int = 0
    size_bytes: int = 0
    size_formatted: str = "0 B"
    format: str = "unknown"
    mime_type: str = "application/octet-stream"
    is_encrypted: bool = False
    is_scanned: bool = False


class DocumentSection(BaseModel):
    section_index: int
    title: Optional[str] = None
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    slide_number: Optional[int] = None
    content: str
    token_estimate: int = 0


class TableData(BaseModel):
    name: str = "Table"
    headers: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    row_count: int = 0
    col_count: int = 0


class ParsedDocument(BaseModel):
    path: str
    filename: str
    format: str
    metadata: DocumentMetadata
    sections: List[DocumentSection] = Field(default_factory=list)
    text_content: str = ""
    tables: List[TableData] = Field(default_factory=list)
    is_scanned: bool = False
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    success: bool = True


class SearchResultChunk(BaseModel):
    doc_id: int
    filename: str
    path: str
    format: str
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    slide_number: Optional[int] = None
    section_title: Optional[str] = None
    snippet: str
    score: float = 0.0
    match_type: str = "fts5"


class SearchResponse(BaseModel):
    query: str
    total_matches: int
    results: List[SearchResultChunk] = Field(default_factory=list)
    search_mode: str = "fts5_bm25"


class IndexStatus(BaseModel):
    total_documents: int = 0
    total_chunks: int = 0
    formats_breakdown: Dict[str, int] = Field(default_factory=dict)
    last_indexed_at: Optional[str] = None
    index_storage_mb: float = 0.0


class SpreadsheetColumnProfile(BaseModel):
    name: str
    dtype: str
    non_null_count: int = 0
    null_count: int = 0
    distinct_count: int = 0
    sample_values: List[Any] = Field(default_factory=list)
    min_val: Optional[Any] = None
    max_val: Optional[Any] = None
    mean_val: Optional[float] = None
    median_val: Optional[float] = None


class SpreadsheetProfile(BaseModel):
    filename: str
    sheet_names: List[str] = Field(default_factory=list)
    active_sheet: str
    row_count: int = 0
    col_count: int = 0
    columns: List[SpreadsheetColumnProfile] = Field(default_factory=list)
    duplicate_row_count: int = 0
    formulas_detected: List[str] = Field(default_factory=list)
    preview_rows: List[Dict[str, Any]] = Field(default_factory=list)
    chart_ready_data: Optional[Dict[str, Any]] = None


class DuplicateFileInfo(BaseModel):
    path: str
    filename: str
    size_bytes: int
    modified_at: str


class DuplicateGroup(BaseModel):
    sha256: str
    file_count: int
    wasted_bytes: int
    wasted_formatted: str
    files: List[DuplicateFileInfo] = Field(default_factory=list)


class FileOrgItem(BaseModel):
    path: str
    filename: str
    size_bytes: int
    category: str
    reason: str
    suggested_action: str
    target_path: Optional[str] = None


class FileOrgPreview(BaseModel):
    scanned_path: str
    total_scanned: int
    duplicate_groups: List[DuplicateGroup] = Field(default_factory=list)
    large_files: List[FileOrgItem] = Field(default_factory=list)
    old_files: List[FileOrgItem] = Field(default_factory=list)
    empty_folders: List[str] = Field(default_factory=list)
    proposed_actions: List[FileOrgItem] = Field(default_factory=list)
    can_execute: bool = False


class FileOrgExecutionResult(BaseModel):
    success: bool
    executed_count: int
    failed_count: int
    rollback_token: Optional[str] = None
    details: List[Dict[str, Any]] = Field(default_factory=list)


class DocumentCitation(BaseModel):
    document_name: str
    path: str
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    slide_number: Optional[int] = None
    section_title: Optional[str] = None
    exact_quote: str


class DocumentQAResult(BaseModel):
    question: str
    answer: str
    directly_extracted: str = ""
    model_interpretation: str = ""
    citations: List[DocumentCitation] = Field(default_factory=list)
    is_grounded: bool = True
    sources_consulted: List[str] = Field(default_factory=list)


class DocumentCompareResult(BaseModel):
    doc_a_name: str
    doc_b_name: str
    similarity_score: float
    common_sections: List[str] = Field(default_factory=list)
    unique_to_a: List[str] = Field(default_factory=list)
    unique_to_b: List[str] = Field(default_factory=list)
    summary_diff: str

