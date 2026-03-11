import logging
import time
import random
from typing import List, Dict, Any, Optional

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

logger = logging.getLogger(__name__)


def _build_driver(headless: bool = True):
    """Crea un driver Chrome undetected in modalita' headless."""
    opts = uc.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=it-IT")
    opts.add_argument("--window-size=1280,800")
    return uc.Chrome(options=opts, use_subprocess=True)


def _accept_cookies(driver):
    """Tenta di chiudere il banner cookie di Google Maps."""
    try:
        btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(., 'Accetta tutto') or contains(., 'Accept all')]"
                           " | //form[@action='https://consent.google.com/save']//button[last()]")
            )
        )
        btn.click()
        time.sleep(1)
    except Exception:
        pass  # Nessun banner, ok


def _parse_hours(driver) -> str:
    """Estrae orari dalla scheda Google Maps aperta nel driver."""
    try:
        # Apre il menu orari se collassato
        toggle = driver.find_elements(
            By.XPATH,
            "//*[@data-item-id='oh']//div[@role='button' or @jsaction]"
        )
        if toggle:
            toggle[0].click()
            time.sleep(0.8)

        rows = driver.find_elements(
            By.XPATH,
            "//*[@data-item-id='oh']//tr"
        )
        lines = []
        for row in rows:
            tds = row.find_elements(By.TAG_NAME, "td")
            if len(tds) >= 2:
                day  = tds[0].text.strip()
                slot = tds[1].text.strip()
                if day:
                    lines.append(f"{day}: {slot}")
        return " | ".join(lines) if lines else ""
    except Exception as e:
        logger.debug(f"[Selenium] Errore parse orari: {e}")
        return ""


def _parse_phone(driver) -> str:
    """Estrae il numero di telefono dalla scheda Google Maps."""
    try:
        el = driver.find_element(
            By.XPATH,
            "//button[@data-item-id[starts-with(., 'phone')]] | "
            "//a[starts-with(@href, 'tel:')]"
        )
        href = el.get_attribute("href") or ""
        if href.startswith("tel:"):
            return href.replace("tel:", "").strip()
        # fallback testo
        return el.text.strip()
    except NoSuchElementException:
        pass
    except Exception as e:
        logger.debug(f"[Selenium] Errore parse telefono: {e}")
    return ""


def _parse_website(driver) -> str:
    """Estrae il sito web dalla scheda Google Maps."""
    try:
        el = driver.find_element(
            By.XPATH,
            "//a[@data-item-id='authority'] | "
            "//a[contains(@href, 'http') and @data-tooltip='Apri il sito web']"
        )
        return (el.get_attribute("href") or "").strip()
    except NoSuchElementException:
        return ""
    except Exception as e:
        logger.debug(f"[Selenium] Errore parse website: {e}")
        return ""


def scrape_maps_url_with_selenium(
    maps_url: str,
    driver,
) -> Dict[str, str]:
    """
    Dato un URL Google Maps di una singola attivita',
    ritorna: phone, hours, website.
    Usa il driver Selenium gia' inizializzato.
    """
    result = {"phone": "", "hours": "", "website": ""}
    try:
        driver.get(maps_url)
        # Attende che la scheda carichi (presenza del titolo h1)
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.TAG_NAME, "h1"))
        )
        _accept_cookies(driver)
        time.sleep(random.uniform(1.2, 2.0))

        result["phone"]   = _parse_phone(driver)
        result["hours"]   = _parse_hours(driver)
        result["website"] = _parse_website(driver)
    except TimeoutException:
        logger.warning(f"[Selenium] Timeout caricamento: {maps_url}")
    except Exception as e:
        logger.error(f"[Selenium] Errore scraping {maps_url}: {e}")
    return result


def bulk_scrape_with_selenium(
    places: List[Dict[str, Any]],
    headless: bool = True,
    delay: float = 1.5,
) -> List[Dict[str, Any]]:
    """
    Riceve lista di dict con campo 'google_maps'.
    Per ognuno apre la pagina con Selenium e arricchisce phone/hours/website.
    Ritorna la lista aggiornata.
    """
    if not SELENIUM_AVAILABLE:
        logger.error("[Selenium] undetected_chromedriver non installato.")
        return places

    driver = None
    try:
        driver = _build_driver(headless=headless)
        for place in places:
            url = place.get("google_maps", "")
            if not url:
                continue
            logger.info(f"[Selenium] Apro: {url}")
            data = scrape_maps_url_with_selenium(url, driver)
            place["telefono"] = data["phone"] or place.get("telefono", "")
            place["orario"]   = data["hours"] or place.get("orario", "")
            # Arricchisce website per il filtro successivo
            place["_website_raw"] = data["website"]
            time.sleep(random.uniform(delay * 0.8, delay * 1.4))
    except Exception as e:
        logger.error(f"[Selenium] Errore sessione: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return places
