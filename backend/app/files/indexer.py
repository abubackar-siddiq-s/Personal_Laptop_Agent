from __future__ import annotations
import hashlib
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.db import conn
from app.files.parsers import (
    SUPPORTED_EXTENSIONS,
    detect_file_format,
    format_size,
    parse_document,
)
from app.files.schemas import (
    DocumentSection,
    IndexStatus,
    ParsedDocument,
    SearchResponse,
    SearchResultChunk,
)
from app.files.security import PERMITTED_ROOTS, validate_file_path


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file efficiently with 64KB blocks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def chunk_document_sections(doc: ParsedDocument, max_chunk_words: int = 350, overlap_words: int = 50) -> List[DocumentSection]:
    """
    Split a document into coherent, bounded chunks.
    Preserves page numbers, sheet names, slide numbers, and section titles.
    """
    chunks: List[DocumentSection] = []
    chunk_counter = 0

    if not doc.sections and doc.text_content:
        # Fallback if no explicit sections were parsed
        words = doc.text_content.split()
        idx = 0
        while idx < len(words):
            chunk_words = words[idx : idx + max_chunk_words]
            block = " ".join(chunk_words)
            chunks.append(
                DocumentSection(
                    section_index=chunk_counter,
                    title="Document Excerpt",
                    content=block,
                    token_estimate=len(chunk_words),
                )
            )
            chunk_counter += 1
            idx += max_chunk_words - overlap_words
        return chunks

    for sec in doc.sections:
        words = sec.content.split()
        if len(words) <= max_chunk_words:
            chunks.append(
                DocumentSection(
                    section_index=chunk_counter,
                    title=sec.title,
                    page_number=sec.page_number,
                    sheet_name=sec.sheet_name,
                    slide_number=sec.slide_number,
                    content=sec.content,
                    token_estimate=len(words),
                )
            )
            chunk_counter += 1
        else:
            idx = 0
            sub_part = 1
            while idx < len(words):
                chunk_words = words[idx : idx + max_chunk_words]
                block = " ".join(chunk_words)
                sub_title = f"{sec.title} (Part {sub_part})" if sec.title else f"Part {sub_part}"
                chunks.append(
                    DocumentSection(
                        section_index=chunk_counter,
                        title=sub_title,
                        page_number=sec.page_number,
                        sheet_name=sec.sheet_name,
                        slide_number=sec.slide_number,
                        content=block,
                        token_estimate=len(chunk_words),
                    )
                )
                chunk_counter += 1
                sub_part += 1
                idx += max_chunk_words - overlap_words

    return chunks


def index_file(file_path: str | Path, force: bool = False) -> Dict[str, Any]:
    """
    Index a single file into SQLite and FTS5.
    Performs incremental indexing: checks mtime, size, and SHA-256 hash.
    Skips if unchanged unless force=True.
    """
    valid_path = validate_file_path(file_path)
    stat = valid_path.stat()
    current_mtime = stat.st_mtime
    current_size = stat.st_size
    path_str = str(valid_path)

    with conn() as c:
        # Check existing record
        row = c.execute(
            "SELECT id, mtime, size_bytes, sha256 FROM file_documents WHERE path = ?",
            (path_str,),
        ).fetchone()

        if row and not force:
            # If mtime and size match, skip SHA check for performance
            if abs(row["mtime"] - current_mtime) < 0.001 and row["size_bytes"] == current_size:
                return {
                    "path": path_str,
                    "status": "skipped",
                    "reason": "File unchanged (mtime & size matched)",
                    "doc_id": row["id"],
                }

        # Compute hash
        sha = compute_sha256(valid_path)
        if row and not force and row["sha256"] == sha:
            # Update mtime in case file was touched without content change
            c.execute("UPDATE file_documents SET mtime = ? WHERE id = ?", (current_mtime, row["id"]))
            return {
                "path": path_str,
                "status": "skipped",
                "reason": "File unchanged (SHA-256 matched)",
                "doc_id": row["id"],
            }

        # Parse document
        parsed = parse_document(valid_path)
        if not parsed.success or parsed.error:
            return {
                "path": path_str,
                "status": "failed",
                "error": parsed.error or "Parsing failed",
            }

        # Delete old document & chunks if re-indexing
        if row:
            doc_id = row["id"]
            c.execute("DELETE FROM file_chunks WHERE document_id = ?", (doc_id,))
            c.execute("DELETE FROM file_documents WHERE id = ?", (doc_id,))

        # Insert document metadata
        meta = parsed.metadata
        cursor = c.execute(
            """
            INSERT INTO file_documents(
                path, filename, extension, format, size_bytes, mtime, sha256,
                title, author, page_count, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                path_str,
                valid_path.name,
                valid_path.suffix.lower(),
                parsed.format,
                current_size,
                current_mtime,
                sha,
                meta.title,
                meta.author,
                meta.page_count or meta.sheet_count or meta.slide_count,
                meta.model_dump_json(),
            ),
        )
        new_doc_id = cursor.lastrowid

        # Chunk and index
        chunks = chunk_document_sections(parsed)
        for ch in chunks:
            c.execute(
                """
                INSERT INTO file_chunks(
                    document_id, chunk_index, section_title, page_number,
                    sheet_name, slide_number, content, token_estimate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_doc_id,
                    ch.section_index,
                    ch.title,
                    ch.page_number,
                    ch.sheet_name,
                    ch.slide_number,
                    ch.content,
                    ch.token_estimate,
                ),
            )

        return {
            "path": path_str,
            "status": "indexed",
            "doc_id": new_doc_id,
            "format": parsed.format,
            "chunks_count": len(chunks),
            "words_count": meta.word_count,
        }


