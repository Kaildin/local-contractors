import logging
import time
import random
import re
from urllib.parse import urlparse, parse_qs

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

from .driver_utils import init_driver
from .text_utils import clean_extracted_text

logger = logging.getLogger(__name__)


def _looks_like_google_status_block(s: str) -> bool:
    s2 = (s or "").strip().lower()
    if not s2:
        return True
    bad_tokens = ["chiuso", "apre", "stelle", "recension", "valutaz", "·", "ore", "orari"]
    return any(t in s2 for t in bad_tokens)


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


def sanitize_address(addr: str) -> str:
    if not addr:
        return ""
    a = addr.strip()
    low = a.lower()
    if any(t in low for t in ["chiuso", "apre", "stelle", "recension", "·"]):
        has_cap = any(tok.isdigit() and len(tok) == 5 for tok in a.split())
        return a if has_cap else ""
    return a


def sanitize_website(url: str) -> str:
    if not url:
        return ""
    u = url.strip()
    if "google." in u.lower():
        return ""
    return u


def _scroll_results_panel(driver, scroll_times: int = 10):
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
        except:
            continue

    if panel:
        for i in range(scroll_times):
            try:
                driver.execute_script("arguments[0].scrollTop += 800;", panel)
                time.sleep(0.6)
            except:
                break
    else:
        logger.debug("Pannello laterale non trovato, uso scroll pagina")
        for i in range(scroll_times):
            driver.execute_script(f"window.scrollBy(0, {400 + i*100});")
            time.sleep(0.5)


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
    Legge il numero di recensioni direttamente dal body text della scheda.
    Google Maps mostra il testo nella forma "11 recensioni" o "11 reviews".
    Prende il primo match con numero > 0.
    """
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        # Cerca tutte le occorrenze "N recensioni" / "N reviews" nel body
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
        except:
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


def scrape_with_selenium(search_urls, driver=None, max_results: int = 20, scroll_times: int = 10):
    results = []
    seen_in_run: set = set()

    if driver is None:
        logger.info("Driver non fornito, inizializzazione...")
        try:
            driver = init_driver(headless=True)
        except Exception as e:
            logger.error(f"Errore inizializzazione Chrome: {e}")
            try:
                driver = init_driver(headless=False)
            except Exception as e2:
                logger.critical(f"Impossibile avviare Chrome: {e2}")
                raise

    for search in search_urls:
        comune_attuale = search['comune']
        keyword = search['keyword']
        url = search['url']

        logger.info(f"Cercando: {keyword} in {comune_attuale}")

        try:
            max_retries = 2
            nav_success = False
            for attempt in range(max_retries + 1):
                try:
                    if driver is None:
                        driver = init_driver(headless=True)
                    driver.get(url)
                    nav_success = True
                    break
                except Exception as e_nav:
                    logger.warning(f"Errore navigazione (tentativo {attempt+1}/{max_retries+1}): {e_nav}")
                    if attempt < max_retries:
                        try:
                            if driver: driver.quit()
                        except: pass
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
                except:
                    continue

            time.sleep(2)

            logger.info("Scrolling per caricare risultati...")
            _scroll_results_panel(driver, scroll_times=scroll_times)

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
                    except:
                        continue
                if not name_candidate:
                    try:
                        name_candidate = el.get_attribute("aria-label") or ""
                    except:
                        pass
                place_urls.append({"href": href, "name": name_candidate})

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

                logger.info(f"Navigazione diretta alla scheda: {name}")
                try:
                    driver.get(place_href)
                except Exception as e_nav:
                    logger.error(f"Errore navigazione scheda '{name}': {e_nav}")
                    continue

                panel_ready = _wait_for_place_page(driver, expected_name=name, timeout=15)
                if not panel_ready:
                    logger.warning(f"[Skip] Scheda non caricata per '{name}', salto.")
                    continue

                maps_url = driver.current_url
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
                                    if _looks_like_google_status_block(addr_text):
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
                    except:
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
                    except:
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
                    except:
                        continue

                if not website:
                    logger.info(f"Sito web non trovato per {name}")

                address = sanitize_address(address)
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
