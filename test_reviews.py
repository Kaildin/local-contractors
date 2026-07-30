import logging
import time
from src.driver_utils import init_driver
from src.selenium_scraper import _navigate_to_place, _extract_num_recensioni

logging.basicConfig(level=logging.INFO)

# Place da testare
TEST_NAME = "L'Antica Pizzeria da Michele"
TEST_PLACE_HREF = "https://www.google.com/maps/place/L'Antica+Pizzeria+da+Michele/@40.8497672,14.260846,17z"
TEST_LANG = "it"


def test_reviews():
    driver, mon = init_driver(headless=True)
    try:
        print(f"\nTest: '{TEST_NAME}'")
        print("Navigazione via Google Search SERP (bypass limited view)...")

        _navigate_to_place(driver, TEST_NAME, TEST_PLACE_HREF, lang=TEST_LANG)

        print(f"URL finale: {driver.current_url}")

        driver.save_screenshot("debug_screen_2.png")
        with open("page_source.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)

        # Attendi un po' per rendering
        time.sleep(3)

        num = _extract_num_recensioni(driver)
        print(f"\nRISULTATO: {num} recensioni")
        assert num > 0, f"FAIL: recensioni = {num}, atteso > 0"
        print("PASS")

    finally:
        if mon:
            mon.stop()
        driver.quit()


if __name__ == "__main__":
    test_reviews()
