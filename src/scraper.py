import json
import logging
import csv
import os
import re
import time
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
import requests

from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

from .selenium_scraper import scrape_with_selenium
from .website_checker import get_website_status, website_is_real
from .driver_utils import cleanup_chrome_tmp
from .text_utils import clean_extracted_text

# Import outreach_saas modules for advanced features
try:
    from outreach_saas.config.definitions import (
        INDUSTRY_CONFIG, 
        KEYWORDS_BY_INDUSTRY, 
        BIG_COMPANY_KEYWORDS,
        IGNORED_EMAIL_DOMAINS,
        LOCAL_PART_IGNORE_PATTERNS
    )
    from outreach_saas.analysis.relevance_analyzer import WebsiteRelevanceAnalyzer
    from outreach_saas.scraping.ddg_search_improved import ddg_search_improved
    from outreach_saas.scraping.deepseek_extractor import extract_admin_with_deepseek
    OUTREACH_AVAILABLE = True
except ImportError as e:
    OUTREACH_AVAILABLE = False
    logger.warning(f"Outreach SaaS modules not available: {e}. Advanced features disabled.")

logger = logging.getLogger(__name__)

CSV_FIELDNAMES = [
    "city", "state", "keyword", "nome", "indirizzo", "telefono",
    "sito_web", "ha_sito_web", "website_status_code", "website_check_reason",
    "num_recensioni", "maps_url",
]

# Extended fieldnames for enriched output
EXTENDED_CSV_FIELDNAMES = CSV_FIELDNAMES + [
    "email",
    "linkedin", 
    "pertinenza",
    "categoria",
    "confidenza_analisi",
    "contatto",
    "industry",
]

