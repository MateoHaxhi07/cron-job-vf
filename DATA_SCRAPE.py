import os
import time
import glob
import pandas as pd
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from psycopg2 import connect
from psycopg2.extras import execute_values

# ---------------- CONSTANTS ----------------
LOGIN_URL = 'https://hospitality.devpos.al/login'
REPORTS_URL = 'https://hospitality.devpos.al/user/0/produktet/shitjet'
NIPT = "K31412026L"
USERNAME = "Elona"
PASSWORD = "Sindi2364*"
DOWNLOAD_FOLDER = "/app/data"
DATABASE_URL = "postgresql://restaurant_db_mg7q_user:d9Zslmf92niOQETVqJaTb2n1Rxg0niYg@dpg-cumpfg8gph6c7387r200-a.frankfurt-postgres.render.com/restaurant_db_mg7q"

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

def setup_driver():
    print("[DEBUG] Setting up Chrome driver...")
    chrome_options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": DOWNLOAD_FOLDER,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.page_load_strategy = "eager"

    driver = webdriver.Chrome(options=chrome_options)
    print("[DEBUG] Chrome driver initialized successfully.")
    return driver

def login_to_website(driver):
    print("[DEBUG] Logging into the website...")
    driver.get(LOGIN_URL)
    WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.NAME, 'nipt'))).send_keys(NIPT)
    WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.NAME, 'username'))).send_keys(USERNAME)
    WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.XPATH, '//input[@formcontrolname="password"]'))).send_keys(PASSWORD)
    driver.find_element(By.XPATH, "//button[contains(., 'Login')]").click()
    time.sleep(5)
    print("[DEBUG] Login successful.")





def adjust_datepicker(driver):
    try:
        # Use the provided XPath to click the calendar icon/input for the start date
        calendar_icon = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.XPATH, "/html/body/app-root/app-dashboard-layout/div[2]/mat-sidenav-container/mat-sidenav-content/div/app-sales-products/div/form/mat-form-field[1]/div/div[1]/div[4]"))
        )
        calendar_icon.click()
        print("[DEBUG] Calendar icon clicked.")

        # Click the "previous month" button six times
        for i in range(6):
            prev_button = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'mat-calendar-previous-button')]"))
            )
            prev_button.click()
            print(f"[DEBUG] Clicked previous month button {i + 1} time(s).")
            time.sleep(1)  # Allow the calendar to update after each click

        # Now that we've navigated 6 months back, click "day 1"
        day_one = WebDriverWait(driver, 30).until(
    EC.element_to_be_clickable((By.XPATH,
       "//div[contains(@class, 'mat-calendar-body-cell-content') and normalize-space(text())='1']"))
)
        day_one.click()
        print("[DEBUG] Day '1' selected in datepicker.")

        print("[DEBUG] Datepicker adjusted successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to adjust datepicker: {e}")

def download_excel_report(driver):
    print("[DEBUG] Navigating to reports page...")
    driver.get(REPORTS_URL)

    # Adjust the datepicker before downloading the report
    adjust_datepicker(driver)

    try:
        WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Shkarko raportin')]"))
        ).click()
        print("[DEBUG] Download button clicked.")
    except Exception as e:
        print(f"[ERROR] Failed to click download button: {e}")
        return

    time.sleep(150)  # Allow file download

    for _ in range(30):
        matching_files = glob.glob(os.path.join(DOWNLOAD_FOLDER, "raport shitjes*.xlsx"))
        if matching_files and not matching_files[0].endswith(".crdownload"):
            file_path = matching_files[0]
            new_file_path = os.path.join(DOWNLOAD_FOLDER, "sales_data.xlsx")
            try:
                os.replace(file_path, new_file_path)
                print(f"[DEBUG] File saved as: {new_file_path}")
                format_excel_file(new_file_path)
                break
            except Exception as e:
                print(f"[ERROR] Failed to rename file: {e}")
                time.sleep(2)
        time.sleep(1)


