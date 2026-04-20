"""
Tech enricher — handles electronics categories: gpu, keyboard, ram, psu, pc, retro, gaming, anime, poster.

Extracts product model from listing titles, then chains price providers:
  Prisjakt (Swedish retail) → eBay (market) → Fallback (category defaults)

To add a new product type: add a handler to extract_model() and optionally
add exact MSRP entries to EXACT_PRICES.
"""

from __future__ import annotations
import re
from typing import Optional

from .enricher import Enricher
from .providers import (
    CachedProvider,
    EbayProvider,
    FallbackProvider,
    PriceChain,
    PrisjaktProvider,
)


# ── Known exact MSRP (model → SEK) ──────────────────────────────────────────
# Beats any API lookup. Expand as you encounter new products.

EXACT_PRICES: dict[str, int] = {
    # NVIDIA GPUs
    "rtx 4090": 22000, "rtx 4080": 16000, "rtx 4070 ti super": 11000,
    "rtx 4070 ti": 10500, "rtx 4070 super": 8500, "rtx 4070": 7500,
    "rtx 4060 ti": 6000, "rtx 4060": 4500,
    "rtx 3090": 18000, "rtx 3080": 10000, "rtx 3070": 7000,
    "rtx 3060 ti": 5500, "rtx 3060": 4500,
    "rtx 2080": 8000, "rtx 2070": 6000, "rtx 2060": 4000,
    "gtx 1080 ti": 6000, "gtx 1080": 5000, "gtx 1070": 3500,
    "gtx 1060": 2500, "gtx 1050 ti": 1800,
    "gtx 980": 2500, "gtx 970": 1800, "gtx 960": 1200,
    # AMD GPUs
    "rx 7900 xtx": 14000, "rx 7900 xt": 11000, "rx 7800 xt": 7500,
    "rx 7600": 4000,
    "rx 6800 xt": 8000, "rx 6700 xt": 5500, "rx 6600 xt": 3500,
    "rx 580": 2000, "rx 570": 1500,
    # Intel GPUs
    "arc b580": 3500, "arc a770": 4500, "arc a750": 3500,
    # Workstation GPUs
    "tesla p100": 5000, "quadro p1000": 3000, "cmp 90hx": 4000,
    # VR headsets
    "meta quest 3s": 4500, "meta quest 3": 6000, "meta quest 2": 2500,
    # Keyboards
    "logitech g413": 800, "logitech g513": 1200, "logitech g915": 2000,
    "razer huntsman": 1500, "razer blackwidow": 1200,
    "corsair k70": 1500, "steelseries apex pro": 2000,
    # RAM (per kit)
    "ddr5 32gb": 1200, "ddr5 16gb": 700, "ddr5 8gb": 400,
    "ddr4 32gb": 800, "ddr4 16gb": 450, "ddr4 8gb": 250,
    # Retro consoles
    "nintendo 64": 1500, "super nintendo": 1200, "nes": 1000,
    "snes": 1200, "game boy": 800, "sega mega drive": 1000,
    "atari 2600": 1500, "atari 7800": 1200,
    "3do": 3000, "intellivision": 1200,
    "xbox 360": 800, "ps1": 800, "ps2": 600,
}

# Category fallback prices when no model match
CATEGORY_DEFAULTS: dict[str, int] = {
    "gpu": 3500, "keyboard": 800, "ram": 600, "psu": 900,
    "pc": 8000, "retro": 1500, "gaming": 500, "anime": 300, "poster": 150,
}


def _clean(title: str) -> str:
    """Lowercase and strip common Swedish noise words for matching."""
    return re.sub(r'\s+', ' ', title.lower().strip())


def _extract_gpu_model(title: str) -> Optional[str]:
    """Extract GPU model like 'RTX 3060 Ti', 'GTX 970', 'RX 580'."""
    t = _clean(title)

    # NVIDIA RTX (most specific first)
    m = re.search(r'rtx\s*(\d{4})\s*(ti\s*super|super|ti)?', t)
    if m:
        variant = (m.group(2) or '').replace(' ', ' ').strip()
        return f"RTX {m.group(1)}{' ' + variant if variant else ''}"

    # NVIDIA GTX (including 3-digit older models like GTX 660, 750)
    m = re.search(r'gtx\s*(\d{3,4})\s*(ti)?', t)
    if m:
        return f"GTX {m.group(1)}{' Ti' if m.group(2) else ''}"

    # AMD RX
    m = re.search(r'rx\s*(\d{4})\s*(xtx|xt)?', t)
    if m:
        variant = (m.group(2) or '').upper()
        return f"RX {m.group(1)}{' ' + variant if variant else ''}"

    # Intel Arc
    m = re.search(r'arc\s*(a\d{3}|b\d{3})', t)
    if m:
        return f"Arc {m.group(1).upper()}"

    # NVIDIA Tesla
    m = re.search(r'tesla\s*(p\d{2,3}|v\d{2,3})', t)
    if m:
        return f"Tesla {m.group(1).upper()}"

    # NVIDIA Quadro
    m = re.search(r'quadro\s*(p\d{3,4}|rtx\s*\d{4})', t)
    if m:
        return f"Quadro {m.group(1).upper()}"

    # NVIDIA CMP
    m = re.search(r'cmp\s*(\d{2,3}hx)', t)
    if m:
        return f"CMP {m.group(1).upper()}"

    return None


