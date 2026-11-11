"""
LAPTOP AI — VISUAL DESKTOP INTELLIGENCE: CORE COORDINATOR
Central engine integrating screenshot capture, local OCR, element detection,
multimodal cloud AI synthesis, visual grounding, and screen comparison.
"""
from __future__ import annotations
import collections
import datetime
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.desktop.screenshots import capture_screenshot, get_screenshots_dir, list_screenshots
from app.desktop.windows import get_active_window
from app.vision.schemas import (
    BoundingBox,
    OCRResult,
    DetectedElement,
    ScreenAnalysisResult,
    VisualGroundingResult,
    ImageComparisonResult,
)
from app.vision.screenshot_processor import (
    validate_image,
    prepare_image_for_cloud,
    crop_image_region,
    cleanup_old_screenshots,
)
from app.vision.ocr import run_ocr
from app.vision.ui_detector import detect_ui_elements
from app.vision.visual_grounding import ground_visual_element
from app.vision.comparison import compare_screenshots
from app.vision.security import (
    verify_vision_execution_allowed,
    sanitize_visual_text,
    format_visual_context_for_llm,
)
from app.providers.router import is_vision_capable, chat_turn, get_key
from app.core.security import audit

logger = logging.getLogger("laptop_ai.vision.engine")


class VisionEngine:
    def __init__(self, max_history: int = 40):
        self._analysis_history: collections.deque = collections.deque(maxlen=max_history)
        self._last_screenshot_path: Optional[str] = None

    def record_analysis(self, result: ScreenAnalysisResult) -> None:
        """Store recent analysis in memory for frontend dashboard consumption."""
        self._analysis_history.appendleft({
            "timestamp": datetime.datetime.now().isoformat(),
            "summary": result.summary,
            "active_application": result.active_application,
            "window_title": result.window_title,
            "image_path": result.image_path,
            "element_count": len(result.detected_elements),
            "error_count": len(result.error_dialogs),
            "provider_used": result.analysis_provider,
            "duration_ms": result.duration_ms,
        })

    def get_history(self, limit: int = 20) -> list[dict]:
        """Return recent screen analyses."""
        return list(self._analysis_history)[:limit]

    def clear_history(self) -> None:
        """Clear cached analysis history."""
        self._analysis_history.clear()

    async def analyze_screen(
        self,
        target: str = "desktop",
        prompt: Optional[str] = None,
        hwnd: Optional[int] = None,
        use_multimodal: bool = True,
    ) -> ScreenAnalysisResult:
        """
        Capture and visually analyze the desktop or target window.
        Extracts active application context, visible text, layout components, and error indicators.
        Fuses multimodal AI (if available) with deterministic local OCR and UIA accessibility.
        """
        t0 = time.time()
        verify_vision_execution_allowed()

        # 1. Capture screen via existing desktop subsystem
        cap_res = capture_screenshot(target=target, hwnd=hwnd)
        if not cap_res.get("success"):
            return ScreenAnalysisResult(
                success=False,
                summary=f"Screenshot capture failed: {cap_res.get('error')}",
                active_application="",
                window_title="",
                error=cap_res.get("error"),
            )

        shot_path = cap_res["path"]
        self._last_screenshot_path = shot_path
        img_w = cap_res.get("width", 1920)
        img_h = cap_res.get("height", 1080)

        # 2. Resolve active window metadata
        active_app = ""
        window_title = ""
        if cap_res.get("window"):
            w_info = cap_res["window"]
            window_title = w_info.get("title", "")
            active_app = w_info.get("rect", {}).get("process", "") or w_info.get("title", "")
        else:
            cur_active = get_active_window()
            if cur_active.get("has_active_window"):
                active_app = cur_active.get("process", "")
                window_title = cur_active.get("title", "")

        # 3. Local OCR Extraction
        ocr_res = run_ocr(shot_path, screen_width=img_w, screen_height=img_h)

        # 4. Visual UI Element Detection (OCR + UIA fusion)
        elements = detect_ui_elements(
            image_path=shot_path,
            ocr_result=ocr_res,
            hwnd=hwnd or (cap_res.get("window", {}).get("hwnd")),
            screen_width=img_w,
            screen_height=img_h,
        )

        error_elements = [el for el in elements if el.element_type in ("error_warning", "dialog")]
        visual_warnings = [el.label for el in error_elements]
        key_snippets = [line.text for line in ocr_res.lines[:8] if len(line.text.strip()) > 3]

        provider_used = "local_ocr_fused"
        summary_text = ""

        # 5. Multimodal Cloud Synthesis (if configured & requested)
        gemini_key = get_key("gemini")
        if use_multimodal and gemini_key:
            try:
                b64_data, mime_type, rw, rh = prepare_image_for_cloud(shot_path, max_dimension=1280)
                user_query = prompt or "Describe what is displayed on this screen, identify the active application, note any visible dialogs or error messages, and summarize the primary user workflow."
                
                analysis_instruction = (
                    "You are the Visual Intelligence component of LAPTOP AI.\n"
                    "Analyze the provided Windows desktop screenshot.\n"
                    "Report:\n"
                    "1. Active application and window context\n"
                    "2. Key visual components and layout\n"
                    "3. Any errors, warnings, or notifications\n"
                    "4. Summary of current desktop state\n"
                    "Keep your analysis clear, factual, and concise."
                )

                messages = [
                    {
                        "role": "user",
                        "content": user_query,
                        "image_base64": b64_data,
                        "image_mime": mime_type,
                    }
                ]

                # Invoke Gemini 2.5 Flash for vision
                ai_turn = await chat_turn(
                    provider="gemini",
                    model="gemini-2.5-flash",
                    messages=messages,
                    system_instruction=analysis_instruction,
                    timeout=20.0,
                )

                if ai_turn and ai_turn.content.strip():
                    summary_text = sanitize_visual_text(ai_turn.content.strip())
                    provider_used = "gemini-2.5-flash"
            except Exception as mm_err:
                logger.warning("Multimodal cloud analysis failed, falling back to local synthesis: %s", mm_err)

        # Local synthesis fallback if cloud was skipped, failed, or unconfigured
        if not summary_text:
            lines_summary = []
            if window_title or active_app:
                lines_summary.append(f"Application: **{active_app or 'Windows'}** (Window: *{window_title or 'Desktop'}*)")
            
            lines_summary.append(f"Visual Elements: Detected {len(elements)} UI components ({len([e for e in elements if e.element_type == 'button'])} buttons, {len([e for e in elements if e.element_type == 'menu'])} menus).")
            
            if error_elements:
                lines_summary.append(f"⚠️ Warnings/Errors Detected ({len(error_elements)}): " + "; ".join(e.label for e in error_elements[:3]))
            else:
                lines_summary.append("No active error dialogs or warning indicators observed.")

            if ocr_res.lines:
                lines_summary.append(f"Key visible text: {', '.join(repr(s) for s in key_snippets[:5])}")

            summary_text = "\n".join(lines_summary)

        duration = (time.time() - t0) * 1000

        result = ScreenAnalysisResult(
            success=True,
            summary=summary_text,
            active_application=active_app,
            window_title=window_title,
            detected_elements=elements[:30],
            error_dialogs=error_elements[:10],
            visual_warnings=visual_warnings[:10],
            key_text_snippets=key_snippets[:10],
            image_path=shot_path,
            analysis_provider=provider_used,
            duration_ms=round(duration, 2),
        )

        self.record_analysis(result)
        audit("vision.screen_analyzed", f"Target: {target}, Elements: {len(elements)}, Provider: {provider_used}")
        return result

    def extract_text(self, target: str = "desktop", hwnd: Optional[int] = None) -> OCRResult:
        """Extract visible text from desktop or window screenshot."""
        verify_vision_execution_allowed()
        cap_res = capture_screenshot(target=target, hwnd=hwnd)
        if not cap_res.get("success"):
            return OCRResult(
                success=False,
                text="",
                line_count=0,
                lines=[],
                error=cap_res.get("error"),
            )
        return run_ocr(cap_res["path"], screen_width=cap_res.get("width"), screen_height=cap_res.get("height"))

    def find_element(
        self,
        query: str,
        target: str = "desktop",
        hwnd: Optional[int] = None,
    ) -> VisualGroundingResult:
        """Locate target element by query on the current screen."""
        verify_vision_execution_allowed()
        cap_res = capture_screenshot(target=target, hwnd=hwnd)
        if not cap_res.get("success"):
            return VisualGroundingResult(
                success=False,
                found=False,
                query=query,
                error=cap_res.get("error"),
            )
        return ground_visual_element(
            query=query,
            image_path=cap_res["path"],
            hwnd=hwnd or (cap_res.get("window", {}).get("hwnd")),
            screen_width=cap_res.get("width"),
            screen_height=cap_res.get("height"),
        )

    def compare_screens(self, image_path_1: str, image_path_2: str) -> ImageComparisonResult:
        """Compare two screenshot files to identify visual and structural changes."""
        verify_vision_execution_allowed()
        return compare_screenshots(image_path_1, image_path_2)

    def describe_region(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        target: str = "desktop",
        hwnd: Optional[int] = None,
    ) -> dict:
        """Inspect and describe a specific rectangular region of the desktop."""
        verify_vision_execution_allowed()
        cap_res = capture_screenshot(target=target, hwnd=hwnd)
        if not cap_res.get("success"):
            return {"success": False, "error": cap_res.get("error")}

        try:
            cropped_img, bbox = crop_image_region(cap_res["path"], x, y, width, height)
            
            # Save cropped region temporarily
            crop_filename = f"crop_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            crop_path = get_screenshots_dir() / crop_filename
            cropped_img.save(str(crop_path), "PNG")

            ocr_res = run_ocr(str(crop_path), screen_width=width, screen_height=height)

            elements = detect_ui_elements(
                image_path=str(crop_path),
                ocr_result=ocr_res,
                screen_width=width,
                screen_height=height,
            )

            return {
                "success": True,
                "region": {
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                    "bbox": bbox.model_dump(),
                },
                "extracted_text": ocr_res.text,
                "element_count": len(elements),
                "elements": [e.model_dump() for e in elements[:10]],
                "crop_path": str(crop_path),
            }
        except Exception as e:
            logger.error("Failed to describe region: %s", e)
            return {"success": False, "error": f"Region analysis error: {str(e)}"}

    def get_last_screenshot_path(self) -> Optional[str]:
        """Return the path to the most recently captured screenshot."""
        if self._last_screenshot_path and Path(self._last_screenshot_path).is_file():
            return self._last_screenshot_path
        shots = list_screenshots(limit=1)
        if shots:
            return shots[0]["path"]
        return None


vision_engine = VisionEngine()

