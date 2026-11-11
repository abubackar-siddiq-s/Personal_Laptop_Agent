"""
LAPTOP AI — VISUAL DESKTOP INTELLIGENCE: LOCAL OCR SUBSYSTEM
Executes lightweight local Windows native OCR (Windows.Media.Ocr)
to extract visible text, application titles, dialog messages, and button labels
with exact physical and normalized bounding boxes.
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from PIL import Image

from app.vision.schemas import BoundingBox, OCRWord, OCRLine, OCRResult
from app.vision.screenshot_processor import validate_image
from app.vision.security import verify_vision_execution_allowed, sanitize_visual_text
from app.core.security import audit

logger = logging.getLogger("laptop_ai.vision.ocr")

WINRT_OCR_SCRIPT = Path(__file__).parent / "winrt_ocr.ps1"

COMMON_BUTTON_TERMS = {
    "ok", "cancel", "save", "save as", "open", "close", "apply", "submit",
    "next", "back", "finish", "done", "yes", "no", "retry", "ignore", "abort",
    "continue", "browse", "run", "search", "send", "agree", "accept", "decline"
}

ERROR_INDICATOR_TERMS = {
    "error", "warning", "failed", "failure", "exception", "critical",
    "access denied", "not found", "cannot find", "crash", "stopped working",
    "syntaxerror", "typeerror", "runtimeerror", "fatal", "unhandled"
}


def run_ocr(
    image_path: str,
    screen_width: Optional[int] = None,
    screen_height: Optional[int] = None,
    timeout: float = 15.0,
) -> OCRResult:
    """
    Execute local OCR on an image file using native Windows.Media.Ocr.
    Extracts text lines and words with physical pixel coordinates.
    Sanitizes output against prompt injection.
    """
    verify_vision_execution_allowed()

    is_valid, err_or_fmt, (img_w, img_h) = validate_image(image_path)
    if not is_valid:
        return OCRResult(
            success=False,
            text="",
            line_count=0,
            lines=[],
            image_path=image_path,
            error=err_or_fmt,
        )

    sw = screen_width or img_w
    sh = screen_height or img_h

    t0 = time.time()

    # Check for test override mock
    if os.environ.get("LAPTOP_AI_TEST_MODE") == "1" and os.environ.get("LAPTOP_AI_MOCK_OCR"):
        try:
            mock_data = json.loads(os.environ["LAPTOP_AI_MOCK_OCR"])
            return _parse_ocr_json(mock_data, image_path, sw, sh, duration_ms=(time.time() - t0) * 1000)
        except Exception as e:
            logger.warning("Mock OCR parsing failed: %s", e)

    if not WINRT_OCR_SCRIPT.is_file():
        return OCRResult(
            success=False,
            text="",
            line_count=0,
            lines=[],
            image_path=image_path,
            error=f"WinRT OCR helper script not found at {WINRT_OCR_SCRIPT}",
        )

    try:
        proc = subprocess.run(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(WINRT_OCR_SCRIPT),
                "-ImagePath",
                str(Path(image_path).resolve()),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )

        duration = (time.time() - t0) * 1000

        if proc.returncode != 0:
            err = proc.stderr.strip() or f"PowerShell exited with code {proc.returncode}"
            logger.warning("WinRT OCR execution failed: %s", err)
            return OCRResult(
                success=False,
                text="",
                line_count=0,
                lines=[],
                image_path=image_path,
                error=f"OCR execution failed: {err}",
                duration_ms=round(duration, 2),
            )

        raw_output = proc.stdout.strip()
        if not raw_output:
            return OCRResult(
                success=True,
                text="",
                line_count=0,
                lines=[],
                image_path=image_path,
                duration_ms=round(duration, 2),
            )

        data = json.loads(raw_output)
        if not data.get("success"):
            return OCRResult(
                success=False,
                text="",
                line_count=0,
                lines=[],
                image_path=image_path,
                error=data.get("error", "Unknown OCR failure"),
                duration_ms=round(duration, 2),
            )

        res = _parse_ocr_json(data, image_path, sw, sh, duration_ms=round(duration, 2))
        audit("vision.ocr_executed", f"Path: {image_path}, Lines: {res.line_count}, Duration: {res.duration_ms}ms")
        return res

    except subprocess.TimeoutExpired:
        duration = (time.time() - t0) * 1000
        return OCRResult(
            success=False,
            text="",
            line_count=0,
            lines=[],
            image_path=image_path,
            error=f"WinRT OCR timed out after {timeout}s",
            duration_ms=round(duration, 2),
        )
    except Exception as e:
        duration = (time.time() - t0) * 1000
        logger.error("OCR process error: %s", e)
        return OCRResult(
            success=False,
            text="",
            line_count=0,
            lines=[],
            image_path=image_path,
            error=f"OCR subsystem error: {type(e).__name__}: {str(e)}",
            duration_ms=round(duration, 2),
        )


def _parse_ocr_json(data: dict, image_path: str, sw: int, sh: int, duration_ms: float) -> OCRResult:
    """Parse raw JSON output from OCR script into validated Pydantic model."""
    raw_lines = data.get("lines", [])
    parsed_lines: list[OCRLine] = []

    for l_data in raw_lines:
        line_text = sanitize_visual_text(l_data.get("text", "").strip())
        l_box_raw = l_data.get("bbox", {})
        line_bbox = BoundingBox.from_coords(
            x1=l_box_raw.get("x1", 0),
            y1=l_box_raw.get("y1", 0),
            x2=l_box_raw.get("x2", 0),
            y2=l_box_raw.get("y2", 0),
            screen_width=sw,
            screen_height=sh,
        )

        parsed_words: list[OCRWord] = []
        for w_data in l_data.get("words", []):
            word_text = sanitize_visual_text(w_data.get("text", "").strip())
            w_box_raw = w_data.get("bbox", {})
            word_bbox = BoundingBox.from_coords(
                x1=w_box_raw.get("x1", 0),
                y1=w_box_raw.get("y1", 0),
                x2=w_box_raw.get("x2", 0),
                y2=w_box_raw.get("y2", 0),
                screen_width=sw,
                screen_height=sh,
            )
            parsed_words.append(OCRWord(text=word_text, bbox=word_bbox, confidence=1.0))

        parsed_lines.append(OCRLine(text=line_text, bbox=line_bbox, words=parsed_words))

    full_text = "\n".join(l.text for l in parsed_lines if l.text)

    return OCRResult(
        success=True,
        text=full_text,
        line_count=len(parsed_lines),
        lines=parsed_lines,
        image_path=image_path,
        engine_used="winrt_native",
        duration_ms=duration_ms,
    )


def find_text_matches(ocr: OCRResult, query: str) -> list[dict]:
    """
    Search for words or lines in OCR output matching query text.
    Returns matched items with labels and bounding boxes.
    """
    if not ocr.success or not ocr.lines or not query:
        return []

    q_lower = query.lower().strip()
    matches = []

    # 1. Exact line match
    for l in ocr.lines:
        if q_lower == l.text.lower():
            matches.append({
                "type": "line",
                "text": l.text,
                "bbox": l.bbox,
                "confidence": 0.95,
            })
        elif q_lower in l.text.lower():
            matches.append({
                "type": "line_partial",
                "text": l.text,
                "bbox": l.bbox,
                "confidence": 0.85,
            })

    # 2. Word matches
    for l in ocr.lines:
        for w in l.words:
            if q_lower == w.text.lower():
                matches.append({
                    "type": "word",
                    "text": w.text,
                    "bbox": w.bbox,
                    "confidence": 0.90,
                })

    return matches

