"""
LAPTOP AI — VISUAL DESKTOP INTELLIGENCE SUBSYSTEM
"""
from app.vision.schemas import (
    BoundingBox,
    OCRWord,
    OCRLine,
    OCRResult,
    DetectedElement,
    ScreenAnalysisResult,
    VisualGroundingResult,
    ImageComparisonResult,
)
from app.vision.security import verify_vision_execution_allowed, sanitize_visual_text
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
from app.vision.engine import vision_engine, VisionEngine
from app.vision.tools import register_vision_tools

__all__ = [
    "BoundingBox",
    "OCRWord",
    "OCRLine",
    "OCRResult",
    "DetectedElement",
    "ScreenAnalysisResult",
    "VisualGroundingResult",
    "ImageComparisonResult",
    "verify_vision_execution_allowed",
    "sanitize_visual_text",
    "validate_image",
    "prepare_image_for_cloud",
    "crop_image_region",
    "cleanup_old_screenshots",
    "run_ocr",
    "detect_ui_elements",
    "ground_visual_element",
    "compare_screenshots",
    "vision_engine",
    "VisionEngine",
    "register_vision_tools",
]

