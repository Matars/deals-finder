"""
Price providers — pluggable price lookup backends.

Chain providers to try multiple sources:
  chain = PriceChain([PrisjaktProvider(), EbayProvider(), FallbackProvider()])
  price, is_estimated = chain.get_price("RTX 3060 Ti", "gpu")

To add a new provider: subclass PriceProvider, implement get_price().
"""

from __future__ import annotations
import re
import sys
import time
from abc import ABC, abstractmethod
from typing import Optional


class PriceProvider(ABC):
    """Base class for a price lookup backend."""

    name: str = "base"

    @abstractmethod
    def get_price(self, model: Optional[str], category: str, title: str = "") -> tuple[Optional[int], bool]:
        """
        Look up the retail/original price in SEK.
        Returns (price, is_estimated).
        Return (None, False) if not found.
        """
        ...


class PriceChain:
    """Try multiple providers in order, return the first successful result."""

    def __init__(self, providers: list[PriceProvider]):
        self.providers = providers

    def get_price(self, model: Optional[str], category: str, title: str = "") -> tuple[Optional[int], bool]:
        for provider in self.providers:
            try:
                price, est = provider.get_price(model, category, title)
                if price is not None and price > 0:
                    return price, est
            except Exception as e:
                print(f"  ⚠ {provider.name}: {e}", file=sys.stderr)
                continue
        return None, False


# ── HTTP helper (lazy import to avoid circular deps) ─────────────────────────

def _http_get(url: str, timeout: int = 15) -> Optional[str]:
    """Lazy-load browser-harness http_get for price lookups."""
    try:
        sys.path.insert(0, "/tmp/browser-harness")
        from helpers import http_get
        return http_get(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
        }, timeout=timeout)
    except Exception:
        return None


# ── Prisjakt provider (Swedish retail prices) ────────────────────────────────

class PrisjaktProvider(PriceProvider):
    """
    Scrapes Prisjakt.nu for Swedish retail prices.
    Good for: electronics, tech, appliances — anything with a model number.
    """
    name = "prisjakt"

    def get_price(self, model: Optional[str], category: str, title: str = "") -> tuple[Optional[int], bool]:
        if not model:
            return None, False

        # Search Prisjakt
        query = re.sub(r'\s+', '+', model.strip())
        url = f"https://www.prisjakt.nu/search?search={query}"
        html = _http_get(url, timeout=12)
        if not html or len(html) < 3000:
            return None, False

        # Extract lowest price from search results
        # Prisjakt shows prices like "1 234 kr" in search results
        price_matches = re.findall(r'(\d[\d\s]*)\s*kr', html)
        if price_matches:
            # Take the first (usually lowest/recommended) price
            price_str = price_matches[0].replace('\xa0', '').replace(' ', '')
            try:
                price = int(price_str)
                if 10 <= price <= 500000:  # sanity check
                    return price, True
            except ValueError:
                pass

        return None, False


# ── eBay provider (market prices) ────────────────────────────────────────────

class EbayProvider(PriceProvider):
    """
    Scrapes eBay for completed/sold listing prices.
    Good for: anything with a resale market — electronics, collectibles, cars.
    """
    name = "ebay"

    def get_price(self, model: Optional[str], category: str, title: str = "") -> tuple[Optional[int], bool]:
        if not model:
            return None, False

        query = re.sub(r'\s+', '%20', model.strip())
        url = f"https://www.ebay.com/sch/i.html?_nkw={query}&LH_Sold=1&LH_Complete=1"
        html = _http_get(url, timeout=12)
        if not html or len(html) < 3000:
            return None, False

        # eBay shows "SEK X XXX" or "$X.XX" — we need to convert or find SEK listings
        # For Swedish eBay (ebay.com with sv locale), prices show in SEK
        sek_matches = re.findall(r'SEK\s*([\d\s]+)', html)
        if sek_matches:
            prices = []
            for m in sek_matches:
                try:
                    p = int(m.replace(' ', '').replace('\xa0', ''))
                    if 10 <= p <= 500000:
                        prices.append(p)
                except ValueError:
                    pass
            if prices:
                # Median sold price
                prices.sort()
                median = prices[len(prices) // 2]
                return median, True

        # Fallback: USD prices (multiply by ~11 for rough SEK)
        usd_matches = re.findall(r'\$([\d,]+(?:\.\d{2})?)', html)
        if usd_matches:
            prices = []
            for m in usd_matches:
                try:
                    usd = float(m.replace(',', ''))
                    sek = int(usd * 11)  # rough USD→SEK
                    if 100 <= sek <= 500000:
                        prices.append(sek)
                except ValueError:
                    pass
            if prices:
                prices.sort()
                median = prices[len(prices) // 2]
                return median, True

        return None, False


# ── Fallback provider (hardcoded defaults per category) ──────────────────────

# Category → rough median retail price in SEK
CATEGORY_DEFAULTS: dict[str, int] = {
    "gpu": 3500,
    "keyboard": 800,
    "ram": 600,
    "psu": 900,
    "pc": 8000,
    "retro": 1500,
    "gaming": 500,
    "anime": 300,
    "poster": 150,
}


class FallbackProvider(PriceProvider):
    """
    Category-level defaults when no model-specific price is found.
    Only used if all other providers fail.
    """
    name = "fallback"

    def get_price(self, model: Optional[str], category: str, title: str = "") -> tuple[Optional[int], bool]:
        default = CATEGORY_DEFAULTS.get(category.lower())
        if default:
            return default, True  # estimated = True since it's a rough default
        return None, False


# ── Cache provider (wraps another provider with disk cache) ──────────────────

class CachedProvider(PriceProvider):
    """
    Wraps a price provider with a simple JSON file cache.
    Avoids re-fetching prices for the same model within TTL.
    """
    name = "cached"

    def __init__(self, inner: PriceProvider, cache_path: str = "enrichment/.price_cache.json",
                 ttl_hours: int = 168):  # 1 week default
        self.inner = inner
        self.cache_path = cache_path
        self.ttl_seconds = ttl_hours * 3600
        self._cache: Optional[dict] = None

    def _load_cache(self) -> dict:
        if self._cache is None:
            try:
                import json
                with open(self.cache_path) as f:
                    self._cache = json.load(f)
            except (FileNotFoundError, Exception):
                self._cache = {}
        return self._cache

    def _save_cache(self):
        import json
        import os
        os.makedirs(os.path.dirname(self.cache_path) or '.', exist_ok=True)
        with open(self.cache_path, 'w') as f:
            json.dump(self._cache, f, indent=2)

    def get_price(self, model: Optional[str], category: str, title: str = "") -> tuple[Optional[int], bool]:
        if not model:
            return None, False

        cache = self._load_cache()
        key = f"{category}:{model}".lower()

        if key in cache:
            entry = cache[key]
            age = time.time() - entry.get("ts", 0)
            if age < self.ttl_seconds:
                return entry["price"], entry["est"]

        # Cache miss — fetch from inner
        price, est = self.inner.get_price(model, category, title)
        if price is not None:
            cache[key] = {"price": price, "est": est, "ts": time.time()}
            self._save_cache()

        return price, est
