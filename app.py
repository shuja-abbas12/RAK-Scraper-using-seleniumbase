# -*- coding: utf-8 -*-

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
import time, json, re
from pathlib import Path

# ======= CONFIG =======
URL = "https://grpportal.rak.ae/irj/portal/judgement_publications"
DATA_DIR = Path("Data")
DATA_DIR.mkdir(exist_ok=True)

TABLE_SEL = (By.CSS_SELECTOR, "table[ct='ST']")
BACK_BTN_XP = "//div[@role='button' and @title='عودة']"
SEL = {
    "court": 'input[data-hint*="ZDE_COURT_TYPE"]',
    "clas": 'input[data-hint*="ZDE_COURT_CLASSIFY_TYPE"]',
    "ctype": 'input[data-hint*="SCMGCASE_TYPE"]',
    "year": 'input[data-hint*="ZADTEL000019"]',
    "num": '#WD6D',
    "search": '#WD6F',
    "busy": 'div[id^="urBusyIndicator"]'
}
DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# ======= UTILS =======
def norm(txt):
    txt = txt.replace("\u200e", "").replace("\u200f", "").translate(DIGIT_MAP)
    return re.sub(r"\s+", " ", txt).strip()

def create_driver():
    print("🔧 Launching browser...")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    return webdriver.Chrome(options=options)

def wait_until_invisible(driver, sel):
    try:
        WebDriverWait(driver, 20).until(EC.invisibility_of_element_located((By.CSS_SELECTOR, sel)))
    except TimeoutException:
        pass

def set_combo(driver, css, value):
    if not value: return
    value = norm(value)
    wait_until_invisible(driver, SEL["busy"])
    box = driver.find_element(By.CSS_SELECTOR, css)
    driver.execute_script("arguments[0].removeAttribute('readonly')", box)
    box.click(); time.sleep(0.5)
    box.send_keys(Keys.ARROW_DOWN)

    print(f"🔍 Matching dropdown for: {value}")
    time.sleep(1)
    options = driver.find_elements(By.XPATH, "//div[@ct='LIB_I']")
    for i, opt in enumerate(options):
        print(f"  [{i+1}] {opt.text.strip()}")

    WebDriverWait(driver, 20).until(
        EC.element_to_be_clickable((By.XPATH, f"//div[@ct='LIB_I' and normalize-space()='{value}']"))
    ).click()
    print(f"✅ Selected: {value}")

def rows_in_view(driver):
    tbl = driver.find_elements(*TABLE_SEL)
    return tbl[0].find_elements(By.CSS_SELECTOR, "tbody tr[role='row']")[1:] if tbl else []

def last_row_id(row_el):
    return "|".join(c.text.strip() for c in row_el.find_elements(By.TAG_NAME, "td"))

def wait_new_rows(driver, prev_last_id, timeout=4):
    end = time.time() + timeout
    while time.time() < end:
        cur = last_row_id(rows_in_view(driver)[-1])
        if cur != prev_last_id:
            return cur
        time.sleep(0.25)
    return cur

def scrape_all_rows(driver, out_path):
    print("🚀 Starting scraping loop...")
    results, seen = [], set()
    WebDriverWait(driver, 30).until(lambda _: len(rows_in_view(driver)) > 0)

    round, stagnant = 0, 0
    while round < 100:
        vis = rows_in_view(driver)
        print(f"📄 Page {round} – {len(vis)} rows")
        for idx in range(len(vis)):
            try:
                vis = rows_in_view(driver)
                row = vis[idx]
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) < 7: continue
                row_data = [c.text.strip() for c in cells]
                rid = "|".join(row_data)
                if not rid or rid in seen: continue
                seen.add(rid)
                driver.execute_script("arguments[0].scrollIntoView({block:'center'})", cells[6])
                cells[6].click()
                WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, BACK_BTN_XP)))
                detail = driver.find_element(By.TAG_NAME, "body").text
                results.append({"index": len(results), "row_data": row_data, "detail_text": detail})
                out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"✅ Row {len(results)} scraped")
                driver.find_element(By.XPATH, BACK_BTN_XP).click()
                WebDriverWait(driver, 20).until(lambda _: len(rows_in_view(driver)) > 0)
            except Exception as e:
                print(f"⚠️  Row error: {e}")
                try: driver.find_element(By.XPATH, BACK_BTN_XP).click()
                except: pass
                continue

        try:
            vis = rows_in_view(driver)
            bottom_before = last_row_id(vis[-1])
            driver.execute_script("arguments[0].scrollIntoView()", vis[-2])
            ActionChains(driver).send_keys(Keys.ARROW_DOWN * 11).perform()
            bottom_after = wait_new_rows(driver, bottom_before)
        except Exception as e:
            print(f"⚠️  Scroll error: {e}")
            break

        stagnant = stagnant + 1 if bottom_after == bottom_before else 0
        if stagnant >= 2: break
        round += 1

    print(f"🎉 Done. {len(results)} total rows.")
    return len(results)

# ======= ENTRY POINT =======
def run_scraper(court, year, clas=None, ctype=None, num=None, file_prefix="result"):
    fname = f"{file_prefix}_{int(time.time())}.json"
    out_path = DATA_DIR / fname
    driver = create_driver()
    try:
        print("🌐 Opening portal...")
        driver.get(URL)
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, SEL["court"])))

        set_combo(driver, SEL["court"], court)
        if clas: set_combo(driver, SEL["clas"], clas)
        if ctype: set_combo(driver, SEL["ctype"], ctype)
        set_combo(driver, SEL["year"], year)

        if num:
            box = driver.find_element(By.CSS_SELECTOR, SEL["num"])
            box.clear()
            box.send_keys(num)

        driver.find_element(By.CSS_SELECTOR, SEL["search"]).click()
        wait_until_invisible(driver, SEL["busy"])

        rows = scrape_all_rows(driver, out_path)
        print(f"✅ Saved to {out_path.resolve()} – {rows} rows")

    except Exception as e:
        print(f"❌ Failed: {e}")
    finally:
        driver.quit()
        print("🧹 Done.")

# ======= RUN IT =======
if __name__ == "__main__":
    run_scraper(
        court="محكمة أول درجة",   # REQUIRED
        year="2025",             # REQUIRED
        clas="مدني",             # OPTIONAL
    )
