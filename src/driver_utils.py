import logging
import os
import shutil
import subprocess
import re

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType
import undetected_chromedriver as uc

logger = logging.getLogger(__name__)


def init_driver(headless: bool = True):
    """Inizializza Chrome con auto-detection della versione installata.
    Identico alla logica di AutReach (driver_utils.py).
    """
    logger.info(f"Inizializzazione driver Chrome (headless={headless})...")

    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.add_argument("--disable-setuid-sandbox")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-backgrounding-occluded-windows")
    chrome_options.add_argument("--disable-breakpad")
    chrome_options.add_argument("--disable-features=TranslateUI")
    chrome_options.add_argument("--disable-ipc-flooding-protection")
    chrome_options.add_argument("--disable-renderer-backgrounding")
    chrome_options.add_argument("--disable-sync")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--lang=it-IT,it")
    chrome_options.add_argument("--window-size=1280,900")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # --- Auto-detect percorso e versione Chrome/Chromium ---
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
            logger.info(f"Trovato browser in: {chromium_binary}")
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
                    logger.info(f"Versione Chrome rilevata: {chromium_version_int}")
        except Exception as e:
            logger.warning(f"Impossibile rilevare versione Chrome: {e}")

        chrome_options.binary_location = chromium_binary

    # --- Tentativo 1: undetected_chromedriver con version_main forzata ---
    try:
        uc_options = Options()
        if headless:
            uc_options.add_argument("--headless=new")
        uc_options.add_argument("--no-sandbox")
        uc_options.add_argument("--disable-dev-shm-usage")
        uc_options.add_argument("--disable-gpu")
        uc_options.add_argument("--lang=it-IT,it")
        uc_options.add_argument("--window-size=1280,900")
        uc_options.add_argument("--disable-blink-features=AutomationControlled")
        if chromium_binary:
            uc_options.binary_location = chromium_binary

        driver = uc.Chrome(
            options=uc_options,
            version_main=chromium_version_int if chromium_version_int else None,
            use_subprocess=True,
        )
        logger.info("Chrome avviato con undetected_chromedriver")
        return driver
    except Exception as uc_error:
        logger.warning(f"undetected_chromedriver fallito: {uc_error} — provo ChromeDriverManager...")

    # --- Tentativo 2: ChromeDriverManager standard ---
    is_chromium = "chromium" in (chromium_binary or "").lower()
    service = webdriver.ChromeService(
        ChromeDriverManager(
            chrome_type=ChromeType.CHROMIUM if is_chromium else ChromeType.GOOGLE,
        ).install()
    )
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    logger.info("Chrome avviato con ChromeDriverManager")
    return driver


def cleanup_chrome_tmp():
    """Pulisce directory temporanee lasciate da Chrome/Selenium."""
    import glob
    patterns = [
        "/tmp/.org.chromium.Chromium.*",
        "/tmp/.com.google.Chrome.*",
        "/tmp/scoped_dir*",
        "/tmp/undetected_chromedriver*",
    ]
    count = 0
    for pattern in patterns:
        for path in glob.glob(pattern):
            try:
                shutil.rmtree(path, ignore_errors=True) if os.path.isdir(path) else os.remove(path)
                count += 1
            except Exception:
                pass
    if count:
        logger.info(f"Pulizia: rimossi {count} file/dir temporanei Chrome")
