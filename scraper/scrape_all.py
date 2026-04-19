#!/usr/bin/env python3
"""
deals-finder scraper — Fast parallel scraping using browser-harness http_get.
Replaces 45+ browser_navigate calls with ~2 seconds of HTTP GETs.

Setup:
  cd /tmp/browser-harness && uv sync
  uv run python3 scraper/scrape_all.py

Output: docs/latest.json (same schema as current)
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote

# browser-harness http_get — pure HTTP, no browser
sys.path.insert(0, "/tmp/browser-harness")
from helpers import http_get

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
}

CATEGORIES = {
    "gpu": ["gpu", "grafikkort"],
    "keyboard": ["tangentbord"],
    "ram": ["ram ddr5", "ram ddr4"],
    "psu": ["nätaggregat"],
    "pc": ["gaming dator"],
    "retro": ["nintendo 64", "retro konsol"],
    "gaming": ["gaming headset"],
    "anime": ["anime figur"],
    "poster": ["poster"],
}


def scrape_blocket_search(query: str, category: str) -> list[dict]:
    """Scrape a single Blocket search page via http_get."""
    url = f"https://www.blocket.se/recommerce/forsale/search?category=0.93&q={quote(query)}"
    try:
        html = http_get(url, headers=HEADERS, timeout=15)
    except Exception as e:
        print(f"  ⚠ blocket/{query}: {e}", file=sys.stderr)
        return []

    if not html or len(html) < 5000:
        print(f"  ⚠ blocket/{query}: empty/blocked ({len(html) if html else 0} bytes)", file=sys.stderr)
        return []

    items = []
    articles = re.findall(r'<article[^>]*>(.*?)</article>', html, re.DOTALL)

    for art in articles:
        link_m = re.search(r'href="(https://www\.blocket\.se/recommerce/forsale/item/\d+)"', art)
        title_m = re.search(r'<h2[^>]*>(.*?)</h2>', art, re.DOTALL)
        price_m = re.search(r'(\d[\d\s]*)\s*kr', art)

        if link_m and title_m:
            title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
            price = int(price_m.group(1).replace(' ', '').replace('\xa0', '')) if price_m else None
            if title and price:
                items.append({
                    "title": title[:120],
                    "url": link_m.group(1),
                    "price": price,
                    "category": category,
                    "source": "blocket",
                })

    print(f"  ✓ blocket/{query}: {len(items)} items", file=sys.stderr)
    return items


def scrape_tradera_search(query: str, category: str) -> list[dict]:
    """
    Scrape Tradera. Items load client-side so we use browser-harness
    js() to extract after page renders. Falls back to HTML pattern matching.

    For now: stub returning empty — use browser-harness for real scraping.
    TODO: integrate browser-harness js() or find Tradera's search API.
    """
    url = f"https://www.tradera.com/search?q={quote(query)}"
    try:
        html = http_get(url, headers=HEADERS, timeout=15)
    except Exception as e:
        print(f"  ⚠ tradera/{query}: {e}", file=sys.stderr)
        return []

    if not html or len(html) < 5000:
        return []

    items = []
    # Extract items from SSR HTML text pattern: "Pris:XXX kr"
    # Pairs title+price from the raw text blocks
    blocks = re.findall(
        r'(?:title|aria-label)="([^"]+)"[^>]*href="(/item/\d+/[^"]+)".*?(?:Pris:)\s*(\d[\d\s]*)\s*kr',
        html, re.DOTALL
    )
    seen = set()
    for title, path, price_str in blocks:
        full_url = f"https://www.tradera.com{path}"
        if full_url in seen:
            continue
        seen.add(full_url)
        price = int(price_str.replace(' ', '').replace('\xa0', ''))
        items.append({
            "title": title[:120],
            "url": full_url,
            "price": price,
            "category": category,
            "source": "tradera",
        })

    print(f"  ✓ tradera/{query}: {len(items)} items (HTML pattern)", file=sys.stderr)
    return items


def scrape_all() -> dict:
    """Scrape all sources in parallel, return structured data."""
    start = time.time()
    all_items = []

    tasks = []
    for cat, queries in CATEGORIES.items():
        for q in queries:
            tasks.append((scrape_blocket_search, q, cat))
            # Add tradera when browser-harness integration is ready
            # tasks.append((scrape_tradera_search, q, cat))

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fn, query, cat) for fn, query, cat in tasks]
        for f in futures:
            try:
                all_items.extend(f.result())
            except Exception as e:
                print(f"  ⚠ task failed: {e}", file=sys.stderr)

    # Deduplicate by URL
    seen = set()
    unique = []
    for item in all_items:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    elapsed = time.time() - start
    print(f"\n✓ {len(unique)} unique items in {elapsed:.1f}s", file=sys.stderr)

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "currency": "SEK",
        "scrape_time_seconds": round(elapsed, 1),
        "sources": sorted(set(i["source"] for i in unique)),
        "items": unique,
    }


if __name__ == "__main__":
    result = scrape_all()
    print(json.dumps(result, ensure_ascii=False, indent=2))
