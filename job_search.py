#!/usr/bin/env python3
"""
Job Search Automation – Phalguni Vatsa
Senior PM | Growth · Monetization · AI · Consumer · User Lifecycle | 10 yrs B2B/B2C SaaS

Sources
  API-based  : Greenhouse, Ashby, Lever, Workday, Amazon (search.json), PayPal
  Playwright : Meta, Google, Amazon (category pages), Discord, Figma
  HTML scrape: Anthropic (SSR table)

Output
  results/YYYY-MM-DD.json   – raw jobs (dated + undated, with fit score)
  index.html                – 2-tab dashboard (dated | undated) + High/Med/Low filter
"""

import json, re, time, logging, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)
DASHBOARD   = SCRIPT_DIR / "index.html"

# ── Constants ────────────────────────────────────────────────────────────────
DAYS   = 4
NOW    = datetime.now(timezone.utc)
CUTOFF = NOW - timedelta(days=DAYS)

PM_KEYWORDS = [
    "product manager", "product owner", "head of product",
    "director of product", "vp of product", "vp, product",
    "principal product", "group product manager",
    "staff product manager", "product lead", "lead product",
    "product strategy", "product management",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

# ── Profile fit scoring ───────────────────────────────────────────────────────
# Based on Phalguni's resume: 10 yrs B2B/B2C SaaS, CVS Health, Autodesk
# Core strengths: user lifecycle, growth, monetization, AI, engagement/retention, 0→1

_HIGH_DOMAINS = [
    "growth", "monetization", "engagement", "retention", "consumer",
    "personalization", "recommendation", "user journey", "user lifecycle",
    "gamif", "onboarding", "activation", "subscription", "payments",
    "checkout", "experimentation", "a/b test", "loyalty", "rewards",
    "zero to one", "0 to 1", "0→1", "data product",
    "ai product", "machine learning", "b2c", "habit", "stickiness",
    "notification", "lifecycle", "incentive", "member", "conversion",
    "funnel", "churn", "dau", "mau", "behavioral",
]
_SENIOR_WORDS = [
    "senior", "staff", "principal", "group product", "lead product",
    "director", "head of product", "vp product", "vp of product",
]
_JUNIOR_WORDS = [
    "associate product", "associate pm", " apm", "junior pm",
    "entry level", "internship", "new grad",
]
_LOW_DOMAINS = [
    "hardware pm", "supply chain", "manufacturing pm", "network pm",
    "security pm", "infrastructure pm", "internal tools pm",
    "legal pm", "physical product pm", "dev tools pm",
]


def score_fit(title: str, description: str = "") -> str:
    text = (title + " " + description).lower()

    if any(k in text for k in _JUNIOR_WORDS):
        return "Low"

    high_hits  = sum(1 for d in _HIGH_DOMAINS if d in text)
    is_senior  = any(k in text for k in _SENIOR_WORDS)
    is_low_dom = any(k in text for k in _LOW_DOMAINS)

    if is_low_dom and not high_hits:
        return "Low"
    if high_hits >= 2:
        return "High"
    if high_hits == 1 and is_senior:
        return "High"
    if high_hits == 1:
        return "Medium"
    if is_senior:
        return "Medium"
    return "Medium"


# ── Shared helpers ────────────────────────────────────────────────────────────

def is_pm(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in PM_KEYWORDS)


def is_recent(dt: datetime) -> bool:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= CUTOFF


def parse_relative_date(text: str) -> Optional[datetime]:
    if not text:
        return None
    t = text.lower()
    if any(w in t for w in ["today", "just now", "hour", "minute"]):
        return NOW
    if "yesterday" in t:
        return NOW - timedelta(days=1)
    m = re.search(r"(\d+)\s*day", t)
    if m:
        return NOW - timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\s*week", t)
    if m:
        return NOW - timedelta(days=int(m.group(1)) * 7)
    m = re.search(r"(\d+)\s*month", t)
    if m:
        return NOW - timedelta(days=int(m.group(1)) * 30)
    return None


def _get(url: str, verify: bool = True, **kwargs) -> Optional[requests.Response]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, verify=verify, **kwargs)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"GET {url[:80]} → {e}")
        return None


def _post(url: str, verify: bool = True, **kwargs) -> Optional[requests.Response]:
    h = {**HEADERS, "Content-Type": "application/json"}
    try:
        r = requests.post(url, headers=h, timeout=20, verify=verify, **kwargs)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"POST {url[:80]} → {e}")
        return None


def job(title: str, company: str, location: str, posted: str,
        url: str, fit: Optional[str] = None) -> Dict:
    return {
        "title":    title,
        "company":  company,
        "location": location or "",
        "posted":   posted,          # "" means no date available
        "url":      url or "",
        "fit":      fit or score_fit(title),
    }


# ══════════════════════════════════════════════════════════════════════════════
# API-BASED SCRAPERS
# ══════════════════════════════════════════════════════════════════════════════

