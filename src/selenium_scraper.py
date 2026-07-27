import logging
import time
import random
import re
import csv

import os
import datetime
from urllib.parse import urlparse, parse_qs, quote_plus


from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

from .driver_utils import init_driver
from .text_utils import clean_extracted_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# lang helpers
# ---------------------------------------------------------------------------

_LANG_CONFIG = {
    "en": {
        "hl": "en",
        "gl": "US",
        "lang": "en-US,en",
        "status_tokens": [
            "closed", "opens", "stars", "review", "rating", "\u00b7", "hours", "open",
        ],
        "address_junk_tokens": [
            "closed", "opens", "stars", "review", "\u00b7",
        ],
    },
    "it": {
        "hl": "it",
        "gl": "IT",
        "lang": "it-IT,it",
        "status_tokens": [
            "chiuso", "apre", "stelle", "recension", "valutaz", "\u00b7", "ore", "orari",
        ],
        "address_junk_tokens": [
            "chiuso", "apre", "stelle", "recension", "\u00b7",
        ],
    },
}


def _get_lang_cfg(lang: str) -> dict:
    """Restituisce la config per il lang richiesto (default: 'en')."""
    return _LANG_CONFIG.get(lang.lower(), _LANG_CONFIG["en"])


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _safe_filename(s: str, max_len: int = 80) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9_\-]+", "", s)
    s = s.strip("_-")
    if not s:
        s = "place"
    return s[:max_len]


def _save_serp_screenshot(driver, *, comune: str, keyword: str, scroll_idx: int) -> str:
    try:
        out_dir = "debug"
        os.makedirs(out_dir, exist_ok=True)

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        comune_slug = _safe_filename(comune)
        keyword_slug = _safe_filename(keyword)
        filename = f"serp_{ts}_{scroll_idx:02d}_{comune_slug}_{keyword_slug}.png"
        path = os.path.join(out_dir, filename)

        time.sleep(0.2)
        ok = driver.save_screenshot(path)
        if ok:
            logger.info(f"[SERP Screenshot] Salvato: {path}")
            return path
    except Exception as e:
        logger.debug(f"[SERP Screenshot] Errore salvataggio: {e}")
    return ""


def _dump_serp_names_csv(place_urls: list, *, comune: str, keyword: str) -> str:
    """
    Scrive un CSV temporaneo in debug/ con i nomi dei business estratti
    dalla pagina dei risultati SERP, prima di navigare nelle singole schede.

    Colonne: index, nome, maps_href
    Nome file: debug/serp_names_<comune>_<keyword>_<timestamp>.csv

    Utile per verificare quanti/quali risultati lo scroll ha caricato
    senza aspettare l'intero scraping delle schede.
    """
    try:
        out_dir = "debug"
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        comune_slug = _safe_filename(comune)
        keyword_slug = _safe_filename(keyword)
        filename = f"serp_names_{comune_slug}_{keyword_slug}_{ts}.csv"
        path = os.path.join(out_dir, filename)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["index", "nome", "maps_href"])
            writer.writeheader()
            for i, entry in enumerate(place_urls, 1):
                writer.writerow({
                    "index": i,
                    "nome": entry.get("name", ""),
                    "maps_href": entry.get("href", ""),
                })
        logger.info(
            f"[SERP dump] {len(place_urls)} nomi scritti in: {path}"
        )
        return path
    except Exception as e:
        logger.warning(f"[SERP dump] Errore scrittura CSV: {e}")
        return ""


def _looks_like_google_status_block(s: str, lang: str = "en") -> bool:
    s2 = (s or "").strip().lower()
    if not s2:
        return True
    cfg = _get_lang_cfg(lang)
    return any(t in s2 for t in cfg["status_tokens"])


def _looks_like_address(s: str) -> bool:
    s2 = (s or "").strip()
    if len(s2) < 8:
        return False
    has_digit = any(ch.isdigit() for ch in s2)
    has_comma = "," in s2
    has_cap = any(token.isdigit() and len(token) == 5 for token in s2.split())
    return has_digit and (has_comma or has_cap)


