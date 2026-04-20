"""
Enrichment module — domain-agnostic enrichment pipeline.

Architecture:
  Enricher (ABC)        → domain-specific logic (extract model, look up prices)
  enrich_all(items)     → routes each item to the right enricher by category

To add a new domain (e.g. cars):
  1. Create cars_enricher.py with a class extending Enricher
  2. Register it: @Enricher.register("car", "vehicle")
  3. Done — pipeline auto-routes items with matching categories.
"""

from __future__ import annotations
import re
from abc import ABC, abstractmethod
from typing import Optional


# ── Registry ─────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, "Enricher"] = {}


class Enricher(ABC):
    """
    Base class for domain-specific enrichers.

    Subclass this and implement:
      - domains: list of category strings this enricher handles
      - extract_model(title) -> (model_name, confidence)
      - lookup_price(model_name, category) -> (original_price, is_estimated)
    """

    # Which categories this enricher handles (e.g. ["gpu", "keyboard", "ram"])
    domains: list[str] = []

    @abstractmethod
    def extract_model(self, title: str, category: str) -> Optional[str]:
        """Extract a normalized product model from the listing title. Return None if unknown."""
        ...

    @abstractmethod
    def lookup_price(self, model: Optional[str], category: str, title: str) -> tuple[Optional[int], bool]:
        """
        Look up the estimated original/retail price.
        Returns (price_in_sek, is_estimated).
        Return (None, False) if no price can be determined.
        """
        ...

    def enrich(self, item: dict) -> dict:
        """
        Full enrichment pass on a single item dict (mutates in place).
        Adds: original_price, original_price_is_estimated, discount_percent, product_model.
        """
        title = item.get("title", "")
        category = item.get("category", "")

        # Extract model
        model = self.extract_model(title, category)
        item["product_model"] = model

        # Look up price
        original_price, is_estimated = self.lookup_price(model, category, title)
        item["original_price"] = original_price
        item["original_price_is_estimated"] = is_estimated

        # Calculate discount — only when price is below original (a real deal).
        # Skip for bundles/PCs where listing price > component MSRP.
        price = item.get("price")
        if original_price and original_price > 0 and price and price < original_price:
            discount = round((1 - price / original_price) * 100)
            item["discount_percent"] = max(0, min(100, discount))
        else:
            item["discount_percent"] = None

        return item

    # ── Registry decorator ───────────────────────────────────────────────

    @classmethod
    def for_domains(cls, *domains: str):
        """Decorator to register an enricher for one or more category domains."""
        def decorator(enricher_cls):
            instance = enricher_cls()
            for domain in domains:
                _REGISTRY[domain.lower()] = instance
            return enricher_cls
        return decorator


def get_enricher(category: str) -> Optional[Enricher]:
    """Find the right enricher for a category. Supports prefix matching (gpu → gpu_enricher)."""
    cat = category.lower().strip()
    # Exact match first
    if cat in _REGISTRY:
        return _REGISTRY[cat]
    # Prefix match: "gpu_old" matches "gpu"
    for domain, enricher in _REGISTRY.items():
        if cat.startswith(domain) or domain.startswith(cat):
            return enricher
    return None


def enrich_all(items: list[dict]) -> list[dict]:
    """
    Enrich a list of scraped items. Routes each to its domain enricher.
    Items without a matching enricher get null enrichment fields.
    """
    for item in items:
        category = item.get("category", "")
        enricher = get_enricher(category)

        if enricher:
            enricher.enrich(item)
        else:
            # No enricher — fill schema-required nulls
            item.setdefault("original_price", None)
            item.setdefault("original_price_is_estimated", False)
            item.setdefault("discount_percent", None)
            item.setdefault("product_model", None)

    return items
