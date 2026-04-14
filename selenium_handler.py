import os
import time
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

logger = logging.getLogger(__name__)

LOGIN_URL    = "https://login.emaktab.uz/"
SITE_URL     = "https://emaktab.uz"
WAIT_TIMEOUT = 20
ACTIVE_WAIT  = 3


def _make_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,800")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(30)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def _do_logout(driver: webdriver.Chrome):
    try:
        driver.delete_all_cookies()
        driver.execute_script("localStorage.clear(); sessionStorage.clear();")
    except Exception as e:
        logger.warning(f"Logout xato: {e}")


def _login_and_wait(driver: webdriver.Chrome, login: str, password: str) -> bool:
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    try:
        logger.info(f"[{login}] Kirish boshlandi")
        driver.get(LOGIN_URL)

        # Wait for login field
        login_field = wait.until(EC.presence_of_element_located((By.NAME, "login")))

        # Fill credentials
        login_field.clear()
        login_field.send_keys(login)

        pwd_field = driver.find_element(By.NAME, "password")
        pwd_field.clear()
        pwd_field.send_keys(password)

        # Submit
        try:
            submit = driver.find_element(By.NAME, "submit")
        except NoSuchElementException:
            submit = driver.find_element(
                By.CSS_SELECTOR, "button[type='submit'], input[type='submit']"
            )
        submit.click()

        # Wait for URL change
        try:
            wait.until(EC.url_changes(LOGIN_URL))
        except TimeoutException:
            # Check for error messages
            errs = driver.find_elements(
                By.CSS_SELECTOR, ".error,.alert,[class*='error'],[class*='invalid']"
            )
            for el in errs:
                if el.text.strip():
                    logger.warning(f"[{login}] Xato: {el.text.strip()}")
            logger.warning(f"[{login}] URL o'zgarmadi. URL: {driver.current_url}")
            return False

        time.sleep(ACTIVE_WAIT)
        final_url = driver.current_url

        # Check if still on login page (failed login)
        if "login" in final_url.lower():
            logger.warning(f"[{login}] Login sahifasida qoldi")
            return False

        logger.info(f"[{login}] Online qilindi")
        _do_logout(driver)
        return True

    except TimeoutException:
        logger.warning(f"[{login}] Timeout")
        driver.save_screenshot(f"error_{login}.png")
        return False
    except WebDriverException as e:
        logger.error(f"[{login}] WebDriver xato: {e}")
        return False
    except Exception as e:
        logger.error(f"[{login}] Xato: {e}")
        return False


def make_all_online(students: list, progress_callback=None) -> dict:
    total   = len(students)
    results = {
        "total":        total,
        "student_ok":   0,
        "student_fail": 0,
        "parent_ok":    0,
        "parent_fail":  0,
    }

    driver = _make_driver()
    try:
        for idx, student in enumerate(students, 1):
            fio = student.get("fio", student["login"])

            ok = _login_and_wait(driver, student["login"], student["password"])
            results["student_ok" if ok else "student_fail"] += 1
            if progress_callback:
                progress_callback(idx, total, fio, "o'quvchi", ok)

            parent = student.get("parent", {})
            if parent.get("login") and parent.get("password"):
                ok_p = _login_and_wait(driver, parent["login"], parent["password"])
                results["parent_ok" if ok_p else "parent_fail"] += 1
                if progress_callback:
                    progress_callback(idx, total, fio, "ota-ona", ok_p)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return results
