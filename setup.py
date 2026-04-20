"""
Interactive setup for deals-finder.

Usage:
  python setup.py              # interactive setup
  python setup.py --generate   # generate scrapers via Hermes (requires hermes agent)
  python setup.py --heal       # check for broken scrapers and auto-repair
"""

import argparse
import json
import os
import subprocess
import sys
import yaml
from pathlib import Path


VENDOR_TEMPLATES = {
    "blocket": {
        "url": "https://www.blocket.se/recommerce/forsale/search?category=0.93&q={query}",
        "country": "SE",
    },
    "tradera": {
        "url": "https://www.tradera.com/search?q={query}",
        "country": "SE",
    },
    "vinted": {
        "url": "https://www.vinted.se/catalog?search_text={query}",
        "country": "SE",
    },
    "ebay": {
        "url": "https://www.ebay.com/sch/i.html?_nkw={query}",
        "country": "US",
    },
    "sellpy": {
        "url": "https://www.sellpy.se/search?q={query}",
        "country": "SE",
    },
    "finn": {
        "url": "https://www.finn.no/search?q={query}",
        "country": "NO",
    },
    "dba": {
        "url": "https://www.dba.dk/soeg/?soeg={query}",
        "country": "DE",
    },
}

DEFAULT_CATEGORIES = [
    {"name": "gpu", "icon": "🎮", "queries": ["gpu", "grafikkort"]},
    {"name": "keyboard", "icon": "⌨️", "queries": ["tangentbord"]},
    {"name": "ram", "icon": "💾", "queries": ["ram ddr5", "ram ddr4"]},
    {"name": "psu", "icon": "🔌", "queries": ["nätaggregat"]},
    {"name": "retro", "icon": "🕹️", "queries": ["nintendo 64", "retro konsol"]},
]


def check_deps():
    """Check required dependencies."""
    missing = []
    try:
        import yaml
    except ImportError:
        missing.append("pyyaml (pip install pyyaml)")

    # Check python version
    if sys.version_info < (3, 11):
        print(f"⚠ python {sys.version_info.major}.{sys.version_info.minor} detected, 3.11+ recommended")

    # Check git
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
    except FileNotFoundError:
        missing.append("git")

    if missing:
        print("missing dependencies:")
        for m in missing:
            print(f"  - {m}")
        return False
    return True