def _extract_real_url_if_google_redirect(href: str) -> str:
    try:
        u = urlparse(href)
        if "google." in (u.netloc or "").lower() and u.path.startswith("/url"):
            q = parse_qs(u.query).get("q", [""])[0]
            return q or href
    except Exception:
        return href
    return href


def _is_valid_external_site(href: str) -> bool:
    if not href:
        return False
    if not href.startswith(("http://", "https://")):
        return False
    href = _extract_real_url_if_google_redirect(href)
    try:
        u = urlparse(href)
        d = (u.netloc or "").lower()
    except Exception:
        return False
    if not d or "." not in d:
        return False
    blocked = ["google.", "gstatic.", "googleusercontent.", "googleapis.", "support.google", "maps.google"]
    if any(b in d for b in blocked):
        return False
    return True


def sanitize_address(addr: str, lang: str = "en") -> str:
    if not addr:
        return ""
    a = addr.strip()
    low = a.lower()
    cfg = _get_lang_cfg(lang)
    if any(t in low for t in cfg["address_junk_tokens"]):
        has_zip = any(tok.isdigit() and len(tok) == 5 for tok in a.split())
        return a if has_zip else ""
    return a


def sanitize_website(url: str) -> str:
    if not url:
        return ""
    u = url.strip()
    if "google." in u.lower():
        return ""
    return u


# ---------------------------------------------------------------------------
# Scroll
# ---------------------------------------------------------------------------

def _scroll_results_panel(
    driver,
    scroll_times: int = 30,
    comune: str = "",
    keyword: str = "",
    stale_limit: int = 6,
    debug_screenshot: bool = False,
):
    """
    Scrolla il pannello risultati Google Maps fino alla fine della lista.

    Si ferma quando:
      1. Viene rilevato l'elemento di fine lista GMaps con testo riconoscibile.
      2. Il conteggio risultati rimane invariato per `stale_limit` scroll
         consecutivi DOPO attesa adattiva (fino a 2.5s per burst tardivi).
    """
    END_OF_LIST_SELECTORS = [
        "div.HlvSq",
        "span.HlvSq",
    ]
    END_OF_LIST_TEXTS = [
        "you've reached the end",
        "hai raggiunto la fine",
        "end of list",
        "fine dell'elenco",
        "no more results",
        "nessun altro risultato",
    ]
    RESULT_SELECTOR = "div[role='article'], div.Nv2PK"

    panel_selectors = [
        "div[role='feed']",
        "div.m6QErb[aria-label]",
        "div.m6QErb.DxyBCb",
        "div.m6QErb",
        "div[jsaction*='scrollend']",
    ]
    panel = None
    for sel in panel_selectors:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                panel = els[0]
                logger.debug(f"Pannello scroll trovato con: {sel}")
                break
        except Exception:
            continue

    if not panel:
        logger.warning("[Scroll] Pannello laterale non trovato, uso scroll pagina (fallback).")

    stale_streak = 0

    for i in range(scroll_times):
        for end_sel in END_OF_LIST_SELECTORS:
            try:
                end_els = driver.find_elements(By.CSS_SELECTOR, end_sel)
                for el in end_els:
                    t = (el.text or "").strip().lower()
                    if t and any(phrase in t for phrase in END_OF_LIST_TEXTS):
                        logger.info(f"[Scroll] Fine lista rilevata (selector) al passo {i + 1}")
                        return
            except Exception:
                continue

        try:
            before_count = len(driver.find_elements(By.CSS_SELECTOR, RESULT_SELECTOR))
        except Exception:
            before_count = 0

        try:
            if panel:
                driver.execute_script("arguments[0].scrollTop += 800;", panel)
            else:
                driver.execute_script("window.scrollBy(0, 800);")
            if debug_screenshot:
                _save_serp_screenshot(
                    driver,
                    comune=comune,
                    keyword=keyword,
                    scroll_idx=i + 1,
                )
        except Exception:
            break

        adaptive_deadline = time.time() + 2.5
        after_count = before_count
        while time.time() < adaptive_deadline:
            time.sleep(0.4)
            try:
                after_count = len(driver.find_elements(By.CSS_SELECTOR, RESULT_SELECTOR))
            except Exception:
                break
            if after_count > before_count:
                logger.debug(f"[Scroll] Nuovi elementi arrivati: {before_count} -> {after_count}")
                break

        if after_count > 0 and after_count == before_count:
            stale_streak += 1
            logger.debug(
                f"[Scroll] Conteggio stabile ({after_count}) - streak {stale_streak}/{stale_limit}"
            )
            if stale_streak >= stale_limit:
                logger.info(
                    f"[Scroll] Nessun nuovo risultato per {stale_limit} scroll consecutivi, stop."
                )
                return
        else:
            stale_streak = 0

    logger.info(f"[Scroll] Raggiunto limite massimo scroll ({scroll_times}).")


