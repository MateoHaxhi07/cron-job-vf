#!/usr/bin/env python3
"""
VILA SALES — CONTINUOUS BACKGROUND WORKER
Runs as a Render Background Worker (not a cron job).
Stays alive, reuses Chrome session, scrapes every 5 minutes.
"""

import os
import sys
import time
import glob
import signal
import tempfile
import traceback
import pandas as pd
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException
from psycopg2 import connect
from psycopg2.extras import execute_values

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
LOGIN_URL       = 'https://hospitality.devpos.al/login'
REPORTS_URL     = 'https://hospitality.devpos.al/user/0/produktet/shitjet'
NIPT            = "K31412026L"
USERNAME        = "Elona"
PASSWORD        = "Sindi2364*"
DOWNLOAD_FOLDER = "/app/data"
DATABASE_URL    = os.environ.get("DATABASE_URL",
    "postgresql://restaurant_db_mg7q_user:"
    "d9Zslmf92niOQETVqJaTb2n1Rxg0niYg"
    "@dpg-cumpfg8gph6c7387r200-a.frankfurt-postgres.render.com/"
    "restaurant_db_mg7q"
)

SCRAPE_INTERVAL_SECONDS = 5 * 60   # 5 minutes
MAX_RETRIES             = 3
SESSION_REFRESH_HOURS   = 2        # Re-login every 2 hours to avoid session expiry

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# ──────────────────────────────────────────────
# GLOBAL STATE
# ──────────────────────────────────────────────
driver = None
last_login_time = None
running = True


def handle_signal(signum, frame):
    """Graceful shutdown on SIGTERM/SIGINT"""
    global running
    print(f"\n[{now()}] Received signal {signum}, shutting down gracefully...")
    running = False


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ──────────────────────────────────────────────
# CHROME DRIVER (reusable)
# ──────────────────────────────────────────────
def create_driver():
    """Create a fresh Chrome driver"""
    global driver

    # Kill existing driver if any
    if driver:
        try:
            driver.quit()
        except:
            pass

    print(f"[{now()}] Starting Chrome...")
    opts = webdriver.ChromeOptions()

    prefs = {
        "download.default_directory": DOWNLOAD_FOLDER,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    }
    opts.add_experimental_option("prefs", prefs)
    opts.add_argument("--headless")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920x1080")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    user_data_dir = tempfile.mkdtemp(prefix="chrome-profile-")
    opts.add_argument(f"--user-data-dir={user_data_dir}")
    opts.page_load_strategy = "eager"

    driver = webdriver.Chrome(options=opts)
    print(f"[{now()}] Chrome ready")
    return driver


def ensure_driver():
    """Ensure driver exists and is responsive"""
    global driver
    try:
        if driver:
            driver.title  # test if driver is alive
            return driver
    except:
        pass
    return create_driver()


# ──────────────────────────────────────────────
# LOGIN (with session reuse)
# ──────────────────────────────────────────────
def login():
    global last_login_time
    d = ensure_driver()

    print(f"[{now()}] Logging in...")
    d.get(LOGIN_URL)
    WebDriverWait(d, 30).until(EC.element_to_be_clickable((By.NAME, 'nipt'))).send_keys(NIPT)
    WebDriverWait(d, 30).until(EC.element_to_be_clickable((By.NAME, 'username'))).send_keys(USERNAME)
    WebDriverWait(d, 30).until(
        EC.element_to_be_clickable((By.XPATH, '//input[@formcontrolname="password"]'))
    ).send_keys(PASSWORD)
    d.find_element(By.XPATH, "//button[contains(., 'Login')]").click()
    time.sleep(5)

    last_login_time = datetime.now()
    print(f"[{now()}] Logged in ✓")


def needs_relogin():
    """Check if we need to re-login (session might have expired)"""
    global last_login_time
    if not last_login_time:
        return True
    hours = (datetime.now() - last_login_time).total_seconds() / 3600
    return hours >= SESSION_REFRESH_HOURS


