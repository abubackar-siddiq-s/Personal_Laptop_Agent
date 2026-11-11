from __future__ import annotations
from typing import Any, Dict, List, Optional
from app.files.engine import engine
from app.tools.registry import Spec, registry


def register_file_tools():
    """Register all 12 Advanced File Intelligence tools in the central tool registry."""

    # 1. files.document.extract
    registry.add(
        Spec(
            name="files.document.extract",
            description=(
                "Extract structured text, sections, metadata, and tables from any supported document "
                "(PDF, DOCX, XLSX, PPTX, CSV, TXT, MD, JSON, XML, HTML, RTF). "
                "Preserves page numbers, sheet names, and slide numbers."
            ),
            source="files",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path or filename to the document to extract.",
                    }
                },
                "required": ["path"],
            },
            handler=lambda path, **kwargs: engine.extract_document(path).model_dump(),
        )
    )

    # 2. files.document.summarize
    registry.add(
        Spec(
            name="files.document.summarize",
            description=(
                "Generate an extract-based summary, key takeaways, and document classification "
                "for any supported document without hallucinating contents."
            ),
            source="files",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the document to summarize.",
                    },
                    "max_sentences": {
                        "type": "integer",
                        "description": "Maximum number of summary sentences to return (default 5).",
                        "default": 5,
                    },
                },
                "required": ["path"],
            },
            handler=lambda path, max_sentences=5, **kwargs: engine.summarize_document(path, max_sentences=max_sentences),
        )
    )

    # 3. files.document.ask
    registry.add(
        Spec(
            name="files.document.ask",
            description=(
                "Ask a factual question about a document. Returns an answer strictly grounded in "
                "extracted text with verifiable citations (page, sheet, or slide numbers)."
            ),
            source="files",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the document to query.",
                    },
                    "question": {
                        "type": "string",
                        "description": "Natural language question about the document content.",
                    },
                },
                "required": ["path", "question"],
            },
            handler=lambda path, question, **kwargs: engine.ask_document(path, question).model_dump(),
        )
    )

    # 4. files.document.compare
    registry.add(
        Spec(
            name="files.document.compare",
            description=(
                "Compare two documents structurally and semantically. Returns vocabulary similarity, "
                "common sections, and sections unique to each document."
            ),
            source="files",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "file_a": {
                        "type": "string",
                        "description": "Path to the first document.",
                    },
                    "file_b": {
                        "type": "string",
                        "description": "Path to the second document.",
                    },
                },
                "required": ["file_a", "file_b"],
            },
            handler=lambda file_a, file_b, **kwargs: engine.compare_documents(file_a, file_b).model_dump(),
        )
    )

    # 5. files.search.semantic
    registry.add(
        Spec(
            name="files.search.semantic",
            description=(
                "Search indexed document chunks using SQLite FTS5 with BM25 relevance ranking. "
                "Returns matching snippets with highlighted search terms and exact source citations."
            ),
            source="files",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query terms or phrase.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of search results to return (default 10).",
                        "default": 10,
                    },
                    "format_filter": {
                        "type": "string",
                        "description": "Optional format filter (e.g. 'pdf', 'docx', 'xlsx').",
                    },
                },
                "required": ["query"],
            },
            handler=lambda query, limit=10, format_filter=None, **kwargs: engine.search_index(
                query, limit=limit, format_filter=format_filter
            ).model_dump(),
        )
    )

    # 6. files.search.content
    registry.add(
        Spec(
            name="files.search.content",
            description=(
                "Content-level keyword search across indexed documents with BM25 snippet retrieval."
            ),
            source="files",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword or phrase.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results.",
                        "default": 10,
                    },
                    "format_filter": {
                        "type": "string",
                        "description": "Format filter (e.g. 'pdf', 'csv').",
                    },
                },
                "required": ["query"],
            },
            handler=lambda query, limit=10, format_filter=None, **kwargs: engine.search_index(
                query, limit=limit, format_filter=format_filter
            ).model_dump(),
        )
    )

    # 7. files.index.status
    registry.add(
        Spec(
            name="files.index.status",
            description="Retrieve status and metrics of the local document index (total documents, chunks, and storage).",
            source="files",
            risk="read",
            schema={"type": "object", "properties": {}},
            handler=lambda **kwargs: engine.get_index_status().model_dump(),
        )
    )

    # 8. files.index.refresh
    registry.add(
        Spec(
            name="files.index.refresh",
            description="Index or update full-text search index for a file or directory of documents.",
            source="files",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to document file or folder to index.",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Whether to index subdirectories recursively (default True).",
                        "default": True,
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "Maximum number of files to index in a single run (default 100).",
                        "default": 100,
                    },
                },
                "required": ["path"],
            },
            handler=lambda path, recursive=True, max_files=100, **kwargs: engine.refresh_index(
                path, recursive=recursive, max_files=max_files
            ),
        )
    )

    # 9. files.spreadsheet.analyze
    registry.add(
        Spec(
            name="files.spreadsheet.analyze",
            description=(
                "Analyze and profile an XLSX or CSV spreadsheet. Computes row counts, column data types, "
                "missing values, duplicate rows, formulas, and numeric statistical summaries."
            ),
            source="files",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the .xlsx or .csv spreadsheet file.",
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": "Optional specific worksheet name to inspect.",
                    },
                },
                "required": ["path"],
            },
            handler=lambda path, sheet_name=None, **kwargs: engine.profile_spreadsheet(
                path, sheet_name=sheet_name
            ).model_dump(),
        )
    )

    # 10. files.duplicates.find
    registry.add(
        Spec(
            name="files.duplicates.find",
            description="Find duplicate files across a directory using SHA-256 cryptographic hashes and report wasted space.",
            source="files",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "Directory path to scan for duplicate files.",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "Max files to scan (default 300).",
                        "default": 300,
                    },
                },
                "required": ["folder_path"],
            },
            handler=lambda folder_path, max_files=300, **kwargs: engine.find_duplicates(
                folder_path, max_files=max_files
            ),
        )
    )

    # 11. files.organize.preview
    registry.add(
        Spec(
            name="files.organize.preview",
            description=(
                "Generate a read-only preview of proposed file organization actions, identifying "
                "large files, old downloads, temporary files, empty folders, and category subfolder moves."
            ),
            source="files",
            risk="read",
            schema={
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "Folder path to analyze for organization.",
                    }
                },
                "required": ["folder_path"],
            },
            handler=lambda folder_path, **kwargs: engine.preview_organization(folder_path),
        )
    )

    # 12. files.organize.execute (CONSEQUENTIAL ACTION -> risk="approval")
    registry.add(
        Spec(
            name="files.organize.execute",
            description=(
                "Execute approved file reorganization actions (moving or quarantining files). "
                "CONSEQUENTIAL OPERATION: Requires user approval. Never permanently deletes files; "
                "moves them safely with rollback tracking."
            ),
            source="files",
            risk="approval",
            schema={
                "type": "object",
                "properties": {
                    "action_items": {
                        "type": "array",
                        "description": "List of action item dictionaries specifying path, suggested_action, and target_path.",
                        "items": {"type": "object"},
                    },
                    "quarantine_root": {
                        "type": "string",
                        "description": "Optional custom quarantine folder path.",
                    },
                },
                "required": ["action_items"],
            },
            handler=lambda action_items, quarantine_root=None, **kwargs: engine.execute_organization(
                action_items, quarantine_root=quarantine_root
            ),
        )
    )
