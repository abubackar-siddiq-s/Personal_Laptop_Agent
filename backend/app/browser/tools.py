from __future__ import annotations
from app.tools.registry import registry, Spec
from app.browser.engine import browser
from app.browser.search import search_web, fetch_page_content


def register_browser_tools():
    """Register all Phase 4 Browser & Web Automation tools into the unified registry."""

    # 1. browser.open
    registry.add(Spec(
        name="browser.open",
        description="Open a new browser tab, optionally navigating to an HTTP/HTTPS URL.",
        source="browser",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Optional HTTP or HTTPS URL to load in the new tab."}
            },
        },
        handler=lambda url=None, **kwargs: browser.open_tab(url=url),
    ))

    # 2. browser.navigate
    registry.add(Spec(
        name="browser.navigate",
        description="Navigate the active browser tab to a secure external HTTP or HTTPS URL.",
        source="browser",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The destination URL to visit (must be HTTP or HTTPS)."}
            },
            "required": ["url"],
        },
        handler=lambda url, **kwargs: browser.navigate(url=url),
    ))

    # 3. browser.back
    registry.add(Spec(
        name="browser.back",
        description="Navigate back to the previous page in history.",
        source="browser",
        risk="read",
        schema={"type": "object", "properties": {}},
        handler=lambda **kwargs: browser.back(),
    ))

    # 4. browser.forward
    registry.add(Spec(
        name="browser.forward",
        description="Navigate forward in browser history.",
        source="browser",
        risk="read",
        schema={"type": "object", "properties": {}},
        handler=lambda **kwargs: browser.forward(),
    ))

    # 5. browser.refresh
    registry.add(Spec(
        name="browser.refresh",
        description="Reload the currently active tab.",
        source="browser",
        risk="read",
        schema={"type": "object", "properties": {}},
        handler=lambda **kwargs: browser.refresh(),
    ))

    # 6. browser.get_url
    registry.add(Spec(
        name="browser.get_url",
        description="Get the current URL of the active browser tab.",
        source="browser",
        risk="read",
        schema={"type": "object", "properties": {}},
        handler=lambda **kwargs: browser.get_url(),
    ))

    # 7. browser.get_title
    registry.add(Spec(
        name="browser.get_title",
        description="Get the title of the active browser tab.",
        source="browser",
        risk="read",
        schema={"type": "object", "properties": {}},
        handler=lambda **kwargs: browser.get_title(),
    ))

    # 8. browser.get_text
    registry.add(Spec(
        name="browser.get_text",
        description="Extract visible readable text from the page. Output is isolated with anti-prompt-injection delimiters.",
        source="browser",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Optional CSS selector to extract text from a specific element instead of the whole page."}
            },
        },
        handler=lambda selector=None, **kwargs: browser.get_text(selector=selector),
    ))

    # 9. browser.get_links
    registry.add(Spec(
        name="browser.get_links",
        description="Extract visible hyperlinks from the page with their anchor text and destination URLs.",
        source="browser",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "max_links": {"type": "integer", "description": "Maximum number of links to return (default: 50)."}
            },
        },
        handler=lambda max_links=50, **kwargs: browser.get_links(max_links=max_links),
    ))

    # 10. browser.find_element
    registry.add(Spec(
        name="browser.find_element",
        description="Locate an element on the active page and inspect its visibility, enabled state, and text using semantic locators (role, text, label, placeholder) or CSS/XPath.",
        source="browser",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Semantic locator (e.g. 'button[name=Submit]', 'text=Search', 'role=button', 'placeholder=Email') or CSS selector."},
                "selector_type": {"type": "string", "enum": ["semantic", "css", "xpath", "role", "text", "label", "placeholder", "test_id"], "description": "Locator strategy (default: semantic)."}
            },
            "required": ["selector"],
        },
        handler=lambda selector, selector_type="semantic", **kwargs: browser.find_element(selector=selector, selector_type=selector_type),
    ))

    # 11. browser.click (Approval Required)
    registry.add(Spec(
        name="browser.click",
        description="Click an interactive element (button, link, checkbox, tab) on the active page. Requires explicit user approval.",
        source="browser",
        risk="approval",
        schema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Semantic locator or CSS selector of the element to click."},
                "selector_type": {"type": "string", "enum": ["semantic", "css", "xpath", "role", "text", "label", "placeholder"], "description": "Locator strategy."}
            },
            "required": ["selector"],
        },
        handler=lambda selector, selector_type="semantic", **kwargs: browser.click(selector=selector, selector_type=selector_type),
    ))

    # 12. browser.fill (Approval Required)
    registry.add(Spec(
        name="browser.fill",
        description="Fill an input field or textarea with text. Requires explicit user approval.",
        source="browser",
        risk="approval",
        schema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Semantic locator or CSS selector of the input element."},
                "text": {"type": "string", "description": "The text to populate into the input field."},
                "selector_type": {"type": "string", "enum": ["semantic", "css", "xpath", "role", "text", "label", "placeholder"], "description": "Locator strategy."}
            },
            "required": ["selector", "text"],
        },
        handler=lambda selector, text, selector_type="semantic", **kwargs: browser.fill(selector=selector, text=text, selector_type=selector_type),
    ))

    # 13. browser.type (Approval Required)
    registry.add(Spec(
        name="browser.type",
        description="Type characters sequentially into an element. Requires explicit user approval.",
        source="browser",
        risk="approval",
        schema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Semantic locator or CSS selector of the input element."},
                "text": {"type": "string", "description": "The text to type."},
                "selector_type": {"type": "string", "enum": ["semantic", "css", "xpath", "role", "text", "label", "placeholder"], "description": "Locator strategy."}
            },
            "required": ["selector", "text"],
        },
        handler=lambda selector, text, selector_type="semantic", delay_ms=50, **kwargs: browser.type(selector=selector, text=text, selector_type=selector_type, delay_ms=delay_ms),
    ))

    # 14. browser.select (Approval Required)
    registry.add(Spec(
        name="browser.select",
        description="Select an option from a dropdown (<select>) element. Requires explicit user approval.",
        source="browser",
        risk="approval",
        schema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Semantic locator or CSS selector of the select dropdown."},
                "value": {"type": "string", "description": "Value or label of the option to select."},
                "selector_type": {"type": "string", "enum": ["semantic", "css", "xpath", "role", "text", "label"], "description": "Locator strategy."}
            },
            "required": ["selector", "value"],
        },
        handler=lambda selector, value, selector_type="semantic", **kwargs: browser.select(selector=selector, value=value, selector_type=selector_type),
    ))

    # 15. browser.press_key (Approval Required)
    registry.add(Spec(
        name="browser.press_key",
        description="Press a keyboard key (e.g. 'Enter', 'Escape', 'Tab', 'ArrowDown'). Requires explicit user approval.",
        source="browser",
        risk="approval",
        schema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key name to press (e.g. 'Enter', 'Escape', 'Tab', 'Backspace')."}
            },
            "required": ["key"],
        },
        handler=lambda key, **kwargs: browser.press_key(key=key),
    ))

    # 16. browser.scroll
    registry.add(Spec(
        name="browser.scroll",
        description="Scroll the active page up, down, to the top, or to the bottom.",
        source="browser",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["down", "up", "top", "bottom"], "description": "Direction to scroll."},
                "amount": {"type": "integer", "description": "Pixel scroll amount (default: 500)."}
            },
        },
        handler=lambda direction="down", amount=500, **kwargs: browser.scroll(direction=direction, amount=amount),
    ))

    # 17. browser.screenshot
    registry.add(Spec(
        name="browser.screenshot",
        description="Capture a screenshot of the active browser tab, saving it to Downloads/LAPTOP_AI/screenshots.",
        source="browser",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "full_page": {"type": "boolean", "description": "Whether to capture the entire scrollable page height (default: false)."}
            },
        },
        handler=lambda full_page=False, **kwargs: browser.screenshot_summary(full_page=full_page),
    ))

    # 18. browser.close_tab
    registry.add(Spec(
        name="browser.close_tab",
        description="Close a specific tab by index or close the active tab.",
        source="browser",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "Zero-based tab index to close. If omitted, closes active tab."}
            },
        },
        handler=lambda index=None, **kwargs: browser.close_tab(index=index),
    ))

    # 19. browser.list_tabs
    registry.add(Spec(
        name="browser.list_tabs",
        description="List all open tabs in the browser with index, title, URL, and active status.",
        source="browser",
        risk="read",
        schema={"type": "object", "properties": {}},
        handler=lambda **kwargs: browser.list_tabs(),
    ))

    # 20. browser.search
    registry.add(Spec(
        name="browser.search",
        description="Search the web using DuckDuckGo to obtain relevant search results with titles, source URLs, and summaries.",
        source="browser",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The web search query string."},
                "max_results": {"type": "integer", "description": "Maximum number of search results to retrieve (default: 5)."}
            },
            "required": ["query"],
        },
        handler=lambda query, max_results=5, **kwargs: search_web(query=query, max_results=max_results),
    ))

    # 21. browser.download_file
    registry.add(Spec(
        name="browser.download_file",
        description="Download a file or PDF from a secure HTTP/HTTPS URL into Downloads/LAPTOP_AI. Validates HTTP 200, Content-Type, non-zero size, and format magic bytes (e.g. %PDF-). Execution of untrusted files is blocked.",
        source="browser",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The HTTP or HTTPS URL of the file to download."},
                "expected_type": {"type": "string", "description": "Optional file type expected, e.g. 'pdf'."},
                "filename": {"type": "string", "description": "Optional target filename."}
            },
            "required": ["url"],
        },
        handler=lambda url, expected_type=None, filename=None, **kwargs: browser.download_file(url=url, expected_type=expected_type, filename=filename),
    ))

    # 22. browser.analyze_tab
    registry.add(Spec(
        name="browser.analyze_tab",
        description="Inspect and describe what is visible in the active browser tab using multimodal vision capabilities (with automatic text-only model detection).",
        source="browser",
        risk="read",
        schema={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Specific questions or instructions about what to inspect in the tab."}
            },
        },
        handler=lambda prompt="Describe what is currently visible in this browser tab", **kwargs: browser.analyze_active_tab(prompt=prompt),
    ))
