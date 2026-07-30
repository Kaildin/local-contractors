import logging
import os
import platform
import shutil
import subprocess
import re
import time
from pathlib import Path
from typing import Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType
import undetected_chromedriver as uc

try:
    import filelock as _filelock_mod
    _FILELOCK_AVAILABLE = True
except ImportError:
    _FILELOCK_AVAILABLE = False

from src.resource_monitor import ChromeResourceMonitor

logger = logging.getLogger(__name__)

_IS_LINUX = platform.system() == "Linux"

# Lock file path used to serialise undetected_chromedriver patching.
# Multiple parallel workers all patch the same binary; without a lock
# they corrupt each other's write and the ChromeDriver crashes with
# 'Connection refused' immediately after startup.
_UCD_LOCK_PATH = Path.home() / ".local" / "share" / "undetected_chromedriver" / "init.lock"

# Realistic macOS Chrome UA used on Linux headless to avoid GMaps bot-detection.
_MACOS_SPOOF_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _apply_headless_flags(options, is_linux: bool) -> None:
    """
    Applica i flag headless corretti in base alla piattaforma.

    macOS / Windows
    ---------------
    --headless=new e' sufficiente; il GPU backend nativo (Metal / ANGLE)
    gestisce il rendering anche senza display.

    Linux
    -----
    Chrome non ha GPU hardware disponibile, quindi:
    - --use-gl=swiftshader  abilita il renderer software (SwiftShader)
      in modo esplicito, senza disabilitarlo come faceva
      --disable-software-rasterizer.
    - --disable-gpu e' ancora necessario per evitare che Chrome tenti
      di usare un GPU driver assente e vada in crash.
    - --run-all-compositor-stages-before-draw assicura che il DOM sia
      completamente dipinto prima che Selenium legga page_source o
      cerchi elementi — critico per Google Maps che e' una SPA
      WebGL/canvas.
    - --force-device-scale-factor=1 normalizza il DPI virtuale
      (su macOS e' 2x per Retina, su Linux headless e' variabile).

    NOTE: --disable-features=VizDisplayCompositor is intentionally NOT used.
    VizDisplayCompositor is the process that composites the DOM after
    SwiftShader renders it. Disabling it prevents Google Maps from
    populating aria-label attributes on review elements, causing
    _extract_num_recensioni to always return 0 on Linux headless.
    """
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")

    if is_linux:
        options.add_argument("--use-gl=swiftshader")
        options.add_argument("--run-all-compositor-stages-before-draw")
        options.add_argument("--force-device-scale-factor=1")
    # NOTE: --disable-software-rasterizer is intentionally NOT added.