# ──────────────────────────────────────────────
# CLEAN OLD FILES
# ──────────────────────────────────────────────
def clean_downloads():
    """Remove old download files before each scrape"""
    for f in glob.glob(os.path.join(DOWNLOAD_FOLDER, "raport shitjes*.xlsx")):
        try:
            os.remove(f)
        except:
            pass
    for f in glob.glob(os.path.join(DOWNLOAD_FOLDER, "*.crdownload")):
        try:
            os.remove(f)
        except:
            pass


# ──────────────────────────────────────────────
# DOWNLOAD REPORT
# ──────────────────────────────────────────────
def download_report():
    """Download Excel report, return file path or None"""
    d = ensure_driver()
    clean_downloads()

    print(f"[{now()}] Navigating to reports...")
    d.get(REPORTS_URL)

    try:
        WebDriverWait(d, 30).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Shkarko raportin')]"))
        ).click()
    except Exception as e:
        print(f"[{now()}] ERROR: Click failed: {e}")
        return None

    # Wait for download (max 120s)
    for i in range(60):
        files = glob.glob(os.path.join(DOWNLOAD_FOLDER, "raport shitjes*.xlsx"))
        if files and not files[0].endswith(".crdownload"):
            dst = os.path.join(DOWNLOAD_FOLDER, "sales_data.xlsx")
            os.replace(files[0], dst)
            print(f"[{now()}] Downloaded → {dst}")
            return dst
        time.sleep(2)

    print(f"[{now()}] ERROR: Download timed out")
    return None


# ──────────────────────────────────────────────
# PARSE EXCEL → DataFrame
# ──────────────────────────────────────────────
def parse_excel(file_path):
    """Parse the DevPOS Excel into a clean DataFrame"""
    df = pd.read_excel(file_path)

    # Drop unwanted columns by index
    drop_idxs = [0, 2, 5, 7, 8, 12, 13, 15, 16, 18, 20, 21, 23, 24, 25]
    df.drop(df.columns[drop_idxs], axis=1, inplace=True)

    # Parse datetime
    df['Data Rregjistrimit'] = pd.to_datetime(df['Data Rregjistrimit'], format='%d/%m/%Y', errors='coerce')
    df['Koha Rregjistrimit'] = df['Koha Rregjistrimit'].astype(str).apply(
        lambda x: x.split(" ")[2] if "days" in x else x
    )
    df['Datetime'] = pd.to_datetime(
        df['Data Rregjistrimit'].dt.strftime('%Y-%m-%d') + ' ' + df['Koha Rregjistrimit'],
        errors='coerce'
    )
    df.drop(['Data Rregjistrimit', 'Koha Rregjistrimit'], axis=1, inplace=True)

    # Rename columns
    mapping = {
        0: 'Order_ID', 1: 'Seller',
        2: 'Buyer_Name', 3: 'Buyer_NIPT',
        4: 'Article_Name', 5: 'Category',
        6: 'Quantity', 7: 'Article_Price',
        8: 'Total_Article_Price', 9: 'Datetime'
    }
    df.rename(columns={df.columns[i]: name for i, name in mapping.items()}, inplace=True)

    # Seller categories
    seller_map = {
        'Enisa': 'Delivery', 'Dea': 'Delivery',
        'Kristian Llupo': 'Bar', 'Pranvera Xherahi': 'Bar',
        'Fjorelo Arapi': 'Restaurant', 'Jonel Demba': 'Restaurant'
    }
    df['Seller Category'] = df['Seller'].map(seller_map)
    df = df[df['Seller'] != 'TOTALI']

    return df


