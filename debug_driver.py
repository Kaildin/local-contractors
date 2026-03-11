import logging
from src.driver_utils import init_driver, cleanup_chrome_tmp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

print("Avvio Chrome (headless=False) per test driver...")
driver = None
try:
    driver = init_driver(headless=False)
    driver.get("https://www.google.com/maps?hl=it")
    print("Chrome aperto su Google Maps. Premi INVIO per chiudere...")
    input()
finally:
    if driver:
        driver.quit()
    cleanup_chrome_tmp()
    print("Driver chiuso e cleanup completato.")
