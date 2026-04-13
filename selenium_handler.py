import os
import time
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

LOGIN_URL    = "https://login.emaktab.uz/"
SITE_URL     = "https://emaktab.uz"
WAIT_TIMEOUT = 20
ACTIVE_WAIT  = 2


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
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def _is_logged_in(driver: webdriver.Chrome) -> bool:
    """Login muvaffaqiyatli bo'lganini tekshiradi."""
    current_url = driver.current_url
    # Hali login sahifasida bo'lsa — login xato
    if "/login" in current_url:
        return False
    # Dashboard/home sahifasiga o'tgan bo'lsa — muvaffaqiyatli
    return True


def _do_logout(driver: webdriver.Chrome):
    """Sessionni tozalash uchun logout qiladi."""
    try:
        # Birinchi usul: to'g'ridan URL orqali
        driver.get(f"{SITE_URL}/logout")
        time.sleep(1)
        # Logout ishlagan bo'lsa login sahifasiga qaytadi
        if "/login" in driver.current_url or driver.current_url == SITE_URL + "/":
            return
    except Exception:
        pass

    try:
        driver.get(f"{SITE_URL}/auth/logout")
        time.sleep(1)
        return
    except Exception:
        pass

    # Ikkinchi usul: cookie tozalash
    try:
        driver.delete_all_cookies()
        driver.execute_script("localStorage.clear(); sessionStorage.clear();")
    except Exception:
        pass


def _login_and_wait(driver: webdriver.Chrome, login: str, password: str) -> bool:
    try:
        driver.get(LOGIN_URL)
        wait = WebDriverWait(driver, WAIT_TIMEOUT)

        # Login field — name="login"
        login_field = wait.until(EC.presence_of_element_located((By.NAME, "login")))
        login_field.clear()
        login_field.send_keys(login)

        # Captcha tekshiruvi — ko'p urinishdan keyin chiqadi
        try:
            exceeded = driver.find_element(By.NAME, "exceededAttempts")
            if exceeded.get_attribute("value") == "true":
                logger.warning(f"Captcha chiqdi, bu login o'tkazib yuborildi: {login}")
                return False
        except NoSuchElementException:
            pass

        # Password field — name="password"
        pwd_field = driver.find_element(By.NAME, "password")
        pwd_field.clear()
        pwd_field.send_keys(password)

        # Submit — input[name="submit"]
        submit = driver.find_element(By.NAME, "submit")
        submit.click()

        # URL o'zgarishini kutamiz
        try:
            wait.until(EC.url_changes(LOGIN_URL))
        except TimeoutException:
            # URL o'zgarmagan — login xato (noto'g'ri parol)
            logger.warning(f"Login xato (URL o'zgarmadi): {login}")
            return False

        time.sleep(ACTIVE_WAIT)

        # Login muvaffaqiyatli bo'lganini tekshir
        if not _is_logged_in(driver):
            logger.warning(f"Login xato (hali login sahifasida): {login}")
            return False

        logger.info(f"Login OK: {login}")

        # Logout — sessionni tozalash
        _do_logout(driver)
        return True

    except TimeoutException:
        logger.warning(f"Timeout: {login}")
        return False
    except WebDriverException as e:
        logger.error(f"WebDriver xato ({login}): {e}")
        return False
    except Exception as e:
        logger.error(f"Kutilmagan xato ({login}): {e}")
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