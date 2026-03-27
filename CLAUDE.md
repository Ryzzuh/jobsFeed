# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A jobs aggregator focused on SEEK.com.au. The project has two parts:
- **Backend**: Flask REST API with Selenium scraping, containerized with Docker
- **Frontend**: Jupyter notebooks for scraping, parsing, and storing job listings in SQLite

## Running the Backend

### Docker (primary method — includes headless Chrome + Xvfb)
```bash
cd backend/
docker build -t jobs-aggregator-api .
docker run -p 5000:5000 jobs-aggregator-api
```

### Local Python
```bash
cd backend/
pip install -r requirements.txt
python app.py
```

API runs on `http://localhost:5000`.

**Endpoints:**
- `GET /test` — health check
- `POST /scraper` — scrape with JSON body `{"query": "<search term>"}`

## Running the Frontend (Jupyter)
```bash
cd frontend/
jupyter notebook main.ipynb
```

The primary scraping logic lives in `frontend/main.ipynb`. It scrapes SEEK job listings and writes results to `frontend/db/seek_app.sqlite`.

## Architecture

```
frontend/main.ipynb  →  SQLite (frontend/db/seek_app.sqlite)
                                       ↑
backend/app.py (Flask API)  ←  Docker container with bundled Chromium + Xvfb
```

**Backend** (`backend/app.py`):
- `start_xvfb()` — starts virtual display for headless Chrome in Docker
- `get_selenium_driver()` — creates Chrome WebDriver using bundled binary at `/app/chromium/`
- `get_data_with_selenium(query)` — core scraping function
- Chrome profile dirs are created per-request under `/app/tmp/chrome-profile-{uuid}`

**Frontend** (`frontend/main.ipynb`):
- Uses Selenium + `asyncio` + `ThreadPoolExecutor` for concurrent page scraping
- Converts relative SEEK dates ("2d", "3h") to hours
- Stores job IDs, posting dates, and listing details in SQLite

**Chrome binaries:**
- Linux (Docker): `backend/chromium/chrome-linux64/chrome` + `backend/chromium/chromedriver`
- Windows (local dev): `frontend/chromedriver-win64/`

## Database

SQLite at `frontend/db/seek_app.sqlite`. Accessed directly via `sqlite3` in the notebooks — no ORM.

## Branch Strategy

- `main` — main branch for PRs
- Feature branches like `feat/BE_jsonRequest` for in-progress work
