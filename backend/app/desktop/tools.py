"""
LAPTOP AI — WINDOWS DESKTOP CONTROL ENGINE: TOOL REGISTRATION
Registers the 9 desktop automation tools with the unified tool registry,
defining provider-safe JSON schemas, risk boundaries, and approval integration.
"""
from __future__ import annotations
import logging
from app.tools.registry import registry, Spec
from app.desktop.windows import get_active_window, list_windows, focus_window
from app.desktop.screenshots import capture_screenshot
from app.desktop.ui_inspection import inspect_ui
from app.desktop.actions import mouse_click, mouse_scroll, keyboard_type, keyboard_press

logger = logging.getLogger("laptop_ai.desktop.tools")


def register_desktop_tools():
    """Register all Phase 6 Desktop Automation tools into the unified tool registry."""

    # 1. desktop.window.active
    registry.add(Spec(
        name="desktop.window.active",
        description="Get detailed telemetry on the currently focused Windows application window (title, process, PID, geometry).",
        source="desktop",
        risk="read",
        schema={
            "type": "object",
            "properties": {},
        },
        handler=lambda **kwargs: get_active_window(),
    ))

    # 2. desktop.window.list
    registry.add(Spec(
        name="desktop.window.list",
        description="List all visible application windows currently open on the Windows desktop.",
        source="desktop",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximum number of windows to return (1..50). Default is 25.", "default": 25},
                "only_visible": {"type": "boolean", "description": "Whether to filter only visible windows. Default is True.", "default": True},
            },
        },
        handler=lambda limit=25, only_visible=True, **kwargs: list_windows(limit=limit, only_visible=only_visible),
    ))

    # 3. desktop.window.focus
    registry.add(Spec(
        name="desktop.window.focus",
        description="Switch focus to an open application window by HWND or title substring.",
        source="desktop",
        risk="approval",
        schema={
            "type": "object",
            "properties": {
                "hwnd": {"type": "integer", "description": "Optional specific window handle to focus."},
                "title": {"type": "string", "description": "Optional window title substring or process name to match and focus."},
            },
        },
        handler=lambda hwnd=None, title=None, **kwargs: focus_window(hwnd=hwnd, title=title),
    ))

    # 4. desktop.screen.capture
    registry.add(Spec(
        name="desktop.screen.capture",
        description="Capture a screenshot of the primary display or active application window and save to Downloads/LAPTOP_AI/Screenshots.",
        source="desktop",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "enum": ["desktop", "window"], "description": "Capture target ('desktop' or 'window'). Default is 'desktop'.", "default": "desktop"},
                "hwnd": {"type": "integer", "description": "Optional specific window handle to capture when target is 'window'."},
            },
        },
        handler=lambda target="desktop", hwnd=None, **kwargs: capture_screenshot(target=target, hwnd=hwnd),
    ))

    # 5. desktop.ui.inspect
    registry.add(Spec(
        name="desktop.ui.inspect",
        description="Inspect accessible UI Automation elements (buttons, inputs, tabs, menus) in the active or target window. Returns exact descendant counts (total, visible, interactive, matched, returned, omitted), query scope, and element attributes.",
        source="desktop",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "hwnd": {"type": "integer", "description": "Optional specific window handle to inspect (defaults to active window)."},
                "max_depth": {"type": "integer", "description": "Maximum UI tree depth to inspect (1..4). Default is 3.", "default": 3},
                "max_elements": {"type": "integer", "description": "Maximum number of accessible elements to return (1..50). Default is 40.", "default": 40},
                "filter_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional filter by control types (e.g. ['Button', 'Edit', 'MenuItem', 'TabItem']).",
                },
                "interactive_only": {"type": "boolean", "description": "Whether to return only clickable or editable controls.", "default": False},
            },
        },
        handler=lambda hwnd=None, max_depth=3, max_elements=40, filter_types=None, interactive_only=False, **kwargs: inspect_ui(
            hwnd=hwnd, max_depth=max_depth, max_elements=max_elements, filter_types=filter_types, interactive_only=interactive_only
        ),
    ))

    # 6. desktop.mouse.click
    registry.add(Spec(
        name="desktop.mouse.click",
        description="Click an identified accessible UI element by name/role, or click specific screen coordinates.",
        source="desktop",
        risk="approval",
        schema={
            "type": "object",
            "properties": {
                "element_query": {"type": "string", "description": "Name or text of the accessible UI element to click in active window."},
                "control_type": {"type": "string", "description": "Optional control type (e.g. 'Button', 'MenuItem', 'TabItem')."},
                "x": {"type": "integer", "description": "Optional fallback screen X coordinate."},
                "y": {"type": "integer", "description": "Optional fallback screen Y coordinate."},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Mouse button to click. Default is 'left'.", "default": "left"},
                "clicks": {"type": "integer", "description": "Number of clicks (1 for single, 2 for double). Default is 1.", "default": 1},
            },
        },
        handler=lambda element_query=None, control_type=None, x=None, y=None, button="left", clicks=1, **kwargs: mouse_click(
            element_query=element_query, control_type=control_type, x=x, y=y, button=button, clicks=clicks
        ),
    ))

    # 7. desktop.mouse.scroll
    registry.add(Spec(
        name="desktop.mouse.scroll",
        description="Scroll the active application window vertically or horizontally.",
        source="desktop",
        risk="approval",
        schema={
            "type": "object",
            "properties": {
                "clicks": {"type": "integer", "description": "Number of scroll notches (1..20). Default is 3.", "default": 3},
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"], "description": "Scroll direction. Default is 'down'.", "default": "down"},
                "x": {"type": "integer", "description": "Optional screen X position to scroll over."},
                "y": {"type": "integer", "description": "Optional screen Y position to scroll over."},
            },
        },
        handler=lambda clicks=3, direction="down", x=None, y=None, **kwargs: mouse_scroll(
            clicks=clicks, direction=direction, x=x, y=y
        ),
    ))

    # 8. desktop.keyboard.type
    registry.add(Spec(
        name="desktop.keyboard.type",
        description="Type text into the currently active application control or window.",
        source="desktop",
        risk="approval",
        schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text string to type into the active field."},
                "press_enter": {"type": "boolean", "description": "Whether to press Enter key after typing.", "default": False},
            },
            "required": ["text"],
        },
        handler=lambda text, press_enter=False, **kwargs: keyboard_type(text=text, press_enter=press_enter),
    ))

    # 9. desktop.keyboard.press
    registry.add(Spec(
        name="desktop.keyboard.press",
        description="Press a validated key or approved shortcut combination (e.g. 'ctrl+s', 'enter', 'tab', 'alt+tab').",
        source="desktop",
        risk="approval",
        schema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Individual key name (e.g. 'enter', 'tab', 'escape', 'f5')."},
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Combination of keys (e.g. ['ctrl', 's'] or ['alt', 'tab']).",
                },
                "modifiers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Modifiers to hold (e.g. ['ctrl'], ['alt'], ['shift']).",
                },
            },
        },
        handler=lambda key=None, keys=None, modifiers=None, **kwargs: keyboard_press(
            key=key, keys=keys, modifiers=modifiers
        ),
    ))

    logger.info("Successfully registered 9 desktop control engine tools.")

