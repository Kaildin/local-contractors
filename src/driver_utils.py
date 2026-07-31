import logging
import os
import shutil
import subprocess
import re
import socket
import time
from typing import Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType
import undetected_chromedriver as uc

from src.resource_monitor import ChromeResourceMonitor

logger = logging.getLogger(__name__)


def _wait_driver_port_ready(driver, timeout: float = 15.0, interval: float = 0.25) -> bool:
    """Polling attivo sulla porta del servizio ChromeDriver.

    Ritorna True appena la porta accetta connessioni TCP, False se scade il timeout.
    Evita il race condition in cui Selenium invia comandi prima che ChromeDriver
    sia davvero in ascolto (errno 111 Connection refused).
    """
    port = getattr(driver.service, "port", None)
    if not port:
        logger.warning("_wait_driver_port_ready: porta non disponibile, skip polling.")
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except OSError:
            time.sleep(interval)

    logger.error(f"_wait_driver_port_ready: timeout {timeout}s sulla porta {port}.")
    return False


def _build_uc_driver(uc_options, chromium_version_int) -> webdriver.Chrome:
    """Tenta di creare un driver uc.Chrome con retry (max 3 tentativi, backoff 1.5s).

    Ogni tentativo esegue anche il polling sulla porta prima di restituire il driver.
    Solleva l'ultima eccezione se tutti i tentativi falliscono.
    """
    last_exc: Exception = RuntimeError("Nessun tentativo eseguito")
    for attempt in range(3):
        driver = None
        try:
            driver = uc.Chrome(
                options=uc_options,
                version_main=chromium_version_int if chromium_version_int else None,
                use_subprocess=True,
                suppress_welcome=True,
            )
            if not _wait_driver_port_ready(driver, timeout=15):
                raise RuntimeError(
                    f"ChromeDriver port not ready after startup (attempt {attempt + 1})"
                )
            logger.info(f"Chrome avviato con undetected_chromedriver (tentativo {attempt + 1})")
            return driver
        except Exception as e:
            last_exc = e
            logger.warning(
                f"Tentativo {attempt + 1}/3 undetected_chromedriver fallito: {e}"
            )
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
            time.sleep(1.5 * (attempt + 1))

    raise last_exc


def init_driver(
    headless: bool = True,
    lang: str = "en-US,en",
    monitor: bool = True,
    monitor_interval: float = 5.0,
    worker_label: str = "",
) -> Tuple[webdriver.Chrome, ChromeResourceMonitor]:
    """Inizializza Chrome con auto-detection della versione installata.

    Args:
        headless: avvia Chrome in modalita' headless se True.
        lang: stringa lingua da passare a --lang (es. 'en-US,en' oppure 'it-IT,it').
        monitor: se True, avvia il ChromeResourceMonitor sul driver creato.
        monitor_interval: intervallo in secondi tra i campionamenti in background.
        worker_label: etichetta opzionale mostrata nei log del monitor
            (es. 'worker-3' o il nome della citta' corrente).

    Returns:
        Tuple (driver, monitor). Se monitor=False, il secondo elemento e'
        un ChromeResourceMonitor non avviato con pid=-1 (inerte).
    """
    logger.info(f"Inizializzazione driver Chrome (headless={headless}, lang={lang})...")

    chromium_paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium-browser"),
        shutil.which("chromium"),
        # macOS paths
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
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

    driver = None
    try:
        uc_options = uc.ChromeOptions()
        if headless:
            uc_options.add_argument("--headless=new")
            uc_options.add_argument("--disable-gpu")
            uc_options.add_argument("--disable-software-rasterizer")
        else:
            uc_options.add_argument("--window-position=0,0")
        uc_options.add_argument("--no-sandbox")
        uc_options.add_argument("--disable-dev-shm-usage")
        uc_options.add_argument("--disable-extensions")
        uc_options.add_argument("--disable-logging")
        uc_options.add_argument("--log-level=3")
        uc_options.add_argument("--disable-setuid-sandbox")
        uc_options.add_argument("--disable-background-networking")
        uc_options.add_argument("--disable-backgrounding-occluded-windows")
        uc_options.add_argument("--disable-breakpad")
        uc_options.add_argument("--disable-features=TranslateUI")
        uc_options.add_argument("--disable-ipc-flooding-protection")
        uc_options.add_argument("--disable-renderer-backgrounding")
        uc_options.add_argument("--disable-sync")
        uc_options.add_argument("--mute-audio")
        uc_options.add_argument("--no-first-run")
        uc_options.add_argument(f"--lang={lang}")
        uc_options.add_argument("--window-size=1280,900")
        if chromium_binary:
            uc_options.binary_location = chromium_binary

        driver = _build_uc_driver(uc_options, chromium_version_int)

    except Exception as uc_error:
        logger.warning(f"undetected_chromedriver fallito dopo tutti i retry: {uc_error} — provo ChromeDriverManager...")

    if driver is None:
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--disable-software-rasterizer")
        else:
            chrome_options.add_argument("--window-position=0,0")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
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
        chrome_options.add_argument(f"--lang={lang}")
        chrome_options.add_argument("--window-size=1280,900")
        chrome_options.add_argument(
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        if chromium_binary:
            chrome_options.binary_location = chromium_binary

        is_chromium = "chromium" in (chromium_binary or "").lower()
        service = webdriver.ChromeService(
            ChromeDriverManager(
                chrome_type=ChromeType.CHROMIUM if is_chromium else ChromeType.GOOGLE,
                driver_version=str(chromium_version_int) if chromium_version_int else None,
            ).install()
        )
        driver = webdriver.Chrome(service=service, options=chrome_options)
        # Polling porta anche sul fallback ChromeDriverManager
        if not _wait_driver_port_ready(driver, timeout=15):
            try:
                driver.quit()
            except Exception:
                pass
            raise RuntimeError("ChromeDriver (fallback) port not ready after startup")
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        logger.info("Chrome avviato con ChromeDriverManager")

    # --- Resource monitor ---------------------------------------------------
    try:
        driver_pid = driver.service.process.pid
        mon = ChromeResourceMonitor(
            driver_pid=driver_pid,
            sample_interval=monitor_interval,
            worker_label=worker_label,
        )
        if monitor:
            mon.start()
            # Snapshot iniziale (attende ~0.5 s per la CPU)
            snap = mon.snapshot()
            if snap:
                logger.info(
                    f"[ResourceMonitor] Driver avviato — {snap} "
                    f"(label={worker_label or 'n/a'})"
                )
    except Exception as e:
        logger.warning(f"[ResourceMonitor] Impossibile avviare il monitor: {e}")
        # Crea un monitor inerte per non rompere il return type
        mon = _NullMonitor()  # type: ignore[assignment]

    return driver, mon


class _NullMonitor:
    """Drop-in replacement when monitoring is unavailable or disabled."""

    def start(self) -> "_NullMonitor":
        return self

    def stop(self) -> None:
        pass

    def snapshot(self):
        return None

    def last_snapshot(self):
        return None

    def peak_ram_mb(self) -> float:
        return 0.0

    def log_stats(self, level: int = logging.INFO) -> None:
        pass


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
