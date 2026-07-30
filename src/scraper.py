import json
import logging
import csv
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

from .selenium_scraper import scrape_with_selenium
from .website_checker import get_website_status, website_is_real
from .driver_utils import cleanup_chrome_tmp

logger = logging.getLogger(__name__)

CSV_FIELDNAMES = [
    "city", "state", "keyword", "nome", "indirizzo", "telefono",
    "sito_web", "ha_sito_web", "website_status_code", "website_check_reason",
    "num_recensioni", "maps_url",
]

_GEOCODE_CACHE_PATH = "debug/geocode_cache.json"


def _load_geocode_cache() -> dict:
    path = Path(_GEOCODE_CACHE_PATH)
    if path.exists():
        try:
            cache = json.loads(path.read_text(encoding="utf-8"))
            logger.debug(f"[Geocode] Cache caricata: {len(cache)} citt\u00e0 in cache.")
            return cache
        except Exception as e:
            logger.warning(f"[Geocode] Errore lettura cache: {e} \u2014 ricomincio da zero.")
            return {}
    logger.debug("[Geocode] Nessuna cache trovata, verr\u00e0 creata al primo geocoding.")
    return {}


def _save_geocode_cache(cache: dict):
    path = Path(_GEOCODE_CACHE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    logger.debug(f"[Geocode] Cache salvata: {len(cache)} voci totali.")


def geocode_city(city: str, state: str = "", cache: dict = None) -> tuple:
    """
    Ritorna (lat, lng) per una citt\u00e0, usando cache locale per evitare
    di ri-interrogare Nominatim su citt\u00e0 gi\u00e0 geocodificate.
    """
    cache = cache if cache is not None else _load_geocode_cache()
    key = f"{city.strip().lower()}|{state.strip().lower()}"

    if key in cache:
        coords = tuple(cache[key])
        logger.info(f"[Geocode] \u2713 Cache HIT per '{city}' ({state}): {coords}")
        return coords

    logger.info(f"[Geocode] Interrogo Nominatim per '{city}' ({state})...")
    geolocator = Nominatim(user_agent="local-contractors-scraper")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)

    query = f"{city}, {state}" if state else city
    location = geocode(query)

    if location:
        coords = (location.latitude, location.longitude)
        logger.info(f"[Geocode] \u2713 Trovato: '{city}' ({state}) => {coords} (raw: '{location.address}')")
        cache[key] = coords
        _save_geocode_cache(cache)
        return coords

    logger.warning(f"[Geocode] \u2717 Nominatim non ha trovato coordinate per '{city}' ({state}). Fallback a URL senza geofencing.")
    return (None, None)


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
    zoom: int = 12,
) -> List[Dict[str, str]]:
    search_urls = []
    geocode_cache = _load_geocode_cache()
    logger.info(f"[Geocode] Inizio geocoding per {len(cities)} citt\u00e0...")

    for city in cities:
        lat, lng = geocode_city(city, state=state, cache=geocode_cache)

        for keyword in keywords:
            query = f"{keyword} {city}".replace(" ", "+")

            if lat is not None and lng is not None:
                url = (
                    f"https://www.google.com/maps/search/{query}"
                    f"/@{lat},{lng},{zoom}z/?hl={lang}&gl={'US' if lang == 'en' else 'IT'}"
                )
                logger.debug(f"[Geocode] URL geofenced per '{city}' + '{keyword}': {url}")
            else:
                url = f"https://www.google.com/maps/search/{query}?hl={lang}&gl={'US' if lang == 'en' else 'IT'}"
                logger.debug(f"[Geocode] URL fallback per '{city}' + '{keyword}': {url}")

            search_urls.append({
                "comune": city,
                "keyword": keyword,
                "url": url,
            })

    geo_ok = sum(1 for c in cities if geocode_city(c, state=state, cache=geocode_cache) != (None, None))
    logger.info(f"[Geocode] Geocoding completato: {geo_ok}/{len(cities)} citt\u00e0 con coordinate.")
    return search_urls


def get_max_results(popolazione: int, lang: str = "en") -> int:
    """
    Adatta max_results alla dimensione della citta'.
    Esportata qui (invece che solo in run_batch.py) in modo che
    parallel_worker.py possa importarla senza dipendere dal modulo CLI.
    """
    if lang == "en":  # US
        if popolazione < 50_000:
            return 20
        elif popolazione < 250_000:
            return 30
        elif popolazione < 1_000_000:
            return 40
        else:
            return 50
    else:  # IT
        if popolazione < 5_000:
            return 10
        elif popolazione < 20_000:
            return 20
        elif popolazione < 100_000:
            return 30
        else:
            return 50


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

    driver = None
    mon = None
    try:
        results_raw, driver, mon = scrape_with_selenium(
            search_urls,
            driver=None,
            max_results=max_results,
            scroll_times=scroll_times,
            headless=headless,
            debug_screenshot=debug_screenshot,
        )
    finally:
        if mon:
            mon.log_stats()
            logger.info(
                f"[ResourceMonitor] Peak RAM per '{comune}': {mon.peak_ram_mb():.1f} MB"
            )
            mon.stop()
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
