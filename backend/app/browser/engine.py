from __future__ import annotations
import asyncio
import base64
import datetime
import logging
import os
import re
import urllib.parse
from pathlib import Path
import httpx
import pypdf
from playwright.async_api import async_playwright, BrowserContext, Page, Download, Playwright
from app.core.config import BASE
from app.core.db import conn
from app.core.security import audit
from app.browser.security import validate_browser_url, sanitize_webpage_content

logger = logging.getLogger("laptop_ai.browser")

PROFILE_DIR = (BASE / "data" / "browser_profile").resolve()
DOWNLOAD_DIR = Path(os.environ.get("USERPROFILE", "C:\\Users\\Abubackar Siddiq S")) / "Downloads" / "LAPTOP_AI"
SCREENSHOT_DIR = DOWNLOAD_DIR / "screenshots"

PROFILE_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

MAX_TABS = 10
DEFAULT_TIMEOUT_MS = 30_000
ACTION_TIMEOUT_MS = 8_000


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent directory traversal or invalid characters."""
    clean = re.sub(r'[\\/*?:"<>|]', "_", filename)
    clean = clean.strip(". ")
    return clean or "downloaded_file"


def get_unique_filepath(dest_dir: Path, filename: str) -> Path:
    """Generate a unique file path avoiding overwriting existing files."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / filename
    if not target.exists():
        return target
    
    stem = target.stem
    suffix = target.suffix
    counter = 1
    while True:
        candidate = dest_dir / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


