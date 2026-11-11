"""
LAPTOP AI — VISUAL DESKTOP INTELLIGENCE: UI ELEMENT DETECTOR
Detects buttons, text inputs, menus, dialogs, toolbars, tabs, icons,
notifications, and error/warning regions by fusing local OCR layout analysis
with live Windows UI Automation accessibility telemetry.
"""
from __future__ import annotations
import logging
from typing import Optional, List, Dict, Any

from app.vision.schemas import BoundingBox, DetectedElement, OCRResult
from app.vision.screenshot_processor import validate_image
from app.desktop.ui_inspection import inspect_ui
from app.desktop.windows import get_active_window

logger = logging.getLogger("laptop_ai.vision.ui_detector")

BUTTON_KEYWORDS = {
    "ok", "cancel", "save", "save as", "open", "close", "apply", "submit",
    "next", "back", "finish", "done", "yes", "no", "retry", "ignore", "abort",
    "continue", "browse", "run", "search", "send", "agree", "accept", "decline",
    "inspect", "execute", "start", "stop", "pause", "resume", "clear", "delete",
    "edit", "copy", "cut", "paste", "download", "install", "update"
}

MENU_KEYWORDS = {
    "file", "edit", "selection", "view", "go", "run", "terminal", "help",
    "tools", "window", "options", "settings", "preferences", "format"
}

ERROR_KEYWORDS = {
    "error", "warning", "failed", "failure", "exception", "critical",
    "access denied", "not found", "cannot find", "crash", "stopped working",
    "syntaxerror", "typeerror", "runtimeerror", "fatal", "unhandled"
}

INPUT_KEYWORDS = {
    "search", "find", "filter", "url", "http", "https", "type here", "enter", "query"
}