def interactive_setup():
    """Run the interactive setup wizard."""
    print("=" * 50)
    print("  deals-finder setup")
    print("=" * 50)
    print()

    config = {}

    # 1. User preferences
    print("── user preferences ──")
    lang = input("  language [sv]: ").strip() or "sv"
    country = input("  country code [SE]: ").strip() or "SE"
    currency = input("  currency [SEK]: ").strip() or "SEK"
    config["user"] = {"language": lang, "country": country, "currency": currency}
    print()

    # 2. Vendors
    print("── vendors ──")
    print(f"  available: {', '.join(VENDOR_TEMPLATES.keys())}")
    vendor_input = input("  which vendors? (comma-separated, or 'all') [blocket,tradera,vinted,ebay]: ").strip()
    if not vendor_input or vendor_input == "all":
        vendor_input = "blocket,tradera,vinted,ebay"

    vendors = []
    for v in vendor_input.split(","):
        v = v.strip().lower()
        if v in VENDOR_TEMPLATES:
            vendors.append({
                "name": v,
                "url": VENDOR_TEMPLATES[v]["url"],
                "enabled": True,
            })
        else:
            print(f"  ⚠ unknown vendor '{v}', adding as custom")
            url = input(f"    search URL for {v} (use {{query}} as placeholder): ").strip()
            if url:
                vendors.append({"name": v, "url": url, "enabled": True})

    # Custom vendors
    print()
    add_custom = input("  add a custom vendor? (y/n) [n]: ").strip().lower()
    while add_custom == "y":
        name = input("    vendor name: ").strip().lower()
        url = input("    search URL (use {query} as placeholder): ").strip()
        if name and url:
            vendors.append({"name": name, "url": url, "enabled": True})
            print(f"    ✓ added {name}")
        add_custom = input("  add another? (y/n) [n]: ").strip().lower()

    config["vendors"] = vendors
    print()

    # 3. Categories
    print("── categories ──")
    print(f"  defaults: {', '.join(c['name'] for c in DEFAULT_CATEGORIES)}")
    use_defaults = input("  use default categories? (y/n) [y]: ").strip().lower()
    if use_defaults != "n":
        config["categories"] = DEFAULT_CATEGORIES
    else:
        config["categories"] = []
        print("  enter categories (empty name to finish):")
        while True:
            name = input("    name: ").strip().lower()
            if not name:
                break
            queries = input("    search terms (comma-separated): ").strip()
            icon = input("    icon [📦]: ").strip() or "📦"
            config["categories"].append({
                "name": name,
                "icon": icon,
                "queries": [q.strip() for q in queries.split(",") if q.strip()],
            })

    # 4. Publishing
    print()
    print("── publishing ──")
    publish_method = input("  method (github_pages/local) [github_pages]: ").strip() or "github_pages"
    config["publish"] = {"method": publish_method}
    if publish_method == "github_pages":
        repo = input("  github repo (owner/repo) []: ").strip()
        config["publish"]["repo"] = repo
        config["publish"]["branch"] = "main"

    # 5. Self-healing
    config["self_heal"] = {"enabled": True, "max_retries": 2}
    config["notify"] = {"discord_channel": ""}

    # Write config
    with open("config.yaml", "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print()
    print(f"✓ config written to config.yaml")
    print()

    # Check for scrapers
    missing_scrapers = []
    for vendor in vendors:
        scraper_path = f"scrapers/{vendor['name']}.py"
        if not os.path.exists(scraper_path):
            missing_scrapers.append(vendor["name"])

    if missing_scrapers:
        print(f"── missing scrapers: {', '.join(missing_scrapers)} ──")
        generate = input("  generate scrapers with hermes? (y/n) [y]: ").strip().lower()
        if generate != "n":
            generate_scrapers(config, missing_scrapers)

    print()
    print("setup complete! next steps:")
    print("  python scrape.py --check    # verify scrapers load")
    print("  python scrape.py            # run a test scrape")
    print("  python scrape.py --heal     # auto-repair broken scrapers")


def generate_scrapers(config: dict, vendor_names: list[str]):
    """
    Generate scraper modules using Hermes agent.
    This is where the magic happens — hermes analyzes each vendor's site
    and writes the appropriate scraper code.
    """
    print(f"\n  launching hermes to generate {len(vendor_names)} scrapers...")

    # Build the prompt for hermes
    vendors_to_generate = []
    for v in config.get("vendors", []):
        if v["name"] in vendor_names:
            vendors_to_generate.append(v)

    prompt = _build_scraper_generation_prompt(vendors_to_generate, config)

    # Write prompt to temp file for hermes to consume
    with open(".hermes_scraper_prompt.md", "w") as f:
        f.write(prompt)

    print(f"  → prompt written to .hermes_scraper_prompt.md")
    print(f"  run: hermes --prompt .hermes_scraper_prompt.md")
    print(f"  or paste it into your hermes session")


def _build_scraper_generation_prompt(vendors: list[dict], config: dict) -> str:
    """Build the hermes prompt for scraper generation."""
    lang = config.get("user", {}).get("language", "sv")
    country = config.get("user", {}).get("country", "SE")

    lines = [
        "# Scraper Generation Task",
        "",
        "Generate Python scraper modules for the following vendor websites.",
        "Each scraper must be a file in `scrapers/<vendor_name>.py` with a `scrape(query, category)` function.",
        "",
        "## Interface",
        "",
        "Each scraper file must export:",
        "```python",
        "def scrape(query: str, category: str) -> ScrapeResult:",
        "    '''",
        "    Scrape listings for a search query.",
        "    Return ScrapeResult with items list. Each item dict must have:",
        "      - title: str",
        "      - url: str (direct link to listing)",
        "      - price: int or None",
        "      - category: str (pass through from input)",
        "      - source: str (vendor name)",
        "    '''",
        "```",
        "",
        "Import ScrapeResult from `scrapers.base`:",
        "```python",
        "import sys, os",
        "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))",
        "from scrapers.base import ScrapeResult",
        "```",
        "",
        "## Instructions",
        "",
        f"1. Use browser-harness to navigate to each vendor's search page",
        f"2. Analyze the DOM to find the right selectors for: title, URL, price",
        f"3. Write a scraper module that uses browser-harness `http_get` for fast HTTP scraping",
        f"4. Handle errors gracefully — return empty items list on failure, don't crash",
        f"5. Language: {lang}, Country: {country}",
        "",
        "If a site renders content client-side (JS), note it in the scraper docstring.",
        "For JS-heavy sites, fall back to regex extraction from HTML.",
        "",
        "## Vendors to generate",
        "",
    ]

    for v in vendors:
        lines.append(f"### {v['name']}")
        lines.append(f"- URL template: `{v['url']}`")
        lines.append(f"- Test with query: `gpu`")
        lines.append("")

    lines.extend([
        "## After generating",
        "",
        "Run `python scrape.py --check` to verify all scrapers load.",
        "Run `python scrape.py` to test a full scrape.",
        "",
        "## Self-healing note",
        "",
        "When a scraper breaks (DOM change), the system will re-invoke this process.",
        "The error details will be in `docs/.scrape_errors.json`.",
    ])

    return "\n".join(lines)


def heal_scrapers(config: dict):
    """
    Check for broken scrapers and generate repair prompts for hermes.
    """
    errors_path = "docs/.scrape_errors.json"
    if not os.path.exists(errors_path):
        print("  no errors found — all scrapers healthy ✓")
        return

    with open(errors_path) as f:
        errors = json.load(f)

    if not errors:
        print("  no errors found — all scrapers healthy ✓")
        return

    print(f"  found {len(errors)} errors:")

    # Group by vendor
    by_vendor = {}
    for err in errors:
        vendor = err["vendor"]
        if vendor not in by_vendor:
            by_vendor[vendor] = []
        by_vendor[vendor].append(err)

    for vendor, errs in by_vendor.items():
        print(f"\n  ── {vendor} ({len(errs)} failures) ──")
        for err in errs[:3]:
            print(f"    query: {err['query']}")
            print(f"    error: {err['errors'][0][:120]}")

    # Build repair prompt
    prompt = _build_heal_prompt(by_vendor, config)
    with open(".hermes_heal_prompt.md", "w") as f:
        f.write(prompt)

    print(f"\n  → repair prompt written to .hermes_heal_prompt.md")
    print(f"  run: hermes --prompt .hermes_heal_prompt.md")


def _build_heal_prompt(by_vendor: dict, config: dict) -> str:
    lines = [
        "# Scraper Auto-Repair",
        "",
        "The following scrapers have broken (likely due to DOM changes).",
        "Re-analyze each vendor's site and patch the scraper.",
        "",
    ]

    for vendor, errors in by_vendor.items():
        lines.append(f"## {vendor}")
        scraper_path = f"scrapers/{vendor}.py"
        lines.append(f"- Scraper file: `{scraper_path}`")
        lines.append(f"- Errors:")
        for err in errors[:3]:
            lines.append(f"  - query=`{err['query']}`: {err['errors'][0][:200]}")
        lines.append("")

    lines.extend([
        "## Steps",
        "",
        "1. Read the current scraper file",
        "2. Use browser-harness to navigate to the vendor's search page",
        "3. Compare the current DOM selectors with what the scraper expects",
        "4. Patch the scraper with corrected selectors",
        "5. Run `python scrape.py --vendor <name>` to verify the fix",
        "6. If fixed, delete `docs/.scrape_errors.json`",
    ])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="deals-finder setup")
    parser.add_argument("--generate", action="store_true", help="generate scrapers with hermes")
    parser.add_argument("--heal", action="store_true", help="auto-repair broken scrapers")
    args = parser.parse_args()

    if not check_deps():
        sys.exit(1)

    if args.heal:
        config = yaml.safe_load(open("config.yaml"))
        heal_scrapers(config)
    elif args.generate:
        config = yaml.safe_load(open("config.yaml"))
        missing = []
        for v in config.get("vendors", []):
            if not os.path.exists(f"scrapers/{v['name']}.py"):
                missing.append(v["name"])
        if missing:
            generate_scrapers(config, missing)
        else:
            print("  all scrapers present ✓")
    else:
        interactive_setup()


if __name__ == "__main__":
    main()