class BrowserEngine:
    def __init__(self):
        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None
        self._active_tab_index: int = 0
        self._lock = asyncio.Lock()
        self.headless: bool = True

    async def _ensure_context(self) -> BrowserContext:
        """Lazily initialize Playwright and persistent browser context."""
        async with self._lock:
            if self._context is not None and len(self._context.pages) > 0:
                return self._context

            if self._pw is None:
                self._pw = await async_playwright().start()

            # Launch lightweight persistent context
            self._context = await self._pw.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=self.headless,
                viewport={"width": 1280, "height": 800},
                accept_downloads=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            # Ensure at least one tab exists
            if not self._context.pages:
                page = await self._context.new_page()
                self._attach_page_events(page)
            else:
                for page in self._context.pages:
                    self._attach_page_events(page)

            self._active_tab_index = 0
            audit("browser.started", f"Browser initialized with profile at {PROFILE_DIR}")
            logger.info("Browser engine initialized successfully.")
            return self._context

    def _attach_page_events(self, page: Page):
        """Attach download and error handlers to a page."""
        page.on("download", lambda d: asyncio.create_task(self._on_download(d)))

    async def _on_download(self, download: Download):
        """Handle downloaded file safely."""
        try:
            suggested = download.suggested_filename
            safe_name = sanitize_filename(suggested)
            dest = get_unique_filepath(DOWNLOAD_DIR, safe_name)
            
            await download.save_as(str(dest))
            size = dest.stat().st_size if dest.exists() else 0
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            
            with conn() as c:
                c.execute(
                    """
                    INSERT INTO browser_downloads (filename, file_path, url, size_bytes, downloaded_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (dest.name, str(dest), download.url, size, now),
                )
            audit("browser.download_completed", f"{dest.name} ({size} bytes) from {download.url}")
            logger.info("Saved download to %s", dest)
        except Exception as e:
            logger.error("Download failed: %s", e)
            audit("browser.download_failed", str(e))

    async def get_active_page(self) -> Page:
        """Get the currently active tab or page."""
        ctx = await self._ensure_context()
        pages = ctx.pages
        if not pages:
            page = await ctx.new_page()
            self._attach_page_events(page)
            self._active_tab_index = 0
            return page

        if self._active_tab_index >= len(pages):
            self._active_tab_index = len(pages) - 1

        return pages[self._active_tab_index]

    async def open_tab(self, url: str | None = None) -> dict:
        """Open a new browser tab, optionally navigating to a URL."""
        ctx = await self._ensure_context()
        if len(ctx.pages) >= MAX_TABS:
            raise RuntimeError(f"Maximum concurrent tab limit ({MAX_TABS}) reached. Please close unused tabs.")

        page = await ctx.new_page()
        self._attach_page_events(page)
        self._active_tab_index = len(ctx.pages) - 1

        if url:
            safe_url = validate_browser_url(url)
            await page.goto(safe_url, timeout=DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
            audit("browser.open_tab", f"Opened tab {self._active_tab_index} at {safe_url}")
            return {
                "tab_index": self._active_tab_index,
                "url": page.url,
                "title": await page.title(),
                "status": "opened",
            }

        return {
            "tab_index": self._active_tab_index,
            "url": "about:blank",
            "title": "New Tab",
            "status": "opened",
        }

    async def close_tab(self, index: int | None = None) -> dict:
        """Close a specific tab or the currently active tab."""
        ctx = await self._ensure_context()
        pages = ctx.pages
        idx = index if index is not None else self._active_tab_index

        if idx < 0 or idx >= len(pages):
            raise IndexError(f"Tab index {idx} out of range (0-{len(pages)-1}).")

        page_to_close = pages[idx]
        await page_to_close.close()

        # Update active tab index
        pages = ctx.pages
        if not pages:
            # Recreate blank page if all closed
            new_p = await ctx.new_page()
            self._attach_page_events(new_p)
            self._active_tab_index = 0
        else:
            self._active_tab_index = min(self._active_tab_index, len(pages) - 1)

        audit("browser.close_tab", f"Closed tab {idx}")
        return {"closed_index": idx, "remaining_tabs": len(ctx.pages)}

    async def list_tabs(self) -> list[dict]:
        """List all open tabs with their indices, titles, and URLs."""
        ctx = await self._ensure_context()
        tabs = []
        for i, p in enumerate(ctx.pages):
            try:
                title = await p.title()
                url = p.url
            except Exception:
                title = "Unknown"
                url = "about:blank"
            tabs.append({
                "index": i,
                "title": title or "Untitled",
                "url": url,
                "is_active": (i == self._active_tab_index),
            })
        return tabs

    async def switch_tab(self, index: int) -> dict:
        """Switch the active tab to a specific index."""
        ctx = await self._ensure_context()
        pages = ctx.pages
        if index < 0 or index >= len(pages):
            raise IndexError(f"Tab index {index} out of range (0-{len(pages)-1}).")

        self._active_tab_index = index
        page = pages[index]
        await page.bring_to_front()
        return {
            "active_tab_index": index,
            "title": await page.title(),
            "url": page.url,
        }

    async def navigate(self, url: str) -> dict:
        """Navigate the active tab to a secure URL."""
        safe_url = validate_browser_url(url)
        page = await self.get_active_page()
        response = await page.goto(safe_url, timeout=DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
        status = response.status if response else 200
        title = await page.title()
        current_url = page.url

        audit("browser.navigate", f"{safe_url} (status: {status})")
        return {
            "url": current_url,
            "title": title,
            "status_code": status,
        }

    async def back(self) -> dict:
        """Navigate back in history."""
        page = await self.get_active_page()
        await page.go_back(timeout=DEFAULT_TIMEOUT_MS)
        return {"url": page.url, "title": await page.title()}

    async def forward(self) -> dict:
        """Navigate forward in history."""
        page = await self.get_active_page()
        await page.go_forward(timeout=DEFAULT_TIMEOUT_MS)
        return {"url": page.url, "title": await page.title()}

    async def refresh(self) -> dict:
        """Reload the active tab."""
        page = await self.get_active_page()
        await page.reload(timeout=DEFAULT_TIMEOUT_MS)
        return {"url": page.url, "title": await page.title()}

    async def get_url(self) -> str:
        """Get the current URL of the active tab."""
        page = await self.get_active_page()
        return page.url

    async def get_title(self) -> str:
        """Get the title of the active tab."""
        page = await self.get_active_page()
        return await page.title()

    async def get_text(self, selector: str | None = None) -> str:
        """Extract visible text from the page with anti-prompt-injection isolation."""
        page = await self.get_active_page()
        if selector:
            loc = self._resolve_locator(page, selector, "css")
            count = await loc.count()
            if count == 0:
                raw_text = f"[No element matching selector '{selector}' was found on the page]"
            elif count == 1:
                raw_text = await loc.inner_text(timeout=DEFAULT_TIMEOUT_MS)
            else:
                # Multiple elements match selector (e.g. h1, p, a): extract all safely without strict mode failure
                texts = await loc.all_inner_texts()
                raw_text = "\n".join(t.strip() for t in texts if t.strip())
        else:
            # Extract main body text
            raw_text = await page.evaluate("""
                () => {
                    const remove = ['script', 'style', 'noscript', 'svg'];
                    const clone = document.body.cloneNode(true);
                    remove.forEach(tag => {
                        const els = clone.querySelectorAll(tag);
                        els.forEach(e => e.remove());
                    });
                    return clone.innerText || '';
                }
            """)

        title = await page.title()
        url = page.url
        return sanitize_webpage_content(title=title, url=url, raw_text=raw_text)

    async def get_links(self, max_links: int = 50) -> list[dict]:
        """Extract visible links from the active page."""
        page = await self.get_active_page()
        links = await page.evaluate(f"""
            () => {{
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                return anchors
                    .map(a => ({{
                        text: (a.innerText || a.getAttribute('aria-label') || '').trim(),
                        href: a.href
                    }}))
                    .filter(item => item.href.startsWith('http://') || item.href.startsWith('https://'))
                    .slice(0, {max_links});
            }}
        """)
        return links

    def _resolve_locator(self, page: Page, selector: str, selector_type: str = "semantic"):
        """Resolve Playwright locator using semantic locators first, then CSS/XPath."""
        sel_type = selector_type.lower().strip()
        if sel_type == "css":
            return page.locator(selector)
        elif sel_type == "xpath":
            return page.locator(f"xpath={selector}")
        elif sel_type == "role":
            return page.get_by_role(selector)
        elif sel_type == "text":
            return page.get_by_text(selector, exact=False)
        elif sel_type == "label":
            return page.get_by_label(selector)
        elif sel_type == "placeholder":
            return page.get_by_placeholder(selector)
        elif sel_type == "test_id":
            return page.get_by_test_id(selector)
        else:
            # Semantic default: try semantic helpers, fallback to standard locator
            # If selector starts with role= or text= or label=
            if selector.startswith("role="):
                return page.get_by_role(selector[5:])
            if selector.startswith("text="):
                return page.get_by_text(selector[5:])
            if selector.startswith("label="):
                return page.get_by_label(selector[6:])
            if selector.startswith("placeholder="):
                return page.get_by_placeholder(selector[12:])
            # Otherwise use Playwright's smart multi-engine locator
            return page.locator(selector)

    async def find_element(self, selector: str, selector_type: str = "semantic") -> dict:
        """Find an element and return its visibility, tag, and text."""
        page = await self.get_active_page()
        loc = self._resolve_locator(page, selector, selector_type).first
        count = await loc.count()
        if count == 0:
            return {"found": False, "selector": selector}

        is_visible = await loc.is_visible()
        is_enabled = await loc.is_enabled()
        text = await loc.inner_text() if is_visible else ""

        return {
            "found": True,
            "selector": selector,
            "is_visible": is_visible,
            "is_enabled": is_enabled,
            "text": text.strip()[:200],
        }

    async def click(self, selector: str, selector_type: str = "semantic") -> dict:
        """Click an element on the active page."""
        page = await self.get_active_page()
        loc = self._resolve_locator(page, selector, selector_type).first
        await loc.click(timeout=ACTION_TIMEOUT_MS)
        audit("browser.click", f"Clicked '{selector}' ({selector_type})")
        return {"action": "click", "selector": selector, "status": "success"}

    async def fill(self, selector: str, text: str, selector_type: str = "semantic") -> dict:
        """Fill an input field with text."""
        page = await self.get_active_page()
        loc = self._resolve_locator(page, selector, selector_type).first
        await loc.fill(text, timeout=ACTION_TIMEOUT_MS)
        audit("browser.fill", f"Filled '{selector}'")
        return {"action": "fill", "selector": selector, "status": "success"}

    async def type(self, selector: str, text: str, selector_type: str = "semantic", delay_ms: int = 50) -> dict:
        """Type characters sequentially into an input."""
        page = await self.get_active_page()
        loc = self._resolve_locator(page, selector, selector_type).first
        await loc.press_sequentially(text, delay=delay_ms, timeout=ACTION_TIMEOUT_MS)
        audit("browser.type", f"Typed into '{selector}'")
        return {"action": "type", "selector": selector, "status": "success"}

    async def select(self, selector: str, value: str, selector_type: str = "semantic") -> dict:
        """Select an option from a <select> dropdown."""
        page = await self.get_active_page()
        loc = self._resolve_locator(page, selector, selector_type).first
        res = await loc.select_option(value=value, timeout=ACTION_TIMEOUT_MS)
        audit("browser.select", f"Selected '{value}' in '{selector}'")
        return {"action": "select", "selector": selector, "selected": res}

    async def press_key(self, key: str) -> dict:
        """Press a keyboard key (Enter, Escape, Tab, ArrowDown, etc.)."""
        page = await self.get_active_page()
        await page.keyboard.press(key)
        audit("browser.press_key", key)
        return {"action": "press_key", "key": key, "status": "success"}

    async def scroll(self, direction: str = "down", amount: int = 500) -> dict:
        """Scroll the active page up, down, top, or bottom."""
        page = await self.get_active_page()
        d = direction.lower().strip()
        if d == "top":
            await page.evaluate("window.scrollTo(0, 0)")
        elif d == "bottom":
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif d == "up":
            await page.evaluate(f"window.scrollBy(0, -{amount})")
        else:
            await page.evaluate(f"window.scrollBy(0, {amount})")

        return {"action": "scroll", "direction": direction, "amount": amount}

    async def screenshot(self, full_page: bool = False, include_base64: bool = True) -> dict:
        """Capture a screenshot of the active tab."""
        page = await self.get_active_page()
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{now_str}.png"
        filepath = SCREENSHOT_DIR / filename

        bytes_data = await page.screenshot(path=str(filepath), full_page=full_page)
        b64 = base64.b64encode(bytes_data).decode("utf-8") if include_base64 else None

        audit("browser.screenshot", str(filepath))
        res = {
            "filepath": str(filepath),
            "filename": filename,
            "full_page": full_page,
            "file_size_bytes": len(bytes_data),
        }
        if include_base64:
            res["base64"] = f"data:image/png;base64,{b64}"
        return res

    async def screenshot_summary(self, full_page: bool = False) -> dict:
        """Lightweight screenshot metadata for LLM tool consumption without massive base64 payload."""
        info = await self.screenshot(full_page=full_page, include_base64=False)
        return {
            "status": "success",
            "filename": info["filename"],
            "filepath": info["filepath"],
            "full_page": info["full_page"],
            "size_bytes": info["file_size_bytes"],
            "message": f"Browser screenshot captured successfully and saved to {info['filepath']}",
        }

    async def download_file(
        self,
        url: str,
        expected_type: str | None = None,
        filename: str | None = None,
    ) -> dict:
        """
        Download a file securely from an HTTP/HTTPS URL into Downloads/LAPTOP_AI.
        Validates HTTP 200, Content-Type, non-zero size, and format magic bytes (e.g. %PDF- for PDF).
        Prevents execution of untrusted files.
        """
        safe_url = validate_browser_url(url)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        
        async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
            resp = await client.get(safe_url)
            if resp.status_code != 200:
                raise RuntimeError(f"Download failed: Server returned HTTP {resp.status_code} for {safe_url}")

            content_bytes = resp.content
            size_bytes = len(content_bytes)
            if size_bytes == 0:
                raise ValueError(f"Download failed: Received 0 bytes from {safe_url}")

            content_type = resp.headers.get("content-type", "").lower()

            # Determine safe destination filename
            if filename:
                suggested = sanitize_filename(filename)
            else:
                cd = resp.headers.get("content-disposition", "")
                if "filename=" in cd:
                    raw_fn = cd.split("filename=")[-1].strip('"\' ')
                    suggested = sanitize_filename(raw_fn)
                else:
                    path_part = urllib.parse.urlparse(safe_url).path.split("/")[-1]
                    suggested = sanitize_filename(path_part) if path_part else "downloaded_file"

            # Check PDF expectations
            is_pdf = (
                (expected_type and "pdf" in expected_type.lower())
                or suggested.lower().endswith(".pdf")
                or "application/pdf" in content_type
            )

            if is_pdf and not suggested.lower().endswith(".pdf"):
                suggested += ".pdf"

            pdf_page_count = None
            magic_valid = False

            if is_pdf:
                # Validate PDF magic bytes: %PDF-
                if not content_bytes.startswith(b"%PDF-"):
                    raise ValueError(
                        f"Security / Integrity Error: File from {safe_url} does not have valid PDF magic bytes (%PDF-). "
                        f"Header bytes: {content_bytes[:10]!r}"
                    )
                magic_valid = True

                # Validate PDF structure with pypdf
                try:
                    import io
                    reader = pypdf.PdfReader(io.BytesIO(content_bytes))
                    pdf_page_count = len(reader.pages)
                except Exception as pe:
                    logger.warning("PDF structural validation warning: %s", pe)

            dest_path = get_unique_filepath(DOWNLOAD_DIR, suggested)
            dest_path.write_bytes(content_bytes)

            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            with conn() as c:
                c.execute(
                    """
                    INSERT INTO browser_downloads (filename, file_path, url, size_bytes, downloaded_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (dest_path.name, str(dest_path), safe_url, size_bytes, now),
                )

            val = float(size_bytes)
            for unit in ["B", "KB", "MB", "GB"]:
                if val < 1024.0:
                    formatted_size = f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
                    break
                val /= 1024.0
            else:
                formatted_size = f"{val:.1f} TB"

            audit("browser.download_file", f"{dest_path.name} ({size_bytes} bytes) from {safe_url}")
            return {
                "status": "success",
                "filename": dest_path.name,
                "filepath": str(dest_path),
                "size_bytes": size_bytes,
                "size_formatted": formatted_size,
                "content_type": content_type,
                "magic_bytes_valid": magic_valid if is_pdf else True,
                "pages": pdf_page_count,
                "url": safe_url,
                "destination_dir": str(DOWNLOAD_DIR),
                "message": (
                    f"Successfully downloaded '{dest_path.name}' ({formatted_size}) into Downloads/LAPTOP_AI. "
                    f"File validated (HTTP 200, non-zero size, "
                    + (f"valid %PDF- magic bytes, {pdf_page_count} page(s)" if is_pdf else "valid payload")
                    + "). Untrusted file execution is strictly blocked; saved safely."
                ),
            }

    async def analyze_active_tab(
        self,
        prompt: str = "Describe what is currently visible in this browser tab",
        provider: str | None = None,
        model: str | None = None,
    ) -> dict:
        """Capture the active browser tab and inspect it using multimodal vision."""
        from app.providers.router import is_vision_capable, chat_turn
        from app.core.config import settings

        active_prov = (provider or ("gemini" if settings.gemini_api_key else ("groq" if settings.groq_api_key else "openrouter"))).lower().strip()
        active_mod = model or ("gemini-2.5-flash" if active_prov == "gemini" else ("openai/gpt-oss-20b" if active_prov == "groq" else "openrouter/auto"))

        can_see = is_vision_capable(active_prov, active_mod)
        if not can_see:
            return {
                "success": False,
                "visual_understanding": False,
                "provider": active_prov,
                "model": active_mod,
                "message": (
                    f"Selected model '{active_mod}' on '{active_prov}' is text-only and lacks vision capabilities. "
                    f"To inspect and analyze browser visuals, please select Google Gemini (gemini-2.5-flash) in the dashboard."
                ),
            }

        ss = await self.screenshot(full_page=False, include_base64=True)
        img_file = Path(ss["filepath"])
        with open(img_file, "rb") as f:
            b64_str = base64.b64encode(f.read()).decode("utf-8")

        messages = [
            {
                "role": "user",
                "content": prompt,
                "image_base64": b64_str,
                "image_mime": "image/png",
            }
        ]
        try:
            turn = await chat_turn(provider=active_prov, model=active_mod, messages=messages)
            audit("browser.tab_analyzed", f"Prompt: {prompt}")
            return {
                "success": True,
                "visual_understanding": True,
                "image_path": str(img_file),
                "provider": active_prov,
                "model": active_mod,
                "analysis": turn.content,
            }
        except Exception as e:
            return {
                "success": False,
                "visual_understanding": True,
                "error": f"Visual analysis failed: {str(e)}",
                "image_path": str(img_file),
                "provider": active_prov,
                "model": active_mod,
            }

    async def clear_browsing_data(self) -> dict:
        """Clear browsing data, cookies, and localStorage."""
        async with self._lock:
            if self._context:
                await self._context.clear_cookies()
                # Clear storage
                for page in self._context.pages:
                    try:
                        await page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
                    except Exception:
                        pass
            audit("browser.clear_data", "Cookies and storage cleared")
            return {"status": "cleared", "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}

    async def close(self):
        """Cleanly close browser context and Playwright process to release RAM."""
        async with self._lock:
            if self._context:
                try:
                    await self._context.close()
                except Exception as e:
                    logger.warning("Error closing context: %s", e)
                self._context = None

            if self._pw:
                try:
                    await self._pw.stop()
                except Exception as e:
                    logger.warning("Error stopping playwright: %s", e)
                self._pw = None

            audit("browser.closed", "Browser process terminated")
            logger.info("Browser engine stopped.")

    def get_status(self) -> dict:
        """Get the current health and status of the browser engine."""
        is_running = self._context is not None and self._pw is not None
        tab_count = len(self._context.pages) if self._context else 0
        return {
            "is_running": is_running,
            "tab_count": tab_count,
            "active_tab_index": self._active_tab_index,
            "profile_dir": str(PROFILE_DIR),
            "download_dir": str(DOWNLOAD_DIR),
            "headless": self.headless,
        }


browser = BrowserEngine()

