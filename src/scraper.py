import logging
import requests
import time
import random
import os
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------
# Geocoding: dato comune -> (lat, lon)
# ---------------------------------------------------------------
def geocode_comune(comune: str, api_key: str) -> tuple:
    """Restituisce (lat, lon) per un comune usando Google Geocoding API."""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": f"{comune}, Italia", "key": api_key}
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data.get("status") == "OK":
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        logger.error(f"[Geocode] Errore per {comune}: {e}")
    return None, None


# ---------------------------------------------------------------
# Core scraper: cerca artigiani SENZA sito e con 1-15 recensioni
# ---------------------------------------------------------------
def search_contractors(
    comune: str,
    keywords: List[str],
    api_key: str,
    min_reviews: int = 1,
    max_reviews: int = 15,
    radius_km: float = 5.0,
) -> List[Dict[str, Any]]:
    """
    Cerca attività artigianali su Google Places.
    Filtra:
      - NESSUN sito web associato
      - Numero recensioni tra min_reviews e max_reviews
    Ritorna lista di dict con: nome, telefono, orario, google_maps_link, comune, keyword, num_recensioni
    """
    lat, lon = geocode_comune(comune, api_key)
    if lat is None:
        logger.warning(f"[Scraper] Impossibile geocodificare {comune}, salto.")
        return []

    nearby_url   = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    details_url  = "https://maps.googleapis.com/maps/api/place/details/json"
    radius_m     = int(radius_km * 1000)
    results      = []
    seen_ids     = set()

    session = requests.Session()
    session.headers.update({"User-Agent": "LocalContractors/1.0"})

    for keyword in keywords:
        logger.info(f"[Scraper] '{keyword}' in {comune}")
        page_token = None

        for _page in range(3):  # max 3 pagine = 60 risultati per keyword
            params = {
                "key":      api_key,
                "location": f"{lat},{lon}",
                "radius":   radius_m,
                "keyword":  keyword,
            }
            if page_token:
                params = {"key": api_key, "pagetoken": page_token}
                time.sleep(2.0)  # obbligatorio per next_page_token

            try:
                resp = session.get(nearby_url, params=params, timeout=20)
                data = resp.json()
            except Exception as e:
                logger.error(f"[Scraper] Errore Nearby: {e}")
                break

            if data.get("status") not in {"OK", "ZERO_RESULTS"}:
                logger.warning(f"[Scraper] Status: {data.get('status')} - {data.get('error_message','')}")
                break

            for place in data.get("results", []):
                place_id         = place.get("place_id")
                user_ratings     = place.get("user_ratings_total", 0) or 0

                # Filtro recensioni
                if not (min_reviews <= user_ratings <= max_reviews):
                    continue

                if place_id in seen_ids:
                    continue
                seen_ids.add(place_id)

                # Fetch Details: website, phone, opening_hours
                det_params = {
                    "key":      api_key,
                    "place_id": place_id,
                    "fields":   "name,formatted_phone_number,opening_hours,website,url",
                    "language": "it",
                }
                website  = ""
                phone    = ""
                hours    = ""
                maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

                try:
                    det_resp = session.get(details_url, params=det_params, timeout=20)
                    det_data = det_resp.json()
                    if det_data.get("status") == "OK":
                        res     = det_data.get("result", {})
                        website = res.get("website", "") or ""
                        phone   = res.get("formatted_phone_number", "") or ""
                        maps_url = res.get("url", maps_url)  # link diretto alla pagina Google
                        oh      = res.get("opening_hours", {})
                        if oh:
                            weekday_text = oh.get("weekday_text", [])
                            hours = " | ".join(weekday_text) if weekday_text else ""
                except Exception as e:
                    logger.debug(f"[Scraper] Errore Details per {place_id}: {e}")

                # Filtro: NESSUN sito web
                if website:
                    continue

                results.append({
                    "nome":          place.get("name", ""),
                    "comune":        comune,
                    "keyword":       keyword,
                    "telefono":      phone,
                    "orario":        hours,
                    "num_recensioni":user_ratings,
                    "google_maps":   maps_url,
                })

                time.sleep(random.uniform(0.2, 0.5))  # piccolo throttle Details

            page_token = data.get("next_page_token")
            if not page_token:
                break

        time.sleep(random.uniform(0.8, 1.5))

    return results
