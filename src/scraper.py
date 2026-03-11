import logging
import time
import random
from typing import List, Dict, Any

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from .website_checker import website_is_real
from .niches import NICHES

logger = logging.getLogger(__name__)


def _build_driver(headless: bool = True) -> uc.Chrome:
    opts = uc.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--lang=it-IT,it")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    return uc.Chrome(options=opts, use_subprocess=True)


def _accept_cookies(driver):
    try:
        btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//button[contains(., 'Accetta tutto') "
                "or contains(., 'Accept all') "
                "or contains(., 'Rifiuta tutto')]"
            ))
        )
        btn.click()
        time.sleep(0.8)
    except Exception:
        pass


def _scroll_results(driver, times: int = 5):
    """Scrolla il pannello risultati per caricare piu' schede."""
    try:
        panel = driver.find_element(
            By.XPATH,
            "//div[@role='feed'] | //div[contains(@aria-label,'Risultati')]"
        )
        for _ in range(times):
            driver.execute_script("arguments[0].scrollTop += 2000", panel)
            time.sleep(random.uniform(1.0, 1.8))
    except Exception:
        pass


def _get_listing_cards(driver) -> list:
    """Ritorna gli elementi <a> che rappresentano le singole attivita' nei risultati."""
    return driver.find_elements(
        By.XPATH,
        "//a[contains(@href,'/maps/place/')]"
    )


def _parse_reviews(driver) -> int:
    """Estrae il numero di recensioni dalla scheda attivita' aperta."""
    try:
        el = driver.find_element(
            By.XPATH,
            "//button[contains(@aria-label,'recensioni') or contains(@aria-label,'reviews')]"
        )
        text = el.get_attribute("aria-label") or el.text
        # es. '12 recensioni' o '(12)'
        import re
        nums = re.findall(r'\d+', text.replace(".", "").replace(",", ""))
        return int(nums[0]) if nums else 0
    except Exception:
        return 0


def _parse_phone(driver) -> str:
    try:
        el = driver.find_element(
            By.XPATH,
            "//a[starts-with(@href,'tel:')] | "
            "//button[@data-item-id[starts-with(.,'phone')]]"
        )
        href = el.get_attribute("href") or ""
        if href.startswith("tel:"):
            return href.replace("tel:", "").strip()
        return el.text.strip()
    except NoSuchElementException:
        return ""
    except Exception as e:
        logger.debug(f"[Parse] phone error: {e}")
        return ""


def _parse_hours(driver) -> str:
    try:
        rows = driver.find_elements(
            By.XPATH, "//*[@data-item-id='oh']//tr"
        )
        if not rows:
            # prova ad aprire il toggle
            try:
                toggle = driver.find_element(
                    By.XPATH, "//*[@data-item-id='oh']//*[@role='button']"
                )
                toggle.click()
                time.sleep(0.8)
                rows = driver.find_elements(
                    By.XPATH, "//*[@data-item-id='oh']//tr"
                )
            except Exception:
                pass
        lines = []
        for row in rows:
            tds = row.find_elements(By.TAG_NAME, "td")
            if len(tds) >= 2:
                day  = tds[0].text.strip()
                slot = tds[1].text.strip()
                if day:
                    lines.append(f"{day}: {slot}")
        return " | ".join(lines)
    except Exception as e:
        logger.debug(f"[Parse] hours error: {e}")
        return ""


def _parse_website(driver) -> str:
    try:
        el = driver.find_element(
            By.XPATH,
            "//a[@data-item-id='authority'] | "
            "//a[@data-tooltip='Apri il sito web'] | "
            "//a[contains(@aria-label,'Sito web')]"
        )
        return (el.get_attribute("href") or "").strip()
    except NoSuchElementException:
        return ""
    except Exception as e:
        logger.debug(f"[Parse] website error: {e}")
        return ""


def _parse_name(driver) -> str:
    try:
        el = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.TAG_NAME, "h1"))
        )
        return el.text.strip()
    except Exception:
        return ""


def _scrape_card(driver, card_url: str, comune: str, keyword: str,
                 min_reviews: int, max_reviews: int,
                 check_website_alive: bool) -> Dict[str, Any] | None:
    """
    Apre la scheda di una singola attivita' e ne estrae i dati.
    Ritorna None se non soddisfa i criteri.
    """
    try:
        driver.get(card_url)
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.TAG_NAME, "h1"))
        )
        _accept_cookies(driver)
        time.sleep(random.uniform(1.0, 1.8))
    except TimeoutException:
        logger.warning(f"[Scraper] Timeout apertura scheda: {card_url}")
        return None

    # Filtro recensioni
    n_reviews = _parse_reviews(driver)
    if not (min_reviews <= n_reviews <= max_reviews):
        logger.debug(f"[Scraper] Skip per recensioni ({n_reviews}): {card_url}")
        return None

    # Dati principali
    name    = _parse_name(driver)
    phone   = _parse_phone(driver)
    hours   = _parse_hours(driver)
    website = _parse_website(driver)

    # Filtro sito reale
    if website_is_real(website, check_alive=check_website_alive):
        logger.info(f"[Scraper] Skip sito reale '{name}': {website}")
        return None

    return {
        "nome":           name,
        "comune":         comune,
        "keyword":        keyword,
        "telefono":       phone,
        "orario":         hours,
        "num_recensioni": n_reviews,
        "google_maps":    card_url,
        "sito_google":    website or "(nessuno)",
    }


def search_contractors(
    comune: str,
    keywords: List[str],
    min_reviews: int = 1,
    max_reviews: int = 15,
    radius_label: str = "",
    check_website_alive: bool = True,
    headless: bool = True,
    scroll_times: int = 5,
) -> List[Dict[str, Any]]:
    """
    Cerca artigiani su Google Maps tramite Selenium.
    Per ogni keyword cerca '<keyword> <comune>' su maps.google.com,
    scrolla i risultati, apre ogni scheda e applica i filtri.
    """
    results  = []
    seen_urls = set()

    driver = _build_driver(headless=headless)
    try:
        # Prima apertura: accetta cookie una volta sola
        driver.get("https://www.google.com/maps?hl=it")
        _accept_cookies(driver)
        time.sleep(1)

        for keyword in keywords:
            query = f"{keyword} {comune}"
            search_url = (
                f"https://www.google.com/maps/search/"
                f"{query.replace(' ', '+')}"
                f"?hl=it"
            )
            logger.info(f"[Scraper] Cerco: {query}")
            driver.get(search_url)
            time.sleep(random.uniform(2.0, 3.0))
            _accept_cookies(driver)

            # Scrolla per caricare piu' risultati
            _scroll_results(driver, times=scroll_times)

            # Raccoglie tutti gli URL delle schede
            cards = _get_listing_cards(driver)
            card_urls = []
            for c in cards:
                href = c.get_attribute("href") or ""
                if "/maps/place/" in href and href not in seen_urls:
                    card_urls.append(href)
                    seen_urls.add(href)

            logger.info(f"[Scraper] Trovate {len(card_urls)} schede per '{query}'")

            for url in card_urls:
                data = _scrape_card(
                    driver, url, comune, keyword,
                    min_reviews, max_reviews, check_website_alive
                )
                if data:
                    results.append(data)
                time.sleep(random.uniform(0.8, 1.5))

    except Exception as e:
        logger.error(f"[Scraper] Errore sessione: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return results
