"""
Main scraper runner. Loads config, runs all enabled scrapers, outputs structured JSON.

Usage:
  python scrape.py                    # run all scrapers
  python scrape.py --vendor blocket   # run single vendor
  python scrape.py --check            # dry run, check if scrapers load
"""

import argparse
import json
import os
import sys
import time
import traceback
import yaml
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from scrapers.base import load_all_scrapers, load_scraper, ScrapeResult


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def run_scrapers(config: dict, vendor_filter: str | None = None) -> tuple[list[dict], list[dict]]:
    """
    Run all enabled scrapers across all categories.
    Returns (all_items, errors) where errors is [{vendor, query, error}]
    """
    scrapers_dir = os.path.join(os.path.dirname(__file__), "scrapers")
    scrapers = load_all_scrapers(config, scrapers_dir)

    if vendor_filter:
        scrapers = {k: v for k, v in scrapers.items() if k == vendor_filter}

    if not scrapers:
        print("⚠ no scrapers loaded", file=sys.stderr)
        return [], []

    categories = config.get("categories", [])
    tasks = []
    for cat in categories:
        cat_name = cat["name"]
        for query in cat.get("queries", []):
            for vendor_name, scraper in scrapers.items():
                tasks.append((scraper, query, cat_name, vendor_name))

    print(f"  running {len(tasks)} scrape tasks across {len(scrapers)} vendors...", file=sys.stderr)

    all_items = []
    errors = []
    start = time.time()

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {}
        for scraper, query, cat_name, vendor_name in tasks:
            f = pool.submit(_safe_scrape, scraper, query, cat_name)
            futures[f] = (vendor_name, query, cat_name)

        for f in futures:
            vendor_name, query, cat_name = futures[f]
            try:
                result = f.result(timeout=60)
                if result.failed:
                    errors.append({
                        "vendor": vendor_name,
                        "query": query,
                        "category": cat_name,
                        "errors": result.errors,
                    })
                else:
                    all_items.extend(result.items)
            except Exception as e:
                errors.append({
                    "vendor": vendor_name,
                    "query": query,
                    "category": cat_name,
                    "errors": [str(e)],
                })

    # Deduplicate by URL
    seen = set()
    unique = []
    for item in all_items:
        url = item.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(item)

    elapsed = time.time() - start
    print(f"  ✓ {len(unique)} unique items, {len(errors)} errors in {elapsed:.1f}s", file=sys.stderr)

    return unique, errors


def _safe_scrape(scraper, query: str, category: str) -> ScrapeResult:
    """Run a scraper with error handling."""
    try:
        return scraper.scrape(query, category)
    except Exception as e:
        tb = traceback.format_exc()
        return ScrapeResult(
            items=[],
            errors=[f"{type(e).__name__}: {e}\n{tb}"],
            vendor=scraper.name,
            query=query,
        )


def build_output(items: list[dict], config: dict) -> dict:
    """Build the final JSON output."""
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "currency": config.get("user", {}).get("currency", "SEK"),
        "items": items,
    }


def main():
    parser = argparse.ArgumentParser(description="deals-finder scraper runner")
    parser.add_argument("--config", default="config.yaml", help="config file path")
    parser.add_argument("--vendor", help="run only this vendor")
    parser.add_argument("--check", action="store_true", help="dry run — just check scrapers load")
    parser.add_argument("--output", default="docs/latest.json", help="output JSON path")
    parser.add_argument("--auto-heal", action="store_true", help="auto-trigger hermes repair on failures")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.check:
        scrapers = load_all_scrapers(config)
        for name, scraper in scrapers.items():
            print(f"  ✓ {name} loaded")
        missing = [v["name"] for v in config.get("vendors", []) if v.get("enabled", True) and v["name"] not in scrapers]
        for name in missing:
            print(f"  ✗ {name} — no scraper file found")
        return

    items, errors = run_scrapers(config, args.vendor)

    if errors:
        print(f"\n⚠ {len(errors)} scrape errors:", file=sys.stderr)
        for err in errors:
            print(f"  {err['vendor']}/{err['query']}: {err['errors'][0][:100]}", file=sys.stderr)

    # Write output
    output = build_output(items, config)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  → {args.output}", file=sys.stderr)

    # Write errors file for self-healing
    if errors:
        errors_path = os.path.join(os.path.dirname(args.output), ".scrape_errors.json")
        with open(errors_path, "w") as f:
            json.dump(errors, f, ensure_ascii=False, indent=2)
        print(f"  → {errors_path} (for self-healing)", file=sys.stderr)

        if args.auto_heal:
            _trigger_healing(config, errors)


def _trigger_healing(config: dict, errors: list[dict]):
    """Auto-trigger hermes self-healing when scrapers fail."""
    by_vendor = {}
    for err in errors:
        v = err["vendor"]
        if v not in by_vendor:
            by_vendor[v] = []
        by_vendor[v].append(err)

    # Check retry limits
    heal_config = config.get("self_heal", {})
    max_retries = heal_config.get("max_retries", 2)
    state_file = ".heal_state.json"

    try:
        with open(state_file) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}

    should_heal = False
    for vendor, errs in by_vendor.items():
        retries = state.get(vendor, 0)
        if retries < max_retries:
            should_heal = True
            state[vendor] = retries + 1
            print(f"  ⟳ auto-heal: {vendor} (attempt {retries + 1}/{max_retries})", file=sys.stderr)
        else:
            print(f"  ✗ {vendor}: max retries ({max_retries}) reached — needs manual fix", file=sys.stderr)

    with open(state_file, "w") as f:
        json.dump(state, f)

    if should_heal:
        # Generate healing prompt
        from setup import _build_heal_prompt
        prompt = _build_heal_prompt(by_vendor, config)
        heal_path = ".hermes_heal_prompt.md"
        with open(heal_path, "w") as f:
            f.write(prompt)
        print(f"  → heal prompt: {heal_path}", file=sys.stderr)
        print(f"  run: hermes --prompt {heal_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
