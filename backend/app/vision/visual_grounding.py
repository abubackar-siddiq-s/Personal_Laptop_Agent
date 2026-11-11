"""
LAPTOP AI — VISUAL DESKTOP INTELLIGENCE: VISUAL GROUNDING
Locates specific visual elements on the desktop from natural language queries
(e.g., "Find the Save button", "Locate the browser address bar", "Find error dialog").
Calculates bounding boxes, center coordinates, and confidence with UIA cross-verification.
GUARANTEES STRICT READ-ONLY SAFETY: NEVER clicks or triggers interactions automatically.
"""
from __future__ import annotations
import logging
import re
from typing import Optional, List

from app.vision.schemas import BoundingBox, DetectedElement, VisualGroundingResult, OCRResult
from app.vision.screenshot_processor import validate_image
from app.vision.ocr import run_ocr
from app.vision.ui_detector import detect_ui_elements
from app.core.security import audit

logger = logging.getLogger("laptop_ai.vision.visual_grounding")

QUERY_STOP_WORDS = {
    "find", "locate", "where", "is", "the", "a", "an", "please", "show", "me",
    "identify", "detect", "point", "to", "get", "tell"
}


def clean_query_term(query: str) -> str:
    """Strip conversational filler from search query to isolate target element name."""
    words = re.findall(r"\b[\w\-]+\b", query.lower())
    filtered = [w for w in words if w not in QUERY_STOP_WORDS]
    return " ".join(filtered).strip() if filtered else query.lower().strip()


def ground_visual_element(
    query: str,
    image_path: str,
    ocr_result: Optional[OCRResult] = None,
    hwnd: Optional[int] = None,
    screen_width: int = 1920,
    screen_height: int = 1080,
) -> VisualGroundingResult:
    """
    Locate an element on the screen matching the natural language query.
    Returns the target bounding box, center coordinates, and cross-verification state.
    Strictly observational — does NOT perform clicking or typing.
    """
    is_valid, err_msg, (img_w, img_h) = validate_image(image_path)
    if not is_valid:
        return VisualGroundingResult(
            success=False,
            found=False,
            query=query,
            error=err_msg,
        )

    sw = screen_width or img_w
    sh = screen_height or img_h

    # 1. Ensure OCR is performed
    active_ocr = ocr_result
    if not active_ocr:
        active_ocr = run_ocr(image_path, screen_width=sw, screen_height=sh)

    # 2. Detect UI elements (OCR + UIA fusion)
    elements = detect_ui_elements(
        image_path=image_path,
        ocr_result=active_ocr,
        hwnd=hwnd,
        screen_width=sw,
        screen_height=sh,
    )

    clean_q = clean_query_term(query)
    raw_q_lower = query.lower().strip()

    candidates: list[DetectedElement] = []

    # Check semantic queries
    is_address_bar_query = any(k in raw_q_lower for k in ("address bar", "url bar", "search bar", "omnibox"))
    is_error_query = any(k in raw_q_lower for k in ("error dialog", "error message", "warning dialog", "error", "warning"))
    is_save_query = "save" in raw_q_lower and not ("as" in raw_q_lower and "save as" not in clean_q)

    for el in elements:
        label_lower = el.label.lower()
        score = 0.0

        # Exact label match
        if clean_q == label_lower or raw_q_lower == label_lower:
            score = 0.98
        # Clean query contained in label or vice versa
        elif clean_q and (clean_q in label_lower or label_lower in clean_q):
            score = 0.90
        # Semantic matching: address bar
        elif is_address_bar_query and (el.element_type == "text_input" or "http" in label_lower or "search" in label_lower):
            # Address bars are typically in the top 25% of the screen
            if el.bbox.y1 < (sh * 0.30):
                score = 0.94
            else:
                score = 0.85
        # Semantic matching: error dialog
        elif is_error_query and el.element_type in ("error_warning", "dialog"):
            score = 0.95
        # Semantic matching: save button
        elif is_save_query and el.element_type == "button" and "save" in label_lower:
            score = 0.96

        if score > 0.0:
            candidate_copy = el.model_copy()
            # Boost confidence if cross-verified via UIA
            if candidate_copy.cross_verified_uia:
                score = min(0.99, score + 0.03)
            candidate_copy.confidence = round(score, 2)
            candidates.append(candidate_copy)

    # Fallback to direct OCR line/word search if no structured elements matched
    if not candidates and active_ocr and active_ocr.lines:
        for line in active_ocr.lines:
            l_lower = line.text.lower()
            if clean_q in l_lower or any(word in l_lower for word in clean_q.split()):
                fallback_el = DetectedElement(
                    id=len(candidates) + 1,
                    element_type="text_region",
                    label=line.text,
                    description=f"Text match: '{line.text}'",
                    bbox=line.bbox,
                    confidence=0.75,
                    detection_method="ocr_text_match",
                    is_interactive=False,
                    cross_verified_uia=False,
                )
                candidates.append(fallback_el)

    # Sort candidates by confidence descending
    candidates.sort(key=lambda c: c.confidence, reverse=True)

    if candidates:
        best_match = candidates[0]
        audit(
            "vision.element_grounded",
            f"Query: '{query}', Found: '{best_match.label}' ({best_match.element_type}), "
            f"Center: {best_match.bbox.center}, Conf: {best_match.confidence}, UIA: {best_match.cross_verified_uia}"
        )
        return VisualGroundingResult(
            success=True,
            found=True,
            query=query,
            matched_element=best_match,
            all_candidates=candidates[:5],
            confidence=best_match.confidence,
            detection_method=best_match.detection_method,
            cross_verified_uia=best_match.cross_verified_uia,
        )
    else:
        audit("vision.element_not_found", f"Query: '{query}' - No visual element located")
        return VisualGroundingResult(
            success=True,
            found=False,
            query=query,
            matched_element=None,
            all_candidates=[],
            confidence=0.0,
            detection_method="none",
            cross_verified_uia=False,
            warning=f"No visual element matching query '{query}' was found on screen.",
        )

