"""
LAPTOP AI — WINDOWS DESKTOP CONTROL ENGINE: SCREENSHOT CAPTURE
Captures desktop and window screenshots, persisting to Downloads/LAPTOP_AI/Screenshots.
Returns clean file references and metadata, avoiding raw base64 injection into prompts.
"""
from __future__ import annotations
import base64
import datetime
import io
import logging
from pathlib import Path
from typing import Optional
from PIL import Image, ImageGrab

from app.desktop.security import ensure_default_desktop, verify_desktop_available
from app.desktop.windows import get_active_window, get_window_rect
from app.core.security import audit

logger = logging.getLogger("laptop_ai.desktop.screenshots")

SCREENSHOTS_DIR = Path.home() / "Downloads" / "LAPTOP_AI" / "Screenshots"


def get_screenshots_dir() -> Path:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    return SCREENSHOTS_DIR


def capture_screenshot(target: str = "desktop", hwnd: Optional[int] = None) -> dict:
    """
    Capture a screenshot of either the entire primary desktop or the active/specified application window.
    Saves to Downloads/LAPTOP_AI/Screenshots.
    
    Returns structured metadata with file path and dimensions.
    Does NOT return large base64 strings in LLM tool outputs to prevent token blowup.
    """
    try:
        verify_desktop_available()
        ensure_default_desktop()
    except Exception as e:
        return {"success": False, "error": str(e)}

    save_dir = get_screenshots_dir()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    bbox = None
    window_meta = None

    if target == "window":
        if hwnd:
            target_hwnd = hwnd
            rect = get_window_rect(target_hwnd)
            title = f"HWND_{target_hwnd}"
        else:
            active = get_active_window()
            if not active.get("has_active_window"):
                return {
                    "success": False,
                    "error": "No active foreground window found to capture. Desktop may be idle.",
                }
            target_hwnd = active["hwnd"]
            rect = active["rect"]
            title = active.get("title", f"HWND_{target_hwnd}")

        window_meta = {"hwnd": target_hwnd, "title": title, "rect": rect}
        if rect["width"] > 0 and rect["height"] > 0:
            # Pillow bbox: (left, top, right, bottom)
            # Ensure coordinates are non-negative
            bbox = (
                max(0, rect["left"]),
                max(0, rect["top"]),
                max(0, rect["right"]),
                max(0, rect["bottom"]),
            )

    try:
        if bbox:
            shot = ImageGrab.grab(bbox=bbox)
            filename = f"window_{timestamp}.png"
        else:
            shot = ImageGrab.grab()
            filename = f"desktop_{timestamp}.png"

        out_path = save_dir / filename
        shot.save(str(out_path), "PNG")
        file_size = out_path.stat().st_size

        audit("desktop.screenshot_captured", f"Target: {target}, Path: {out_path}, Size: {shot.size}")

        res = {
            "success": True,
            "target": target,
            "path": str(out_path),
            "filename": filename,
            "width": shot.size[0],
            "height": shot.size[1],
            "file_size_bytes": file_size,
            "timestamp": timestamp,
        }
        if window_meta:
            res["window"] = window_meta
        return res

    except Exception as e:
        logger.error("Screenshot capture failed: %s", e)
        return {
            "success": False,
            "error": f"Screenshot capture failed: {type(e).__name__}: {str(e)}. Desktop session may be detached or locked.",
        }


def list_screenshots(limit: int = 20) -> list[dict]:
    """List recent screenshots saved in Downloads/LAPTOP_AI/Screenshots."""
    save_dir = get_screenshots_dir()
    files = sorted(save_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    results = []
    for f in files[:limit]:
        try:
            st = f.stat()
            results.append({
                "filename": f.name,
                "path": str(f),
                "file_size_bytes": st.st_size,
                "created_at": datetime.datetime.fromtimestamp(st.st_ctime).isoformat(),
            })
        except Exception:
            continue
    return results


def get_screenshot_thumbnail(file_path: str, max_width: int = 360) -> Optional[str]:
    """
    Generate a compact base64 JPEG thumbnail specifically for the frontend UI tab.
    Strictly bounded in dimension to prevent high memory or network overhead.
    """
    path = Path(file_path)
    if not path.is_file():
        return None
    try:
        with Image.open(path) as img:
            ratio = max_width / float(img.width) if img.width > max_width else 1.0
            new_size = (int(img.width * ratio), int(img.height * ratio))
            thumb = img.resize(new_size, Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            thumb.convert("RGB").save(buf, format="JPEG", quality=70)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        logger.warning("Failed to generate thumbnail for %s: %s", file_path, e)
        return None
