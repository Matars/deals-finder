# deals-finder

Automated second-hand tech deals for Sweden. Scrapes Blocket, Tradera, and more — publishes a filterable deals page to GitHub Pages.

**Live demo:** https://matars.github.io/deals-finder/

## Quick Start (2 minutes)

### 1. Fork this repo

Click **Fork** → pick your GitHub account.

### 2. Edit config.yaml

```yaml
categories:
  gpu:
    icon: "🎮"
    label: "GPUs"
    queries:
      - gpu
      - grafikkort

  keyboard:
    icon: "⌨️"
    label: "Keyboards"
    queries:
      - tangentbord
```

Add/remove categories and search terms. Use Swedish terms for best results.

### 3. Enable GitHub Pages

Settings → Pages → Source: **Deploy from a branch** → Branch: **main** → Folder: **/docs**

### 4. Run it

Go to **Actions** tab → **Daily Deals Scrape** → **Run workflow**

That's it. Your deals page is live at `https://<your-username>.github.io/deals-finder/`

## How It Works

```
GitHub Actions (daily 09:00)
  → python3 scraper/scrape_all.py
    → http_get per search term (parallel, ~2s)
    → deduplicate by URL
    → write docs/latest.json + archive
  → git commit + push
  → GitHub Pages serves the static site
```

No server, no database, no API keys required. Just GitHub.

## What's Scraped

| Source | Method | Status |
|--------|--------|--------|
| Blocket | http_get (static HTML) | ✅ Working |
| Tradera | http_get (HTML patterns) | ⚠️ Partial |
| Vinted | Needs browser | 🔜 |
| eBay | http_get (rate-limited) | 🔜 |

## Customization

### config.yaml

```yaml
# Enable/disable sources
sources:
  - name: blocket
    enabled: true
  - name: tradera
    enabled: true

# Add your own categories
categories:
  gpu:
    icon: "🎮"
    label: "GPUs"
    queries:
      - gpu
      - grafikkort
      - rtx 4070  # add specific models

# Discord notifications (optional)
discord:
  enabled: true
  webhook_url: "https://discord.com/api/webhooks/..."
```

### Add a new source

1. Add a `scrape_<source>()` function in `scraper/scrape_all.py`
2. Register it in the `SCRAPERS` dict
3. Add it to `sources` in `config.yaml`

### Run locally

```bash
pip install pyyaml
python3 scraper/scrape_all.py --config config.yaml --dry-run | head -50
```

## Architecture

```
your-repo/
├── config.yaml           ← your categories, sources, search terms
├── scraper/
│   └── scrape_all.py     ← the scraper (stdlib + pyyaml)
├── docs/                 ← GitHub Pages output
│   ├── index.html        ← kanban board UI
│   ├── latest.json       ← today's deals
│   └── archive/          ← daily snapshots
└── .github/workflows/
    └── scrape.yml         ← daily cron via GitHub Actions
```

## Local Scraper (no GitHub needed)

```bash
# Install
pip install pyyaml

# Run scraper
python3 scraper/scrape_all.py

# Check output
cat docs/latest.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{len(d[\"items\"])} items from {d[\"sources\"]}')"

# Open the page
open docs/index.html  # macOS
xdg-open docs/index.html  # Linux
```

## Advanced: Browser Automation

For JS-rendered sites (Tradera, Vinted), install [browser-harness](https://github.com/browser-use/browser-harness):

```bash
git clone https://github.com/browser-use/browser-harness
cd browser-harness && uv sync

# Use http_get from browser-harness for faster scraping
uv run python3 scraper/scrape_all.py
```

Or use [Browser Use Cloud](https://cloud.browser-use.com) for managed stealth browsers with CAPTCHA solving.

## License

MIT