def _extract_vr_model(title: str) -> Optional[str]:
    m = re.search(r'meta\s+quest\s*(3s?|2|pro)', _clean(title))
    if m:
        return f"Meta Quest {m.group(1).upper()}"
    return None


def _extract_keyboard_model(title: str) -> Optional[str]:
    t = _clean(title)
    # Swedish stop words that are NOT model names
    stop_words = {'tangentbord', 'keyboard', 'mechanical', 'optical', 'wireless',
                  'med', 'kabel', 'svart', 'vit', 'rgb', 'led', 'belysning',
                  'handledsstöd', 'nordic', 'nordiskt'}
    m = re.search(r'(logitech|razer|corsair|steelseries|hyperx|ducky|filco|apple|anne pro|nzxt|asus|roccat)\s+(\w[\w-]*)', t)
    if m:
        model_part = m.group(2)
        if model_part.lower() not in stop_words and len(model_part) > 2:
            return f"{m.group(1).title()} {model_part.upper()}"
        return f"{m.group(1).title()} keyboard"
    # Brand-only fallback
    m = re.search(r'(apple|logitech|razer|corsair|steelseries|hyperx)', t)
    if m:
        return f"{m.group(1).title()} keyboard"
    return None


def _extract_ram_model(title: str) -> Optional[str]:
    t = _clean(title)
    ddr = re.search(r'ddr(\d)', t)
    cap = re.search(r'(\d{1,3})\s*gb', t)
    if ddr and cap:
        return f"DDR{ddr.group(1)} {cap.group(1)}GB"
    return None


def _extract_psu_model(title: str) -> Optional[str]:
    t = _clean(title)
    watt = re.search(r'(\d{3,4})\s*w', t)
    brand = re.search(r'(corsair|evga|seasonic|be quiet|deepcool|nzxt|asus|msi)', t)
    if watt and brand:
        return f"{brand.group(1).title()} {watt.group(1)}W"
    elif watt:
        return f"{watt.group(1)}W PSU"
    return None


def _extract_pc_model(title: str) -> Optional[str]:
    """For PCs, extract the GPU as the differentiating model."""
    gpu = _extract_gpu_model(title)
    if gpu:
        return gpu
    t = _clean(title)
    cpu = re.search(r'(i[3579]-\w+|ryzen\s*\d\s*\w+)', t)
    if cpu:
        return cpu.group(1).upper()
    return None


def _extract_retro_model(title: str) -> Optional[str]:
    t = _clean(title)
    # Known consoles
    patterns = [
        r'(nintendo\s*64|n64)',
        r'(super\s*nintendo|snes)',
        r'(nintendo\s*entertainment\s*system|\bnes\b)',
        r'(game\s*boy\s*(?:advance|color|micro)?)',
        r'(sega\s*mega\s*drive|sega\s*genesis)',
        r'(atari\s*\d{3,4})',
        r'(3do|intellivision)',
        r'(xbox\s*360|xbox\s*one|xbox\s*original)',
        r'(playstation\s*[1-5]|ps[1-5])',
        r'(psp|ps\s*vita)',
    ]
    for p in patterns:
        m = re.search(p, t)
        if m:
            return m.group(1).title()
    # Device type fallback
    m = re.search(r'(handh[åa]llen|bärbar|portable)\s*(konsol|spelkonsol|console)', t)
    if m:
        return "Handheld console"
    return None


def _extract_model(title: str, category: str) -> Optional[str]:
    """Route to category-specific extractor."""
    extractors = {
        "gpu": _extract_gpu_model,
        "keyboard": _extract_keyboard_model,
        "ram": _extract_ram_model,
        "psu": _extract_psu_model,
        "pc": _extract_pc_model,
        "retro": _extract_retro_model,
    }
    extractor = extractors.get(category)
    if extractor:
        return extractor(title)
    return None


# ── Tech enricher ────────────────────────────────────────────────────────────

@Enricher.for_domains("gpu", "keyboard", "ram", "psu", "pc", "retro", "gaming", "anime", "poster")
class TechEnricher(Enricher):
    """Enricher for electronics/tech categories."""

    def __init__(self):
        self.price_chain = PriceChain([
            CachedProvider(PrisjaktProvider(), cache_path="enrichment/.price_cache.json"),
            EbayProvider(),
            FallbackProvider(),
        ])

    def extract_model(self, title: str, category: str) -> Optional[str]:
        return _extract_model(title, category)

    def lookup_price(self, model: Optional[str], category: str, title: str = "") -> tuple[Optional[int], bool]:
        if not model:
            price = CATEGORY_DEFAULTS.get(category)
            return (price, True) if price else (None, False)

        # Check exact prices (instant, free)
        key = model.lower().strip()
        if key in EXACT_PRICES:
            return EXACT_PRICES[key], True

        # Partial match
        for known, price in EXACT_PRICES.items():
            if known in key or key in known:
                return price, True

        # Only GPU and PC benefit from external providers (Prisjakt/eBay).
        # Other categories match unrelated products → use EXACT_PRICES or defaults.
        if category.lower() not in ('gpu', 'pc'):
            price = CATEGORY_DEFAULTS.get(category)
            return (price, True) if price else (None, False)

        # Fall through to price chain
        return self.price_chain.get_price(model, category, title)
