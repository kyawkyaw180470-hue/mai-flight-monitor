# -*- coding: utf-8 -*-
"""MAI Flight Monitor — GitHub Actions (single-shot)"""
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urlencode

import requests

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options
    from selenium.common.exceptions import WebDriverException
except ImportError as e:
    print(f"Missing library: {e}")
    sys.exit(1)


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()
DEPARTURE_DATE = os.environ.get("DEPARTURE_DATE", "").strip()
ADULTS = int(os.environ.get("ADULTS", "1"))
CHILDREN = int(os.environ.get("CHILDREN", "0"))
INFANTS = int(os.environ.get("INFANTS", "0"))

if not all([TELEGRAM_TOKEN, CHAT_ID, DEPARTURE_DATE]):
    print("ERROR: Missing required env vars (TELEGRAM_TOKEN, CHAT_ID, DEPARTURE_DATE)")
    sys.exit(1)

DEP_PORT, ARR_PORT = "RGN", "MYT"
STATE_FILE = "state.txt"


def build_url():
    params = {
        "currency": "USD", "language": "en", "tripType": "ONE_WAY",
        "depPort": DEP_PORT, "arrPort": ARR_PORT,
        "departureDate": DEPARTURE_DATE, "returnDate": DEPARTURE_DATE,
        "passengerQuantities[0].passengerType": "ADULT",
        "passengerQuantities[0].quantity": ADULTS,
        "passengerQuantities[1].passengerType": "CHILD",
        "passengerQuantities[1].quantity": CHILDREN,
        "passengerQuantities[2].passengerType": "INFANT",
        "passengerQuantities[2].quantity": INFANTS,
        "passengerQuantities[3].passengerType": "NTNL",
        "passengerQuantities[3].quantity": 0,
        "availabilityParametricLinkRequestParams": 0,
        "withCalendar": "true",
    }
    return "https://book-myanmar.crane.aero/ibe/availability/?" + urlencode(params)


AVAILABILITY_URL = build_url()


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return f.read().strip()
    return "unknown"


def save_state(state):
    with open(STATE_FILE, "w") as f:
        f.write(state)


def send_telegram(message):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML",
                  "disable_web_page_preview": False},
            timeout=30,
        )
        if r.status_code == 200 and r.json().get("ok"):
            log("Telegram sent OK")
            return True
        log(f"Telegram failed: HTTP {r.status_code} - {r.text[:200]}")
    except requests.RequestException as e:
        log(f"Telegram error: {e}")
    return False


def make_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver


def check_once(driver):
    log(f"Checking {DEP_PORT}->{ARR_PORT} {DEPARTURE_DATE} ...")
    driver.get(AVAILABILITY_URL)
    time.sleep(15)

    body_text = driver.find_element(By.TAG_NAME, "body").text.lower()

    block_markers = (
        "sorry, you have been blocked", "attention required",
        "unable to access crane.aero", "why have i been blocked",
        "cloudflare ray id", "security service to protect",
    )
    if any(m in body_text for m in block_markers):
        log("UNKNOWN: Cloudflare/security block")
        return "unknown"

    no_flight_signals = (
        "no flights", "no flight found", "no result", "not available",
        "no availability", "sold out", "no seat", "flight not found",
        "no flight available", "unavailable",
    )
    has_price = bool(re.search(r"\$\s*\d+|\d+\s*usd|\d+\.\d{2}", body_text))
    has_flight_number = bool(re.search(r"\b8m\s?\d{3,4}\b", body_text))
    no_flight = any(s in body_text for s in no_flight_signals)

    log(f"no_flight={no_flight}, has_price={has_price}, has_flight_no={has_flight_number}")

    if (has_price or has_flight_number) and not no_flight:
        log("TICKET AVAILABLE!")
        return "available"

    log("Not available yet")
    return "unavailable"


def main():
    log("MAI Flight Monitor starting (GitHub Actions)")
    log(f"Route: {DEP_PORT} -> {ARR_PORT}; Date: {DEPARTURE_DATE}")

    old_state = load_state()
    log(f"Previous state: {old_state}")

    driver = None
    try:
        driver = make_driver()
        new_state = check_once(driver)
    except WebDriverException as e:
        log(f"WebDriver Error: {str(e)[:200]}")
        new_state = "unknown"
    except Exception as e:
        log(f"Error: {e}")
        new_state = "unknown"
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    log(f"New state: {new_state}")

    if new_state == "available" and old_state != "available":
        message = (
            f"✈️ <b>MAI Ticket Available!</b>\n\n"
            f"🛫 Route: <b>Yangon → Myitkyina</b>\n"
            f"📅 Date: <b>{DEPARTURE_DATE}</b>\n"
            f"👥 Passengers: {ADULTS} Adult"
            + (f", {CHILDREN} Child" if CHILDREN else "")
            + (f", {INFANTS} Infant" if INFANTS else "")
            + f"\n\n👉 Book now:\n{AVAILABILITY_URL}"
        )
        send_telegram(message)
    elif new_state == "available" and old_state == "available":
        log("Still available — no notification (already sent)")

    save_state(new_state)
    log("Done.")


if __name__ == "__main__":
    main()