from flask import Flask, request, jsonify
import subprocess
import time
import os
import uuid
import shutil
import math
import re
import random
import asyncio
from string import Template
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from sqlite3 import Error
from contextlib import closing

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
CHROMEDRIVER_PATH = '/app/chromium/chromedriver'
CHROME_BINARY = '/app/chromium/chrome-linux64/chrome'
DB_PATH = os.environ.get('DB_PATH', '/app/db/seek_app.sqlite')
TMP_DIR = '/app/tmp'

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/117.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/117.0",
]

LOCATION_MAP = {
    'Melbourne': {'state': 'VIC', 'postcode': 3000},
    'Sydney':    {'state': 'NSW', 'postcode': 2000},
}

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Virtual display
# ---------------------------------------------------------------------------

def start_xvfb():
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":99"
        subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1920x1080x24"])
        time.sleep(2)


# ---------------------------------------------------------------------------
# Selenium driver (per-request profile dir)
# ---------------------------------------------------------------------------

def get_selenium_driver(user_agent=None):
    profile_dir = os.path.join(TMP_DIR, f"chrome-profile-{uuid.uuid4()}")
    options = Options()
    options.page_load_strategy = 'none'
    options.binary_location = CHROME_BINARY
    for arg in [
        "--disable-gpu", "--window-size=1920,1080", "--no-sandbox",
        "--disable-dev-shm-usage", "--log-level=3", "--no-first-run",
        "--disable-background-networking",
    ]:
        options.add_argument(arg)
    if user_agent:
        options.add_argument(f"--user-agent={user_agent}")
    options.add_argument(f"--user-data-dir={profile_dir}")
    service = Service(executable_path=CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    return driver, profile_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def calc_hours_to_sub(listing_date):
    m = re.match(r'(\d+)([hdm])(.*)', listing_date)
    if not m:
        return 0
    return math.prod([
        int(s) if s.isdigit() else 24 if s == 'd' else 1 if s == 'h' else 0.1 if s == 'm' else 0
        for s in m.groups()
    ])

def fmt_sql(v):
    """Format a value for SQL: NULL or escaped string."""
    return 'NULL' if v in (None, '') else '"' + str(v).replace('"', "''") + '"'


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_search_results_with_selenium(url):
    job_ads = {}
    driver, profile_dir = get_selenium_driver()
    try:
        driver.get(url)
        logger.info(f"Scraped {url}")
        WebDriverWait(driver, 22).until(
            EC.presence_of_all_elements_located((By.TAG_NAME, 'article'))
        )
        driver.execute_script("window.stop();")
        jobs = driver.execute_script("""
            let articles = Array.from(document.getElementsByTagName('article'))
            let jobs = {}
            articles.map(article => {
                let jobId = article.dataset.jobId
                jobs[jobId] = {}
                let elements = Array.from(article.querySelectorAll('[data-automation]'))
                return elements.map(el => {
                    let dataKey = el.dataset.automation
                    jobs[jobId][dataKey] = el.innerText.trim()
                })
            })
            return jobs
        """)
        job_ads.update(jobs)
    except Exception as e:
        logger.error(f"Error scraping {url}: {e}")
    finally:
        driver.quit()
        shutil.rmtree(profile_dir, ignore_errors=True)
    return job_ads


def fetch_job_page(job_id):
    driver, profile_dir = get_selenium_driver(user_agent=random.choice(USER_AGENTS))
    job_detail = {}
    try:
        time.sleep(random.uniform(1.5, 3.0))
        driver.get(f"https://www.seek.com.au/job/{job_id}")
        WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located((By.XPATH, '//div[@role="main"]'))
        )
        driver.execute_script("window.stop();")
        jscript = Template("""
            let jobId = $jobId
            let jobDocument = document.querySelector('[role="main"]')
            let elements = Array.from(jobDocument.querySelectorAll('[data-automation]'))
            let jobDetail = {[jobId]: elements.reduce((acc, el) => ({...acc, [el.dataset.automation]: el.innerText.trim()}), {})}
            return jobDetail
        """).safe_substitute(jobId=job_id)
        job_detail = driver.execute_script(jscript) or {}
    except Exception as e:
        logger.error(f"Failed fetching job {job_id}: {e}")
    finally:
        driver.quit()
        shutil.rmtree(profile_dir, ignore_errors=True)
    return job_detail


