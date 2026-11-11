from __future__ import annotations
import httpx
import logging
import urllib.parse
from bs4 import BeautifulSoup
from app.core.security import audit
from app.browser.security import sanitize_webpage_content

logger = logging.getLogger("laptop_ai.search")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Known canonical documentation mappings for major libraries/frameworks
CANONICAL_DOCS: dict[str, list[str]] = {
    "fastapi": ["fastapi.tiangolo.com", "github.com/fastapi/fastapi"],
    "python": ["python.org", "docs.python.org"],
    "react": ["react.dev", "reactjs.org"],
    "playwright": ["playwright.dev"],
    "pydantic": ["docs.pydantic.dev", "pydantic.dev"],
    "django": ["djangoproject.com", "docs.djangoproject.com"],
    "flask": ["flask.palletsprojects.com"],
    "sqlite": ["sqlite.org"],
    "typescript": ["typescriptlang.org"],
    "vite": ["vite.dev", "vitejs.dev"],
    "node": ["nodejs.org"],
    "nodejs": ["nodejs.org"],
    "rust": ["rust-lang.org", "doc.rust-lang.org"],
    "docker": ["docs.docker.com", "docker.com"],
    "tailwind": ["tailwindcss.com"],
    "nextjs": ["nextjs.org"],
    "vue": ["vuejs.org"],
    "express": ["expressjs.com"],
    "pytorch": ["pytorch.org"],
    "tensorflow": ["tensorflow.org"],
}

# Known third-party documentation aggregators and mirrors
THIRD_PARTY_AGGREGATORS = {
    "devdocs.io",
    "geeksforgeeks.org",
    "w3schools.com",
    "tutorialspoint.com",
    "javatpoint.com",
    "freecodecamp.org",
    "programiz.com",
    "cprogramming.com",
    "educative.io",
    "baeldung.com",
}


def clean_ddg_url(raw_url: str) -> str:
    """Extract clean target URL if redirected through DuckDuckGo."""
    if "uddg=" in raw_url:
        try:
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
            if "uddg" in parsed:
                return parsed["uddg"][0]
        except Exception:
            pass
    if raw_url.startswith("//"):
        return "https:" + raw_url
    return raw_url


def classify_search_result(url: str, title: str, query: str) -> tuple[str, bool, int]:
    """
    Classify a search result into official/canonical, third-party, or general.
    Returns: (source_type, is_canonical, rank_boost_score)
    Lower score = higher priority in ranked output.
    """
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    q_lower = query.lower()
    wants_official = any(w in q_lower for w in ("official", "canonical", "documentation", "docs"))

    # Check canonical library matches
    for tech, canonical_hosts in CANONICAL_DOCS.items():
        if tech in q_lower:
            for ch in canonical_hosts:
                if host == ch or host.endswith("." + ch):
                    return ("official", True, -100)

    # Check third-party aggregators
    for tpa in THIRD_PARTY_AGGREGATORS:
        if host == tpa or host.endswith("." + tpa):
            score = 200 if wants_official else 50
            return ("third_party", False, score)

    # Check general official or GitHub source code
    if host.endswith(".org") or host.endswith(".dev") or "github.com" in host:
        return ("general", False, -10)

    return ("general", False, 0)


async def search_web(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web via DuckDuckGo public search interface.
    Prioritizes official canonical documentation and tags/demotes third-party mirrors.
    """
    q = query.strip()
    if not q:
        raise ValueError("Search query cannot be empty.")

    headers = {"User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=12.0, headers=headers, follow_redirects=True) as client:
            resp = None
            for attempt in range(2):
                resp = await client.post("https://html.duckduckgo.com/html/", data={"q": q})
                if resp.status_code == 200:
                    break
                await asyncio.sleep(0.5)

            if not resp or resp.status_code != 200:
                # Fallback to GET request
                resp = await client.get(f"https://html.duckduckgo.com/html/?q={httpx.URL(q)}")

            if resp.status_code != 200:
                raise RuntimeError(f"Search provider returned status code {resp.status_code}")

            soup = BeautifulSoup(resp.text, "html.parser")
            raw_candidates = []
            
            for orig_rank, item in enumerate(soup.select(".result"), start=1):
                a_tag = item.select_one(".result__title a")
                snip_tag = item.select_one(".result__snippet")
                if not a_tag or not a_tag.get("href"):
                    continue

                title = a_tag.get_text(strip=True)
                raw_href = a_tag["href"]
                final_url = clean_ddg_url(raw_href)
                snippet = snip_tag.get_text(strip=True) if snip_tag else ""

                if not final_url.startswith(("http://", "https://")):
                    continue

                source_type, is_canonical, boost = classify_search_result(final_url, title, q)
                display_title = title
                if source_type == "third_party":
                    display_title = f"[Third-Party] {title}"

                raw_candidates.append({
                    "orig_rank": orig_rank,
                    "title": display_title,
                    "url": final_url,
                    "snippet": snippet,
                    "source_type": source_type,
                    "is_canonical": is_canonical,
                    "score": boost + orig_rank,
                })

            # Sort by score (canonical official first, third-party aggregators demoted)
            raw_candidates.sort(key=lambda x: x["score"])

            # If user explicitly asked for "official", filter out third-party aggregators if official results exist
            wants_official = "official" in q.lower()
            has_canonical = any(c["is_canonical"] for c in raw_candidates)
            if wants_official and has_canonical:
                filtered = [c for c in raw_candidates if c["source_type"] != "third_party"]
                if filtered:
                    raw_candidates = filtered

            results = []
            for rank, c in enumerate(raw_candidates[:max_results], start=1):
                results.append({
                    "rank": rank,
                    "title": c["title"],
                    "url": c["url"],
                    "snippet": c["snippet"],
                    "source_type": c["source_type"],
                    "is_canonical": c["is_canonical"],
                })

            audit("web.search", f"Query: '{q}' -> {len(results)} results (canonical prioritized)")
            return results
    except Exception as e:
        logger.error("Web search failed for '%s': %s", q, e)
        audit("web.search_failed", f"Query: '{q}', error: {str(e)}")
        raise RuntimeError(f"Web search failed: {type(e).__name__}: {str(e)}")


async def fetch_page_content(url: str, max_chars: int = 12_000) -> dict:
    """Fetch and parse visible text from a webpage."""
    headers = {"User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                raise RuntimeError(f"Failed to fetch page: HTTP {resp.status_code}")

            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
                tag.decompose()

            title = soup.title.string if soup.title else ""
            raw_text = soup.get_text(separator="\n", strip=True)
            sanitized = sanitize_webpage_content(title=title or url, url=url, raw_text=raw_text, max_chars=max_chars)

            return {
                "title": title or url,
                "url": url,
                "content": sanitized,
            }
    except Exception as e:
        logger.error("Fetch page content failed for '%s': %s", url, e)
        raise RuntimeError(f"Failed to fetch content from '{url}': {str(e)}")

