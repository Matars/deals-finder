#!/usr/bin/env python3
"""
Post-process a deals JSON file with price enrichment.

Usage:
  python3 enrich_json.py docs/latest.json              # enrich in place
  python3 enrich_json.py docs/latest.json -o out.json  # write to separate file

Can be called from cron job after scraping, or manually.
"""

import json
import sys
import os

# Add scraper dir to path so enrichment imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enrichment import enrich_all


def enrich_file(path: str, output: str | None = None):
    with open(path) as f:
        data = json.load(f)

    items = data.get("items", [])
    if not items:
        print(f"⚠ no items in {path}", file=sys.stderr)
        return

    before = sum(1 for i in items if i.get("original_price"))
    enrich_all(items)
    after = sum(1 for i in items if i.get("original_price"))

    out_path = output or path
    with open(out_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✓ enriched {after - before} new items ({after}/{len(items)} total) → {out_path}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: enrich_json.py <input.json> [-o output.json]", file=sys.stderr)
        sys.exit(1)

    inp = sys.argv[1]
    out = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "-o" else None
    enrich_file(inp, out)