EMAIL_PATTERNS = [
    r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b',
    r'mailto:\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'
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


def _append_lead_to_extended_csv(output_csv: str, row: Dict[str, Any]):
    """Append to extended CSV with all fields including email, relevance, etc."""
    path = Path(output_csv)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists() and path.stat().st_size > 0
    try:
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=EXTENDED_CSV_FIELDNAMES, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        logger.error(f"[Salvataggio incrementale esteso] Errore: {e}")


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


def _extract_emails_from_text(text: str) -> List[str]:
    """Estrae email da testo usando regex patterns."""
    emails = []
    if not text:
        return emails
    
    for pattern in EMAIL_PATTERNS:
        try:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                email = match.strip().lower()
                if email and email not in emails:
                    emails.append(email)
        except Exception as e:
            logger.debug(f"Errore estrazione email con pattern {pattern}: {e}")
    
    return emails


def _extract_emails_from_website(url: str, timeout: int = 10) -> List[str]:
    """Estrae email da un sito web tramite HTTP request."""
    if not url:
        return []
    
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            text = response.text
            return _extract_emails_from_text(text)
    except Exception as e:
        logger.debug(f"Errore download sito {url}: {e}")
    
    return []


def _filter_valid_emails(emails: List[str]) -> List[str]:
    """Filtra email valide escludendo domini ignorati e pattern indesiderati."""
    valid_emails = []
    
    for email in emails:
        if not email or '@' not in email:
            continue
        
        try:
            domain = email.split('@')[1].lower()
            local_part = email.split('@')[0].lower()
            
            # Check ignored domains
            if domain in IGNORED_EMAIL_DOMAINS:
                logger.debug(f"Email scartata - dominio ignorato: {email}")
                continue
            
            # Check local part patterns
            if any(pattern.match(local_part) for pattern in LOCAL_PART_IGNORE_PATTERNS):
                logger.debug(f"Email scartata - local part pattern: {email}")
                continue
            
            # Check for disposable email domains
            disposable_domains = ['mailinator.com', 'tempmail.com', 'guerrillamail.com']
            if domain in disposable_domains:
                logger.debug(f"Email scartata - dominio temporaneo: {email}")
                continue
            
            valid_emails.append(email)
        except Exception:
            continue
    
    return valid_emails


def _is_big_company(name: str) -> bool:
    """Check if company name contains big company keywords."""
    if not name:
        return False
    name_lower = name.lower()
    return any(kw in name_lower for kw in BIG_COMPANY_KEYWORDS)


def _get_industry_keywords(industry: str) -> List[str]:
    """Get keywords for a specific industry."""
    return KEYWORDS_BY_INDUSTRY.get(industry, [])


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
    stop_event: Optional[threading.Event] = None,
    industry: Optional[str] = None,
    enable_email_extraction: bool = True,
    enable_relevance_analysis: bool = True,
    enable_admin_search: bool = False,
) -> List[Dict[str, Any]]:
    """
    Enhanced search_contractors with email extraction, relevance analysis, and admin search.
    
    Args:
        comune: City/comune to search
        keywords: List of keywords to search for
        debug_screenshot: Enable debug screenshots
        min_reviews: Minimum number of reviews
        max_reviews: Maximum number of reviews
        check_website_alive: Check if website is alive
        headless: Run browser in headless mode
        scroll_times: Number of scroll attempts
        max_results: Maximum results per search
        output_csv: Output CSV file path
        lang: Language (en/it)
        state: State/region
        stop_event: Event to stop processing
        industry: Industry for relevance analysis
        enable_email_extraction: Enable email extraction from websites
        enable_relevance_analysis: Enable website relevance analysis
        enable_admin_search: Enable admin name search via DeepSeek
    """
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
            stop_event=stop_event,
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

        # Skip big companies
        if _is_big_company(nome):
            logger.info(f"[Filter] Saltata grande impresa: {nome}")
            continue

        # Clean address and phone
        r["indirizzo"] = clean_extracted_text(r.get("indirizzo", ""))
        r["telefono"] = clean_extracted_text(r.get("telefono", ""))

        # Initialize extended fields
        r["email"] = ""
        r["linkedin"] = ""
        r["pertinenza"] = False
        r["categoria"] = "Sconosciuto"
        r["confidenza_analisi"] = 0.0
        r["contatto"] = ""
        r["industry"] = industry or ""

        # Extract emails if enabled
        if enable_email_extraction and website and status["ok"]:
            try:
                emails = _extract_emails_from_website(website)
                filtered_emails = _filter_valid_emails(emails)
                if filtered_emails:
                    r["email"] = ", ".join(filtered_emails)
                    logger.info(f"[Email] Trovate {len(filtered_emails)} email valide per {nome}")
            except Exception as e:
                logger.debug(f"[Email] Errore estrazione email per {nome}: {e}")

        # Analyze website relevance if enabled
        if enable_relevance_analysis and website and status["ok"]:
            try:
                analyzer = WebsiteRelevanceAnalyzer(industry=industry or "fotovoltaico")
                analysis = analyzer.analyze_website_relevance(website)
                r["pertinenza"] = analysis.get("is_relevant", False)
                r["categoria"] = analysis.get("category", "Sconosciuto")
                r["confidenza_analisi"] = analysis.get("confidence", 0.0)
                logger.info(f"[Relevance] {nome}: pertinenza={r['pertinenza']}, categoria={r['categoria']}")
            except Exception as e:
                logger.debug(f"[Relevance] Errore analisi pertinenza per {nome}: {e}")

        # Search for admin if enabled
        if enable_admin_search and nome:
            try:
                query = f"{nome} amministratore"
                ddg_results = ddg_search_improved(query, max_results=5)
                if ddg_results:
                    payload = f"AZIENDA: {nome}\nQUERY: {query}\n\nRISULTATI (DuckDuckGo):\n"
                    for i, item in enumerate(ddg_results[:5], 1):
                        payload += f"\n[{i}] TITOLO: {item.get('title', '')}\n[{i}] SNIPPET: {item.get('snippet', '')}\n[{i}] URL: {item.get('url', '')}"
                    
                    admin_name = extract_admin_with_deepseek(payload)
                    if admin_name:
                        r["contatto"] = admin_name
                        logger.info(f"[Admin] Amministratore trovato: {admin_name}")
            except Exception as e:
                logger.debug(f"[Admin] Errore ricerca admin per {nome}: {e}")

        filtered.append(r)
        already_seen.add(key)

        if output_csv:
            if enable_email_extraction or enable_relevance_analysis or enable_admin_search:
                _append_lead_to_extended_csv(output_csv, r)
            else:
                _append_lead_to_csv(output_csv, r)
            logger.info(f"[Salvataggio] Lead salvato: {nome} (ha_sito_web={status['ok']}, reason={status['reason']})")

    return filtered
