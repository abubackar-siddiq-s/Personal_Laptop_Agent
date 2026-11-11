from __future__ import annotations
import csv
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.files.parsers import format_size
from app.files.schemas import (
    SpreadsheetColumnProfile,
    SpreadsheetProfile,
    TableData,
)
from app.files.security import validate_file_path, verify_zip_archive_safety


def infer_type(values: List[Any]) -> str:
    """Infer dominant data type of a column: integer, float, date, boolean, text."""
    non_nulls = [v for v in values if v is not None and str(v).strip() != ""]
    if not non_nulls:
        return "empty"

    int_count = 0
    float_count = 0
    bool_count = 0
    date_count = 0

    for v in non_nulls:
        s = str(v).strip()
        if s.lower() in ("true", "false"):
            bool_count += 1
            continue
        try:
            int(s.replace(",", ""))
            int_count += 1
            continue
        except ValueError:
            pass
        try:
            float(s.replace(",", ""))
            float_count += 1
            continue
        except ValueError:
            pass
        if ("-" in s or "/" in s) and len(s) in (8, 9, 10):
            date_count += 1

    total = len(non_nulls)
    if int_count / total > 0.8:
        return "integer"
    if (int_count + float_count) / total > 0.8:
        return "float"
    if bool_count / total > 0.8:
        return "boolean"
    if date_count / total > 0.8:
        return "date"
    return "text"


