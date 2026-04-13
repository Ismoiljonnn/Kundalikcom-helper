import os
import time
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logger = logging.getLogger(__name__)

LOGIN_URL  = "https://kundalik.com/login"
SITE_URL   = "https://kundalik.com"
WAIT_TIMEOUT = 15
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
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    chromedriver = "/usr/local/bin/chromedriver"
    if os.path.exists(chromedriver):
        service = Service(chromedriver)
    else:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def _login_and_wait(driver: webdriver.Chrome, login: str, password: str) -> bool:
    try:
        driver.get(LOGIN_URL)
        wait = WebDriverWait(driver, WAIT_TIMEOUT)

        inp_user = wait.until(EC.presence_of_element_located((By.NAME, "username")))
        inp_user.clear()
        inp_user.send_keys(login)

        inp_pass = driver.find_element(By.NAME, "password")
        inp_pass.clear()
        inp_pass.send_keys(password)

        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        wait.until(EC.url_changes(LOGIN_URL))

        time.sleep(ACTIVE_WAIT)

        # Logout
        for url in [f"{SITE_URL}/logout", f"{SITE_URL}/auth/logout"]:
            try:
                driver.get(url)
                time.sleep(1)
                return True
            except Exception:
                continue

        try:
            driver.find_element(
                By.CSS_SELECTOR, "a[href*='logout'], button[class*='logout']"
            ).click()
            time.sleep(1)
        except NoSuchElementException:
            pass

        return True

    except TimeoutException:
        logger.warning(f"Timeout: {login}")
        return False
    except Exception as e:
        logger.error(f"Error ({login}): {e}")
        return False


def make_all_online(students: list, progress_callback=None) -> dict:
    total = len(students)
    results = {"total": total, "student_ok": 0, "student_fail": 0,
               "parent_ok": 0, "parent_fail": 0}

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
        driver.quit()

    return results