def greenhouse(company: str, board: str) -> List[Dict]:
    r = _get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs")
    if not r:
        return []
    out = []
    for j in r.json().get("jobs", []):
        if not is_pm(j.get("title", "")):
            continue
        try:
            posted = datetime.fromisoformat(j["updated_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        if not is_recent(posted):
            continue
        out.append(job(
            j.get("title", ""), company,
            (j.get("location") or {}).get("name", ""),
            posted.strftime("%Y-%m-%d"),
            j.get("absolute_url", ""),
        ))
    if out:
        log.info(f"  ✓ {company} (Greenhouse): {len(out)} role(s)")
    return out


def ashby(company: str, slug: str) -> List[Dict]:
    r = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not r:
        return []
    out = []
    for j in r.json().get("jobs", []):
        if not is_pm(j.get("title", "")):
            continue
        published = j.get("publishedDate", "")
        if not published:
            continue
        try:
            posted = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except Exception:
            continue
        if not is_recent(posted):
            continue
        primary = j.get("primaryLocation") or {}
        loc = primary.get("city", "")
        out.append(job(
            j.get("title", ""), company, loc,
            posted.strftime("%Y-%m-%d"),
            j.get("jobUrl", ""),
        ))
    if out:
        log.info(f"  ✓ {company} (Ashby): {len(out)} role(s)")
    return out


def lever(company: str, board: str) -> List[Dict]:
    r = _get(f"https://api.lever.co/v0/postings/{board}?mode=json")
    if not r:
        return []
    out = []
    for j in r.json():
        if not is_pm(j.get("text", "")):
            continue
        ts = j.get("createdAt", 0)
        posted = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        if not is_recent(posted):
            continue
        cats = j.get("categories", {})
        out.append(job(
            j.get("text", ""), company,
            cats.get("location", ""),
            posted.strftime("%Y-%m-%d"),
            j.get("hostedUrl", ""),
        ))
    if out:
        log.info(f"  ✓ {company} (Lever): {len(out)} role(s)")
    return out


_WD_RE = re.compile(r"(\d+)\s+day", re.I)

def _parse_wd_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    sl = s.lower()
    if "today" in sl:
        return NOW
    if "yesterday" in sl:
        return NOW - timedelta(days=1)
    m = _WD_RE.search(sl)
    if m:
        return NOW - timedelta(days=int(m.group(1)))
    if "30+" in sl or "month" in sl:
        return NOW - timedelta(days=40)
    return None


def workday(company: str, host: str, tenant: str, site: str) -> List[Dict]:
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    r = _post(url, json={"appliedFacets": {}, "limit": 20, "offset": 0,
                          "searchText": "product manager"})
    if not r:
        return []
    out = []
    for j in r.json().get("jobPostings", []):
        if not is_pm(j.get("title", "")):
            continue
        posted = _parse_wd_date(j.get("postedOn", ""))
        if not posted or not is_recent(posted):
            continue
        path = j.get("externalPath", "")
        out.append(job(
            j.get("title", ""), company,
            j.get("locationsText", ""),
            posted.strftime("%Y-%m-%d"),
            f"https://{host}{path}",
        ))
    if out:
        log.info(f"  ✓ {company} (Workday): {len(out)} role(s)")
    return out


def amazon_api() -> List[Dict]:
    """amazon.jobs/en/search.json using category slugs from the official category pages."""
    r = _get(
        "https://www.amazon.jobs/en/search.json",
        params={
            "category[]": [
                "project-program-product-management-technical",
                "project-program-product-management-non-tech",
            ],
            "result_limit": 100,
            "sort": "recent",
        },
    )
    if not r:
        return []
    out = []
    for j in r.json().get("jobs", []):
        if not is_pm(j.get("title", "")):
            continue
        try:
            posted = datetime.strptime(j["posted_date"], "%B %d, %Y").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if not is_recent(posted):
            continue
        path = j.get("job_path", "")
        out.append(job(
            j.get("title", ""), "Amazon",
            j.get("location", ""),
            posted.strftime("%Y-%m-%d"),
            f"https://www.amazon.jobs{path}",
        ))
    if out:
        log.info(f"  ✓ Amazon (API): {len(out)} role(s)")
    return out


def anthropic_scrape() -> List[Dict]:
    """Scrape anthropic.com/careers/jobs HTML table directly (no date available)."""
    from bs4 import BeautifulSoup
    html_headers = {**HEADERS, "Accept": "text/html,application/xhtml+xml,*/*"}
    try:
        import requests as _req
        r = _req.get("https://www.anthropic.com/careers/jobs",
                     headers=html_headers, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log.warning(f"Anthropic scrape → {e}")
        return []
    if not r:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        link = row.find("a", href=re.compile(r"greenhouse\.io"))
        if not link:
            continue
        url = link.get("href", "")
        title = ""
        for cell in cells:
            if cell.find("a", href=re.compile(r"greenhouse")):
                title = re.sub(r"\s*Apply\s*$", "", cell.get_text(strip=True), flags=re.I).strip()
                break
        if not title:
            title = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        if not is_pm(title):
            continue
        location = cells[-1].get_text(strip=True)
        out.append(job(title, "Anthropic", location, "", url))   # no date
    if out:
        log.info(f"  ✓ Anthropic (HTML): {len(out)} role(s) [no date]")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# PLAYWRIGHT SCRAPERS  (response-interception pattern)
# ══════════════════════════════════════════════════════════════════════════════

def _meta_pw(browser) -> List[Dict]:
    captured: List[dict] = []

    def on_response(resp):
        if "metacareers.com/graphql" in resp.url:
            try:
                data = resp.json()
                results = ((data.get("data") or {})
                           .get("job_search", {})
                           .get("results", []))
                captured.extend(results)
            except Exception:
                pass

    page = browser.new_page()
    page.on("response", on_response)
    try:
        for url in [
            # URL 1 – keyword + offices (user-provided)
            ("https://www.metacareers.com/jobsearch?q=Product%20Manager&sort_by_new=true"
             "&offices[0]=San%20Francisco%2C%20CA&offices[1]=Remote%2C%20US"
             "&offices[2]=Menlo%20Park%2C%20CA&offices[3]=New%20York%2C%20NY"
             "&roles[0]=Full%20time%20employment"),
            # URL 2 – Product Management team (user-provided)
            "https://www.metacareers.com/jobsearch?teams[0]=Product%20Management&roles[0]=Full%20time%20employment",
        ]:
            page.goto(url, wait_until="networkidle", timeout=35000)
            page.wait_for_timeout(3000)
    except Exception as e:
        log.warning(f"Meta page: {e}")
    finally:
        page.close()

    out, seen = [], set()
    for j in captured:
        title = j.get("title", "")
        if not is_pm(title) or title in seen:
            continue
        seen.add(title)
        ts = j.get("creation_time", 0)
        if ts:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            if not is_recent(dt):
                continue
            posted_str = dt.strftime("%Y-%m-%d")
        else:
            posted_str = ""
        jid  = j.get("id", "")
        locs = j.get("locations", [])
        loc  = ", ".join(l.get("city", "") for l in locs if l.get("city"))
        out.append(job(title, "Meta", loc, posted_str,
                       f"https://www.metacareers.com/jobs/{jid}/"))
    if out:
        log.info(f"  ✓ Meta (Playwright): {len(out)} role(s)")
    return out


def _google_pw(browser) -> List[Dict]:
    captured: List[dict] = []

    def on_response(resp):
        if "careers.google.com" in resp.url or (
                "google.com" in resp.url and "jobs" in resp.url):
            try:
                data = resp.json()
                if isinstance(data, dict) and "jobs" in data:
                    captured.extend(data["jobs"])
            except Exception:
                pass

    page = browser.new_page()
    page.on("response", on_response)
    try:
        # User-provided URL (employment_type=FULL_TIME)
        page.goto(
            "https://www.google.com/about/careers/applications/jobs/results"
            "?employment_type=FULL_TIME&q=product+manager",
            wait_until="networkidle", timeout=35000,
        )
        page.wait_for_timeout(4000)
    except Exception as e:
        log.warning(f"Google page: {e}")
    finally:
        page.close()

    out = []
    for j in captured:
        title = j.get("title", "")
        if not is_pm(title):
            continue
        pub = j.get("publish_time", "")
        if pub:
            try:
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                if not is_recent(dt):
                    continue
                posted_str = dt.strftime("%Y-%m-%d")
            except Exception:
                posted_str = ""
        else:
            posted_str = ""
        jid = j.get("job_id", "")
        out.append(job(
            title, "Google",
            ", ".join(j.get("locations", [])),
            posted_str,
            f"https://careers.google.com/jobs/results/{jid}",
        ))
    if out:
        log.info(f"  ✓ Google (Playwright): {len(out)} role(s)")
    return out


def _amazon_pw(browser) -> List[Dict]:
    """Load the user-provided Amazon category pages and capture the search API response."""
    captured: List[dict] = []

    def on_response(resp):
        url = resp.url
        if "amazon.jobs" in url and "search" in url and "content" not in url:
            try:
                data = resp.json()
                jobs = data.get("jobs", data.get("hits", []))
                if jobs:
                    captured.extend(jobs)
            except Exception:
                pass

    page = browser.new_page()
    page.on("response", on_response)
    try:
        for url in [
            # User-provided category page URLs
            "https://amazon.jobs/content/en/job-categories/project-program-product-management-technical",
            "https://amazon.jobs/content/en/job-categories/project-program-product-management-non-tech",
        ]:
            page.goto(url, wait_until="networkidle", timeout=35000)
            page.wait_for_timeout(3000)
    except Exception as e:
        log.warning(f"Amazon page: {e}")
    finally:
        page.close()

    out, seen = [], set()
    for j in captured:
        title = j.get("title", "")
        if not is_pm(title) or title in seen:
            continue
        seen.add(title)
        try:
            posted = datetime.strptime(j["posted_date"], "%B %d, %Y").replace(tzinfo=timezone.utc)
            if not is_recent(posted):
                continue
            posted_str = posted.strftime("%Y-%m-%d")
        except Exception:
            posted_str = ""
        path = j.get("job_path", "")
        out.append(job(
            title, "Amazon",
            j.get("location", ""),
            posted_str,
            f"https://www.amazon.jobs{path}",
        ))
    if out:
        log.info(f"  ✓ Amazon (Playwright): {len(out)} role(s)")
    return out


def _discord_pw(browser) -> List[Dict]:
    """Discord's own page calls api.greenhouse.io — intercept that response."""
    captured: List[dict] = []

    def on_response(resp):
        if "api.greenhouse.io" in resp.url and "discord" in resp.url:
            try:
                data = resp.json()
                captured.extend(data.get("jobs", []))
            except Exception:
                pass

    page = browser.new_page()
    page.on("response", on_response)
    try:
        page.goto("https://discord.com/careers", wait_until="networkidle", timeout=35000)
        page.wait_for_timeout(5000)
    except Exception as e:
        log.warning(f"Discord page: {e}")
    finally:
        page.close()

    out = []
    for j in captured:
        title = j.get("title", "")
        if not is_pm(title):
            continue
        try:
            posted = datetime.fromisoformat(j["updated_at"].replace("Z", "+00:00"))
            if not is_recent(posted):
                continue
            posted_str = posted.strftime("%Y-%m-%d")
        except Exception:
            posted_str = ""
        out.append(job(
            title, "Discord",
            (j.get("location") or {}).get("name", ""),
            posted_str,
            j.get("absolute_url", ""),
        ))
    if out:
        log.info(f"  ✓ Discord (Playwright): {len(out)} role(s)")
    return out


def _figma_pw(browser) -> List[Dict]:
    """Intercept whatever ATS Figma's careers page calls."""
    captured: List[dict] = []

    def on_response(resp):
        url = resp.url
        if any(x in url for x in ["greenhouse.io", "ashbyhq.com",
                                   "lever.co", "figma.com/api"]):
            try:
                data = resp.json()
                jobs = data.get("jobs", data.get("postings", []))
                if jobs:
                    captured.extend(jobs)
            except Exception:
                pass

    page = browser.new_page()
    page.on("response", on_response)
    try:
        page.goto("https://www.figma.com/careers/", wait_until="networkidle", timeout=35000)
        page.wait_for_timeout(4000)
    except Exception as e:
        log.warning(f"Figma page: {e}")
    finally:
        page.close()

    out = []
    for j in captured:
        title = j.get("title", j.get("text", ""))
        if not is_pm(title):
            continue
        posted_str = ""
        for field in ["updated_at", "publishedDate", "createdAt"]:
            val = j.get(field)
            if val:
                try:
                    dt = (datetime.fromtimestamp(val / 1000, tz=timezone.utc)
                          if isinstance(val, int) else
                          datetime.fromisoformat(str(val).replace("Z", "+00:00")))
                    if not is_recent(dt):
                        break
                    posted_str = dt.strftime("%Y-%m-%d")
                    break
                except Exception:
                    pass
        url_val = j.get("absolute_url", j.get("hostedUrl", j.get("jobUrl", "")))
        loc = (j.get("location") or {}).get("name", "") or \
              (j.get("categories") or {}).get("location", "")
        out.append(job(title, "Figma", loc, posted_str, url_val))
    if out:
        log.info(f"  ✓ Figma (Playwright): {len(out)} role(s)")
    return out


def run_playwright_scrapers() -> List[Dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("Playwright not installed — skipping browser-based scrapers")
        return []

    all_jobs: List[Dict] = []
    scrapers = [_meta_pw, _google_pw, _amazon_pw, _discord_pw, _figma_pw]

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled"],
            )
            for scraper in scrapers:
                try:
                    jobs = scraper(browser)
                    all_jobs.extend(jobs)
                    time.sleep(1)
                except Exception as e:
                    log.error(f"  ✗ {scraper.__name__}: {e}")
            browser.close()
    except Exception as e:
        log.error(f"Playwright browser failed: {e}")

    return all_jobs


# ══════════════════════════════════════════════════════════════════════════════
# COMPANY LISTS
# ══════════════════════════════════════════════════════════════════════════════

GREENHOUSE_COMPANIES = [
    # Companies confirmed on Greenhouse
    ("Reddit",     "reddit"),
    ("Pinterest",  "pinterest"),
    ("Block",      "block"),
    ("Coinbase",   "coinbase"),
    ("Databricks", "databricks"),
    ("Airbnb",     "airbnb"),
    ("Stripe",     "stripe"),
    ("Redfin",     "redfin"),
    ("Zillow",     "zillow"),
    ("LinkedIn",   "linkedin"),
]

ASHBY_COMPANIES = [
    ("OpenAI",  "openai"),
    ("Notion",  "notion"),   # notion.com/careers uses Ashby
    ("Shopify", "shopify"),
    ("Miro",    "miro"),
]

WORKDAY_COMPANIES = [
    # (name, host, tenant, site)
    ("PayPal", "paypal.wd1.myworkdayjobs.com", "paypal", "jobs"),
]

# Playwright handles: Meta, Google, Amazon, Discord, Figma
# HTML scrape handles: Anthropic


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════════

def run_all() -> List[Dict]:
    all_jobs: List[Dict] = []

    log.info("── API scrapers ─────────────────────────────────────────")
    for name, board in GREENHOUSE_COMPANIES:
        try:
            all_jobs.extend(greenhouse(name, board))
        except Exception as e:
            log.error(f"  ✗ {name}: {e}")
        time.sleep(0.4)

    for name, slug in ASHBY_COMPANIES:
        try:
            all_jobs.extend(ashby(name, slug))
        except Exception as e:
            log.error(f"  ✗ {name}: {e}")
        time.sleep(0.4)

    for name, host, tenant, site in WORKDAY_COMPANIES:
        try:
            all_jobs.extend(workday(name, host, tenant, site))
        except Exception as e:
            log.error(f"  ✗ {name}: {e}")
        time.sleep(0.4)

    try:
        all_jobs.extend(amazon_api())
    except Exception as e:
        log.error(f"  ✗ Amazon API: {e}")

    try:
        all_jobs.extend(anthropic_scrape())
    except Exception as e:
        log.error(f"  ✗ Anthropic: {e}")

    log.info("── Playwright scrapers ──────────────────────────────────")
    try:
        all_jobs.extend(run_playwright_scrapers())
    except Exception as e:
        log.error(f"  ✗ Playwright: {e}")

    # Deduplicate by URL (fallback to company::title)
    seen, unique = set(), []
    for j in all_jobs:
        key = j["url"] or f"{j['company']}::{j['title']}"
        if key not in seen:
            seen.add(key)
            unique.append(j)

    return sorted(unique, key=lambda x: (x["posted"], x["company"]), reverse=True)


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def load_all_results() -> Dict[str, List[Dict]]:
    cutoff7 = NOW - timedelta(days=7)
    data: Dict[str, List[Dict]] = {}
    for f in sorted(RESULTS_DIR.glob("*.json"), reverse=True):
        try:
            date_dt = datetime.strptime(f.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if date_dt >= cutoff7:
                data[f.stem] = json.loads(f.read_text())
        except Exception:
            continue
    return data


def generate_dashboard(all_data: Dict[str, List[Dict]]) -> None:
    all_jobs = []
    for date, jobs in all_data.items():
        for j in jobs:
            j = dict(j)
            j["run_date"] = date
            all_jobs.append(j)

    dated   = [j for j in all_jobs if j.get("posted")]
    undated = [j for j in all_jobs if not j.get("posted")]

    run_dates  = sorted(all_data.keys(), reverse=True)
    companies  = sorted({j["company"] for j in all_jobs})

    def company_opts(jobs):
        cos = sorted({j["company"] for j in jobs})
        return "".join(f'<option value="{c}">{c}</option>' for c in cos)

    def date_pills(jobs):
        dates = sorted({j["run_date"] for j in jobs}, reverse=True)
        html  = '<button class="pill active" data-date="all">All dates</button>\n'
        for d in dates:
            cnt = sum(1 for j in jobs if j["run_date"] == d)
            html += f'<button class="pill" data-date="{d}">{d} <span class="badge">{cnt}</span></button>\n'
        return html

    json_dated   = json.dumps(dated,   ensure_ascii=False)
    json_undated = json.dumps(undated, ensure_ascii=False)

    DASHBOARD.write_text(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Job Search — Phalguni Vatsa</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body {{ font-family: system-ui, sans-serif; background:#f8fafc; }}

    /* Tab nav */
    .tab-nav {{ display:flex; gap:4px; border-bottom:2px solid #e2e8f0; margin-bottom:24px; }}
    .tab-btn {{
      padding:10px 20px; font-size:.9rem; font-weight:600; cursor:pointer;
      border:none; background:transparent; color:#64748b;
      border-bottom:3px solid transparent; margin-bottom:-2px; transition:all .15s;
    }}
    .tab-btn.active {{ color:#1e40af; border-bottom-color:#1e40af; }}
    .tab-btn:hover:not(.active) {{ color:#334155; }}
    .tab-panel {{ display:none; }}
    .tab-panel.active {{ display:block; }}

    /* Pills */
    .pill {{
      display:inline-flex; align-items:center; gap:5px;
      padding:5px 12px; border-radius:9999px; border:1.5px solid #cbd5e1;
      font-size:.78rem; font-weight:500; cursor:pointer; background:white; transition:all .15s;
    }}
    .pill.active {{ background:#1e40af; color:white; border-color:#1e40af; }}
    .pill:hover:not(.active) {{ border-color:#1e40af; color:#1e40af; }}
    .badge {{
      background:#e2e8f0; color:#475569; padding:1px 6px;
      border-radius:9999px; font-size:.7rem;
    }}
    .pill.active .badge {{ background:#3b82f6; color:white; }}

    /* Fit badges */
    .fit-high   {{ background:#dcfce7; color:#166534; }}
    .fit-medium {{ background:#fef9c3; color:#854d0e; }}
    .fit-low    {{ background:#f1f5f9; color:#475569; }}
    .fit-badge  {{
      display:inline-block; padding:2px 9px; border-radius:9999px;
      font-size:.7rem; font-weight:700; letter-spacing:.03em;
    }}

    /* Fit filter buttons */
    .fit-pill {{
      display:inline-flex; align-items:center; gap:4px;
      padding:4px 12px; border-radius:9999px; border:1.5px solid #e2e8f0;
      font-size:.75rem; font-weight:600; cursor:pointer; background:white; transition:all .15s;
    }}
    .fit-pill.active-high   {{ background:#dcfce7; color:#166534; border-color:#86efac; }}
    .fit-pill.active-medium {{ background:#fef9c3; color:#854d0e; border-color:#fde68a; }}
    .fit-pill.active-low    {{ background:#f1f5f9; color:#475569; border-color:#cbd5e1; }}
    .fit-pill.active-all    {{ background:#1e40af; color:white;   border-color:#1e40af; }}

    /* Job card */
    .job-card {{
      background:white; border:1px solid #e2e8f0; border-radius:12px;
      padding:16px 20px; transition:box-shadow .15s;
    }}
    .job-card:hover {{ box-shadow:0 4px 16px rgba(0,0,0,.08); }}
    .company-tag {{
      display:inline-block; padding:2px 9px; border-radius:9999px;
      font-size:.72rem; font-weight:600; background:#eff6ff; color:#1d4ed8;
    }}
    .apply-btn {{
      display:inline-flex; align-items:center; gap:4px;
      padding:7px 15px; background:#1e40af; color:white;
      border-radius:8px; font-size:.8rem; font-weight:500;
      text-decoration:none; transition:background .15s; white-space:nowrap;
    }}
    .apply-btn:hover {{ background:#1d3a9e; }}
  </style>
</head>
<body class="min-h-screen">

<!-- Header -->
<header class="bg-gradient-to-r from-blue-900 to-blue-700 text-white py-10 px-6">
  <div class="max-w-5xl mx-auto flex flex-wrap items-start justify-between gap-4">
    <div>
      <h1 class="text-3xl font-bold tracking-tight">Job Search Dashboard</h1>
      <p class="mt-1 text-blue-200 text-sm">Phalguni Vatsa · PM Roles · Auto-updated Mon–Thu 3 pm PST</p>
    </div>
    <div class="text-right">
      <div class="text-4xl font-bold">{len(dated)}</div>
      <div class="text-blue-200 text-sm">dated roles (7 days)</div>
      <div class="text-sm text-blue-300 mt-1">{len(undated)} undated listings</div>
    </div>
  </div>
</header>

<div class="max-w-5xl mx-auto px-6 pt-8 pb-16">

  <!-- Tabs -->
  <div class="tab-nav">
    <button class="tab-btn active" data-tab="dated">
      With Posting Date <span class="ml-1 text-xs font-normal opacity-70">({len(dated)})</span>
    </button>
    <button class="tab-btn" data-tab="undated">
      New / Untracked <span class="ml-1 text-xs font-normal opacity-70">({len(undated)})</span>
    </button>
  </div>

  <!-- ── TAB 1: DATED ───────────────────────────────────────────── -->
  <div id="panel-dated" class="tab-panel active">

    <!-- Run-date pills -->
    <div class="flex flex-wrap gap-2 items-center mb-3">
      <span class="text-xs font-medium text-slate-400 mr-1">Run date:</span>
      {date_pills(dated)}
    </div>

    <!-- Fit filter -->
    <div class="flex flex-wrap gap-2 items-center mb-3">
      <span class="text-xs font-medium text-slate-400 mr-1">Fit:</span>
      <button class="fit-pill active-all"    data-fit-dated="all"    >All</button>
      <button class="fit-pill"               data-fit-dated="High"   >🟢 High</button>
      <button class="fit-pill"               data-fit-dated="Medium" >🟡 Medium</button>
      <button class="fit-pill"               data-fit-dated="Low"    >⚪ Low</button>
    </div>

    <!-- Search + company -->
    <div class="flex flex-wrap gap-3 mb-3">
      <input id="search-dated" type="text" placeholder="Search roles…"
        class="flex-1 min-w-[200px] border border-slate-200 rounded-lg px-4 py-2 text-sm
               focus:outline-none focus:ring-2 focus:ring-blue-500"/>
      <select id="co-dated"
        class="border border-slate-200 rounded-lg px-4 py-2 text-sm bg-white
               focus:outline-none focus:ring-2 focus:ring-blue-500">
        <option value="">All companies</option>
        {company_opts(dated)}
      </select>
    </div>
    <p id="count-dated" class="text-xs text-slate-400 mb-4"></p>
    <div id="list-dated"   class="grid gap-3"></div>
    <div id="empty-dated"  class="hidden py-20 text-center text-slate-400">
      <div class="text-5xl mb-3">🔍</div><p class="font-medium">No matching roles</p>
    </div>
  </div>

  <!-- ── TAB 2: UNDATED ─────────────────────────────────────────── -->
  <div id="panel-undated" class="tab-panel">
    <p class="text-sm text-slate-500 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 mb-4">
      ⏱ These roles come from career pages that don't expose posting dates.
      They're shown here for completeness — check each listing for the actual date.
    </p>

    <!-- Fit filter -->
    <div class="flex flex-wrap gap-2 items-center mb-3">
      <span class="text-xs font-medium text-slate-400 mr-1">Fit:</span>
      <button class="fit-pill active-all"    data-fit-undated="all"    >All</button>
      <button class="fit-pill"               data-fit-undated="High"   >🟢 High</button>
      <button class="fit-pill"               data-fit-undated="Medium" >🟡 Medium</button>
      <button class="fit-pill"               data-fit-undated="Low"    >⚪ Low</button>
    </div>

    <!-- Search + company -->
    <div class="flex flex-wrap gap-3 mb-3">
      <input id="search-undated" type="text" placeholder="Search roles…"
        class="flex-1 min-w-[200px] border border-slate-200 rounded-lg px-4 py-2 text-sm
               focus:outline-none focus:ring-2 focus:ring-blue-500"/>
      <select id="co-undated"
        class="border border-slate-200 rounded-lg px-4 py-2 text-sm bg-white
               focus:outline-none focus:ring-2 focus:ring-blue-500">
        <option value="">All companies</option>
        {company_opts(undated)}
      </select>
    </div>
    <p id="count-undated" class="text-xs text-slate-400 mb-4"></p>
    <div id="list-undated"  class="grid gap-3"></div>
    <div id="empty-undated" class="hidden py-20 text-center text-slate-400">
      <div class="text-5xl mb-3">🔍</div><p class="font-medium">No matching roles</p>
    </div>
  </div>

</div><!-- /max-w -->

<script>
// ── Data ────────────────────────────────────────────────────────────────────
const DATED   = {json_dated};
const UNDATED = {json_undated};

// ── State ───────────────────────────────────────────────────────────────────
const state = {{
  dated:   {{ date:"all", fit:"all", search:"", company:"" }},
  undated: {{ fit:"all",  search:"", company:"" }},
}};

// ── Fit badge helper ────────────────────────────────────────────────────────
function fitBadge(fit) {{
  const cls = fit === "High" ? "fit-high" : fit === "Medium" ? "fit-medium" : "fit-low";
  return `<span class="fit-badge ${{cls}}">${{fit}}</span>`;
}}

// ── Render a tab ─────────────────────────────────────────────────────────────
function render(tab) {{
  const jobs  = tab === "dated" ? DATED : UNDATED;
  const s     = state[tab];
  const listEl  = document.getElementById(`list-${{tab}}`);
  const countEl = document.getElementById(`count-${{tab}}`);
  const emptyEl = document.getElementById(`empty-${{tab}}`);

  const filtered = jobs.filter(j => {{
    if (tab === "dated" && s.date !== "all" && j.run_date !== s.date) return false;
    if (s.fit     !== "all" && j.fit     !== s.fit)     return false;
    if (s.company !== ""    && j.company !== s.company) return false;
    if (s.search) {{
      const q = s.search.toLowerCase();
      if (!j.title.toLowerCase().includes(q) &&
          !j.company.toLowerCase().includes(q) &&
          !(j.location||"").toLowerCase().includes(q)) return false;
    }}
    return true;
  }});

  listEl.innerHTML = filtered.map(j => `
    <div class="job-card">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="flex-1 min-w-0">
          <div class="flex flex-wrap items-center gap-2 mb-1">
            <span class="company-tag">${{j.company}}</span>
            ${{fitBadge(j.fit)}}
            ${{j.posted ? `<span class="text-xs text-slate-400">${{j.posted}}</span>` : ""}}
            ${{j.location ? `<span class="text-xs text-slate-400">📍 ${{j.location}}</span>` : ""}}
          </div>
          <h3 class="font-semibold text-slate-800 text-[15px] leading-snug">${{j.title}}</h3>
          ${{j.match_reason ? `<p class="text-xs text-slate-500 italic mt-1">💡 ${{j.match_reason}}</p>` : ""}}
        </div>
        ${{j.url ? `<a href="${{j.url}}" target="_blank" rel="noopener" class="apply-btn shrink-0">Apply ↗</a>` : ""}}
      </div>
    </div>`).join("");

  const show = filtered.length > 0;
  emptyEl.style.display = show ? "none" : "block";
  countEl.textContent   = `Showing ${{filtered.length}} of ${{jobs.length}} roles`;
}}

// ── Tab switching ─────────────────────────────────────────────────────────────
document.querySelectorAll(".tab-btn").forEach(btn => {{
  btn.addEventListener("click", () => {{
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`panel-${{btn.dataset.tab}}`).classList.add("active");
  }});
}});

// ── Date pills (dated tab) ────────────────────────────────────────────────────
document.querySelectorAll(".pill[data-date]").forEach(btn => {{
  btn.addEventListener("click", () => {{
    document.querySelectorAll(".pill[data-date]").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    state.dated.date = btn.dataset.date;
    render("dated");
  }});
}});

// ── Fit filter (both tabs) ────────────────────────────────────────────────────
function setupFitPills(tab) {{
  const attr = `data-fit-${{tab}}`;
  document.querySelectorAll(`[${{attr}}]`).forEach(btn => {{
    btn.addEventListener("click", () => {{
      document.querySelectorAll(`[${{attr}}]`).forEach(b => {{
        b.className = "fit-pill";   // reset
      }});
      const val = btn.getAttribute(attr);
      btn.className = `fit-pill active-${{val.toLowerCase()}}`;
      state[tab].fit = val;
      render(tab);
    }});
  }});
}}
setupFitPills("dated");
setupFitPills("undated");

// ── Search ────────────────────────────────────────────────────────────────────
["dated","undated"].forEach(tab => {{
  document.getElementById(`search-${{tab}}`).addEventListener("input", e => {{
    state[tab].search = e.target.value.trim();
    render(tab);
  }});
  document.getElementById(`co-${{tab}}`).addEventListener("change", e => {{
    state[tab].company = e.target.value;
    render(tab);
  }});
}});

// ── Init ──────────────────────────────────────────────────────────────────────
render("dated");
render("undated");
</script>
</body>
</html>""", encoding="utf-8")
    log.info(f"Dashboard written → {DASHBOARD}")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# MATCH REASON  (Claude Haiku — 1 API call for all jobs)
# ══════════════════════════════════════════════════════════════════════════════

_PROFILE_SUMMARY = (
    "Phalguni Vatsa — Senior PM, 10 yrs B2B/B2C SaaS. "
    "Owns the full user lifecycle: onboarding, activation, engagement, retention, and monetization. "
    "CVS Health (30M-user consumer app): scaled $17M+ monetization platform (gift card checkout + incentives), "
    "led 0→1 AI personalization + recommendation engine, gamified retention loops (Badges, Streaks, Team Challenges), "
    "multichannel notification strategy, membership tiering, onboarding funnel re-architecture (+20% activation). "
    "Autodesk ($5B+ ARR subscription): renewal automation, VoC dashboard (NPS +20pts), personalized checkout upsell/cross-sell. "
    "Core skills: user journey optimization, growth, monetization, engagement/retention loops, AI-driven personalization, "
    "experimentation/A/B testing, 0→1 launches, B2C consumer SaaS, behavioral analytics, DAU/MAU growth."
)


def generate_match_reasons(jobs: List[Dict]) -> List[Dict]:
    """Call Claude Haiku once with all jobs batched; add match_reason to each."""
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping match reasons")
        for j in jobs:
            j.setdefault("match_reason", "")
        return jobs

    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed — skipping match reasons")
        for j in jobs:
            j.setdefault("match_reason", "")
        return jobs

    # Build numbered job list for the prompt
    lines = [
        f"{i+1}. {j['company']} | {j['title']}"
        + (f" | {j['location']}" if j.get("location") else "")
        for i, j in enumerate(jobs)
    ]

    prompt = (
        f"Candidate profile: {_PROFILE_SUMMARY}\n\n"
        "For each job below write exactly ONE sentence (≤15 words) explaining why it matches "
        "this candidate's specific experience. Be concrete — mention the overlapping skill or domain. "
        "Return a JSON array of strings only, one string per job, in the same order.\n\n"
        "Jobs:\n" + "\n".join(lines)
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        reasons: List[str] = json.loads(m.group(0)) if m else []
        for i, j in enumerate(jobs):
            j["match_reason"] = reasons[i] if i < len(reasons) else ""
        log.info(f"  ✓ Match reasons generated for {len(jobs)} roles")
    except Exception as e:
        log.warning(f"Match reason generation failed: {e}")
        for j in jobs:
            j.setdefault("match_reason", "")

    return jobs


def main():
    today = NOW.strftime("%Y-%m-%d")
    log.info(f"=== Job Search Run: {today} ===")

    jobs = run_all()
    log.info("── Match reasons (Claude Haiku) ─────────────────────────")
    jobs = generate_match_reasons(jobs)

    result_file = RESULTS_DIR / f"{today}.json"
    result_file.write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"Saved {len(jobs)} role(s) → {result_file}")

    all_data = load_all_results()
    generate_dashboard(all_data)

    dated_count   = sum(1 for j in jobs if j.get("posted"))
    undated_count = sum(1 for j in jobs if not j.get("posted"))
    high  = sum(1 for j in jobs if j.get("fit") == "High")
    med   = sum(1 for j in jobs if j.get("fit") == "Medium")
    low   = sum(1 for j in jobs if j.get("fit") == "Low")
    log.info(
        f"Done. {len(jobs)} roles  |  "
        f"dated: {dated_count}  undated: {undated_count}  |  "
        f"High: {high}  Medium: {med}  Low: {low}"
    )


if __name__ == "__main__":
    main()