def compute_numeric_stats(values: List[Any]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Compute min, max, mean, and median for numeric values."""
    nums: List[float] = []
    for v in values:
        if v is None:
            continue
        try:
            clean = str(v).replace(",", "").replace("$", "").replace("%", "").strip()
            nums.append(float(clean))
        except (ValueError, TypeError):
            continue

    if not nums:
        return None, None, None, None

    nums.sort()
    min_val = nums[0]
    max_val = nums[-1]
    mean_val = sum(nums) / len(nums)
    n = len(nums)
    if n % 2 == 1:
        median_val = nums[n // 2]
    else:
        median_val = (nums[n // 2 - 1] + nums[n // 2]) / 2.0

    return min_val, max_val, round(mean_val, 2), round(median_val, 2)


def profile_spreadsheet(
    file_path: str | Path,
    sheet_name: Optional[str] = None,
    max_rows_preview: int = 50,
) -> SpreadsheetProfile:
    """
    Comprehensive spreadsheet profiler supporting XLSX and CSV.
    Computes dimensions, column types, null counts, distincts, numeric statistics,
    identifies formulas, detects duplicate rows, and prepares chart-ready datasets.
    """
    valid_path = validate_file_path(file_path)
    ext = valid_path.suffix.lower()

    if ext not in (".xlsx", ".csv"):
        raise ValueError(f"Spreadsheet profiling only supports .xlsx and .csv files (got '{ext}').")

    sheet_names: List[str] = []
    active_sheet_name = ""
    headers: List[str] = []
    data_rows: List[List[Any]] = []
    formulas_detected: List[str] = []

    if ext == ".xlsx":
        import openpyxl

        verify_zip_archive_safety(valid_path)
        # Load values
        wb_data = openpyxl.load_workbook(str(valid_path), read_only=True, data_only=True)
        sheet_names = wb_data.sheetnames
        target_sheet = sheet_name if sheet_name and sheet_name in sheet_names else sheet_names[0]
        active_sheet_name = target_sheet
        ws = wb_data[target_sheet]

        for r_idx, row in enumerate(ws.iter_rows(values_only=True)):
            if r_idx == 0:
                headers = [str(c or f"Col_{i+1}") for i, c in enumerate(row)]
            else:
                if any(c is not None for c in row):
                    data_rows.append(list(row))
        wb_data.close()

        # Load formulas to detect calculation logic
        try:
            wb_formula = openpyxl.load_workbook(str(valid_path), read_only=True, data_only=False)
            ws_f = wb_formula[target_sheet]
            for r in ws_f.iter_rows(values_only=True):
                for cell in r:
                    if isinstance(cell, str) and cell.startswith("="):
                        if cell not in formulas_detected:
                            formulas_detected.append(cell)
            wb_formula.close()
        except Exception:
            pass

    elif ext == ".csv":
        sheet_names = [valid_path.stem]
        active_sheet_name = valid_path.stem

        with open(valid_path, "r", encoding="utf-8", errors="replace") as f:
            sample = f.read(4096)
            f.seek(0)
            delim = ","
            try:
                dialect = csv.Sniffer().sniff(sample)
                delim = dialect.delimiter
            except Exception:
                pass

            reader = csv.reader(f, delimiter=delim)
            for r_idx, row in enumerate(reader):
                if r_idx == 0:
                    headers = row
                else:
                    if any(c.strip() for c in row):
                        data_rows.append(row)

    row_count = len(data_rows)
    col_count = len(headers)

    # Detect duplicate rows
    row_tuples = [tuple(r[:col_count]) for r in data_rows]
    unique_rows = set(row_tuples)
    duplicate_row_count = row_count - len(unique_rows)

    # Column profiling
    columns_profile: List[SpreadsheetColumnProfile] = []
    numeric_col_names: List[str] = []

    for c_idx, h_name in enumerate(headers):
        col_values = [r[c_idx] if c_idx < len(r) else None for r in data_rows]
        dtype = infer_type(col_values)
        non_null = sum(1 for v in col_values if v is not None and str(v).strip() != "")
        null_count = row_count - non_null
        distinct = len(set(str(v) for v in col_values if v is not None))
        sample_vals = [v for v in col_values if v is not None][:5]

        min_val, max_val, mean_val, median_val = None, None, None, None
        if dtype in ("integer", "float"):
            numeric_col_names.append(h_name)
            min_val, max_val, mean_val, median_val = compute_numeric_stats(col_values)

        columns_profile.append(
            SpreadsheetColumnProfile(
                name=h_name,
                dtype=dtype,
                non_null_count=non_null,
                null_count=null_count,
                distinct_count=distinct,
                sample_values=sample_vals,
                min_val=min_val,
                max_val=max_val,
                mean_val=mean_val,
                median_val=median_val,
            )
        )

    # Preview rows
    preview: List[Dict[str, Any]] = []
    for r in data_rows[:max_rows_preview]:
        row_dict = {}
        for c_idx, h in enumerate(headers):
            row_dict[h] = r[c_idx] if c_idx < len(r) else ""
        preview.append(row_dict)

    # Chart-ready dataset preparation
    chart_data = None
    if headers and numeric_col_names and data_rows:
        # Pick category column: first text column
        cat_col = next((c.name for c in columns_profile if c.dtype in ("text", "date")), headers[0])
        val_col = numeric_col_names[0]
        labels = [str(r.get(cat_col, f"Row {i+1}")) for i, r in enumerate(preview[:15])]
        points = []
        for r in preview[:15]:
            try:
                v = float(str(r.get(val_col, 0)).replace(",", "").replace("$", ""))
            except Exception:
                v = 0.0
            points.append(v)

        chart_data = {
            "type": "bar",
            "title": f"{val_col} by {cat_col}",
            "category_axis": cat_col,
            "value_axis": val_col,
            "labels": labels,
            "series": [
                {
                    "name": val_col,
                    "data": points,
                }
            ],
        }

    return SpreadsheetProfile(
        filename=valid_path.name,
        sheet_names=sheet_names,
        active_sheet=active_sheet_name,
        row_count=row_count,
        col_count=col_count,
        columns=columns_profile,
        duplicate_row_count=duplicate_row_count,
        formulas_detected=formulas_detected[:20],
        preview_rows=preview,
        chart_ready_data=chart_data,
    )


def query_spreadsheet(
    file_path: str | Path,
    filter_column: Optional[str] = None,
    filter_value: Optional[str] = None,
    sort_by: Optional[str] = None,
    descending: bool = False,
    sheet_name: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Execute filtering and sorting on spreadsheet data.
    Strictly read-only; never overwrites or modifies the original file.
    """
    profile = profile_spreadsheet(file_path, sheet_name=sheet_name, max_rows_preview=1000)
    rows = profile.preview_rows

    if filter_column and filter_value:
        col_clean = filter_column.strip()
        val_clean = filter_value.strip().lower()
        rows = [r for r in rows if val_clean in str(r.get(col_clean, "")).lower()]

    if sort_by and sort_by in profile.sheet_names or any(c.name == sort_by for c in profile.columns):
        col_type = next((c.dtype for c in profile.columns if c.name == sort_by), "text")
        if col_type in ("integer", "float"):
            def sort_key(r):
                try:
                    return float(str(r.get(sort_by, 0)).replace(",", ""))
                except Exception:
                    return float("-inf")
            rows = sorted(rows, key=sort_key, reverse=descending)
        else:
            rows = sorted(rows, key=lambda r: str(r.get(sort_by, "")).lower(), reverse=descending)

    return {
        "filename": profile.filename,
        "sheet": profile.active_sheet,
        "total_matched": len(rows),
        "results": rows[:limit],
        "columns": [c.name for c in profile.columns],
    }

