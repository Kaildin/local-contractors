import logging
import time
import random
import re
from typing import List, Dict, Any

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from .driver_utils import init_driver, cleanup_chrome_tmp
from .website_checker import website_is_real

logger = logging.getLogger(__name__)


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


def _get_card_urls(driver) -> list:
    cards = driver.find_elements(
        By.XPATH, "//a[contains(@href,'/maps/place/')]"
    )
    return [
        c.get_attribute("href") for c in cards
        if c.get_attribute("href") and "/maps/place/" in (c.get_attribute("href") or "")
    ]


def _parse_reviews(driver) -> int:
    try:
        el = driver.find_element(
            By.XPATH,
            "//button[contains(@aria-label,'recensioni') or contains(@aria-label,'reviews')]"
        )
        text = el.get_attribute("aria-label") or el.text
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
        logger.debug(f"[Parse] phone: {e}")
        return ""


def _parse_hours(driver) -> str:
    try:
        rows = driver.find_elements(By.XPATH, "//*[@data-item-id='oh']//tr")
        if not rows:
            try:
                toggle = driver.find_element(
                    By.XPATH, "//*[@data-item-id='oh']//*[@role='button']"
                )
                toggle.click()
                time.sleep(0.8)
                rows = driver.find_elements(By.XPATH, "//*[@data-item-id='oh']//tr")
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
        logger.debug(f"[Parse] hours: {e}")
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
        logger.debug(f"[Parse] website: {e}")
        return ""


def _parse_name(driver) -> str:
    try:
        el = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.TAG_NAME, "h1"))
        )
        return el.text.strip()
    except Exception:
        return ""


def _scrape_card(
    driver, url: str, comune: str, keyword: str,
    min_reviews: int, max_reviews: int,
    check_website_alive: bool
) -> Dict[str, Any] | None:
    try:
        driver.get(url)
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.TAG_NAME, "h1"))
        )
        _accept_cookies(driver)
        time.sleep(random.uniform(1.0, 1.8))
    except TimeoutException:
        logger.warning(f"[Scraper] Timeout: {url}")
        return None

    n_reviews = _parse_reviews(driver)
    if not (min_reviews <= n_reviews <= max_reviews):
        logger.debug(f"[Scraper] Skip recensioni ({n_reviews}): {url}")
        return None

    name    = _parse_name(driver)
    phone   = _parse_phone(driver)
    hours   = _parse_hours(driver)
    website = _parse_website(driver)

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
        "google_maps":    url,
        "sito_google":    website or "(nessuno)",
    }


def search_contractors(
    comune: str,
    keywords: List[str],
    min_reviews: int = 1,
    max_reviews: int = 15,
    check_website_alive: bool = True,
    headless: bool = True,
    scroll_times: int = 5,
) -> List[Dict[str, Any]]:
    results   = []
    seen_urls = set()

    driver = init_driver(headless=headless)
    try:
        driver.get("https://www.google.com/maps?hl=it")
        _accept_cookies(driver)
        time.sleep(1)

        for keyword in keywords:
            query      = f"{keyword} {comune}"
            search_url = (
                f"https://www.google.com/maps/search/"
                f"{query.replace(' ', '+')}?hl=it"
            )
            logger.info(f"[Scraper] Cerco: {query}")
            driver.get(search_url)
            time.sleep(random.uniform(2.0, 3.0))
            _accept_cookies(driver)
            _scroll_results(driver, times=scroll_times)

            card_urls = [
                u for u in _get_card_urls(driver)
                if u not in seen_urls
            ]
            seen_urls.update(card_urls)
            logger.info(f"[Scraper] {len(card_urls)} schede per '{query}'")

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
        cleanup_chrome_tmp()

    return results
