import logging
import requests
import time
import random
from typing import List, Dict, Any

from .website_checker import website_is_real

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
# Core scraper Places API + filtro sito reale
# ---------------------------------------------------------------
def search_contractors(
    comune: str,
    keywords: List[str],
    api_key: str,
    min_reviews: int = 1,
    max_reviews: int = 15,
    radius_km: float = 5.0,
    check_website_alive: bool = True,
) -> List[Dict[str, Any]]:
    """
    Cerca attivita' artigianali su Google Places.

    Filtra FUORI le attivita' che hanno un sito web REALE, cioe':
      - Non e' un profilo social (Facebook, Instagram, ecc.)
      - Non e' una directory (PagineGialle, TripAdvisor, ecc.)
      - Il sito risponde online (check HTTP)

    Tiene DENTRO le attivita' che:
      - Non hanno sito web
      - O hanno solo un link social/directory (= niente sito vero)
      - O hanno un dominio morto/non raggiungibile

    Ritorna lista di dict: nome, telefono, orario, google_maps,
                           comune, keyword, num_recensioni
    """
    lat, lon = geocode_comune(comune, api_key)
    if lat is None:
        logger.warning(f"[Scraper] Impossibile geocodificare {comune}, salto.")
        return []

    nearby_url  = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    details_url = "https://maps.googleapis.com/maps/api/place/details/json"
    radius_m    = int(radius_km * 1000)
    results     = []
    seen_ids    = set()

    session = requests.Session()
    session.headers.update({"User-Agent": "LocalContractors/1.0"})

    for keyword in keywords:
        logger.info(f"[Scraper] '{keyword}' in {comune}")
        page_token = None

        for _page in range(3):  # max 3 pagine x keyword = ~60 candidati
            params = {
                "key":      api_key,
                "location": f"{lat},{lon}",
                "radius":   radius_m,
                "keyword":  keyword,
            }
            if page_token:
                params = {"key": api_key, "pagetoken": page_token}
                time.sleep(2.0)

            try:
                resp = session.get(nearby_url, params=params, timeout=20)
                data = resp.json()
            except Exception as e:
                logger.error(f"[Scraper] Errore Nearby: {e}")
                break

            if data.get("status") not in {"OK", "ZERO_RESULTS"}:
                logger.warning(
                    f"[Scraper] Status: {data.get('status')} - "
                    f"{data.get('error_message','')}"
                )
                break

            for place in data.get("results", []):
                place_id     = place.get("place_id")
                user_ratings = place.get("user_ratings_total", 0) or 0

                # --- Filtro n. recensioni ---
                if not (min_reviews <= user_ratings <= max_reviews):
                    continue

                if place_id in seen_ids:
                    continue
                seen_ids.add(place_id)

                # --- Place Details ---
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
                        res      = det_data.get("result", {})
                        website  = res.get("website", "") or ""
                        phone    = res.get("formatted_phone_number", "") or ""
                        maps_url = res.get("url", maps_url)
                        oh       = res.get("opening_hours", {})
                        if oh:
                            wt    = oh.get("weekday_text", [])
                            hours = " | ".join(wt) if wt else ""
                except Exception as e:
                    logger.debug(f"[Scraper] Errore Details per {place_id}: {e}")

                # --- Filtro sito web reale ---
                # website_is_real() ritorna True se il sito e' un vero sito attivo.
                # Noi vogliamo il CONTRARIO: teniamo chi NON ha un sito reale.
                if website_is_real(website, check_alive=check_website_alive):
                    logger.info(
                        f"[Scraper] Scartato '{place.get('name','')}' "
                        f"- ha sito reale: {website}"
                    )
                    continue

                results.append({
                    "nome":           place.get("name", ""),
                    "comune":         comune,
                    "keyword":        keyword,
                    "telefono":       phone,
                    "orario":         hours,
                    "num_recensioni": user_ratings,
                    "google_maps":    maps_url,
                    # Utile per debug: mostra cosa aveva su Google
                    "sito_google":    website or "(nessuno)",
                })

                time.sleep(random.uniform(0.2, 0.5))

            page_token = data.get("next_page_token")
            if not page_token:
                break

        time.sleep(random.uniform(0.8, 1.5))

    return results
