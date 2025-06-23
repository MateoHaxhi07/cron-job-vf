#!/usr/bin/env python3
import os
import time
import glob
import tempfile
import pandas as pd
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from psycopg2 import connect
from psycopg2.extras import execute_values

# ---------------- CONSTANTS ----------------
LOGIN_URL       = 'https://hospitality.devpos.al/login'
REPORTS_URL     = 'https://hospitality.devpos.al/user/0/produktet/shitjet'
NIPT            = "K31412026L"
USERNAME        = "Elona"
PASSWORD        = "Sindi2364*"
DOWNLOAD_FOLDER = "/app/data"
DATABASE_URL    = (
    "postgresql://restaurant_db_mg7q_user:"
    "d9Zslmf92niOQETVqJaTb2n1Rxg0niYg"
    "@dpg-cumpfg8gph6c7387r200-a.frankfurt-postgres.render.com/"
    "restaurant_db_mg7q"
)

# ensure download folder exists
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)


def setup_driver():
    """
    Initialize headless Chrome with:
      - download prefs
      - headless & stability flags
      - a unique user-data-dir per run to avoid “already in use” errors
    """
    print("[DEBUG] Setting up Chrome driver...")
    chrome_options = webdriver.ChromeOptions()

    # 1) Download preferences
    prefs = {
        "download.default_directory": DOWNLOAD_FOLDER,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True
    }
    chrome_options.add_experimental_option("prefs", prefs)

    # 2) Headless & stability flags
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")             # helps in Docker/cron
    chrome_options.add_argument("--disable-dev-shm-usage")  # avoids shared memory issues

    # 3) Unique Chrome profile folder
    user_data_dir = tempfile.mkdtemp(prefix="chrome-profile-")
    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

    chrome_options.page_load_strategy = "eager"

    driver = webdriver.Chrome(options=chrome_options)
    print(f"[DEBUG] Chrome driver initialized (profile: {user_data_dir})")
    return driver


def login_to_website(driver):
    print("[DEBUG] Logging in…")
    driver.get(LOGIN_URL)
    WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.NAME, 'nipt'))).send_keys(NIPT)
    WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.NAME, 'username'))).send_keys(USERNAME)
    WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.XPATH, '//input[@formcontrolname="password"]'))
    ).send_keys(PASSWORD)
    driver.find_element(By.XPATH, "//button[contains(., 'Login')]").click()
    time.sleep(5)
    print("[DEBUG] Login complete.")


def download_excel_report(driver):
    print("[DEBUG] Navigating to reports page…")
    driver.get(REPORTS_URL)
    try:
        WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Shkarko raportin')]"))
        ).click()
        print("[DEBUG] Clicked download.")
    except Exception as e:
        print(f"[ERROR] Click failed: {e}")
        return

    # wait up to 60*2s = 120s for download to finish
    for i in range(60):
        files = glob.glob(os.path.join(DOWNLOAD_FOLDER, "raport shitjes*.xlsx"))
        if files and not files[0].endswith(".crdownload"):
            src = files[0]
            dst = os.path.join(DOWNLOAD_FOLDER, "sales_data.xlsx")
            os.replace(src, dst)
            print(f"[DEBUG] Downloaded file → {dst}")
            format_excel_file(dst)
            return
        time.sleep(2)
        print(f"[DEBUG] Waiting for file… {i+1}/60")
    print("[ERROR] Download timed out.")


