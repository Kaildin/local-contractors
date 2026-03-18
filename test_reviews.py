import logging
import time
from src.driver_utils import init_driver
from src.selenium_scraper import _extract_num_recensioni
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logging.basicConfig(level=logging.INFO)

def test_reviews():
    driver = init_driver(headless=True)
    try:
        # Naviga a Google Maps principale
        driver.get("https://www.google.com/maps?hl=it")
        time.sleep(4)
        
        cookie_selectors = [
            (By.ID, "L2AGLb"),
            (By.CSS_SELECTOR, ".tHlp8d"),
            (By.XPATH, "//button[contains(., 'Accetta tutto')]"),
            (By.XPATH, "//button[contains(., 'Accept all')]")
        ]
        for sel_type, sel in cookie_selectors:
            try:
                consent = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((sel_type, sel)))
                driver.execute_script("arguments[0].click();", consent)
                print("Cookies accepted")
                break
            except Exception as e:
                pass
                
        time.sleep(2)
        
        # Cerca il locale
        print("Searching for place...")
        search_box_selectors = ["input#searchboxinput", "input[name='q']"]
        search_box = None
        for sel in search_box_selectors:
            try:
                search_box = WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                break
            except:
                pass
                
        if search_box:
            search_box.send_keys("L'Antica Pizzeria da Michele Napoli")
            search_box.submit()
            # In alternativa: driver.find_element(By.ID, "searchbox-searchbutton").click()
            time.sleep(6)
            
        driver.save_screenshot("debug_screen_2.png")
        with open("page_source.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)

        try:
            print("TITLE:", driver.find_element(By.CSS_SELECTOR, "h1").text)
        except Exception:
            pass

        print("EXTRACTION RESULT:", _extract_num_recensioni(driver))
    finally:
        driver.quit()

if __name__ == "__main__":
    test_reviews()