# ---------------------------------------------------------------------------
# Place extraction helpers
# ---------------------------------------------------------------------------

def _extract_place_url_from_element(element) -> str:
    try:
        links = element.find_elements(By.CSS_SELECTOR, "a[href*='/maps/place/']")
        if links:
            href = links[0].get_attribute("href") or ""
            if href:
                return href
        tag = element.tag_name
        if tag == "a":
            href = element.get_attribute("href") or ""
            if "/maps/place/" in href:
                return href
    except Exception as e:
        logger.debug(f"[ExtractURL] Errore: {e}")
    return ""


def _extract_num_recensioni(driver) -> int:
    """
    Legge il numero di recensioni dalla scheda Google Maps.
    """

    try:
        body_src = driver.page_source

        m = re.search(
            r'([0-9][0-9\.\,\s]{0,9})\n?(?:&nbsp;)?(?:recensioni?|reviews?)',
            body_src, re.IGNORECASE
        )
        if m:
            n = int(re.sub(r'[^\d]', '', m.group(1)))
            if 0 < n < 500000:
                logger.info(f"[Rec] trovate {n} da JSON embedded (pattern A)")
                return n

        rating_positions = [m.start() for m in re.finditer(
            r'[,\[]\s*[1-5]\.[0-9]\s*,', body_src
        )]
        for rpos in rating_positions:
            window = body_src[rpos:rpos + 200]
            m2 = re.search(r'[,\[]\s*([1-9]\d{1,5})\s*[,\]]', window)
            if m2:
                n = int(m2.group(1))
                if 0 < n < 200000:
                    logger.info(f"[Rec] trovate {n} da JSON embedded (pattern B)")
                    return n

    except Exception as e:
        logger.debug(f"[Rec] Strategia 0 fallita: {e}")

    try:
        for sel in [
            "span[aria-label*='recension']",
            "span[aria-label*='review']",
            "button[aria-label*='recension']",
            "button[aria-label*='review']",
        ]:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                label = el.get_attribute("aria-label") or ""
                m = re.search(r'([\d][\d\.,]*)', label)
                if m:
                    n = int(re.sub(r'[^\d]', '', m.group(1)))
                    if n > 0:
                        logger.info(f"[Rec] trovate {n} recensioni da aria-label")
                        return n
    except Exception as e:
        logger.debug(f"[Rec] Metodo aria-label fallito: {e}")

    try:
        for sel in [
            "div.F7nice",
            "span.UY7F9",
            "div.UaQhfb span",
            "div.fontBodyMedium span.UY7F9",
            "button.DkEaL",
            "div[jsaction*='pane.rating']",
        ]:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    txt = (el.text or "").strip()
                    if not txt:
                        continue
                    m = re.search(r'\(([0-9][0-9\.\,]*)\)', txt)
                    if m:
                        n = int(re.sub(r'[^\d]', '', m.group(1)))
                        if n > 0:
                            logger.info(f"[Rec] trovate {n} da {sel} (parentesi)")
                            return n
                    m2 = re.search(r'([0-9][0-9\.\,]*)\s*recensioni?', txt, re.IGNORECASE)
                    if not m2:
                        m2 = re.search(r'([0-9][0-9\.\,]*)\s*reviews?', txt, re.IGNORECASE)
                    if m2:
                        n = int(re.sub(r'[^\d]', '', m2.group(1)))
                        if n > 0:
                            logger.info(f"[Rec] trovate {n} da {sel} (testo)")
                            return n
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"[Rec] Strategia 1b fallita: {e}")

    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        matches = re.findall(
            r'([\d][\d\.\,\s]*?)\s+(?:recensioni?|reviews?)',
            body_text,
            re.IGNORECASE
        )
        for raw in matches:
            clean = re.sub(r'[^\d]', '', raw)
            if clean:
                n = int(clean)
                if n > 0:
                    logger.info(f"[Rec] trovate {n} recensioni dal body text")
                    return n
    except Exception as e:
        logger.debug(f"[Rec] Errore lettura body: {e}")
    return 0