def detect_ui_elements(
    image_path: str,
    ocr_result: Optional[OCRResult] = None,
    hwnd: Optional[int] = None,
    screen_width: int = 1920,
    screen_height: int = 1080,
) -> list[DetectedElement]:
    """
    Detect visual UI elements on screen by fusing OCR visual text regions
    with native Windows UI Automation accessible controls.
    Returns normalized bounding boxes and physical screen coordinates.
    """
    is_valid, _, (img_w, img_h) = validate_image(image_path)
    sw = screen_width or (img_w if is_valid else 1920)
    sh = screen_height or (img_h if is_valid else 1080)

    detected: list[DetectedElement] = []
    seen_regions: list[BoundingBox] = []

    def is_overlapping(box1: BoundingBox, box2: BoundingBox, threshold: float = 0.5) -> bool:
        # Check intersection over union (IoU) or significant containment
        ix1 = max(box1.x1, box2.x1)
        iy1 = max(box1.y1, box2.y1)
        ix2 = min(box1.x2, box2.x2)
        iy2 = min(box1.y2, box2.y2)
        iw = max(0, ix2 - ix1)
        ih = max(0, iy2 - iy1)
        inter_area = iw * ih
        area1 = box1.width * box1.height
        area2 = box2.width * box2.height
        if area1 <= 0 or area2 <= 0:
            return False
        overlap = inter_area / float(min(area1, area2))
        return overlap >= threshold

    # 1. Inspect live UI Automation elements for ground truth accessible controls
    uia_elements: list[dict] = []
    try:
        target_hwnd = hwnd
        if not target_hwnd:
            act = get_active_window()
            if act.get("has_active_window"):
                target_hwnd = act.get("hwnd")

        if target_hwnd:
            uia_res = inspect_ui(hwnd=target_hwnd, max_depth=3, max_elements=50)
            if uia_res.get("success") and uia_res.get("accessible"):
                uia_elements = uia_res.get("elements", [])
    except Exception as e:
        logger.debug("UIA inspection skipped during visual detection: %s", e)

    # 2. Extract OCR-based visual elements
    if ocr_result and ocr_result.success:
        for idx, line in enumerate(ocr_result.lines):
            line_lower = line.text.lower().strip()
            if not line_lower:
                continue

            # A. Check Error / Warning regions
            if any(err_term in line_lower for err_term in ERROR_KEYWORDS):
                elem = DetectedElement(
                    id=len(detected) + 1,
                    element_type="error_warning",
                    label=line.text,
                    description=f"Error or warning message: '{line.text}'",
                    bbox=line.bbox,
                    confidence=0.92,
                    detection_method="ocr_visual",
                    is_interactive=False,
                    cross_verified_uia=False,
                )
                detected.append(elem)
                seen_regions.append(line.bbox)
                continue

            # B. Check Menu headers
            if line_lower in MENU_KEYWORDS or any(line_lower.startswith(m + " ") for m in MENU_KEYWORDS):
                elem = DetectedElement(
                    id=len(detected) + 1,
                    element_type="menu",
                    label=line.text,
                    description=f"Menu item: '{line.text}'",
                    bbox=line.bbox,
                    confidence=0.88,
                    detection_method="ocr_visual",
                    is_interactive=True,
                    cross_verified_uia=False,
                )
                detected.append(elem)
                seen_regions.append(line.bbox)
                continue

            # C. Check Buttons by keyword
            if line_lower in BUTTON_KEYWORDS or any(line_lower.startswith(b + " ") for b in BUTTON_KEYWORDS):
                elem = DetectedElement(
                    id=len(detected) + 1,
                    element_type="button",
                    label=line.text,
                    description=f"Action button: '{line.text}'",
                    bbox=line.bbox,
                    confidence=0.85,
                    detection_method="ocr_visual",
                    is_interactive=True,
                    cross_verified_uia=False,
                )
                detected.append(elem)
                seen_regions.append(line.bbox)
                continue

            # D. Check Input / Address bar indicators
            if any(term in line_lower for term in INPUT_KEYWORDS) or "http" in line_lower or "www." in line_lower:
                elem = DetectedElement(
                    id=len(detected) + 1,
                    element_type="text_input",
                    label=line.text,
                    description=f"Text input or address bar: '{line.text}'",
                    bbox=line.bbox,
                    confidence=0.84,
                    detection_method="ocr_visual",
                    is_interactive=True,
                    cross_verified_uia=False,
                )
                detected.append(elem)
                seen_regions.append(line.bbox)
                continue

    # 3. Fuse with UI Automation accessible controls
    for u_el in uia_elements:
        c_type = u_el.get("control_type", "")
        name = u_el.get("name", "").strip()
        bounds = u_el.get("bounds", [0, 0, 0, 0])
        if len(bounds) != 4:
            continue
        ux1, uy1, ux2, uy2 = bounds
        if ux2 <= ux1 or uy2 <= uy1:
            continue

        u_bbox = BoundingBox.from_coords(ux1, uy1, ux2, uy2, screen_width=sw, screen_height=sh)

        # Check if already detected via OCR
        matched_existing = None
        for d_el in detected:
            if is_overlapping(d_el.bbox, u_bbox, threshold=0.4) or (name and name.lower() == d_el.label.lower()):
                matched_existing = d_el
                break

        if matched_existing:
            # Upgrade detection to UIA fused
            matched_existing.cross_verified_uia = True
            matched_existing.confidence = min(0.98, matched_existing.confidence + 0.12)
            matched_existing.detection_method = "uia_fused"
            matched_existing.attributes["automation_id"] = u_el.get("automation_id")
            matched_existing.attributes["uia_control_type"] = c_type
        else:
            # New accessible element not captured by OCR text
            elem_type = "button"
            is_interactive = True
            if c_type in ("Edit", "Document"):
                elem_type = "text_input"
            elif c_type in ("MenuItem", "Menu", "MenuBar"):
                elem_type = "menu"
            elif c_type in ("TabItem", "Tab"):
                elem_type = "tab"
            elif c_type in ("ToolBar", "Header"):
                elem_type = "toolbar"
            elif c_type in ("Window", "Pane") and ("dialog" in name.lower() or "alert" in name.lower()):
                elem_type = "dialog"
            elif c_type in ("Thumb", "ScrollBar"):
                elem_type = "toolbar"
            else:
                elem_type = "button"

            if name or c_type in ("Button", "Edit", "MenuItem", "TabItem"):
                label_val = name if name else f"Unnamed {c_type}"
                elem = DetectedElement(
                    id=len(detected) + 1,
                    element_type=elem_type,
                    label=label_val,
                    description=f"Accessible {c_type}: '{label_val}'",
                    bbox=u_bbox,
                    confidence=0.90,
                    detection_method="uia_accessible",
                    is_interactive=is_interactive,
                    cross_verified_uia=True,
                    attributes={"automation_id": u_el.get("automation_id"), "uia_control_type": c_type},
                )
                detected.append(elem)

    # Re-index element IDs 1..N
    for i, el in enumerate(detected):
        el.id = i + 1

    return detected

