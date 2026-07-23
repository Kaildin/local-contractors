import logging
import csv
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from .selenium_scraper import scrape_with_selenium
from .website_checker import get_website_status, website_is_real
from .driver_utils import cleanup_chrome_tmp

logger = logging.getLogger(__name__)

CSV_FIELDNAMES = [
    "city", "state", "keyword", "nome", "indirizzo", "telefono",
    "sito_web", "ha_sito_web", "website_status_code", "website_check_reason",
    "num_recensioni", "maps_url",
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
                city = (row.get("city") or row.get("comune") or "").strip().lower()
                if nome:
                    seen.add((nome, city))
        logger.info(f"[Resume] CSV esistente: {len(seen)} lead gia' presenti, verranno saltati.")
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


def build_search_urls(
    cities: List[str],
    keywords: List[str],
    lang: str = "en",
    state: str = "",
) -> List[Dict[str, str]]:
    search_urls = []
    for city in cities:
        for keyword in keywords:
            if state:
                query = f"{keyword} {city} {state}".replace(" ", "+")
            else:
                query = f"{keyword} {city}".replace(" ", "+")
            search_urls.append({
                "comune": city,
                "keyword": keyword,
                "url": f"https://www.google.com/maps/search/{query}?hl={lang}&gl={'US' if lang == 'en' else 'IT'}",
            })
    return search_urls


def search_contractors(
    comune: str,
    keywords: List[str],
    debug_screenshot: bool = False,
    min_reviews: int = 1,
    max_reviews: int = 15,
    check_website_alive: bool = True,
    headless: bool = True,
    scroll_times: int = 10,
    max_results: int = 20,
    output_csv: Optional[str] = None,
    lang: str = "en",
    state: str = "",
) -> List[Dict[str, Any]]:
    already_seen: set = set()
    if output_csv:
        already_seen = _load_already_scraped(output_csv)

    search_urls = build_search_urls([comune], keywords, lang=lang, state=state)

    results_raw, driver = scrape_with_selenium(
        search_urls,
        driver=None,
        max_results=max_results,
        scroll_times=scroll_times,
        headless=headless,
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
        city_r = (r.get("comune") or "").strip()

        key = (nome.lower(), city_r.lower())
        if key in already_seen:
            logger.info(f"[Resume] Gia' presente, saltato: {nome}")
            continue

        n = r.get("num_recensioni") or 0
        try:
            n = int(n)
        except Exception:
            n = 0
        if n and not (min_reviews <= n <= max_reviews):
            logger.info(f"[Filter] Scartato '{nome}' - recensioni fuori range: {n}")
            continue

        website = (r.get("sito_web") or "").strip()

        if website and not website_is_real(website, check_alive=False):
            status = {
                "ok": False,
                "status_code": None,
                "final_url": website,
                "reason": "social_or_builder",
            }
        else:
            status = get_website_status(website) if (website and check_website_alive) else {
                "ok": bool(website),
                "status_code": None,
                "final_url": website,
                "reason": "not_checked" if website else "empty_url",
            }

        r["ha_sito_web"] = status["ok"]
        r["website_status_code"] = status["status_code"]
        r["website_check_reason"] = status["reason"]

        r["city"] = city_r
        r["state"] = state or ""

        if not r.get("maps_url"):
            suffix = f"+{state}" if state else ""
            r["maps_url"] = (
                f"https://www.google.com/maps/search/"
                f"{nome.replace(' ', '+')}+{city_r.replace(' ', '+')}{suffix}"
                f"?hl={lang}"
            )

        filtered.append(r)
        already_seen.add(key)

        if output_csv:
            _append_lead_to_csv(output_csv, r)
            logger.info(f"[Salvataggio] Lead salvato: {nome} (ha_sito_web={status['ok']}, reason={status['reason']})")

    return filtered
