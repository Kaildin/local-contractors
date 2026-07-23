import logging
import requests
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

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

WEBSITE_BUILDER_DOMAINS = {
    "wixsite.com",
    "wix.com",
    "squarespace.com",
    "weebly.com",
    "webnode.it",
    "webnode.com",
    "jimdo.com",
    "strikingly.com",
    "yolasite.com",
    "godaddysites.com",
    "wordpress.com",
    "blogger.com",
    "blogspot.com",
    "altervista.org",
}


def _root_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
        parts = host.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return host
    except Exception:
        return ""


def is_social_or_directory(url: str) -> bool:
    if not url:
        return False
    return _root_domain(url) in SOCIAL_DOMAINS


def is_website_builder(url: str) -> bool:
    if not url:
        return False
    return _root_domain(url) in WEBSITE_BUILDER_DOMAINS


def get_website_status(url: str, timeout: int = 8) -> dict:
    if not url:
        return {
            "ok": False,
            "status_code": None,
            "final_url": "",
            "reason": "empty_url",
        }

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        r = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
            verify=False,
            stream=True,
        )
        code = r.status_code
        if code < 400:
            return {"ok": True, "status_code": code, "final_url": r.url, "reason": "ok"}
        if code == 403:
            return {"ok": True, "status_code": code, "final_url": r.url, "reason": "forbidden_but_present"}
        return {"ok": False, "status_code": code, "final_url": r.url, "reason": f"http_{code}"}
    except requests.RequestException as e:
        return {"ok": False, "status_code": None, "final_url": url, "reason": type(e).__name__}


def website_is_real(url: str, check_alive: bool = True) -> bool:
    if not url:
        return False
    if is_social_or_directory(url):
        return False
    if is_website_builder(url):
        return False
    if check_alive:
        return get_website_status(url)["ok"]
    return True
