from pathlib import Path
import json, time, sys

from seleniumbase import SB
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import StaleElementReferenceException

URL = "https://grpportal.rak.ae/sap/bc/webdynpro/sap/ZWDA_ESERV_JUD_PUBL"
TABLE_SEL = (By.CSS_SELECTOR, "table[ct='ST']")
BACK_BTN_XP = "//div[@role='button' and @title='عودة']"
OUT_FILE = Path("Data/final_output.json")
OUT_FILE.parent.mkdir(exist_ok=True)

def rows_in_view(sb):
    """Return a fresh list of visible table rows, skipping the header."""
    table = sb.find_elements(*TABLE_SEL)[0]
    return table.find_elements(By.CSS_SELECTOR, "tbody tr[role='row']")[1:]

def last_row_id(row_el):
    """Generate a unique identifier string from a row's cell contents."""
    cells = row_el.find_elements(By.TAG_NAME, "td")
    return "|".join(c.text.strip() for c in cells)

def wait_new_rows(sb, prev_last_id, timeout=4):
    """
    Wait until a new row appears at the bottom of the table or timeout occurs.
    Returns the last row's ID after scrolling.
    """
    end = time.time() + timeout
    while time.time() < end:
        cur_last_id = last_row_id(rows_in_view(sb)[-1])
        if cur_last_id != prev_last_id:
            return cur_last_id
        time.sleep(0.25)
    return cur_last_id

results: list[dict] = []
seen_rows: set[str] = set()

with SB(uc=True, headless=False) as sb:
    sb.uc_open(URL)
    sb.wait_for_ready_state_complete()
    input("Please complete login and CAPTCHA, then press Enter...")

    sb.wait_for_element(*TABLE_SEL, timeout=60)

    scroll_round = 0
    scroll_limit = 100
    stagnant_hits = 0

    while scroll_round < scroll_limit:
        rows = rows_in_view(sb)
        if not rows:
            print("No rows found. Exiting.")
            break

        print(f"\nPage {scroll_round}: {len(rows)} visible rows")

        for idx in range(len(rows)):
            try:
                rows = rows_in_view(sb)  # Refresh element handles
                row = rows[idx]
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) < 7:
                    continue

                row_data = [c.text.strip() for c in cells]
                row_id = "|".join(row_data)
                if not row_id or row_id in seen_rows:
                    continue
                seen_rows.add(row_id)

                # Scroll to and click the detail button
                sb.driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", cells[6]
                )
                cells[6].click()
                sb.wait_for_element(BACK_BTN_XP, timeout=25)

                detail_text = sb.driver.find_element(By.TAG_NAME, "body").text

                results.append({
                    "index": len(results),
                    "row_data": row_data,
                    "detail_text": detail_text
                })

                OUT_FILE.write_text(
                    json.dumps(results, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                print(f"Saved row #{len(results)-1}")

                sb.click(BACK_BTN_XP)
                sb.wait_for_element(*TABLE_SEL, timeout=30)

            except StaleElementReferenceException:
                continue
            except Exception as e:
                print(f"Row-handling error: {e}")
                try:
                    sb.click(BACK_BTN_XP)
                except Exception:
                    pass
                sb.wait_for_element(*TABLE_SEL, timeout=30)
                continue

        try:
            rows = rows_in_view(sb)
            bottom_before = last_row_id(rows[-1])

            sb.click(
                "table[ct='ST'] tr[role='row']:nth-last-of-type(2) "
                "td:nth-child(3)"
            )
            act = ActionChains(sb.driver)
            for _ in range(11):
                act.send_keys(Keys.ARROW_DOWN)
            act.perform()

            bottom_after = wait_new_rows(sb, bottom_before)

        except StaleElementReferenceException:
            continue
        except Exception as e:
            print(f"Scrolling error: {e}")
            break

        if bottom_after == bottom_before:
            stagnant_hits += 1
        else:
            stagnant_hits = 0

        if stagnant_hits >= 2:
            print("No new rows detected after scrolling. Exiting.")
            break

        scroll_round += 1

    print(f"\nFinished. Total unique rows scraped: {len(results)}")
    print(f"Output written to: {OUT_FILE.resolve()}")
