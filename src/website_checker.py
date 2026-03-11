import logging
import requests
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Domini social/directory che NON contano come "sito web reale"
SOCIAL_DOMAINS = {
    "facebook.com", "fb.com",
    "instagram.com",
    "twitter.com", "x.com",
    "linkedin.com",
    "tiktok.com",
    "youtube.com",
    "wa.me", "whatsapp.com",
    "t.me", "telegram.org",
    "paginegialle.it", "paginebianche.it",
    "tripadvisor.it", "tripadvisor.com",
    "yelp.com",
    "booking.com",
    "trustpilot.com",
    "google.com", "google.it",
    "maps.google.com",
    "linktr.ee",
    "bio.link",
    "beacons.ai",
}


def _root_domain(url: str) -> str:
    """Estrae il dominio radice (es. 'facebook.com') da un URL."""
    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
        # Gestisce sottodomini: prende gli ultimi 2 segmenti
        parts = host.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return host
    except Exception:
        return ""


def is_social_or_directory(url: str) -> bool:
    """True se l'URL punta a un social network o directory, non a un sito proprietario."""
    if not url:
        return False
    domain = _root_domain(url)
    return domain in SOCIAL_DOMAINS


def is_website_alive(url: str, timeout: int = 8) -> bool:
    """
    Verifica con requests (HEAD poi GET) se il sito risponde con 2xx o 3xx.
    NON usa Selenium qui: e' un check HTTP veloce.
    Ritorna False se:
      - timeout / errore connessione
      - HTTP >= 400
      - dominio non risolve
    """
    if not url:
        return False

    # Assicura schema
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }

    try:
        # Prima prova HEAD (veloce)
        r = requests.head(url, headers=headers, timeout=timeout,
                          allow_redirects=True, verify=False)
        if r.status_code < 400:
            return True
        # Alcuni server non supportano HEAD, prova GET
        r = requests.get(url, headers=headers, timeout=timeout,
                         allow_redirects=True, verify=False, stream=True)
        return r.status_code < 400
    except Exception as e:
        logger.debug(f"[WebCheck] {url} -> non raggiungibile: {e}")
        return False


def website_is_real(url: str, check_alive: bool = True) -> bool:
    """
    Ritorna True SOLO se il sito:
      1. non e' un social/directory
      2. (opzionale) risponde online
    """
    if not url:
        return False
    if is_social_or_directory(url):
        logger.info(f"[WebCheck] Scartato (social/directory): {url}")
        return False
    if check_alive and not is_website_alive(url):
        logger.info(f"[WebCheck] Scartato (sito morto): {url}")
        return False
    return True
