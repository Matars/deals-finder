"""
Base scraper interface. All vendor scrapers must implement this.

Hermes generates vendor-specific scrapers that implement this interface.
Each scraper is a Python file in scrapers/ with a `scrape()` function.
"""

from __future__ import annotations
import importlib
import os
import sys
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import importlib.util


@dataclass
class ScrapeResult:
    """Result from a single scrape operation."""
    items: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    vendor: str = ""
    query: str = ""

    @property
    def success(self) -> bool:
        return len(self.items) > 0 or len(self.errors) == 0

    @property
    def failed(self) -> bool:
        return len(self.errors) > 0 and len(self.items) == 0


class ScraperInterface(ABC):
    """
    Abstract base for vendor scrapers.

    Generated scrapers must implement:
      - scrape(query, category) -> ScrapeResult
      - name property

    Items must have: title, url, price (int or None), category, source
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Vendor name (e.g. 'blocket', 'tradera')"""
        ...

    @abstractmethod
    def scrape(self, query: str, category: str) -> ScrapeResult:
        """
        Scrape listings for a search query.

        Returns:
            ScrapeResult with items list. Each item dict must have:
              - title: str
              - url: str (direct link to listing)
              - price: int or None (in vendor's currency)
              - category: str (passed through)
              - source: str (vendor name)
        """
        ...


def load_scraper(vendor_name: str, scrapers_dir: str = "scrapers") -> Optional[ScraperInterface]:
    """
    Dynamically load a scraper module by vendor name.

    Looks for scrapers/<vendor_name>.py with a scrape(query, category) function.
    Returns None if scraper file doesn't exist.
    """
    module_path = os.path.join(scrapers_dir, f"{vendor_name}.py")
    if not os.path.exists(module_path):
        return None

    try:
        spec = importlib.util.spec_from_file_location(vendor_name, module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, 'scrape') and callable(module.scrape):
            # Wrap in adapter to match ScraperInterface
            class FunctionScraper(ScraperInterface):
                name = vendor_name
                def scrape(self, query, category):
                    return module.scrape(query, category)

            return FunctionScraper()
    except Exception as e:
        print(f"  ✗ failed to load scraper {vendor_name}: {e}", file=sys.stderr)
        return None

    return None


def load_all_scrapers(config: dict, scrapers_dir: str = "scrapers") -> dict[str, ScraperInterface]:
    """Load all enabled vendor scrapers from config."""
    scrapers = {}
    for vendor in config.get("vendors", []):
        if not vendor.get("enabled", True):
            continue
        name = vendor["name"]
        scraper = load_scraper(name, scrapers_dir)
        if scraper:
            scrapers[name] = scraper
        else:
            print(f"  ⚠ no scraper found for {name}", file=sys.stderr)
    return scrapers
