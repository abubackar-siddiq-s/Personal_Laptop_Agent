from __future__ import annotations
import datetime
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.db import conn
from app.files.indexer import compute_sha256
from app.files.parsers import format_size
from app.files.schemas import (
    DuplicateFileInfo,
    DuplicateGroup,
    FileOrgExecutionResult,
    FileOrgItem,
    FileOrgPreview,
)
from app.files.security import (
    PERMITTED_ROOTS,
    SecurityError,
    validate_file_path,
)

LARGE_FILE_THRESHOLD_BYTES = 50 * 1024 * 1024  # 50 MB
OLD_FILE_DAYS = 90
UNNECESSARY_EXTENSIONS = {".tmp", ".temp", ".bak", ".log", ".dmp", ".old"}

CATEGORY_EXTENSIONS = {
    "Documents": {".pdf", ".docx", ".doc", ".txt", ".md", ".rtf"},
    "Spreadsheets": {".xlsx", ".xls", ".csv"},
    "Presentations": {".pptx", ".ppt"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Media": {".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mp3", ".wav"},
    "Code": {".py", ".ts", ".tsx", ".js", ".jsx", ".html", ".css", ".json", ".xml", ".sql"},
}


def categorize_file(path: Path) -> str:
    """Categorize file by extension into high-level functional groups."""
    ext = path.suffix.lower()
    for cat, exts in CATEGORY_EXTENSIONS.items():
        if ext in exts:
            return cat
    return "Other"


def suggest_clean_filename(path: Path) -> str:
    """Generate a clean, standardized filename (e.g., replace spaces, standardize dates)."""
    stem = path.stem.strip()
    ext = path.suffix.lower()

    # Replace sequences of spaces/underscores with single underscore
    clean_stem = "_".join(part for part in stem.replace("-", " ").replace("_", " ").split() if part)
    if not clean_stem:
        clean_stem = "file"

    return f"{clean_stem}{ext}"


def find_duplicates(folder_path: str | Path, max_files: int = 300) -> List[DuplicateGroup]:
    """
    Detect exact file duplicates across a permitted directory using SHA-256 hashes.
    Computes wasted storage space per duplicate group.
    """
    valid_dir = validate_file_path(folder_path)
    if not valid_dir.is_dir():
        raise ValueError(f"Path '{valid_dir}' is not a directory.")

    size_map: Dict[int, List[Path]] = {}
    files_scanned = 0

    # First pass: group by file size to avoid hashing unique file sizes
    for p in valid_dir.rglob("*"):
        if not p.is_file():
            continue
        files_scanned += 1
        if files_scanned > max_files:
            break
        try:
            sz = p.stat().st_size
            if sz > 0:  # Skip 0-byte files for duplicate content hashing
                size_map.setdefault(sz, []).append(p)
        except (PermissionError, OSError):
            continue

    # Second pass: hash only files with matching sizes
    hash_map: Dict[str, List[Path]] = {}
    for sz, path_list in size_map.items():
        if len(path_list) > 1:
            for p in path_list:
                try:
                    h = compute_sha256(p)
                    hash_map.setdefault(h, []).append(p)
                except Exception:
                    continue

    duplicate_groups: List[DuplicateGroup] = []
    for sha, paths in hash_map.items():
        if len(paths) > 1:
            try:
                single_size = paths[0].stat().st_size
            except Exception:
                single_size = 0
            wasted = single_size * (len(paths) - 1)
            file_infos = []
            for p in paths:
                try:
                    st = p.stat()
                    file_infos.append(
                        DuplicateFileInfo(
                            path=str(p),
                            filename=p.name,
                            size_bytes=st.st_size,
                            modified_at=datetime.datetime.fromtimestamp(st.st_mtime).isoformat(),
                        )
                    )
                except Exception:
                    continue

            duplicate_groups.append(
                DuplicateGroup(
                    sha256=sha,
                    file_count=len(paths),
                    wasted_bytes=wasted,
                    wasted_formatted=format_size(wasted),
                    files=file_infos,
                )
            )

    duplicate_groups.sort(key=lambda g: g.wasted_bytes, reverse=True)
    return duplicate_groups


def preview_file_organization(
    folder_path: str | Path,
    include_duplicates: bool = True,
    max_scan_items: int = 500,
) -> FileOrgPreview:
    """
    Read-only discovery of file clutter, duplicates, large files, old downloads, and empty folders.
    Generates proposed organization actions without making any disk modifications.
    """
    valid_dir = validate_file_path(folder_path)
    if not valid_dir.is_dir():
        raise ValueError(f"Path '{valid_dir}' is not a directory.")

    duplicate_groups = find_duplicates(valid_dir, max_files=max_scan_items) if include_duplicates else []
    large_files: List[FileOrgItem] = []
    old_files: List[FileOrgItem] = []
    empty_folders: List[str] = []
    proposed_actions: List[FileOrgItem] = []

    now = datetime.datetime.now()
    scanned_count = 0

    for root, dirs, files in os.walk(valid_dir):
        # Empty folder detection
        if not dirs and not files and root != str(valid_dir):
            empty_folders.append(root)

        for f in files:
            scanned_count += 1
            if scanned_count > max_scan_items:
                break
            f_path = Path(root) / f
            try:
                st = f_path.stat()
            except (PermissionError, OSError):
                continue

            sz = st.st_size
            ext = f_path.suffix.lower()
            mtime = datetime.datetime.fromtimestamp(st.st_mtime)
            age_days = (now - mtime).days
            cat = categorize_file(f_path)

            # Large files
            if sz > LARGE_FILE_THRESHOLD_BYTES:
                large_files.append(
                    FileOrgItem(
                        path=str(f_path),
                        filename=f,
                        size_bytes=sz,
                        category=cat,
                        reason=f"Large file ({format_size(sz)})",
                        suggested_action="Review for archival or external storage",
                    )
                )

            # Old / Unnecessary temp files
            if ext in UNNECESSARY_EXTENSIONS or (age_days > OLD_FILE_DAYS and "download" in root.lower()):
                reason = f"Temporary file format ({ext})" if ext in UNNECESSARY_EXTENSIONS else f"Unmodified for {age_days} days"
                item = FileOrgItem(
                    path=str(f_path),
                    filename=f,
                    size_bytes=sz,
                    category="Cleanup Candidate",
                    reason=reason,
                    suggested_action="Move to Quarantine / Review",
                )
                old_files.append(item)
                proposed_actions.append(item)

            # Categorization proposal (suggest subfolder)
            target_subfolder = valid_dir / cat
            if cat != "Other" and f_path.parent == valid_dir:
                proposed_actions.append(
                    FileOrgItem(
                        path=str(f_path),
                        filename=f,
                        size_bytes=sz,
                        category=cat,
                        reason=f"Consolidate {cat} into structured subfolder",
                        suggested_action="Organize into category folder",
                        target_path=str(target_subfolder / f),
                    )
                )

    return FileOrgPreview(
        scanned_path=str(valid_dir),
        total_scanned=scanned_count,
        duplicate_groups=duplicate_groups[:15],
        large_files=large_files[:15],
        old_files=old_files[:20],
        empty_folders=empty_folders[:20],
        proposed_actions=proposed_actions[:30],
        can_execute=len(proposed_actions) > 0,
    )


def execute_file_organization(
    action_items: List[Dict[str, Any]],
    quarantine_root: Optional[str | Path] = None,
) -> FileOrgExecutionResult:
    """
    Execute proposed organization actions (move/quarantine).
    Strict Safety Controls:
    1. Requires explicit approval (enforced via tool risk='approval').
    2. NEVER permanently deletes files; moves them to a quarantine directory.
    3. Records every operation in file_organize_history for rollback.
    """
    if not action_items:
        return FileOrgExecutionResult(success=True, executed_count=0, failed_count=0, details=[])

    # Default quarantine folder under Downloads/LAPTOP_AI/Quarantine
    q_dir = Path.home() / "Downloads" / "LAPTOP_AI" / "Quarantine"
    if quarantine_root:
        q_dir = validate_file_path(quarantine_root, allow_create=True)
    q_dir.mkdir(parents=True, exist_ok=True)

    rollback_token = f"rollback_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    executed = 0
    failed = 0
    details = []

    for item in action_items:
        src_path_str = item.get("path")
        target_path_str = item.get("target_path")
        suggested = item.get("suggested_action", "")

        try:
            src = validate_file_path(src_path_str)
            if not src.exists() or not src.is_file():
                failed += 1
                details.append({"path": src_path_str, "status": "failed", "error": "File does not exist"})
                continue

            # Determine destination
            if target_path_str:
                dest = validate_file_path(target_path_str, allow_create=True)
            else:
                dest = q_dir / f"{src.stem}_{int(datetime.datetime.now().timestamp())}{src.suffix}"

            file_size = src.stat().st_size
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Move file safely
            shutil.move(str(src), str(dest))

            # Record in SQLite history
            with conn() as c:
                c.execute(
                    """
                    INSERT INTO file_organize_history(
                        action, source_path, target_path, backup_path, status, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        suggested or "move",
                        str(src),
                        str(dest),
                        str(dest),
                        "completed",
                        json.dumps({"rollback_token": rollback_token, "size": file_size}),
                    ),
                )

            executed += 1
            details.append({"source": str(src), "destination": str(dest), "status": "moved"})
        except Exception as e:
            failed += 1
            details.append({"source": src_path_str, "status": "failed", "error": str(e)})

    return FileOrgExecutionResult(
        success=(failed == 0),
        executed_count=executed,
        failed_count=failed,
        rollback_token=rollback_token,
        details=details,
    )


def rollback_file_organization(rollback_token: str) -> Dict[str, Any]:
    """
    Roll back previously executed file organization actions using the rollback token.
    Restores files from quarantine or destination back to their original source paths.
    """
    with conn() as c:
        rows = c.execute(
            "SELECT id, source_path, target_path, details_json FROM file_organize_history WHERE status = 'completed'"
        ).fetchall()

        matched = [r for r in rows if rollback_token in (r["details_json"] or "")]
        if not matched:
            return {"success": False, "error": f"No active actions found for rollback token '{rollback_token}'."}

        restored = 0
        failed = 0
        for r in matched:
            curr = Path(r["target_path"])
            orig = Path(r["source_path"])
            try:
                if curr.exists():
                    orig.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(curr), str(orig))
                    c.execute(
                        "UPDATE file_organize_history SET status = 'rolled_back', rolled_back_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (r["id"],),
                    )
                    restored += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

        return {
            "success": True,
            "restored_count": restored,
            "failed_count": failed,
            "rollback_token": rollback_token,
        }