# ──────────────────────────────────────────────
# INSERT TO DATABASE (only new rows)
# ──────────────────────────────────────────────
def insert_to_db(df):
    """Insert only new rows to PostgreSQL"""
    df['Datetime'] = pd.to_datetime(df['Datetime'], errors='coerce')
    df.dropna(subset=["Datetime"], inplace=True)

    if df.empty:
        print(f"[{now()}] No valid rows after cleanup")
        return 0

    conn = connect(DATABASE_URL, sslmode="require")
    cur = conn.cursor()

    try:
        # Get latest record from DB
        cur.execute('SELECT MAX("Datetime") FROM sales;')
        max_dt = cur.fetchone()[0]
        max_id = None
        if max_dt:
            cur.execute('SELECT MAX("Order_ID") FROM sales WHERE "Datetime"=%s;', (max_dt,))
            max_id = cur.fetchone()[0]

        # Filter new rows
        def is_new(r):
            if not max_dt:
                return True
            if r['Datetime'] > max_dt:
                return True
            if r['Datetime'] == max_dt:
                if not max_id:
                    return True
                try:
                    return float(r['Order_ID']) > float(max_id)
                except:
                    return str(r['Order_ID']) > str(max_id)
            return False

        new_df = df[df.apply(is_new, axis=1)]

        if new_df.empty:
            print(f"[{now()}] No new rows")
            return 0

        records = [
            (
                r['Order_ID'], r['Seller'],
                r['Article_Name'], r['Category'], float(r['Quantity']),
                float(r['Article_Price']), float(r['Total_Article_Price']),
                r['Datetime'], r['Seller Category'],
                r['Buyer_Name'], r['Buyer_NIPT']
            ) for _, r in new_df.iterrows()
        ]

        execute_values(cur, """
            INSERT INTO sales
              ("Order_ID","Seller",
               "Article_Name","Category","Quantity",
               "Article_Price","Total_Article_Price","Datetime",
               "Seller Category","Buyer_Name","Buyer_NIPT")
            VALUES %s
        """, records)
        conn.commit()

        count = len(records)
        print(f"[{now()}] Inserted {count} new rows ✓")
        return count

    finally:
        cur.close()
        conn.close()


# ──────────────────────────────────────────────
# SINGLE SCRAPE CYCLE
# ──────────────────────────────────────────────
def run_one_cycle():
    """Execute one full scrape → parse → insert cycle"""
    start = time.time()

    # Re-login if needed
    if needs_relogin():
        login()

    # Download
    file_path = download_report()
    if not file_path:
        print(f"[{now()}] Cycle failed: no download")
        return False

    # Parse
    df = parse_excel(file_path)
    print(f"[{now()}] Parsed {len(df)} rows from Excel")

    # Insert
    new_count = insert_to_db(df)

    elapsed = round(time.time() - start, 1)
    print(f"[{now()}] Cycle complete: {new_count} new rows in {elapsed}s")
    return True


# ──────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────
def main():
    print(f"[{now()}] ========================================")
    print(f"[{now()}] VILA SALES WORKER STARTING")
    print(f"[{now()}] Interval: {SCRAPE_INTERVAL_SECONDS}s ({SCRAPE_INTERVAL_SECONDS//60} min)")
    print(f"[{now()}] ========================================")

    consecutive_failures = 0

    while running:
        try:
            success = run_one_cycle()
            if success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
        except WebDriverException as e:
            print(f"[{now()}] Chrome error: {e}")
            print(f"[{now()}] Will recreate driver on next cycle")
            consecutive_failures += 1
            # Force driver recreation
            global driver, last_login_time
            try:
                driver.quit()
            except:
                pass
            driver = None
            last_login_time = None
        except Exception as e:
            print(f"[{now()}] ERROR: {e}")
            traceback.print_exc()
            consecutive_failures += 1

        # If too many failures, recreate everything
        if consecutive_failures >= MAX_RETRIES:
            print(f"[{now()}] {MAX_RETRIES} consecutive failures — resetting driver")
            try:
                driver.quit()
            except:
                pass
            driver = None
            last_login_time = None
            consecutive_failures = 0

        # Wait for next cycle
        if running:
            print(f"[{now()}] Next scrape in {SCRAPE_INTERVAL_SECONDS//60} min...")
            # Sleep in small chunks so we can respond to SIGTERM quickly
            for _ in range(SCRAPE_INTERVAL_SECONDS // 5):
                if not running:
                    break
                time.sleep(5)

    # Cleanup
    print(f"[{now()}] Shutting down...")
    if driver:
        try:
            driver.quit()
        except:
            pass
    print(f"[{now()}] Worker stopped. Goodbye.")


if __name__ == "__main__":
    main()
