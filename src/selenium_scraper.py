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


def _extract_num_recensioni(driver) -> int:
    """
    Estrae il numero di recensioni dalla scheda Google Maps aperta.
    Usa selettori basati su aria-label (stabili) invece di class name hashati.
    """
    try:
        # Strategia 1: bottone/span stelle con aria-label che contiene sia stelle che recensioni
        for sel in [
            "button[aria-label*='stell'][aria-label*='recension']",
            "button[aria-label*='star'][aria-label*='review']",
            "span[aria-label*='stell'][aria-label*='recension']",
            "span[aria-label*='star'][aria-label*='review']",
        ]:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                label = el.get_attribute("aria-label") or ""
                m = re.search(r"([\d\.,]+)\s*(recensioni|recensione|reviews|review)", label, re.IGNORECASE)
                if m:
                    raw = m.group(1).replace(".", "").replace(",", "")
                    try:
                        return int(raw)
                    except ValueError:
                        continue

        # Strategia 2: qualsiasi elemento con aria-label contenente la parola recensioni/reviews
        for sel in [
            "[aria-label*='recensioni']",
            "[aria-label*='recensione']",
            "[aria-label*='reviews']",
            "[aria-label*='review']",
        ]:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                label = el.get_attribute("aria-label") or ""
                m = re.search(r"([\d\.,]+)\s*(recensioni|recensione|reviews|review)", label, re.IGNORECASE)
                if m:
                    raw = m.group(1).replace(".", "").replace(",", "")
                    try:
                        return int(raw)
                    except ValueError:
                        continue

        # Strategia 3: fallback su body text — cerca "(N.NNN) recension" nel testo visibile
        page_text = driver.find_element(By.TAG_NAME, "body").text
        m = re.search(r"\(([\d][\d\.,]*)\)\s*(?:recensioni?|reviews?)", page_text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(".", "").replace(",", "")
            try:
                return int(raw)
            except ValueError:
                pass

    except Exception as e:
        logger.debug(f"Errore lettura recensioni: {e}")
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


def _wait_for_panel_ready(driver, expected_name: str, timeout: int = 12) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            current_url = driver.current_url
            if "/maps/place/" not in current_url:
                time.sleep(0.5)
                continue

            h1_text = _get_h1(driver)
            if not h1_text:
                time.sleep(0.5)
                continue

            if _name_matches_title(expected_name, h1_text):
                time.sleep(1.0)
                return True
            else:
                logger.debug(f"[Wait panel] h1='{h1_text}' != atteso='{expected_name}', aspetto...")
                time.sleep(0.5)

        except Exception as e:
            logger.debug(f"[Wait panel] Eccezione: {e}")
            time.sleep(0.5)

    logger.warning(f"[Wait panel] Timeout ({timeout}s) in attesa scheda per '{expected_name}'")
    return False


def _debug_dump_panel(driver, expected_name: str):
    """
    LOG DIAGNOSTICO TEMPORANEO — rimuovere dopo il fix.
    Dumpa URL, h1, tutti i link authority e tutti gli span ZkP5Je
    presenti nel DOM al momento dell'estrazione.
    """
    try:
        logger.info(f"[DEBUG] ===== DUMP scheda attesa: '{expected_name}' =====")
        logger.info(f"[DEBUG] URL corrente: {driver.current_url}")
        logger.info(f"[DEBUG] h1: '{_get_h1(driver)}'")

        authority_els = driver.find_elements(By.CSS_SELECTOR, "a[data-item-id='authority']")
        if authority_els:
            for i, el in enumerate(authority_els):
                logger.info(f"[DEBUG] authority[{i}] href='{el.get_attribute('href')}' text='{el.text.strip()}'")
        else:
            logger.info("[DEBUG] Nessun link authority nel DOM")

        rec_els = driver.find_elements(By.CSS_SELECTOR, "[aria-label*='recension']")
        if rec_els:
            for i, el in enumerate(rec_els[:5]):
                logger.info(f"[DEBUG] recension[{i}] tag={el.tag_name} aria-label='{el.get_attribute('aria-label')}'")
        else:
            logger.info("[DEBUG] Nessun elemento aria-label*='recension' trovato")

        logger.info(f"[DEBUG] ===== FINE DUMP =====")
    except Exception as e:
        logger.info(f"[DEBUG] Errore durante dump: {e}")


def _get_main_panel(driver):
    """
    Restituisce il contenitore principale della scheda dettaglio (div[role='main']).
    Se non trovato, restituisce il driver stesso come fallback (ricerca globale).
    """
    try:
        panels = driver.find_elements(By.CSS_SELECTOR, "div[role='main']")
        if panels:
            return panels[0]
    except Exception:
        pass
    return driver


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

            n_to_process = min(max_results, len(result_elements))
            for i in range(n_to_process):
                try:
                    logger.info(f"Elaborazione risultato {i+1}/{n_to_process}")

                    result_elements = driver.find_elements(By.CSS_SELECTOR, used_selector)
                    if i >= len(result_elements):
                        break

                    element = result_elements[i]
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
                    time.sleep(1)

                    name = ""
                    name_selectors = [
                        "h3", ".qBF1Pd", ".fontHeadlineSmall", "[jsan*='fontHeadlineSmall']",
                        ".section-result-title", "span.OSrXXb", "[jstcache]", "[class*='title']"
                    ]
                    for ns in name_selectors:
                        try:
                            name_elements = element.find_elements(By.CSS_SELECTOR, ns)
                            if name_elements:
                                name = name_elements[0].text.strip()
                                if name: break
                        except:
                            continue

                    if not name:
                        try:
                            name = driver.execute_script("""
                                var el = arguments[0];
                                var headers = el.querySelectorAll('h1,h2,h3,h4,h5,.fontHeadlineSmall,[class*="title"],[class*="name"]');
                                if (headers && headers.length > 0) return headers[0].innerText;
                                return el.innerText.split('\\n')[0];
                            """, element)
                        except:
                            pass

                    if not name:
                        name = element.get_attribute("aria-label") or ""

                    if not name:
                        logger.warning("Nome non trovato, risultato saltato")
                        continue

                    run_key = (name.strip().lower(), comune_attuale.strip().lower())
                    if run_key in seen_in_run:
                        logger.info(f"[Dedup run] Gia' scrapato questa run, saltato: {name}")
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

                        clicked = False
                        for click_method in click_methods:
                            try:
                                click_method()
                                time.sleep(0.5)
                                clicked = True
                                break
                            except:
                                continue

                        if not clicked:
                            logger.warning(f"Nessun metodo click funzionato per: {name}")
                            try:
                                driver.get(current_list_page_url)
                                time.sleep(1)
                            except:
                                pass
                            continue

                    except Exception:
                        try:
                            driver.get(current_list_page_url)
                        except:
                            pass
                        continue

                    panel_ready = _wait_for_panel_ready(driver, expected_name=name, timeout=12)
                    if not panel_ready:
                        logger.warning(f"[Skip] Scheda non pronta per '{name}', salto.")
                        try:
                            driver.get(current_list_page_url)
                            time.sleep(1.5)
                        except:
                            pass
                        continue

                    # ================================================================
                    # DEBUG DIAGNOSTICO TEMPORANEO — rimuovere dopo il fix
                    # ================================================================
                    _debug_dump_panel(driver, name)

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

                    # ----------------------------------------------------------------
                    # FIX Bug 1 — Website contamination
                    # Cerchiamo il link authority SOLO nel pannello principale (div[role='main'])
                    # per evitare di leggere link residui della scheda precedente ancora nel DOM.
                    # ----------------------------------------------------------------
                    main_panel = _get_main_panel(driver)

                    website_selectors = [
                        "a[data-item-id='authority']",
                        "a[data-item-id='website']",
                        "a[aria-label*='Sito web']",
                        "a[aria-label*='sito web']",
                        "a[aria-label*='Website']",
                        "a[aria-label*='website']",
                        "a[href^='http'][data-item-id]",
                    ]

                    # Attesa attiva: aspetta fino a 5s che l'authority link nel pannello
                    # principale sia stabilizzato (href non vuoto o assente = niente sito web).
                    authority_stable = False
                    for _ in range(10):
                        try:
                            auth_els = main_panel.find_elements(By.CSS_SELECTOR, "a[data-item-id='authority']")
                            if auth_els:
                                href_check = auth_els[0].get_attribute("href") or ""
                                if href_check:
                                    authority_stable = True
                                    break
                            else:
                                # Nessun link authority nel pannello principale = attività senza sito
                                authority_stable = True
                                break
                        except Exception:
                            break
                        time.sleep(0.5)

                    for selector in website_selectors:
                        try:
                            web_elements = main_panel.find_elements(By.CSS_SELECTOR, selector)
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
                            except:
                                continue
                    except:
                        pass

            pause_time = random.uniform(3, 5)
            time.sleep(pause_time)

        except Exception as e:
            logger.error(f"Errore generale per {keyword} {comune_attuale}: {str(e)}")

    return results, driver
