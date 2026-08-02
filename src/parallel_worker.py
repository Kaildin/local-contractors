"""
src/parallel_worker.py

Worker function designed to run inside a *separate OS process*.
Each worker owns its own Chrome / WebDriver instance, which is the
only safe way to parallelise Selenium (no shared driver, no threads
talking to the same browser, no GIL contention).

Usage: called internally by run_batch.py when --workers > 1.
Do NOT import this module at the top level of run_batch.py;
the import happens inside the worker function to avoid forking
already-initialised Chrome handles.

NOTE: In parallel mode, we use webdriver.Chrome + ChromeDriverManager directly
instead of undetected_chromedriver to avoid issues with subprocess inheritance
and remote debugging ports that cause 'Connection refused' errors.
"""

from __future__ import annotations

import logging
import signal
import time
import traceback
import platform
import os
import shutil
import subprocess
import re
from typing import Any, Dict, List, Optional, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

logger = logging.getLogger(__name__)

# Flag usato dall'handler SIGTERM per interrompere il loop delle citta'
_STOP_REQUESTED = False


def _handle_sigterm(signum, frame):
    """Setta il flag di stop quando il processo riceve SIGTERM o SIGINT."""
    global _STOP_REQUESTED
    _STOP_REQUESTED = True
    logger.warning("[Worker] SIGTERM/SIGINT ricevuto — stop al prossimo ciclo")


# ---------------------------------------------------------------------------
# Worker-specific driver init (no undetected_chromedriver)
# ---------------------------------------------------------------------------

_IS_LINUX = platform.system() == "Linux"

_MACOS_SPOOF_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _apply_headless_flags_worker(options, is_linux: bool) -> None:
    """Applica i flag headless corretti per i worker paralleli."""
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    if is_linux:
        options.add_argument("--use-gl=swiftshader")
        options.add_argument("--run-all-compositor-stages-before-draw")
        options.add_argument("--force-device-scale-factor=1")


