"""
LAPTOP AI — WINDOWS DESKTOP CONTROL ENGINE: UI ELEMENT INSPECTION
Inspects accessible UI Automation elements in active or target application windows.
Extracts names, roles, bounds, and supported patterns in a compact, token-bounded structure.
Calculates independent descendant counts (total, visible, interactive, matched, returned, omitted)
and enforces exact element limits post-traversal without silent omission or hallucination.
"""
from __future__ import annotations
import ctypes
import logging
from typing import Optional, List, Dict, Any

from app.desktop.security import ensure_default_desktop, verify_desktop_available, is_sensitive_window
from app.desktop.windows import get_active_window, get_window_text, get_window_process_info
from app.core.security import audit

logger = logging.getLogger("laptop_ai.desktop.ui_inspection")

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

MAX_SAFE_DEPTH = 4
MAX_SAFE_ELEMENTS = 50

INTERACTIVE_CONTROL_TYPES = {
    "Button", "Edit", "MenuItem", "Menu", "MenuBar", "TabItem", "Tab",
    "ComboBox", "CheckBox", "RadioButton", "Hyperlink", "ListItem", "List",
    "TreeItem", "Tree", "ToolBar", "SplitButton", "Document", "ScrollBar",
    "Slider", "Spinner", "Thumb", "HeaderItem", "DataGrid"
}


def get_element_patterns(wrapper: Any) -> list[str]:
    """Safely detect which UI Automation patterns an element implements."""
    patterns = []
    candidates = [
        ("invoke", "Invoke"),
        ("value", "Value"),
        ("toggle", "Toggle"),
        ("selection_item", "SelectionItem"),
        ("scroll", "Scroll"),
        ("expand_collapse", "ExpandCollapse"),
    ]
    for attr, name in candidates:
        try:
            if getattr(wrapper, f"iface_{attr}", None):
                patterns.append(name)
        except Exception:
            pass
    return patterns


