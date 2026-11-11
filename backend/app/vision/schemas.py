"""
LAPTOP AI — VISUAL DESKTOP INTELLIGENCE: SCHEMAS & DATA MODELS
Pydantic schemas and dataclasses for visual element detection,
bounding box representations, OCR output, and screenshot comparisons.
"""
from __future__ import annotations
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Physical and normalized coordinates of a visual screen region."""
    x1: int = Field(..., description="Left pixel coordinate")
    y1: int = Field(..., description="Top pixel coordinate")
    x2: int = Field(..., description="Right pixel coordinate")
    y2: int = Field(..., description="Bottom pixel coordinate")
    width: int = Field(..., description="Box width in pixels")
    height: int = Field(..., description="Box height in pixels")
    center: list[int] = Field(default_factory=list, description="[center_x, center_y] pixel coordinates")
    normalized: list[float] = Field(default_factory=list, description="[nx1, ny1, nx2, ny2] in range 0.0 to 1.0")

    @classmethod
    def from_coords(cls, x1: int, y1: int, x2: int, y2: int, screen_width: int = 1920, screen_height: int = 1080) -> BoundingBox:
        x1_clamped = max(0, x1)
        y1_clamped = max(0, y1)
        x2_clamped = max(x1_clamped, x2)
        y2_clamped = max(y1_clamped, y2)
        w = x2_clamped - x1_clamped
        h = y2_clamped - y1_clamped
        cx = x1_clamped + (w // 2)
        cy = y1_clamped + (h // 2)

        sw = max(1, screen_width)
        sh = max(1, screen_height)
        norm = [
            round(x1_clamped / sw, 4),
            round(y1_clamped / sh, 4),
            round(x2_clamped / sw, 4),
            round(y2_clamped / sh, 4),
        ]
        return cls(
            x1=x1_clamped,
            y1=y1_clamped,
            x2=x2_clamped,
            y2=y2_clamped,
            width=w,
            height=h,
            center=[cx, cy],
            normalized=norm,
        )


class OCRWord(BaseModel):
    """A recognized text word with its physical bounding box."""
    text: str
    bbox: BoundingBox
    confidence: float = 1.0


class OCRLine(BaseModel):
    """A recognized line of text composed of individual words."""
    text: str
    bbox: BoundingBox
    words: list[OCRWord] = Field(default_factory=list)


class OCRResult(BaseModel):
    """Structured OCR extraction output."""
    success: bool
    text: str
    line_count: int
    lines: list[OCRLine] = Field(default_factory=list)
    image_path: str = ""
    engine_used: str = "winrt_native"
    duration_ms: float = 0.0
    error: Optional[str] = None


class DetectedElement(BaseModel):
    """A recognized visual UI component on the Windows desktop."""
    id: int
    element_type: str = Field(..., description="button, text_input, menu, dialog, toolbar, icon, tab, notification, error_warning")
    label: str
    description: str
    bbox: BoundingBox
    confidence: float = Field(..., ge=0.0, le=1.0)
    detection_method: str = Field(..., description="ocr_text, uia_fused, visual_heuristic, multimodal_ai")
    is_interactive: bool = True
    cross_verified_uia: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)


class ScreenAnalysisResult(BaseModel):
    """Holistic understanding of desktop visual state."""
    success: bool
    summary: str
    active_application: str
    window_title: str
    detected_elements: list[DetectedElement] = Field(default_factory=list)
    error_dialogs: list[DetectedElement] = Field(default_factory=list)
    visual_warnings: list[str] = Field(default_factory=list)
    key_text_snippets: list[str] = Field(default_factory=list)
    image_path: str = ""
    analysis_provider: str = ""
    duration_ms: float = 0.0
    error: Optional[str] = None


class VisualGroundingResult(BaseModel):
    """Result of targeting a specific visual element from natural language."""
    success: bool
    found: bool
    query: str
    matched_element: Optional[DetectedElement] = None
    all_candidates: list[DetectedElement] = Field(default_factory=list)
    confidence: float = 0.0
    detection_method: str = ""
    cross_verified_uia: bool = False
    safety_notice: str = "Visual grounding identifies target coordinates for inspection only. Autonomous clicking is disabled."
    warning: Optional[str] = None
    error: Optional[str] = None


class ImageComparisonResult(BaseModel):
    """Structural and visual difference analysis between two screenshots."""
    success: bool
    changed: bool
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    change_percentage: float = Field(..., ge=0.0, le=100.0)
    has_major_layout_change: bool = False
    changed_regions: list[BoundingBox] = Field(default_factory=list)
    change_summary: str
    image_path_1: str = ""
    image_path_2: str = ""
    error: Optional[str] = None

