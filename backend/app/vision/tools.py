"""
LAPTOP AI — VISUAL DESKTOP INTELLIGENCE: AGENT TOOLS REGISTRATION
Registers the 5 vision intelligence tools into the central unified tool registry:
1. vision.screen.analyze
2. vision.screen.extract_text
3. vision.screen.find_element
4. vision.screen.compare
5. vision.screen.describe_region
"""
from __future__ import annotations
import logging
from typing import Optional

from app.tools.registry import registry, Spec
from app.vision.engine import vision_engine

logger = logging.getLogger("laptop_ai.vision.tools")


def register_vision_tools() -> None:
    """Register all Visual Desktop Intelligence tools in the central tool registry."""

    # 1. vision.screen.analyze
    registry.add(Spec(
        name="vision.screen.analyze",
        description="Visually inspect and analyze the Windows desktop or active application window. Identifies running applications, visible text, UI layout, error dialogs, and visual warnings.",
        source="vision",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["desktop", "window"],
                    "description": "Capture the entire desktop or only the active window. Default is 'desktop'.",
                    "default": "desktop",
                },
                "prompt": {
                    "type": "string",
                    "description": "Optional specific visual question or inspection focus (e.g. 'What error message is shown?').",
                },
                "hwnd": {
                    "type": "integer",
                    "description": "Optional specific window handle to capture when target is 'window'.",
                },
            },
        },
        handler=lambda target="desktop", prompt=None, hwnd=None, **kwargs: vision_engine.analyze_screen(
            target=target, prompt=prompt, hwnd=hwnd
        ),
    ))

    # 2. vision.screen.extract_text
    registry.add(Spec(
        name="vision.screen.extract_text",
        description="Extract visible text from the Windows desktop or active window using local Optical Character Recognition (OCR). Returns line-by-line and word-level text with screen coordinates.",
        source="vision",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["desktop", "window"],
                    "description": "Target screen area ('desktop' or 'window'). Default is 'desktop'.",
                    "default": "desktop",
                },
                "hwnd": {
                    "type": "integer",
                    "description": "Optional specific window handle to inspect.",
                },
            },
        },
        handler=lambda target="desktop", hwnd=None, **kwargs: vision_engine.extract_text(
            target=target, hwnd=hwnd
        ).model_dump(),
    ))

    # 3. vision.screen.find_element
    registry.add(Spec(
        name="vision.screen.find_element",
        description="Locate a specific visual UI element on screen by query (e.g. 'Save button', 'browser address bar', 'error dialog'). Returns bounding boxes, center coordinates, and cross-verification status without clicking.",
        source="vision",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Description or text of the element to locate (e.g. 'Save', 'Search bar', 'Cancel').",
                },
                "target": {
                    "type": "string",
                    "enum": ["desktop", "window"],
                    "description": "Search across the entire 'desktop' or within active 'window'. Default is 'desktop'.",
                    "default": "desktop",
                },
                "hwnd": {
                    "type": "integer",
                    "description": "Optional specific window handle to search.",
                },
            },
            "required": ["query"],
        },
        handler=lambda query, target="desktop", hwnd=None, **kwargs: vision_engine.find_element(
            query=query, target=target, hwnd=hwnd
        ).model_dump(),
    ))

    # 4. vision.screen.compare
    registry.add(Spec(
        name="vision.screen.compare",
        description="Compare two desktop screenshots to detect visual changes, layout modifications, and changed screen regions while suppressing sub-pixel rendering noise.",
        source="vision",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "image_path_1": {
                    "type": "string",
                    "description": "File path to the base screenshot.",
                },
                "image_path_2": {
                    "type": "string",
                    "description": "File path to the comparison screenshot.",
                },
            },
            "required": ["image_path_1", "image_path_2"],
        },
        handler=lambda image_path_1, image_path_2, **kwargs: vision_engine.compare_screens(
            image_path_1=image_path_1, image_path_2=image_path_2
        ).model_dump(),
    ))

    # 5. vision.screen.describe_region
    registry.add(Spec(
        name="vision.screen.describe_region",
        description="Inspect and describe a specific rectangular region of the desktop specified by pixel coordinates (x, y, width, height).",
        source="vision",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "Left pixel coordinate."},
                "y": {"type": "integer", "description": "Top pixel coordinate."},
                "width": {"type": "integer", "description": "Width of the region in pixels."},
                "height": {"type": "integer", "description": "Height of the region in pixels."},
                "target": {
                    "type": "string",
                    "enum": ["desktop", "window"],
                    "description": "Screen target ('desktop' or 'window'). Default is 'desktop'.",
                    "default": "desktop",
                },
            },
            "required": ["x", "y", "width", "height"],
        },
        handler=lambda x, y, width, height, target="desktop", **kwargs: vision_engine.describe_region(
            x=x, y=y, width=width, height=height, target=target
        ),
    ))

    logger.info("Successfully registered 5 Visual Desktop Intelligence tools into central registry.")