def _get_h1(driver) -> str:
    for sel in ["h1.DUwDvf", "h1.fontHeadlineLarge", "h1"]:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                t = els[0].text.strip()
                if t:
                    return t
        except Exception:
            continue
    return ""


def _name_matches_title(name: str, title: str) -> bool:
    name_words = [w for w in name.strip().lower().split() if len(w) > 2]
    if not name_words:
        return True
    title_norm = title.strip().lower()
    matches = sum(1 for w in name_words if w in title_norm)
    return (matches / len(name_words)) >= 0.4


def _wait_for_place_page(driver, expected_name: str, timeout: int = 15) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if "/maps/place/" not in driver.current_url:
                time.sleep(0.5)
                continue
            h1_text = _get_h1(driver)
            if not h1_text:
                time.sleep(0.5)
                continue
            if _name_matches_title(expected_name, h1_text):
                panels = driver.find_elements(By.CSS_SELECTOR, "div[role='main']")
                if panels:
                    btns = panels[0].find_elements(By.TAG_NAME, "button")
                    if len(btns) >= 3:
                        time.sleep(0.5)
                        return True
                time.sleep(0.5)
            else:
                logger.debug(f"[Wait] h1='{h1_text}' != atteso='{expected_name}'")
                time.sleep(0.5)
        except Exception as e:
            logger.debug(f"[Wait] Eccezione: {e}")
            time.sleep(0.5)
    logger.warning(f"[Wait] Timeout ({timeout}s) per '{expected_name}'")
    return False


def _wait_for_authority_link(driver, timeout: int = 6) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, "a[data-item-id='authority']")
            if els:
                href = els[0].get_attribute("href") or ""
                if href and _is_valid_external_site(href):
                    return True
            panels = driver.find_elements(By.CSS_SELECTOR, "div[role='main']")
            if panels:
                btns = panels[0].find_elements(By.TAG_NAME, "button")
                if len(btns) >= 5:
                    return False
        except Exception:
            pass
        time.sleep(0.4)
    return False