# ---------------------------------------------------------------------------
# Async orchestration
# ---------------------------------------------------------------------------

async def async_scrape_page(url, executor):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, scrape_search_results_with_selenium, url)


async def scrape_all_pages(urls):
    result = {}
    with ThreadPoolExecutor(max_workers=len(urls)) as executor:
        pages = await asyncio.gather(*[async_scrape_page(url, executor) for url in urls])
    for page in pages:
        result.update(page)
    return result


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    return conn


def db_write(command):
    conn = db_connect()
    with closing(conn.cursor()) as cursor:
        cursor.execute(command)
        conn.commit()
    conn.close()


def db_commandTemplate_insert_jobSearchResults(jobs_obj):
    now = datetime.now()
    now_ts = int(datetime.now(timezone.utc).timestamp())
    now_str = repr(now.strftime("%Y-%m-%d %H:%M:%S"))
    tz = repr(time.tzname[time.localtime().tm_isdst])

    search_result_keys = [
        'jobTitle', 'jobCompany', 'jobCardLocation', 'jobLocation',
        'jobSubClassification', 'jobClassification', 'jobShortDescription',
        'jobListingDate', 'jobSalary', ' job-list-view-job-link',
        'job-list-item-link-overlay', 'company-logo-container',
        'company-logo', 'signed-out-save-job',
    ]

    rows = []
    for job_id, val in jobs_obj.items():
        fields = ', '.join(fmt_sql(val.get(k)) for k in search_result_keys)
        listing_date = val.get('jobListingDate')
        hours = calc_hours_to_sub(listing_date) if listing_date else 0
        listing_dt = repr((now - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S"))
        rows.append(f"({job_id}, {fields}, {listing_dt}, {now_ts}, {now_str}, {now_str}, {tz})")

    return f"""INSERT OR IGNORE INTO job_listing (
    data_jobId, jobTitle, jobCompany, jobCardLocation, jobLocation,
    jobSubClassification, jobClassification, jobShortDescription,
    jobListingDate, jobSalary, job_list_view_job_link, job_list_item_link_overlay,
    company_logo_container, company_logo, signed_out_save_job,
    data_joblistingDateTime, data_createdTimestamp, data_createdDateTime,
    data_updatedDateTime, data_timezoneLocale
) VALUES {', '.join(rows)}"""


def db_commandTemplate_insert_jobSearchKWD(jobs_obj, search_terms):
    now_ts = int(datetime.now(timezone.utc).timestamp())
    now_str = repr(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    tz = repr(time.tzname[time.localtime().tm_isdst])
    role = repr(search_terms.get('searchTerm_role', ''))
    location = repr(search_terms.get('searchTerm_location', ''))

    rows = [
        f"({job_id}, {role}, {location}, {now_ts}, {now_str}, {now_str}, {tz})"
        for job_id in jobs_obj
    ]

    return f"""INSERT OR IGNORE INTO job_kwd (
    data_jobId, data_searchTerm_role, data_searchTerm_location,
    data_createdTimestamp, data_createdDateTime, data_updatedDateTime, data_timezoneLocale
) VALUES {', '.join(rows)}"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/scraper", methods=["POST"])
def scraper():
    data = request.get_json()
    role = data.get("searchTerm_role")
    location = data.get("searchTerm_location", "Melbourne")
    pages = int(data.get("pages", 3))

    if not role:
        return jsonify({"error": "Missing 'searchTerm_role'"}), 400

    loc = LOCATION_MAP.get(location, LOCATION_MAP["Melbourne"])
    role_slug = role.replace(" ", "-")
    urls = [
        f"https://www.seek.com.au/{role_slug}-jobs/in-{location}-{loc['state']}-{loc['postcode']}?page={i+1}"
        for i in range(pages)
    ]

    start_xvfb()

    try:
        result = asyncio.run(scrape_all_pages(urls))
        logger.info(f"Scraped {len(result)} ads for '{role}' in {location}.")

        search_terms = {"searchTerm_role": role, "searchTerm_location": location}
        if result:
            try:
                db_write(db_commandTemplate_insert_jobSearchResults(result))
                db_write(db_commandTemplate_insert_jobSearchKWD(result, search_terms))
            except Exception as e:
                logger.warning(f"DB write error: {e}")

        return jsonify({"count": len(result), "jobs": result})
    except Exception as e:
        logger.error(f"Scraper error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/test", methods=["GET"])
def test():
    return 'hello world'


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
