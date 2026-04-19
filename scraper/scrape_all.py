#!/usr/bin/env python3
"""
deals-finder scraper — Fast parallel scraping for second-hand tech deals.

Reads config.yaml for categories, search terms, and sources.
Outputs docs/latest.json for GitHub Pages.

Usage:
  python3 scraper/scrape_all.py              # uses config.yaml in repo root
  python3 scraper/scrape_all.py --config /path/to/config.yaml

Requirements:
  pip install pyyaml
  # For http_get scraping: no extra deps (stdlib only)
  # For browser-harness scraping: pip install browser-harness
"""
import json
import re
import sys
import time
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml required. Install: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


def load_config(config_path: str) -> dict:
    """Load config.yaml."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def http_get(url: str, headers: dict = None, timeout: int = 15) -> str:
    """Simple HTTP GET — no browser needed."""
    h = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml",
    }
    if headers:
        h.update(headers)
    req = Request(url, headers=h)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def scrape_blocket(query: str, category: str, config: dict) -> list[dict]:
    """Scrape Blocket via http_get (static HTML)."""
    url = f"https://www.blocket.se/recommerce/forsale/search?category=0.93&q={quote(query)}"
    try:
        html = http_get(url, timeout=config.get("timeout", 15))
    except Exception as e:
        print(f"  ⚠ blocket/{query}: {e}", file=sys.stderr)
        return []

    if not html or len(html) < 5000:
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


def scrape_tradera(query: str, category: str, config: dict) -> list[dict]:
    """
    Scrape Tradera. Items load client-side — this uses HTML text patterns.
    For better results, use browser-harness or the Cloud SDK.
    """
    url = f"https://www.tradera.com/search?q={quote(query)}"
    try:
        html = http_get(url, timeout=config.get("timeout", 15))
    except Exception as e:
        print(f"  ⚠ tradera/{query}: {e}", file=sys.stderr)
        return []

    if not html or len(html) < 5000:
        return []

    items = []
    # Extract from raw text pattern: title + "Pris:XXX kr"
    text_blocks = re.findall(
        r'(?:title|aria-label)="([^"]{10,})"[^>]*href="(/item/\d+/[^"]+)"',
        html
    )
    # Find all prices
    prices_on_page = re.findall(r'(\d[\d\s]*)\s*kr', html)

    seen = set()
    for title, path in text_blocks:
        full_url = f"https://www.tradera.com{path}"
        if full_url in seen:
            continue
        seen.add(full_url)
        # Try to find price near this item in the HTML
        idx = html.find(path)
        nearby = html[idx:idx + 1000] if idx > 0 else ""
        price_m = re.search(r'Pris:\s*(\d[\d\s]*)\s*kr', nearby)
        price = int(price_m.group(1).replace(' ', '').replace('\xa0', '')) if price_m else None
        if title and price:
            items.append({
                "title": title[:120],
                "url": full_url,
                "price": price,
                "category": category,
                "source": "tradera",
            })

    print(f"  ✓ tradera/{query}: {len(items)} items", file=sys.stderr)
    return items


# Source dispatch table
SCRAPERS = {
    "blocket": scrape_blocket,
    "tradera": scrape_tradera,
    # Add more sources here:
    # "vinted": scrape_vinted,
    # "ebay": scrape_ebay,
}


def scrape_all(config: dict) -> dict:
    """Scrape all enabled sources in parallel."""
    start = time.time()
    all_items = []
    scraper_config = config.get("scraper", {})
    categories = config.get("categories", {})
    sources = config.get("sources", [])
    enabled_sources = {s["name"] for s in sources if s.get("enabled", True)}

    # Build tasks
    tasks = []
    for cat_key, cat_cfg in categories.items():
        queries = cat_cfg.get("queries", [])
        for q in queries:
            for src_name in enabled_sources:
                if src_name in SCRAPERS:
                    tasks.append((SCRAPERS[src_name], q, cat_key))

    if not tasks:
        print("⚠ No tasks to run. Check config.yaml categories and sources.", file=sys.stderr)
        return {"date": datetime.now().strftime("%Y-%m-%d"), "currency": "SEK", "items": []}

    # Execute in parallel
    max_workers = scraper_config.get("max_workers", 8)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(fn, query, cat, scraper_config) for fn, query, cat in tasks]
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
    sources_used = sorted(set(i["source"] for i in unique))
    print(f"\n✓ {len(unique)} unique items from {sources_used} in {elapsed:.1f}s", file=sys.stderr)

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "currency": "SEK",
        "scrape_time_seconds": round(elapsed, 1),
        "sources": sources_used,
        "items": unique,
    }


def save_output(data: dict, docs_dir: str):
    """Save latest.json and archive snapshot."""
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)
    archive_dir = docs / "archive"
    archive_dir.mkdir(exist_ok=True)

    date = data["date"]

    # Save latest.json
    latest_path = docs / "latest.json"
    with open(latest_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✓ Saved {latest_path}", file=sys.stderr)

    # Save archive
    archive_json = archive_dir / f"{date}.json"
    with open(archive_json, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Update archive index
    archive_index_path = archive_dir / "archive.json"
    archive_index = []
    if archive_index_path.exists():
        try:
            archive_index = json.loads(archive_index_path.read_text())
        except json.JSONDecodeError:
            pass

    # Add today if not already there
    if not any(e.get("date") == date for e in archive_index):
        archive_index.insert(0, {"date": date, "count": len(data["items"])})
        archive_index = archive_index[:90]  # keep 90 days

    with open(archive_index_path, "w") as f:
        json.dump(archive_index, f, indent=2)

    print(f"✓ Archive: {archive_json}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Scrape second-hand tech deals")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--docs", default="docs", help="Output directory for GitHub Pages")
    parser.add_argument("--dry-run", action="store_true", help="Print JSON to stdout, don't save files")
    args = parser.parse_args()

    # Find config relative to repo root
    config_path = Path(args.config)
    if not config_path.is_absolute():
        # Look relative to this script's parent directory
        script_dir = Path(__file__).parent
        repo_root = script_dir.parent
        config_path = repo_root / args.config

    if not config_path.exists():
        print(f"ERROR: Config not found: {config_path}", file=sys.stderr)
        print("Copy config.yaml.example to config.yaml and edit it.", file=sys.stderr)
        sys.exit(1)

    config = load_config(str(config_path))
    result = scrape_all(config)

    if args.dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        docs_dir = Path(args.docs)
        if not docs_dir.is_absolute():
            docs_dir = Path(__file__).parent.parent / args.docs
        save_output(result, str(docs_dir))


if __name__ == "__main__":
    main()