def _navigate_to_place(driver, name: str, place_href: str, lang: str = "en"):
    cfg = _get_lang_cfg(lang)
    hl = cfg["hl"]
    gl = cfg["gl"]

    try:
        os.makedirs("debug", exist_ok=True)
    except Exception:
        pass

    def _has_review_signals() -> bool:
        review_selectors = [
            "span[aria-label*='recension']",
            "span[aria-label*='review']",
            "button[aria-label*='recension']",
            "button[aria-label*='review']",
            "[data-tab-index='1']",
            "div[role='tab']",
            "div.F7nice",
            "span.ceNzKf",
            "div.UaQhfb",
        ]
        for sel in review_selectors:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                visible = [e for e in els if e.is_displayed()]
                if visible:
                    logger.info(f"[Nav] Segnale recensioni trovato con selector: {sel}")
                    return True
            except Exception:
                continue
        return False

    def _click_first_place_result() -> bool:
        selectors = [
            "a[href*='/maps/place/']",
            "div[role='feed'] a[href*='/maps/place/']",
            "div[role='article'] a[href*='/maps/place/']",
            "div.Nv2PK a[href*='/maps/place/']",
        ]

        for sel in selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, sel)
                logger.info(f"[Nav] Trovati {len(elements)} candidati con {sel}")
                for idx, el in enumerate(elements[:5]):
                    try:
                        href = el.get_attribute("href") or ""
                        if "/maps/place/" not in href:
                            continue
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});", el
                        )
                        time.sleep(0.8)
                        driver.execute_script("arguments[0].click();", el)
                        logger.info(f"[Nav] Click risultato #{idx+1} con href: {href}")
                        time.sleep(4)
                        if "/maps/place/" in driver.current_url:
                            return True
                    except Exception as e:
                        logger.debug(f"[Nav] Click candidato fallito: {e}")
                        continue
            except Exception as e:
                logger.debug(f"[Nav] Selector fallito {sel}: {e}")
                continue

        return False

    try:
        driver.get("https://www.google.com")
        time.sleep(2)
        logger.info("[Nav] Warmup completato")
    except Exception as e:
        logger.debug(f"[Nav] Warmup fallito: {e}")

    name_encoded = quote_plus(name)
    search_url = (
        f"https://www.google.com/maps/search/{name_encoded}"
        f"/?hl={hl}&gl={gl}&authuser=0"
    )
    logger.info(f"[Nav] Navigazione via search: {search_url}")
    try:
        driver.get(search_url)
        time.sleep(5)
        logger.info(f"[Nav] URL dopo search: {driver.current_url}")
    except Exception as e:
        logger.warning(f"[Nav] Search navigation fallita: {e}")

    if "/maps/place/" in driver.current_url and _has_review_signals():
        logger.info("[Nav] Place page valida gia' ottenuta via search")
        return

    if "/maps/place/" not in driver.current_url:
        logger.info("[Nav] Non siamo su una scheda place, provo click da lista risultati")
        clicked = _click_first_place_result()
        logger.info(f"[Nav] Esito click da lista: {clicked}")
        logger.info(f"[Nav] URL dopo click lista: {driver.current_url}")

        if "/maps/place/" in driver.current_url and _has_review_signals():
            logger.info("[Nav] Scheda place ottenuta cliccando dalla lista")
            return

    if "/maps/place/" in driver.current_url:
        logger.info("[Nav] Siamo su place page, attendo eventuale rendering tardivo")
        for _ in range(6):
            if _has_review_signals():
                logger.info("[Nav] Segnali recensioni comparsi dopo attesa")
                return
            time.sleep(1)

    logger.info("[Nav] Fallback finale su URL diretto")
    try:
        driver.get(place_href)
        time.sleep(4)
        logger.info(f"[Nav] URL dopo fallback diretto: {driver.current_url}")
    except Exception as e:
        logger.error(f"[Nav] Fallback diretto fallito: {e}")
        raise


# ---------------------------------------------------------------------------
# Main scrape entry point
# ---------------------------------------------------------------------------

