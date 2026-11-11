import asyncio
import sys
sys.path.insert(0, 'backend')
from app.browser.search import search_web

async def test():
    results = await search_web("official FastAPI documentation", max_results=5)
    print("SEARCH RESULTS:")
    for r in results:
        print(f"{r['rank']}. [{r['source_type'].upper()}] {r['title']} -> {r['url']}")
    
    # Assert canonical source is #1
    assert results[0]["is_canonical"] == True, "Rank 1 must be canonical official docs"
    assert "fastapi.tiangolo.com" in results[0]["url"], "URL should be fastapi.tiangolo.com"
    # Assert DevDocs or other third-party is filtered or tagged
    for r in results:
        if "devdocs.io" in r["url"]:
            assert r["source_type"] == "third_party"
    print("ALL SEARCH QUALITY ASSERTIONS PASSED!")

if __name__ == "__main__":
    asyncio.run(test())