def inspect_ui(
    hwnd: Optional[int] = None,
    max_depth: int = 3,
    max_elements: int = 40,
    filter_types: Optional[List[str]] = None,
    interactive_only: bool = False,
) -> dict:
    """
    Inspect accessible UI elements in the active or target window using Windows UI Automation.
    Traverses the UI tree to max_depth and calculates:
      - total_descendants: All UIA descendants found at depth.
      - visible_descendants: Descendants with positive dimensions and visible status.
      - interactive_descendants: Descendants with interactive control types.
      - matched_descendants: Descendants matching query filters (interactive_only, filter_types).
      - elements_returned: Exact slice min(matched_descendants, limit).
      - elements_omitted: Elements matching filters but exceeding limit.
    Guarantees strict read-only execution.
    """
    try:
        if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "ole32"):
            ctypes.windll.ole32.CoInitialize(None)
    except Exception:
        pass

    try:
        verify_desktop_available()
        ensure_default_desktop()
    except Exception as e:
        return {"success": False, "accessible": False, "error": str(e)}

    target_hwnd = hwnd
    target_title = ""
    target_process = ""

    if not target_hwnd:
        active = get_active_window()
        if not active.get("has_active_window"):
            return {
                "success": False,
                "accessible": False,
                "error": "No active foreground window found to inspect.",
            }
        target_hwnd = active["hwnd"]
        target_title = active.get("title", "")
        target_process = active.get("process", "")
    else:
        target_title = get_window_text(target_hwnd)
        _, target_process = get_window_process_info(target_hwnd)

    if not target_hwnd or (user32 and not user32.IsWindow(target_hwnd)):
        return {
            "success": False,
            "accessible": False,
            "error": f"Invalid or closed window handle: HWND {target_hwnd}.",
        }

    # Security check for sensitive credential prompts
    if is_sensitive_window(target_title, target_process):
        audit("desktop.security_block", f"Blocked UI inspection of sensitive window: {target_title} ({target_process})")
        return {
            "success": False,
            "accessible": False,
            "is_sensitive": True,
            "error": f"Security restriction: Window '{target_title}' is an administrative or credential boundary. Inspection blocked.",
        }

    depth = max(1, min(max_depth, MAX_SAFE_DEPTH))
    limit = max(1, min(max_elements, MAX_SAFE_ELEMENTS))
    allowed_types = set(t.strip().lower() for t in filter_types) if filter_types else None
    filter_names = list(filter_types) if filter_types else []

    query_scope = {
        "max_depth": depth,
        "requested_limit": limit,
        "interactive_only": interactive_only,
        "filter_types": filter_names,
    }

    try:
        from pywinauto import Desktop
        d = Desktop(backend="uia")
        root_window = d.window(handle=target_hwnd)

        descendants = root_window.descendants(depth=depth)
        total_descendants = len(descendants)

        visible_count = 0
        interactive_count = 0
        matched_count = 0
        serialization_errors = 0

        matched_elements: list[dict] = []
        seen_element_keys: set = set()

        # Traverse ALL descendants without early break to ensure accurate counting
        for idx, child in enumerate(descendants):
            try:
                # 1. Retrieve control type directly from UIA property
                c_type = None
                if hasattr(child, "element_info") and hasattr(child.element_info, "control_type"):
                    c_type = child.element_info.control_type
                if not c_type:
                    c_type = "Unknown"
                else:
                    c_type = str(c_type).strip()

                is_interactive = c_type in INTERACTIVE_CONTROL_TYPES
                if is_interactive:
                    interactive_count += 1

                # 2. Retrieve bounding rectangle and dimensions safely
                rect = None
                width, height = 0, 0
                try:
                    rect = child.rectangle()
                    width = max(0, rect.right - rect.left)
                    height = max(0, rect.bottom - rect.top)
                except Exception:
                    rect = None

                is_visible = False
                try:
                    is_visible = bool(child.is_visible())
                except Exception:
                    pass

                # Element is visible if UIA reports visible and has positive bounding dimensions
                is_renderable = is_visible and (width > 0) and (height > 0)
                if is_renderable:
                    visible_count += 1

                # 3. Check query matching criteria
                if interactive_only and not is_interactive:
                    continue

                if allowed_types and c_type.lower() not in allowed_types:
                    continue

                # Query elements must be renderable
                if not is_renderable:
                    continue

                # Deduplication: check runtime_id or coordinate fingerprint
                runtime_id = getattr(child.element_info, "runtime_id", None)
                if runtime_id:
                    key = ("rid", tuple(runtime_id))
                else:
                    auto_id_val = getattr(child.element_info, "automation_id", None)
                    name_raw = ""
                    try:
                        name_raw = child.window_text().strip()
                    except Exception:
                        pass
                    key = ("prop", c_type, str(auto_id_val), name_raw, rect.left if rect else 0, rect.top if rect else 0, width, height)

                if key in seen_element_keys:
                    continue
                seen_element_keys.add(key)

                # Match count increments for every valid element matching filters
                matched_count += 1

                # 4. Serialize up to requested limit
                if len(matched_elements) < limit:
                    try:
                        name = child.window_text().strip()
                        auto_id_raw = getattr(child.element_info, "automation_id", None)
                        automation_id = None
                        if auto_id_raw is not None:
                            s_aid = str(auto_id_raw).strip()
                            if s_aid:
                                automation_id = s_aid

                        center_x = rect.left + (width // 2) if rect else 0
                        center_y = rect.top + (height // 2) if rect else 0

                        is_enabled = True
                        try:
                            is_enabled = bool(child.is_enabled())
                        except Exception:
                            pass

                        patterns = get_element_patterns(child)
                        elem_idx = len(matched_elements) + 1

                        matched_elements.append({
                            "id": elem_idx,
                            "element_id": elem_idx,
                            "name": name if len(name) <= 100 else name[:97] + "...",
                            "control_type": c_type,
                            "automation_id": automation_id,
                            "center": {"x": center_x, "y": center_y},
                            "bounds": [rect.left, rect.top, rect.right, rect.bottom] if rect else [0, 0, 0, 0],
                            "rect": {
                                "left": rect.left if rect else 0,
                                "top": rect.top if rect else 0,
                                "right": rect.right if rect else 0,
                                "bottom": rect.bottom if rect else 0,
                                "width": width,
                                "height": height,
                            },
                            "is_enabled": is_enabled,
                            "is_visible": is_visible,
                            "patterns": patterns,
                        })
                    except Exception as ser_err:
                        serialization_errors += 1
                        logger.warning("Failed to serialize UI element: %s", ser_err)

            except Exception as child_err:
                logger.debug("Failed during UI child inspection: %s", child_err)
                continue

        counts = {
            "total_descendants": total_descendants,
            "visible_descendants": visible_count,
            "interactive_descendants": interactive_count,
            "matched_descendants": matched_count,
            "elements_returned": len(matched_elements),
            "elements_omitted": max(0, matched_count - len(matched_elements)),
            "serialization_errors": serialization_errors,
        }

        audit(
            "desktop.ui_inspected",
            f"HWND {target_hwnd} ({target_title}): {len(matched_elements)} returned, "
            f"{counts['elements_omitted']} omitted, {total_descendants} total descendants",
        )

        return {
            "success": True,
            "accessible": True,
            "window": {
                "hwnd": target_hwnd,
                "title": target_title,
                "process": target_process,
            },
            "query_scope": query_scope,
            "counts": counts,
            "elements_count": len(matched_elements),
            "total_accessible_descendants": total_descendants,
            "truncated": counts["elements_omitted"] > 0,
            "elements": matched_elements,
        }

    except Exception as e:
        logger.warning("UI Automation inspection failed for HWND %s: %s", target_hwnd, e)
        return {
            "success": True,
            "accessible": False,
            "window": {
                "hwnd": target_hwnd,
                "title": target_title,
                "process": target_process,
            },
            "query_scope": query_scope,
            "counts": {
                "total_descendants": 0,
                "visible_descendants": 0,
                "interactive_descendants": 0,
                "matched_descendants": 0,
                "elements_returned": 0,
                "elements_omitted": 0,
                "serialization_errors": 0,
            },
            "elements_count": 0,
            "total_accessible_descendants": 0,
            "truncated": False,
            "elements": [],
            "reason": (
                f"Application UI tree is not accessible via Windows UIAutomation ({type(e).__name__}). "
                "The application may use custom hardware-accelerated graphics (e.g. WebGL, Direct3D, Java). "
                "Use window-relative coordinates, keyboard shortcuts, or screenshot analysis instead."
            ),
        }
