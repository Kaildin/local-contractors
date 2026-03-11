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
    """Riconosce se una stringa è il blocco orari/rating di Google invece dell'indirizzo."""
    s2 = (s or "").strip().lower()
    if not s2:
        return True
    bad_tokens = ["chiuso", "apre", "stelle", "recension", "valutaz", "·", "ore", "orari"]
    return any(t in s2 for t in bad_tokens)

def _looks_like_address(s: str) -> bool:
    """Verifica euristica se una stringa somiglia a un indirizzo (numeri, virgole o CAP)."""
    s2 = (s or "").strip()
    if len(s2) < 8:
        return False
    has_digit = any(ch.isdigit() for ch in s2)
    has_comma = "," in s2
    has_cap = any(token.isdigit() and len(token) == 5 for token in s2.split())
    return (has_digit and (has_comma or has_cap))

def _extract_real_url_if_google_redirect(href: str) -> str:
    """Estrae l'URL reale se si tratta di un redirect di Google."""
    try:
        u = urlparse(href)
        if "google." in (u.netloc or "").lower() and u.path.startswith("/url"):
            q = parse_qs(u.query).get("q", [""])[0]
            return q or href
    except Exception:
        return href
    return href

def _is_valid_external_site(href: str) -> bool:
    """Verifica se l'URL è un sito esterno valido (non Google)."""
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
    """Pulisce l'indirizzo da pattern comuni di Google non desiderati."""
    if not addr:
        return ""
    a = addr.strip()
    low = a.lower()
    if any(t in low for t in ["chiuso", "apre", "stelle", "recension", "·"]):
        has_cap = any(tok.isdigit() and len(tok) == 5 for tok in a.split())
        return a if has_cap else ""
    return a

def sanitize_website(url: str) -> str:
    """Pulisce l'URL eliminando link Google residui."""
    if not url:
        return ""
    u = url.strip()
    if "google." in u.lower():
        return ""
    return u


def scrape_with_selenium(search_urls, driver=None):
    """Scrape dei risultati utilizzando Selenium su Google Maps.
    search_urls: lista di dict con chiavi 'comune', 'keyword', 'url'
    """
    results = []

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
            for i in range(7):
                driver.execute_script(f"window.scrollBy(0, {300 + i*100});")
                time.sleep(0.5)

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

            for i in range(min(10, len(result_elements))):
                try:
                    logger.info(f"Elaborazione risultato {i+1}/{min(10, len(result_elements))}")

                    result_elements = driver.find_elements(By.CSS_SELECTOR, used_selector)
                    if i >= len(result_elements): break

                    element = result_elements[i]
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
                    time.sleep(1)

                    name = ""
                    name_selectors = ["h3", ".qBF1Pd", ".fontHeadlineSmall", "[jsan*='fontHeadlineSmall']",
                                    ".section-result-title", "span.OSrXXb", "[jstcache]", "[class*='title']"]

                    for ns in name_selectors:
                        try:
                            name_elements = element.find_elements(By.CSS_SELECTOR, ns)
                            if name_elements:
                                name = name_elements[0].text.strip()
                                if name: break
                        except: continue

                    if not name:
                        try:
                            name = driver.execute_script("""
                                var el = arguments[0];
                                var headers = el.querySelectorAll('h1, h2, h3, h4, h5, .fontHeadlineSmall, [class*="title"], [class*="name"]');
                                if (headers && headers.length > 0) return headers[0].innerText;
                                return el.innerText.split('\\n')[0];
                            """, element)
                        except: pass

                    if not name: name = element.get_attribute("aria-label") or ""

                    if not name:
                        logger.warning("Nome non trovato, risultato saltato")
                        continue

                    logger.info(f"Apertura dettagli per: {name}")
                    current_list_page_url = driver.current_url

                    try:
                        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
                        time.sleep(0.5)

                        click_methods = [
                            lambda: element.click(),
                            lambda: ActionChains(driver).move_to_element(element).click().perform(),
                            lambda: driver.execute_script("arguments[0].click();", element),
                            lambda: driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));", element)
                        ]

                        success = False
                        for click_method in click_methods:
                            try:
                                click_method()
                                time.sleep(1.5)
                                if "/maps/place/" in driver.current_url:
                                    success = True
                                    break
                            except: continue

                        if not success:
                            try:
                                driver.get(current_list_page_url)
                                time.sleep(1)
                            except:
                                driver.get(url)
                                time.sleep(1.5)
                            continue

                    except Exception:
                        try: driver.get(current_list_page_url)
                        except: pass
                        continue

                    # Estrazione dettagli
                    address = ""
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
                                            logger.debug(f"Saltato candidato indirizzo (google block): {addr_text}")
                                            continue
                                        if not _looks_like_address(addr_text):
                                            logger.debug(f"Saltato candidato indirizzo (no address format): {addr_text}")
                                            continue
                                        temp_list = clean_extracted_text(addr_text)
                                        if name and name.lower() in temp_list.lower() and len(temp_list) > len(name) + 5:
                                            if re.search(r'\d+[.,]\d+\(\d+\)', temp_list): continue
                                        address = temp_list
                                        break
                                if address: break
                        except: continue

                    phone = ""
                    phone_selectors = [
                        "button[data-item-id='phone:tel']", "button[aria-label*='telefono']", "button[aria-label*='phone']",
                        "button[data-tooltip*='telefono']", "[data-item-id*='phone']", "button[aria-label*='call']", ".rogA2c"
                    ]
                    for selector in phone_selectors:
                        try:
                            phone_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                            if phone_elements:
                                for pe in phone_elements:
                                    phone_text = pe.text.strip() or pe.get_attribute("aria-label")
                                    if phone_text:
                                        phone = clean_extracted_text(phone_text)
                                        if re.search(r'\d', phone): break
                                if phone and re.search(r'\d', phone): break
                        except: continue

                    website = ""
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
                                        break
                                    if not website:
                                        web_text = we.text.strip() or we.get_attribute("aria-label") or ""
                                        if web_text and ("sito web:" in web_text.lower() or "website:" in web_text.lower()):
                                            site_match = re.search(r'https?://[^\s"\']+', web_text)
                                            if site_match:
                                                cand_href = _extract_real_url_if_google_redirect(site_match.group(0))
                                                if _is_valid_external_site(cand_href):
                                                    website = cand_href
                                                    break
                                if website: break
                        except: continue

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
                        "num_recensioni": "",
                    }

                    results.append(result)

                    try:
                        driver.get(current_list_page_url)
                        time.sleep(1.5)
                    except:
                        try:
                            driver.back()
                            time.sleep(1.5)
                        except:
                            driver.get(url)
                            time.sleep(2)

                except Exception as e:
                    logger.error(f"Errore nell'estrazione del risultato: {str(e)}")
                    try:
                        driver.get(url)
                        time.sleep(2)
                        for selector in selectors_to_try:
                            try:
                                temp_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                                if temp_elements and len(temp_elements) > 0:
                                    result_elements = temp_elements
                                    used_selector = selector
                                    break
                            except: continue
                    except: pass

            pause_time = random.uniform(3, 5)
            time.sleep(pause_time)

        except Exception as e:
            logger.error(f"Errore generale per {keyword} {comune_attuale}: {str(e)}")

    return results, driver