def init_driver(
    headless: bool = True,
    lang: str = "en-US,en",
    monitor: bool = True,
    monitor_interval: float = 5.0,
    worker_label: str = "",
) -> Tuple[webdriver.Chrome, "ChromeResourceMonitor"]:
    """Inizializza Chrome con auto-detection della versione installata.

    La chiamata a uc.Chrome() e' protetta da un FileLock su Linux per
    evitare la race condition in cui piu' worker paralleli tentano di
    patchare lo stesso binario undetected_chromedriver simultaneamente,
    provocando 'Connection refused' immediato su tutti i driver tranne
    il primo.

    Args:
        headless: avvia Chrome in modalita' headless se True.
        lang: stringa lingua da passare a --lang.
        monitor: se True, avvia il ChromeResourceMonitor sul driver creato.
        monitor_interval: intervallo in secondi tra i campionamenti.
        worker_label: etichetta opzionale nei log del monitor.

    Returns:
        Tuple (driver, monitor).
    """
    logger.info(
        f"Inizializzazione driver Chrome "
        f"(headless={headless}, lang={lang}, platform={platform.system()})..."
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

    _spoof_ua = _MACOS_SPOOF_UA if (_IS_LINUX and headless) else None

    _COMMON_FLAGS = [
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
    ]
    if _spoof_ua:
        _COMMON_FLAGS.append(f"--user-agent={_spoof_ua}")
        logger.info("[UA Spoof] Linux headless — UA impostato a macOS Chrome126")

    driver = None
    try:
        uc_options = uc.ChromeOptions()
        if headless:
            _apply_headless_flags(uc_options, _IS_LINUX)
        else:
            uc_options.add_argument("--window-position=0,0")
        for flag in _COMMON_FLAGS:
            uc_options.add_argument(flag)
        if chromium_binary:
            uc_options.binary_location = chromium_binary

        # --- FileLock: serialise uc patching across parallel workers ----------
        # undetected_chromedriver writes to a single shared binary file during
        # patching. Concurrent workers race on that write, the losers get a
        # corrupted binary and immediately hit 'Connection refused'.
        # We hold the lock only for the uc.Chrome() constructor call (the
        # actual patch + process launch), then release it so other workers
        # can proceed while this worker is already running.
        if _FILELOCK_AVAILABLE:
            _UCD_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
            lock = _filelock_mod.FileLock(str(_UCD_LOCK_PATH), timeout=120)
            with lock:
                logger.debug("[UCDLock] Lock acquisito — avvio uc.Chrome()")
                driver = uc.Chrome(
                    options=uc_options,
                    version_main=chromium_version_int if chromium_version_int else None,
                    use_subprocess=True,
                    suppress_welcome=True,
                )
            logger.debug("[UCDLock] Lock rilasciato")
        else:
            # filelock not installed: fall back to unprotected init
            # (install with: pip install filelock)
            logger.warning(
                "[UCDLock] filelock non installato — init uc.Chrome() non serializzato. "
                "Installa con: pip install filelock"
            )
            driver = uc.Chrome(
                options=uc_options,
                version_main=chromium_version_int if chromium_version_int else None,
                use_subprocess=True,
                suppress_welcome=True,
            )
        logger.info("Chrome avviato con undetected_chromedriver")
    except Exception as uc_error:
        logger.warning(f"undetected_chromedriver fallito: {uc_error} — provo ChromeDriverManager...")

    if driver is None:
        chrome_options = Options()
        if headless:
            _apply_headless_flags(chrome_options, _IS_LINUX)
        else:
            chrome_options.add_argument("--window-position=0,0")
        for flag in _COMMON_FLAGS:
            chrome_options.add_argument(flag)
        chrome_options.add_argument("--remote-debugging-port=9222")
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
        logger.info("Chrome avviato con ChromeDriverManager")

    # Patch navigator.webdriver via CDP
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'platform', {get: () => 'MacIntel'});
            """
        })
        logger.info("[CDP] navigator.webdriver + platform patch applicata")
    except Exception as e:
        logger.warning(f"[CDP] Patch navigator fallita: {e}")

    # --- Resource monitor ---------------------------------------------------
    mon: "ChromeResourceMonitor"
    try:
        driver_pid = driver.service.process.pid
        mon = ChromeResourceMonitor(
            driver_pid=driver_pid,
            sample_interval=monitor_interval,
            worker_label=worker_label,
        )
        if monitor:
            mon.start()
            snap = mon.snapshot()
            if snap:
                logger.info(
                    f"[ResourceMonitor] Driver avviato — {snap} "
                    f"(label={worker_label or 'n/a'})"
                )
    except Exception as e:
        logger.warning(f"[ResourceMonitor] Impossibile avviare il monitor: {e}")
        mon = _NullMonitor()  # type: ignore[assignment]

    return driver, mon


def quit_driver(driver, mon=None, label: str = "") -> None:
    """Chiude driver + monitor in modo sicuro, killando i processi figli.

    Chiama driver.quit() per mandare il segnale di shutdown a Chrome,
    poi killa esplicitamente il processo ChromeDriver e i suoi figli
    tramite psutil per garantire che nessun processo orfano rimanga in
    memoria dopo uno stop forzato o un'eccezione.

    Args:
        driver: istanza webdriver.Chrome da chiudere.
        mon: ChromeResourceMonitor opzionale da stoppare prima del quit.
        label: etichetta per il log (es. nome citta').
    """
    tag = f"[{label}] " if label else ""

    # 1. Stoppa il monitor di risorse
    if mon is not None:
        try:
            mon.stop()
        except Exception:
            pass

    if driver is None:
        return

    # 2. Prova quit() pulito
    try:
        driver.quit()
        logger.debug(f"{tag}driver.quit() completato")
    except Exception as e:
        logger.warning(f"{tag}driver.quit() fallito: {e}")

    # 3. Kill esplicito del processo ChromeDriver + figli tramite psutil
    try:
        import psutil
        try:
            pid = driver.service.process.pid
        except Exception:
            return
        try:
            proc = psutil.Process(pid)
            children = proc.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            proc.kill()
            logger.debug(f"{tag}Processo ChromeDriver PID={pid} killato")
        except psutil.NoSuchProcess:
            pass  # gia' morto, va bene
        except Exception as e:
            logger.warning(f"{tag}Kill ChromeDriver fallito: {e}")
    except ImportError:
        logger.debug(f"{tag}psutil non disponibile — skip kill esplicito")


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
