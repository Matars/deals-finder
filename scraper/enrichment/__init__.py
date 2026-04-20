"""
deals-finder enrichment module.

Usage:
  from enrichment import enrich_all
  enriched_items = enrich_all(scraped_items)

To add a new domain enricher:
  1. Create domain_enricher.py with a class extending Enricher
  2. Decorate with @Enricher.for_domains("category1", "category2")
  3. Import it here so it registers at startup
"""

from .enricher import Enricher, enrich_all, get_enricher

# Import domain enrichers so they self-register via decorators
from . import tech_enricher  # noqa: F401

__all__ = ["enrich_all", "Enricher", "get_enricher"]