def index_directory(
    dir_path: str | Path,
    recursive: bool = True,
    max_files: int = 100,
) -> Dict[str, Any]:
    """
    Index all supported documents within a permitted directory.
    Enforces bounded file limits to prevent system stall.
    """
    valid_dir = validate_file_path(dir_path)
    if not valid_dir.is_dir():
        raise ValueError(f"Path '{valid_dir}' is not a directory.")

    indexed = 0
    skipped = 0
    failed = 0
    details = []

    pattern = "**/*" if recursive else "*"
    for item in valid_dir.glob(pattern):
        if not item.is_file():
            continue
        if item.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if indexed + skipped + failed >= max_files:
            break

        try:
            res = index_file(item)
            details.append(res)
            if res["status"] == "indexed":
                indexed += 1
            elif res["status"] == "skipped":
                skipped += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            details.append({"path": str(item), "status": "failed", "error": str(e)})

    return {
        "directory": str(valid_dir),
        "total_processed": indexed + skipped + failed,
        "indexed": indexed,
        "skipped": skipped,
        "failed": failed,
        "details": details[:30],
    }


def search_documents(
    query: str,
    limit: int = 10,
    format_filter: Optional[str] = None,
) -> SearchResponse:
    """
    Search indexed documents using SQLite FTS5 with BM25 ranking.
    Extracts highlighted match snippets and exact page/sheet/slide references.
    """
    clean_query = query.strip()
    if not clean_query:
        return SearchResponse(query=query, total_matches=0, results=[])

    # Sanitize FTS5 query terms (escape quotes, remove special FTS syntax that could error)
    sanitized_terms = re.findall(r"\w+", clean_query)
    if not sanitized_terms:
        return SearchResponse(query=query, total_matches=0, results=[])

    fts_query = " OR ".join(f'"{t}"' for t in sanitized_terms)

    with conn() as c:
        sql = """
        SELECT 
            c.id AS chunk_id,
            c.document_id,
            d.filename,
            d.path,
            d.format,
            c.page_number,
            c.sheet_name,
            c.slide_number,
            c.section_title,
            snippet(file_chunks_fts, 0, '<b>', '</b>', '...', 25) AS snippet_text,
            bm25(file_chunks_fts) AS bm25_score
        FROM file_chunks_fts
        JOIN file_chunks c ON file_chunks_fts.rowid = c.id
        JOIN file_documents d ON c.document_id = d.id
        WHERE file_chunks_fts MATCH ?
        """
        params: List[Any] = [fts_query]

        if format_filter:
            sql += " AND d.format = ?"
            params.append(format_filter.lower().lstrip("."))

        sql += " ORDER BY bm25_score ASC LIMIT ?"
        params.append(max(1, min(limit, 50)))

        rows = c.execute(sql, params).fetchall()

        results = []
        for r in rows:
            results.append(
                SearchResultChunk(
                    doc_id=r["document_id"],
                    filename=r["filename"],
                    path=r["path"],
                    format=r["format"],
                    page_number=r["page_number"],
                    sheet_name=r["sheet_name"],
                    slide_number=r["slide_number"],
                    section_title=r["section_title"],
                    snippet=r["snippet_text"] or "",
                    score=round(abs(float(r["bm25_score"])), 4),
                    match_type="fts5_bm25",
                )
            )

        return SearchResponse(
            query=clean_query,
            total_matches=len(results),
            results=results,
            search_mode="fts5_bm25",
        )


def get_index_status() -> IndexStatus:
    """Retrieve indexing statistics, document counts, format distribution, and database size."""
    with conn() as c:
        doc_count = c.execute("SELECT COUNT(*) AS cnt FROM file_documents").fetchone()["cnt"]
        chunk_count = c.execute("SELECT COUNT(*) AS cnt FROM file_chunks").fetchone()["cnt"]
        last_date = c.execute("SELECT MAX(indexed_at) AS last_idx FROM file_documents").fetchone()["last_idx"]

        fmt_rows = c.execute(
            "SELECT format, COUNT(*) AS cnt FROM file_documents GROUP BY format"
        ).fetchall()
        breakdown = {r["format"]: r["cnt"] for r in fmt_rows}

        # Estimate index table storage size
        size_bytes = c.execute("PRAGMA page_size").fetchone()[0] * c.execute("PRAGMA page_count").fetchone()[0]
        size_mb = round(size_bytes / (1024 * 1024), 2)

        return IndexStatus(
            total_documents=doc_count,
            total_chunks=chunk_count,
            formats_breakdown=breakdown,
            last_indexed_at=last_date,
            index_storage_mb=size_mb,
        )


def clear_document_index() -> Dict[str, Any]:
    """Purge all indexed document metadata and FTS chunks from SQLite."""
    with conn() as c:
        c.execute("DELETE FROM file_chunks;")
        c.execute("DELETE FROM file_documents;")
        return {"success": True, "message": "Document index cleared successfully."}
