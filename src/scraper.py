import logging
import csv
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from .selenium_scraper import scrape_with_selenium
from .website_checker import website_is_real
from .driver_utils import cleanup_chrome_tmp

logger = logging.getLogger(__name__)

CSV_FIELDNAMES = [
    "comune", "keyword", "nome", "indirizzo", "telefono",
    "sito_web", "ha_sito_web", "num_recensioni", "maps_url",
]


def _load_already_scraped(output_csv: str) -> set:
    seen = set()
    path = Path(output_csv)
    if not path.exists():
        return seen
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                nome = (row.get("nome") or "").strip().lower()
                comune = (row.get("comune") or "").strip().lower()
                if nome:
                    seen.add((nome, comune))
        logger.info(f"[Resume] CSV esistente: {len(seen)} lead già presenti, verranno saltati.")
    except Exception as e:
        logger.warning(f"[Resume] Errore lettura CSV esistente: {e}")
    return seen


def _append_lead_to_csv(output_csv: str, row: Dict[str, Any]):
    path = Path(output_csv)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists() and path.stat().st_size > 0
    try:
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        logger.error(f"[Salvataggio incrementale] Errore: {e}")


def build_search_urls(comuni: List[str], keywords: List[str]) -> List[Dict[str, str]]:
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
    scroll_times: int = 10,
    max_results: int = 20,
    output_csv: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Wrapper principale: costruisce gli URL, lancia scrape_with_selenium,
    applica solo il filtro recensioni.
    Salva ogni lead (con o senza sito) in modo incrementale.
    La colonna ha_sito_web (True/False) permette di filtrare in post.
    """
    already_seen: set = set()
    if output_csv:
        already_seen = _load_already_scraped(output_csv)

    search_urls = build_search_urls([comune], keywords)

    results_raw, driver = scrape_with_selenium(
        search_urls,
        driver=None,
        max_results=max_results,
        scroll_times=scroll_times,
    )

    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    cleanup_chrome_tmp()

    filtered = []
    for r in results_raw:
        nome = (r.get("nome") or "").strip()
        comune_r = (r.get("comune") or "").strip()

        # --- Deduplicazione: salta se già nel CSV ---
        key = (nome.lower(), comune_r.lower())
        if key in already_seen:
            logger.info(f"[Resume] Già presente, saltato: {nome}")
            continue

        # --- Filtro recensioni (unico filtro rimasto) ---
        n = r.get("num_recensioni") or 0
        try:
            n = int(n)
        except Exception:
            n = 0
        if n and not (min_reviews <= n <= max_reviews):
            logger.info(f"[Filter] Scartato '{nome}' - recensioni fuori range: {n}")
            continue

        # --- Classifica sito web: ha_sito_web per filtrare in post ---
        website = (r.get("sito_web") or "").strip()
        ha_sito = website_is_real(website, check_alive=check_website_alive) if website else False
        r["ha_sito_web"] = ha_sito

        if not r.get("maps_url"):
            r["maps_url"] = f"https://www.google.com/maps/search/{nome.replace(' ', '+')}+{comune_r}?hl=it"

        filtered.append(r)
        already_seen.add(key)

        if output_csv:
            _append_lead_to_csv(output_csv, r)
            logger.info(f"[Salvataggio] Lead salvato: {nome} (ha_sito_web={ha_sito})")

    return filtered