def _init_worker_driver(
    headless: bool = True,
    lang: str = "en-US,en",
    worker_label: str = "",
) -> Tuple[webdriver.Chrome, Any]:
    """
    Inizializza Chrome per i worker paralleli usando SOLO ChromeDriverManager.

    Questo evita i problemi di undetected_chromedriver con:
    - Subprocess inheritance in ProcessPoolExecutor
    - Remote debugging ports che causano 'Connection refused'
    - Patch del binario che causa race conditions

    Returns:
        Tuple (driver, None) - il monitor non e' disponibile in questa modalita'
    """
    logger.info(
        f"[WorkerDriver] Inizializzazione driver Chrome per worker "
        f"(headless={headless}, lang={lang}, label={worker_label})"
    )

    chromium_paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium-browser"),
        shutil.which("chromium"),
    ]
    chromium_binary = None
    for path in chromium_paths:
        if path and os.path.exists(path):
            chromium_binary = path
            logger.info(f"[WorkerDriver] Trovato browser in: {chromium_binary}")
            break

    chromium_version_int = None
    if chromium_binary:
        try:
            result = subprocess.run(
                [chromium_binary, "--version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                match = re.search(r'(\d+)\.\d+\.\d+\.\d+', result.stdout)
                if match:
                    chromium_version_int = int(match.group(1))
                    logger.info(f"[WorkerDriver] Versione Chrome rilevata: {chromium_version_int}")
        except Exception as e:
            logger.warning(f"[WorkerDriver] Impossibile rilevare versione Chrome: {e}")

    spoof_ua = _MACOS_SPOOF_UA if (_IS_LINUX and headless) else None

    _WORKER_FLAGS = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-logging",
        "--log-level=3",
        "--disable-setuid-sandbox",
        "--disable-background-networking",
        "--disable-backgrounding-occluded-windows",
        "--disable-breakpad",
        "--disable-features=TranslateUI",
        "--disable-ipc-flooding-protection",
        "--disable-renderer-backgrounding",
        "--disable-sync",
        "--mute-audio",
        "--no-first-run",
        "--window-size=1920,1080",
        f"--lang={lang}",
        "--disable-blink-features=AutomationControlled",
        "--exclude-switches=enable-automation",
        "--remote-debugging-port=0",
        "--disable-remote-debugging",
    ]
    if spoof_ua:
        _WORKER_FLAGS.append(f"--user-agent={spoof_ua}")
        logger.info("[WorkerDriver] Linux headless — UA impostato a macOS Chrome126")

    chrome_options = Options()
    if headless:
        _apply_headless_flags_worker(chrome_options, _IS_LINUX)
    else:
        chrome_options.add_argument("--window-position=0,0")

    for flag in _WORKER_FLAGS:
        chrome_options.add_argument(flag)

    if chromium_binary:
        chrome_options.binary_location = chromium_binary

    is_chromium = "chromium" in (chromium_binary or "").lower()
    service = Service(
        ChromeDriverManager(
            chrome_type=ChromeType.CHROMIUM if is_chromium else ChromeType.GOOGLE,
            driver_version=str(chromium_version_int) if chromium_version_int else None,
        ).install()
    )

    driver = webdriver.Chrome(service=service, options=chrome_options)
    logger.info("[WorkerDriver] Chrome avviato con ChromeDriverManager")

    # Patch navigator.webdriver via CDP
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'platform', {get: () => 'MacIntel'});
            """
        })
        logger.info("[WorkerDriver] navigator.webdriver + platform patch applicata")
    except Exception as e:
        logger.warning(f"[WorkerDriver] Patch navigator fallita: {e}")

    return driver, None  # No monitor in worker mode


def worker_scrape_cities(
    city_entries: List[Dict[str, Any]],
    keywords: List[str],
    *,
    lang: str = "en",
    headless: bool = True,
    scroll_times: int = 30,
    min_reviews: int = 1,
    max_reviews: int = 100,
    check_website_alive: bool = True,
    debug_screenshot: bool = False,
    output_csv: Optional[str] = None,
    worker_id: int = 0,
) -> List[Dict[str, Any]]:
    """
    Process a list of city entries serially, each with its own fresh driver.

    Il worker passa driver_factory=_make_worker_driver a scrape_with_selenium
    in modo che TUTTE le ricreazioni del driver (riciclo periodico, recovery
    da crash, _safe_get, _navigate_to_place) usino _init_worker_driver invece
    di init_driver seriale (che usa undetected_chromedriver e causa
    'Connection refused' dentro ProcessPoolExecutor).
    """
    global _STOP_REQUESTED
    _STOP_REQUESTED = False

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    from src.scraper import get_max_results  # noqa: PLC0415
    from src.selenium_scraper import scrape_with_selenium
    from src.website_checker import get_website_status, website_is_real
    from src.text_utils import clean_extracted_text
    from src.niches import NICHES
    import csv
    import json
    from pathlib import Path

    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [W{worker_id}][%(levelname)s] %(name)s: %(message)s",
    )

    # Stagger startup
    stagger_secs = worker_id * 2
    if stagger_secs > 0:
        logger.info(f"[W{worker_id}] Startup stagger: attendo {stagger_secs}s...")
        time.sleep(stagger_secs)

    # ---------------------------------------------------------------------------
    # Factory per questo worker: usa SEMPRE _init_worker_driver (ChromeDriverManager
    # puro, senza undetected_chromedriver). Viene passata a scrape_with_selenium
    # come driver_factory cosi tutti i restart/recycle usano il driver corretto.
    # ---------------------------------------------------------------------------
    _captured_headless = headless
    _captured_lang = lang
    _captured_worker_id = worker_id

    def _make_worker_driver(label: str = "") -> webdriver.Chrome:
        """Factory che crea un nuovo driver worker-safe (senza ucd)."""
        logger.info(f"[W{_captured_worker_id}] Creazione nuovo driver worker (label={label})")
        driver, _ = _init_worker_driver(
            headless=_captured_headless,
            lang=_captured_lang,
            worker_label=label or f"W{_captured_worker_id}",
        )
        return driver

    all_results: List[Dict[str, Any]] = []
    driver = None

    try:
        # Inizializza driver una volta per questo worker
        driver, _ = _init_worker_driver(
            headless=headless,
            lang=lang,
            worker_label=f"W{worker_id}",
        )

        for entry in city_entries:
            if _STOP_REQUESTED:
                logger.warning(f"[W{worker_id}] Stop richiesto — esco dal loop citta'")
                break

            city = entry["city"]
            state = entry["state"]
            population = entry["population"]
            max_results = get_max_results(population, lang=lang)

            logger.info(f"[W{worker_id}] Scraping '{city}' ({state}) – max_results={max_results}")

            if _STOP_REQUESTED:
                logger.warning(f"[W{worker_id}] Stop richiesto prima di {city} — interrompo")
                break

            try:
                from src.scraper import build_search_urls
                search_urls = build_search_urls([city], keywords, lang=lang, state=state)

                # Passa driver_factory=_make_worker_driver: ogni volta che
                # scrape_with_selenium deve ricreare il driver (riciclo, crash,
                # _safe_get, _navigate_to_place) usa ChromeDriverManager puro
                # invece di undetected_chromedriver.
                results_raw, driver, _ = scrape_with_selenium(
                    search_urls,
                    driver=driver,
                    max_results=max_results,
                    scroll_times=scroll_times,
                    headless=headless,
                    debug_screenshot=debug_screenshot,
                    driver_factory=_make_worker_driver,
                )

                from src.scraper import CSV_FIELDNAMES, _load_already_scraped, _append_lead_to_csv

                already_seen: set = set()
                if output_csv:
                    already_seen = _load_already_scraped(output_csv)

                filtered = []
                for r in results_raw:
                    nome = (r.get("nome") or "").strip()
                    city_r = (r.get("comune") or "").strip()

                    key = (nome.lower(), city_r.lower())
                    if key in already_seen:
                        logger.info(f"[Resume] Gia' presente, saltato: {nome}")
                        continue

                    n = r.get("num_recensioni") or 0
                    try:
                        n = int(n)
                    except Exception:
                        n = 0
                    if n and not (min_reviews <= n <= max_reviews):
                        logger.info(f"[Filter] Scartato '{nome}' - recensioni fuori range: {n}")
                        continue

                    website = (r.get("sito_web") or "").strip()

                    if website and not website_is_real(website, check_alive=False):
                        status = {
                            "ok": False,
                            "status_code": None,
                            "final_url": website,
                            "reason": "social_or_builder",
                        }
                    else:
                        status = get_website_status(website) if (website and check_website_alive) else {
                            "ok": bool(website),
                            "status_code": None,
                            "final_url": website,
                            "reason": "not_checked" if website else "empty_url",
                        }

                    r["ha_sito_web"] = status["ok"]
                    r["website_status_code"] = status["status_code"]
                    r["website_check_reason"] = status["reason"]

                    r["city"] = city_r
                    r["state"] = state or ""

                    if not r.get("maps_url"):
                        suffix = f"+{state}" if state else ""
                        r["maps_url"] = (
                            f"https://www.google.com/maps/search/"
                            f"{nome.replace(' ', '+')}+{city_r.replace(' ', '+')}{suffix}"
                            f"?hl={lang}"
                        )

                    filtered.append(r)
                    already_seen.add(key)

                    if output_csv:
                        _append_lead_to_csv(output_csv, r)
                        logger.info(f"[Salvataggio] Lead salvato: {nome} (ha_sito_web={status['ok']}, reason={status['reason']})")

                logger.info(f"[W{worker_id}] '{city}' -> {len(filtered)} lead")
                all_results.extend(filtered)
            except Exception:
                logger.error(
                    f"[W{worker_id}] Errore su '{city}': {traceback.format_exc()}"
                )

    finally:
        if driver:
            try:
                driver.quit()
                logger.info(f"[W{worker_id}] Driver chiuso")
            except Exception as e:
                logger.warning(f"[W{worker_id}] Errore chiusura driver: {e}")

        try:
            import glob
            patterns = [
                "/tmp/.org.chromium.Chromium.*",
                "/tmp/.com.google.Chrome.*",
                "/tmp/scoped_dir*",
                "/tmp/undetected_chromedriver*",
            ]
            for pattern in patterns:
                for path in glob.glob(pattern):
                    try:
                        shutil.rmtree(path, ignore_errors=True) if os.path.isdir(path) else os.remove(path)
                    except Exception:
                        pass
        except Exception:
            pass

    return all_results
