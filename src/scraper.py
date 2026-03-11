import logging
from typing import List, Dict, Any

from .selenium_scraper import scrape_with_selenium
from .website_checker import website_is_real
from .driver_utils import cleanup_chrome_tmp

logger = logging.getLogger(__name__)


def build_search_urls(comuni: List[str], keywords: List[str]) -> List[Dict[str, str]]:
    """Costruisce la lista di URL di ricerca Google Maps per ogni comune x keyword."""
    search_urls = []
    for comune in comuni:
        for keyword in keywords:
            query = f"{keyword} {comune}".replace(" ", "+")
            search_urls.append({
                "comune": comune,
                "keyword": keyword,
                "url": f"https://www.google.com/maps/search/{query}?hl=it",
            })
    return search_urls


def search_contractors(
    comune: str,
    keywords: List[str],
    min_reviews: int = 1,
    max_reviews: int = 15,
    check_website_alive: bool = True,
    headless: bool = True,
    scroll_times: int = 5,
) -> List[Dict[str, Any]]:
    """
    Wrapper principale: costruisce gli URL, lancia scrape_with_selenium,
    poi applica il filtro sito web reale e recensioni.
    """
    search_urls = build_search_urls([comune], keywords)

    results_raw, driver = scrape_with_selenium(search_urls, driver=None)

    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    cleanup_chrome_tmp()

    # Filtro recensioni e sito web
    filtered = []
    for r in results_raw:
        n = r.get("num_recensioni") or 0
        try:
            n = int(n)
        except Exception:
            n = 0

        # num_recensioni e' vuoto nello scraper originale (Maps non lo espone facilmente)
        # il filtro lo applichiamo solo se il valore e' disponibile
        if n and not (min_reviews <= n <= max_reviews):
            continue

        website = r.get("sito_web", "") or ""
        if website_is_real(website, check_alive=check_website_alive):
            logger.info(f"[Filter] Scartato '{r.get('nome','')}' - sito reale: {website}")
            continue

        # rinomina sito_web -> sito_google per compatibilita' con app.py
        r["sito_google"] = website or "(nessuno)"
        r["google_maps"] = f"https://www.google.com/maps/search/{r.get('nome','').replace(' ','+')}+{comune}?hl=it"
        filtered.append(r)

    return filtered