def scrape_with_selenium(
    search_urls,
    driver=None,
    max_results: int = 20,
    scroll_times: int = 30,
    headless: bool = True,
    lang: str = "en",
    debug_screenshot: bool = False,
):
    cfg = _get_lang_cfg(lang)
    results = []
    seen_in_run: set = set()

    if driver is None:
        logger.info("Driver non fornito, inizializzazione...")
        try:
            driver = init_driver(headless=headless, lang=cfg["lang"])
        except Exception as e:
            logger.error(f"Errore inizializzazione Chrome: {e}")
            try:
                driver = init_driver(headless=False, lang=cfg["lang"])
            except Exception as e2:
                logger.critical(f"Impossibile avviare Chrome: {e2}")
                raise

    for search in search_urls:
        comune_attuale = search['comune']
        keyword = search['keyword']
        url = search['url']

        logger.info(f"Cercando: {keyword} in {comune_attuale} [lang={lang}]")

        try:
            max_retries = 2
            nav_success = False
            for attempt in range(max_retries + 1):
                try:
                    if driver is None:
                        driver = init_driver(headless=headless, lang=cfg["lang"])
                    driver.get(url)
                    nav_success = True
                    break
                except Exception as e_nav:
                    logger.warning(f"Errore navigazione (tentativo {attempt+1}/{max_retries+1}): {e_nav}")
                    if attempt < max_retries:
                        try:
                            if driver: driver.quit()
                        except Exception:
                            pass
                        driver = None
                        time.sleep(2)
                    else:
                        raise e_nav

            if not nav_success:
                logger.error(f"Impossibile navigare a {url} dopo retry. Salto.")
                continue

            cookie_selectors = [
                (By.ID, "L2AGLb"),
                (By.CSS_SELECTOR, ".tHlp8d"),
                (By.CSS_SELECTOR, "button[aria-label='Accetta tutto']"),
                (By.CSS_SELECTOR, "button[aria-label='Accept all']"),
                (By.XPATH, "//button[contains(text(), 'Accetta tutto')]"),
                (By.XPATH, "//button[contains(text(), 'Accept all')]"),
                (By.XPATH, "//div[@role='dialog']//button[contains(., 'Accetta')]"),
                (By.XPATH, "//div[@role='dialog']//button[contains(., 'Accept')]")
            ]

            for selector_type, selector in cookie_selectors:
                try:
                    consent_button = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((selector_type, selector))
                    )
                    driver.execute_script("arguments[0].click();", consent_button)
                    time.sleep(1)
                    break
                except Exception:
                    continue

            time.sleep(2)

            logger.info("Scrolling per caricare risultati...")
            _scroll_results_panel(
                driver,
                scroll_times=scroll_times,
                comune=comune_attuale,
                keyword=keyword,
                debug_screenshot=debug_screenshot,
            )

            selectors_to_try = [
                "div[role='article']",
                "div.Nv2PK",
                "a[href^='/maps/place']",
                "div.section-result",
                "div.bfdHYd",
                "div.V0h1Ob-haAclf",
                "div.DxyBCb"
            ]

            result_elements = []
            used_selector = ""

            for selector in selectors_to_try:
                try:
                    temp_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if temp_elements and len(temp_elements) > 0:
                        result_elements = temp_elements
                        used_selector = selector
                        logger.info(f"Trovati {len(result_elements)} risultati usando: {selector}")
                        break
                except Exception as e:
                    logger.warning(f"Errore con selettore {selector}: {str(e)}")

            if not result_elements:
                logger.warning(f"Nessun risultato trovato per {keyword} {comune_attuale}")
                continue

            place_urls = []
            for el in result_elements[:max_results]:
                href = _extract_place_url_from_element(el)
                name_candidate = ""
                for ns in ["h3", ".qBF1Pd", ".fontHeadlineSmall", "[jsan*='fontHeadlineSmall']"]:
                    try:
                        ne = el.find_elements(By.CSS_SELECTOR, ns)
                        if ne:
                            name_candidate = ne[0].text.strip()
                            if name_candidate:
                                break
                    except Exception:
                        continue
                if not name_candidate:
                    try:
                        name_candidate = el.get_attribute("aria-label") or ""
                    except Exception:
                        pass
                place_urls.append({"href": href, "name": name_candidate})

            # ----------------------------------------------------------------
            # SERP names dump — scritto subito dopo lo scroll, prima di
            # navigare nelle singole schede. Utile per verificare quanti
            # business ha caricato lo scroll senza aspettare l'intero run.
            # File: debug/serp_names_<comune>_<keyword>_<ts>.csv
            # ----------------------------------------------------------------
            _dump_serp_names_csv(
                place_urls,
                comune=comune_attuale,
                keyword=keyword,
            )

            n_to_process = min(max_results, len(place_urls))
            for i in range(n_to_process):
                entry = place_urls[i]
                place_href = entry["href"]
                name = entry["name"]

                logger.info(f"Elaborazione risultato {i+1}/{n_to_process}")

                if not name:
                    logger.warning("Nome non trovato, risultato saltato")
                    continue

                run_key = (name.strip().lower(), comune_attuale.strip().lower())
                if run_key in seen_in_run:
                    logger.info(f"[Dedup run] Gia' scrapato questa run, saltato: {name}")
                    continue

                if not place_href:
                    logger.warning(f"URL scheda non trovato per '{name}', salto.")
                    continue

                logger.info(f"Navigazione scheda con bypass limited view: {name}")
                try:
                    _navigate_to_place(driver, name, place_href, lang=lang)
                except Exception as e_nav:
                    logger.error(f"Errore navigazione scheda '{name}': {e_nav}")
                    continue

                panel_ready = _wait_for_place_page(driver, expected_name=name, timeout=15)
                if not panel_ready:
                    logger.warning(f"[Skip] Scheda non caricata per '{name}', salto.")
                    continue

                maps_url = driver.current_url

                try:
                    WebDriverWait(driver, 8).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR,
                            "span[aria-label*='recension'], "
                            "span[aria-label*='review'], "
                            "div.F7nice")))
                except Exception:
                    pass

                num_recensioni = _extract_num_recensioni(driver)
                logger.info(f"Recensioni rilevate per {name}: {num_recensioni}")

                address = ""
                phone = ""
                website = ""

                address_selectors = [
                    "button[data-item-id='address']",
                    "button[aria-label*='Indirizzo']",
                    "button[aria-label*='indirizzo']",
                    "button[aria-label*='Address']",
                    "button[aria-label*='address']",
                    "[data-item-id*='address']",
                ]
                for selector in address_selectors:
                    try:
                        addr_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if addr_elements:
                            for ae in addr_elements:
                                addr_text = ae.text.strip() or ae.get_attribute("aria-label") or ""
                                if addr_text:
                                    if _looks_like_google_status_block(addr_text, lang=lang):
                                        continue
                                    if not _looks_like_address(addr_text):
                                        continue
                                    temp = clean_extracted_text(addr_text)
                                    if name and name.lower() in temp.lower() and len(temp) > len(name) + 5:
                                        if re.search(r'\d+[.,]\d+\(\d+\)', temp):
                                            continue
                                    address = temp
                                    break
                            if address:
                                break
                    except Exception:
                        continue

                phone_selectors = [
                    "button[data-item-id='phone:tel']",
                    "button[aria-label*='telefono']",
                    "button[aria-label*='phone']",
                    "button[data-tooltip*='telefono']",
                    "[data-item-id*='phone']",
                    "button[aria-label*='call']",
                    ".rogA2c"
                ]
                for selector in phone_selectors:
                    try:
                        phone_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if phone_elements:
                            for pe in phone_elements:
                                phone_text = pe.text.strip() or pe.get_attribute("aria-label")
                                if phone_text:
                                    phone = clean_extracted_text(phone_text)
                                    if re.search(r'\d', phone):
                                        break
                            if phone and re.search(r'\d', phone):
                                break
                    except Exception:
                        continue

                _wait_for_authority_link(driver, timeout=6)

                website_selectors = [
                    "a[data-item-id='authority']",
                    "a[data-item-id='website']",
                    "a[aria-label*='Sito web']",
                    "a[aria-label*='sito web']",
                    "a[aria-label*='Website']",
                    "a[aria-label*='website']",
                    "a[href^='http'][data-item-id]",
                ]
                for selector in website_selectors:
                    try:
                        web_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if web_elements:
                            for we in web_elements:
                                href = we.get_attribute("href") or ""
                                href = _extract_real_url_if_google_redirect(href)
                                if _is_valid_external_site(href):
                                    website = href
                                    logger.info(f"Sito web trovato per {name}: {website}")
                                    break
                                if not website:
                                    web_text = we.text.strip() or we.get_attribute("aria-label") or ""
                                    if web_text and ("sito web:" in web_text.lower() or "website:" in web_text.lower()):
                                        site_match = re.search(r'https?://[^\s"\']+', web_text)
                                        if site_match:
                                            cand = _extract_real_url_if_google_redirect(site_match.group(0))
                                            if _is_valid_external_site(cand):
                                                website = cand
                                                break
                            if website:
                                break
                    except Exception:
                        continue

                if not website:
                    logger.info(f"Sito web non trovato per {name}")

                address = sanitize_address(address, lang=lang)
                website = sanitize_website(website)

                result = {
                    "comune": comune_attuale,
                    "keyword": keyword,
                    "nome": name,
                    "indirizzo": address,
                    "telefono": phone,
                    "sito_web": website,
                    "num_recensioni": num_recensioni,
                    "maps_url": maps_url,
                }

                results.append(result)
                seen_in_run.add(run_key)

            pause_time = random.uniform(3, 5)
            time.sleep(pause_time)

        except Exception as e:
            logger.error(f"Errore generale per {keyword} {comune_attuale}: {str(e)}")

    return results, driver