def format_excel_file(file_path):
    print(f"[DEBUG] Processing file: {file_path}")
    df = pd.read_excel(file_path)
    
    # Replace all "-" characters in the DataFrame
    df = df.replace("-", "", regex=True)
    
    # Delete unnecessary columns
    columns_to_delete = [0, 2, 5, 7, 8, 9, 10, 12, 13, 15, 16, 18, 20, 21, 23, 24, 25]
    df.drop(df.columns[columns_to_delete], axis=1, inplace=True)
    
    # Convert the date column using the provided format
    df['Data Rregjistrimit'] = pd.to_datetime(
        df['Data Rregjistrimit'], format='%d/%m/%Y', errors='coerce'
    )
    
    # Helper function to process the time column:
    def process_time(x):
        x_str = str(x).strip()
        # If the string contains "days", extract the actual time part
        if "days" in x_str:
            parts = x_str.split(" ")
            if len(parts) >= 3:
                return parts[2]
        return x_str

    # Apply the helper function to clean up the time values
    df['Koha Rregjistrimit'] = df['Koha Rregjistrimit'].astype(str).apply(process_time)
    
    # Combine the formatted date and cleaned time into a single Datetime column
    df['Datetime'] = pd.to_datetime(
        df['Data Rregjistrimit'].dt.strftime('%Y-%m-%d') + ' ' + df['Koha Rregjistrimit'],
        errors='coerce'
    )
    
    # Remove the now redundant individual date and time columns
    df.drop(['Data Rregjistrimit', 'Koha Rregjistrimit'], axis=1, inplace=True)
    
    # Rename remaining columns as needed
    df.rename(columns={
        df.columns[0]: 'Order_ID',
        df.columns[1]: 'Seller',
        df.columns[2]: 'Article_Name',
        df.columns[3]: 'Category',
        df.columns[4]: 'Quantity',
        df.columns[5]: 'Article_Price',
        df.columns[6]: 'Total_Article_Price',
        df.columns[7]: 'Datetime'
    }, inplace=True)
    
    # Map sellers to categories
    seller_categories = {
        'Enisa': 'Delivery',
        'Dea': 'Delivery',
        'Kristian Llupo': 'Bar',
        'Pranvera Xherahi': 'Bar',
        'Fjorelo Arapi': 'Restaurant',
        'Jonel Demba': 'Restaurant'
    }
    df['Seller Category'] = df['Seller'].map(seller_categories)
    
    # Remove rows where Seller is "TOTALI"
    df = df[df['Seller'] != 'TOTALI']
    
    # Save the processed file as a CSV
    csv_path = os.path.splitext(file_path)[0] + '.csv'
    df.to_csv(csv_path, index=False)

    
    print(f"[DEBUG] File formatted and saved as CSV at: {csv_path}")

def import_data_to_database():
    print("[DEBUG] Starting database import...")
    file_path = os.path.join(DOWNLOAD_FOLDER, "sales_data.csv")
    if not os.path.exists(file_path):
        print(f"[ERROR] CSV file not found: {file_path}")
        return

    try:
        df = pd.read_csv(file_path)
        print(f"[DEBUG] CSV loaded with {len(df)} rows.")
    except Exception as e:
        print(f"[ERROR] Failed to load CSV: {e}")
        return

    # Convert 'Datetime' to proper datetime or set to None
    df['Datetime'] = pd.to_datetime(df['Datetime'], errors='coerce')
    df.dropna(subset=["Datetime"], inplace=True)


    try:
        conn = connect(DATABASE_URL, sslmode="require")
        cursor = conn.cursor()

        cursor.execute('TRUNCATE TABLE "sales";')
        print("[DEBUG] Existing records cleared.")

        records = [
            (
                row['Order_ID'],
                row['Seller'],
                row['Article_Name'],
                row['Category'],
                float(row['Quantity']),
                float(row['Article_Price']),
                float(row['Total_Article_Price']),
                row['Datetime'],
                row['Seller Category']
            )
            for index, row in df.iterrows()
        ]

        execute_values(cursor, """
            INSERT INTO "sales" ("Order_ID", "Seller", "Article_Name", "Category", "Quantity",
                                 "Article_Price", "Total_Article_Price", "Datetime", "Seller Category")
            VALUES %s
        """, records)

        conn.commit()
        print("[DEBUG] Data inserted into the database.")
    except Exception as e:
        print(f"[ERROR] Database operation failed: {e}")
    finally:
        if conn:
            cursor.close()
            conn.close()
            print("[DEBUG] Database connection closed.")


def main():
    driver = setup_driver()
    try:
        login_to_website(driver)
        download_excel_report(driver)
        import_data_to_database()
    finally:
        driver.quit()

if __name__ == "__main__":
    print("[DEBUG] Starting script execution...")
    main()
    print("[DEBUG] Script execution completed.")