def format_excel_file(file_path):
    print(f"[DEBUG] Reading Excel: {file_path}")
    df = pd.read_excel(file_path)

    # 1) Inspect raw columns & sample
    print("[DEBUG] Raw columns:", df.columns.tolist())
    print("[DEBUG] Raw sample row:", df.iloc[0].to_dict() if not df.empty else "EMPTY DF")

    # 2) Drop unwanted columns by index
    drop_idxs = [0, 2, 5, 7, 8, 12, 13, 15, 16, 18, 20, 21, 23, 24, 25]
    df.drop(df.columns[drop_idxs], axis=1, inplace=True)

    # 3) Parse date + time into a single Datetime column
    df['Data Rregjistrimit'] = pd.to_datetime(df['Data Rregjistrimit'], format='%d/%m/%Y', errors='coerce')
    df['Koha Rregjistrimit'] = df['Koha Rregjistrimit'].astype(str).apply(
        lambda x: x.split(" ")[2] if "days" in x else x
    )
    df['Datetime'] = pd.to_datetime(
        df['Data Rregjistrimit'].dt.strftime('%Y-%m-%d') + ' ' + df['Koha Rregjistrimit'],
        errors='coerce'
    )

    # 4) Drop the old date/time columns
    df.drop(['Data Rregjistrimit', 'Koha Rregjistrimit'], axis=1, inplace=True)

    # 5) Rename the remaining columns
    mapping = {
        0: 'Order_ID', 1: 'Seller',
        2: 'Buyer_Name', 3: 'Buyer_NIPT',
        4: 'Article_Name', 5: 'Category',
        6: 'Quantity', 7: 'Article_Price',
        8: 'Total_Article_Price', 9: 'Datetime'
    }
    df.rename(columns={df.columns[i]: name for i, name in mapping.items()}, inplace=True)
    print("[DEBUG] After rename cols:", df.columns.tolist())

    # 6) Log missing buyer info
    print("[DEBUG] Buyer_Name null count:", df['Buyer_Name'].isna().sum(), "/", len(df))
    print("[DEBUG] Buyer_NIPT null count:", df['Buyer_NIPT'].isna().sum(), "/", len(df))

    # 7) Map seller categories & filter out totals
    seller_map = {
        'Enisa': 'Delivery', 'Dea': 'Delivery',
        'Kristian Llupo': 'Bar', 'Pranvera Xherahi': 'Bar',
        'Fjorelo Arapi': 'Restaurant', 'Jonel Demba': 'Restaurant'
    }
    df['Seller Category'] = df['Seller'].map(seller_map)
    df = df[df['Seller'] != 'TOTALI']

    # 8) Save to CSV
    csv_path = file_path.replace('.xlsx', '.csv')
    df.to_csv(csv_path, index=False)
    print(f"[DEBUG] Formatted CSV: {csv_path}")
    print("[DEBUG] CSV sample row:", df[['Buyer_Name', 'Buyer_NIPT']].head().to_dict(orient='records'))


def import_data_to_database():
    print("[DEBUG] Importing to DB…")
    csv_path = os.path.join(DOWNLOAD_FOLDER, "sales_data.csv")
    if not os.path.exists(csv_path):
        print("[ERROR] CSV missing:", csv_path)
        return

    df = pd.read_csv(csv_path)
    df['Datetime'] = pd.to_datetime(df['Datetime'], errors='coerce')
    df.dropna(subset=["Datetime"], inplace=True)

    conn = connect(DATABASE_URL, sslmode="require")
    cur  = conn.cursor()

    # find latest inserted datetime and order_id
    cur.execute('SELECT MAX("Datetime") FROM sales;')
    max_dt = cur.fetchone()[0]
    max_id = None
    if max_dt:
        cur.execute('SELECT MAX("Order_ID") FROM sales WHERE "Datetime"=%s;', (max_dt,))
        max_id = cur.fetchone()[0]
    print(f"[DEBUG] DB latest: datetime={max_dt}, order_id={max_id}")

    # filter only new rows
    def is_new(r):
        if not max_dt: return True
        if r['Datetime'] > max_dt: return True
        if r['Datetime'] == max_dt:
            if not max_id: return True
            try:
                return float(r['Order_ID']) > float(max_id)
            except:
                return str(r['Order_ID']) > str(max_id)
        return False

    new_df = df[df.apply(is_new, axis=1)]
    print("[DEBUG] New rows found:", len(new_df))
    if not new_df.empty:
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
        print("[DEBUG] Inserted to DB.")
    else:
        print("[DEBUG] No new data to insert.")

    cur.close()
    conn.close()
    print("[DEBUG] DB connection closed.")


def main():
    print("[DEBUG] Script start.")
    driver = setup_driver()
    try:
        login_to_website(driver)
        download_excel_report(driver)
        import_data_to_database()
    finally:
        driver.quit()
        print("[DEBUG] Driver closed.")
    print("[DEBUG] Script end.")


if __name__ == "__main__":
    print("[DEBUG] Starting script execution...")
    main()
    print("[DEBUG] Script execution completed.")
