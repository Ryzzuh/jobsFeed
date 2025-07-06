from flask import Flask, request, jsonify
import subprocess
import time
import os
import tempfile
import uuid
import shutil

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ANSI colors
c = (
    "\033[0m",   # End of color
    "\033[36m",  # Cyan
    "\033[91m",  # Red
    "\033[35m",  # Magenta
)


app = Flask(__name__)

def start_xvfb():
    """Starts virtual display if not already running."""
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":99"
        subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1920x1080x24"])
        time.sleep(2)  # give Xvfb time to start

def get_data_with_selenium(query):
    print(f"{c[1]}Your Text Here{c[0]}", flush=True)
    
    """Selenium job to run with GUI in virtual display."""
    start_xvfb()

    # Set up Chrome options
    options = Options()
    options.page_load_strategy = 'none'
    # options.binary_location = f'{os.getcwd()}/app/chromium/chromium-browser'
    options.binary_location = f'/app/chromium/chrome-linux64/chrome'
    print(options.binary_location)
    options.add_argument("--disable-gpu")  # Optional
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=3")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-background-networking")

    
    # Path to ChromeDriver binary (adjust if needed)
    chromedriver_path = f'/app/chromium/chromedriver'
    print('chromedriver_path: ', chromedriver_path)
    
    service = Service(executable_path=chromedriver_path)

    # Use a temporary directory for Chrome user data
    profile_dir = f"/app/tmp/chrome-profile-{uuid.uuid4()}"
    options.add_argument(f"--user-data-dir={profile_dir}")
    
    # Create the WebDriver
    driver = webdriver.Chrome(service=service, options=options)

    try:
        # Use the driver
        driver.get("https://www.selenium.dev/selenium/web/web-form.html")
        title = driver.title
        print("Page title:", title)
    finally:
        # Clean up
        driver.quit()
        time.sleep(2)
        shutil.rmtree(profile_dir, ignore_errors=True)

    return title

@app.route("/scraper", methods=["POST"])
def scraper():
    print('scraping...')
    data = request.get_json()
    query = data.get("query")

    if not query:
        return jsonify({"error": "Missing 'query' parameter"}), 400

    try:
        result = get_data_with_selenium(query)
        return jsonify({"title": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/test", methods=["GET"])
def test():
    return 'hello world'

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)