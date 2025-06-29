from __future__ import annotations
import os, time, threading, atexit, sys, re, unicodedata
from io import StringIO
from pathlib import Path
import pandas as pd, gradio as gr
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import *

# ── helpers ─────────────────────────────────────────────────────
DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
def normalize(txt: str) -> str:
    txt = txt.replace("\u200e","").replace("\u200f","").translate(DIGIT_MAP)
    txt = re.sub(r"\s+", " ", txt).strip()
    parts = txt.split()
    if len(parts) > 1 and all(len(p) == 1 for p in parts):
        txt = "".join(parts)
    return txt

def has_arabic(s): return any("ARABIC" in unicodedata.name(ch,"") for ch in s)

def log(m,* ,ok=False,warn=False,err=False):
    if sys.stdout.isatty():
        c="\033[92m"if ok else"\033[93m"if warn else"\033[91m"if err else"\033[96m"
        print(c+m+"\033[0m")
    else: print(m)

# ── constants ───────────────────────────────────────────────────
URL="https://grpportal.rak.ae/irj/portal/judgement_publications"
SEL=dict(
    court='input[data-hint*="ZDE_COURT_TYPE"]',
    clas ='input[data-hint*="ZDE_COURT_CLASSIFY_TYPE"]',
    ctype='input[data-hint*="SCMGCASE_TYPE"]',
    year ='input[data-hint*="ZADTEL000019"]',
    num  ='#WD6D',
    search='#WD6F',
    clear ='#WD71',
    busy  ='div[id^="urBusyIndicator"]')
DATA_DIR="Data"; Path(DATA_DIR).mkdir(exist_ok=True)

# ── WebDriver (headless) ───────────────────────────────────────
opt=webdriver.ChromeOptions()
opt.add_argument("--headless=new")
opt.add_argument("--disable-gpu"); opt.add_argument("--no-sandbox")
opt.add_argument("--window-size=1920,1080")
drv=webdriver.Chrome(options=opt)
wait=WebDriverWait(drv,25)
atexit.register(drv.quit)
lock=threading.Lock()

# ── frame utilities ────────────────────────────────────────────
def dfs(css):
    try: drv.find_element(By.CSS_SELECTOR,css); return True
    except NoSuchElementException:
        for fr in drv.find_elements(By.TAG_NAME,"iframe"):
            drv.switch_to.frame(fr)
            if dfs(css): return True
            drv.switch_to.parent_frame()
    return False

def enter_form():
    deadline=time.time()+40
    while time.time()<deadline:
        drv.switch_to.default_content()
        if dfs(SEL["court"]):
            log("✓ داخل الإطار", ok=True); return
        time.sleep(1)
    raise RuntimeError("iframe النموذج غير موجود")

def idle():
    try: wait.until(
        EC.invisibility_of_element_located((By.CSS_SELECTOR,SEL["busy"])))
    except TimeoutException: pass

# ── combo box helpers ──────────────────────────────────────────
def current(css):
    try: return normalize(drv.find_element(By.CSS_SELECTOR,css).get_attribute("value"))
    except NoSuchElementException: return ""

def open_list(box):
    box.click(); time.sleep(0.25)
    if not drv.find_elements(By.CSS_SELECTOR,"div.lsListbox__value[role='option']"):
        box.send_keys(Keys.ARROW_DOWN)

def set_combo(css,val,label):
    if not val: return
    val = normalize(val)
    if current(css)==val:
        log(f"↷ {label} = {val} (no change)"); return
    for k in range(4):
        try:
            idle()
            box=drv.find_element(By.CSS_SELECTOR,css)
            drv.execute_script("arguments[0].removeAttribute('readonly')",box)
            open_list(box)
            opt=wait.until(EC.element_to_be_clickable(
                (By.XPATH,f"//div[@ct='LIB_I' and normalize-space()='{val}']")))
            opt.click(); log(f"✓ {label} ← {val}",ok=True)
            if css==SEL["court"]: time.sleep(0.8)
            return
        except Exception:
            log(f"retry {k+1}/4 {label}",warn=True); time.sleep(0.6)
    raise RuntimeError(f"لا يمكن اختيار {label}")

def list_opts(css,label):
    idle(); box=drv.find_element(By.CSS_SELECTOR,css)
    drv.execute_script("arguments[0].removeAttribute('readonly')",box)
    open_list(box)
    items=wait.until(EC.presence_of_all_elements_located(
        (By.CSS_SELECTOR,"div.lsListbox__value[role='option']")))
    names=[normalize(i.text) for i in items if normalize(i.text)]
    box.send_keys(Keys.ESCAPE)
    log(f"✓ {label} options ({len(names)})",ok=True); return names

# ── fixed-path grid helpers ─────────────────────────────────────
GRID_PATH = [1, 0]          # root → iframe[1] → iframe[0]

def switch_to_grid_frame():
    drv.switch_to.default_content()
    for idx in GRID_PATH:
        frames = drv.find_elements(By.TAG_NAME, "iframe")
        if idx >= len(frames):
            raise RuntimeError("تغيّر هيكل الإطارات")
        drv.switch_to.frame(frames[idx])
    # last hop: the inline <iframe srcdoc="..."> created by Web-Dynpro
    inner = drv.find_elements(By.TAG_NAME, "iframe")
    if inner:
        drv.switch_to.frame(inner[0])

def wait_grid_df(timeout=15) -> pd.DataFrame|None:
    switch_to_grid_frame()
    deadline = time.time() + timeout
    headers  = ("رقم القضية", "Case/File No.")
    while time.time() < deadline:
        html = drv.page_source
        if any(h in html for h in headers):
            df = pick_table(html)
            if df is not None and not df.empty:
                return df
        time.sleep(0.5)
    return None

# ── table picker (header-based) ─────────────────────────────────
def pick_table(html)->pd.DataFrame|None:
    soup=BeautifulSoup(html,"lxml")
    hdr_tbl=soup.select_one(
        "table:has(td:contains('رقم القضية'), th:contains('رقم القضية'))")
    if hdr_tbl:
        return pd.read_html(StringIO(str(hdr_tbl)),flavor="lxml")[0]
    for tbl in soup.select("table"):
        hdr=" ".join(td.get_text() for td in tbl.find("tr").find_all(["td","th"]))
        if has_arabic(hdr) and len(tbl.find_all("tr"))>=3:
            return pd.read_html(StringIO(str(tbl)),flavor="lxml")[0]
    return None

# ── NEW: crawl every iframe for the first non-empty table ───────
def crawl_for_df() -> pd.DataFrame|None:
    def _dfs() -> pd.DataFrame|None:
        df = pick_table(drv.page_source)
        if df is not None and not df.empty:
            return df
        for fr in drv.find_elements(By.TAG_NAME,"iframe"):
            drv.switch_to.frame(fr)
            try:
                found = _dfs()
                if found is not None and not found.empty:
                    return found
            finally:
                drv.switch_to.parent_frame()
        return None
    return _dfs()

# ── initialise page & dropdown lists ───────────────────────────
with lock:
    drv.get(URL); log("landing page")
    enter_form()
    DEG=list_opts(SEL["court"],"درجة القضاء")
    YRS=list_opts(SEL["year" ],"السنة")

last_df:pd.DataFrame|None=None
def norm(x): return None if x in ("",None,"None") else x

# ── Gradio callbacks ───────────────────────────────────────────
def cb_cls(d):
    if not d: return gr.Dropdown()
    with lock:
        set_combo(SEL["court"],d,"درجة")
        return gr.Dropdown(choices=list_opts(SEL["clas"],"التصنيف"))

def cb_typ(d,c):
    if not (d and c): return gr.Dropdown()
    with lock:
        set_combo(SEL["court"],d,"درجة"); set_combo(SEL["clas"],c,"التصنيف")
        return gr.Dropdown(choices=list_opts(SEL["ctype"],"النوع"))

def do_search(deg,cls,typ,yr,num):
    global last_df
    deg,cls,typ,yr = map(norm,(deg,cls,typ,yr))
    with lock:
        try:
            log(f"--- بحث {deg=} {cls=} {typ=} {yr=} {num=}")
            enter_form()
            set_combo(SEL["court"],deg,"درجة")
            set_combo(SEL["clas"], cls,"التصنيف")
            set_combo(SEL["ctype"],typ,"النوع")
            set_combo(SEL["year"], yr,"السنة")
            b=drv.find_element(By.CSS_SELECTOR,SEL["num"]); b.clear()
            if num: b.send_keys(num)
            drv.find_element(By.CSS_SELECTOR,SEL["search"]).click(); idle()

            df = wait_grid_df()        # ← NEW: exact-frame wait
            if df is None:
                last_df=None
                return "لا توجد بيانات", gr.update(visible=False), gr.update(visible=False), ""

            if df.iloc[:,0].astype(str).str.strip().eq("").all():
                df = df.iloc[:,1:]
            last_df = df
            return f"عُثر على {len(df)} صفوف.", gr.update(visible=True), gr.update(visible=True), ""
        except Exception as e:
            last_df=None
            return f"⚠ {e}", gr.update(visible=False), gr.update(visible=False), ""
        
def save_json(name):
    if last_df is None: return "لا توجد بيانات للحفظ."
    if not name: return "أدخل اسم الملف."
    path=Path(DATA_DIR)/f"{name}.json"
    if path.exists(): return "⚠ الاسم مستخدم، اختر اسمًا آخر."
    last_df.to_json(path,orient="records",force_ascii=False,indent=2)
    log(f"✓ saved {path}",ok=True)
    return f"✓ تم الحفظ إلى {path}"

def clear_all():
    global last_df
    with lock:
        try: drv.find_element(By.CSS_SELECTOR,SEL["clear"]).click()
        except NoSuchElementException: pass
        enter_form(); last_df=None
    return None,None,None,None,"",gr.update(visible=False),gr.update(visible=False),""

# ── UI (unchanged) ─────────────────────────────────────────────
with gr.Blocks(title="سـاحـة الأحكام") as demo:
    gr.Markdown("### استعلام أحكام دائرة محاكم رأس الخيمة")
    with gr.Row():
        deg=gr.Dropdown(label="درجة",choices=DEG,interactive=True)
        cls=gr.Dropdown(label="التصنيف",interactive=True)
        typ=gr.Dropdown(label="النوع",interactive=True)
    with gr.Row():
        yr =gr.Dropdown(label="السنة",choices=YRS,interactive=True)
        num=gr.Textbox(label="رقم القضية",lines=1)
    msg   =gr.Markdown()
    fname =gr.Textbox(label="اسم ملف JSON",visible=False)
    save_b=gr.Button("حفظ",visible=False)
    save_m=gr.Markdown()

    deg.change(cb_cls, inputs=deg, outputs=cls)
    cls.change(cb_typ, inputs=[deg,cls], outputs=typ)

    gr.Button("بحث").click(do_search,
        inputs=[deg,cls,typ,yr,num],
        outputs=[msg,fname,save_b,save_m])
    save_b.click(save_json, fname, save_m)
    gr.Button("مسح").click(clear_all,
        outputs=[deg,cls,typ,yr,num,msg,fname,save_b,save_m])

if __name__=="__main__":
    demo.launch()