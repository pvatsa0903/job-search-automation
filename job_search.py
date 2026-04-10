#!/usr/bin/env python3
"""
Job Search Automation – Phalguni Vatsa
Finds Product Manager roles posted in the last 4 days at top tech companies.
Saves results/YYYY-MM-DD.json and regenerates index.html (GitHub Pages dashboard).
"""

import json
import os
import re
import sys
import time
import logging
import requests
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
DAYS    = 4
NOW     = datetime.now(timezone.utc)
CUTOFF  = NOW - timedelta(days=DAYS)

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
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

# ── Helpers ──────────────────────────────────────────────────────────────────
def is_pm(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in PM_KEYWORDS)

def is_recent(dt: datetime) -> bool:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= CUTOFF

def _get(url: str, verify=True, **kwargs) -> Optional[requests.Response]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, verify=verify, **kwargs)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"GET {url[:80]} → {e}")
        return None

def _post(url: str, verify=True, **kwargs) -> Optional[requests.Response]:
    h = {**HEADERS, "Content-Type": "application/json"}
    try:
        r = requests.post(url, headers=h, timeout=20, verify=verify, **kwargs)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"POST {url[:80]} → {e}")
        return None

def job(title, company, location, posted, url) -> Dict:
    return {
        "title":    title,
        "company":  company,
        "location": location or "",
        "posted":   posted,
        "url":      url or "",
    }

# ── Greenhouse ───────────────────────────────────────────────────────────────
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
            j.get("title", ""),
            company,
            (j.get("location") or {}).get("name", ""),
            posted.strftime("%Y-%m-%d"),
            j.get("absolute_url", ""),
        ))
    if out:
        log.info(f"  ✓ {company} (Greenhouse): {len(out)} role(s)")
    return out

# ── Lever ────────────────────────────────────────────────────────────────────
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
            j.get("text", ""),
            company,
            cats.get("location", ""),
            posted.strftime("%Y-%m-%d"),
            j.get("hostedUrl", ""),
        ))
    if out:
        log.info(f"  ✓ {company} (Lever): {len(out)} role(s)")
    return out

# ── Amazon ───────────────────────────────────────────────────────────────────
def amazon() -> List[Dict]:
    r = _get(
        "https://www.amazon.jobs/en/search.json",
        params={
            "base_query": "product manager",
            "category[]": "product-management",
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
            j.get("title", ""),
            "Amazon",
            j.get("location", ""),
            posted.strftime("%Y-%m-%d"),
            f"https://www.amazon.jobs{path}",
        ))
    if out:
        log.info(f"  ✓ Amazon: {len(out)} role(s)")
    return out

# ── Google ───────────────────────────────────────────────────────────────────
def google() -> List[Dict]:
    # careers.google.com redirects; use the resolved application URL directly
    r = _get(
        "https://www.google.com/about/careers/applications/api/jobs/jobs-v1/search/",
        params={"company": "Google", "q": "product manager", "page_size": 20},
    )
    if not r:
        return []
    out = []
    for j in r.json().get("jobs", []):
        if not is_pm(j.get("title", "")):
            continue
        try:
            posted = datetime.fromisoformat(j["publish_time"].replace("Z", "+00:00"))
        except Exception:
            continue
        if not is_recent(posted):
            continue
        jid = j.get("job_id", "")
        out.append(job(
            j.get("title", ""),
            "Google",
            ", ".join(j.get("locations", [])),
            posted.strftime("%Y-%m-%d"),
            f"https://careers.google.com/jobs/results/{jid}",
        ))
    if out:
        log.info(f"  ✓ Google: {len(out)} role(s)")
    return out

# ── Microsoft ────────────────────────────────────────────────────────────────
def microsoft() -> List[Dict]:
    r = _get(
        "https://gcsservices.careers.microsoft.com/search/api/v1/search",
        params={"q": "product manager", "l": "en_us", "pg": 1, "pgSz": 20, "o": "Relevance", "flt": "true"},
        verify=False,  # MS cert mismatch on azureedge CDN
    )
    if not r:
        return []
    try:
        jobs = r.json()["operationResult"]["result"]["jobs"]
    except Exception:
        return []
    out = []
    for j in jobs:
        if not is_pm(j.get("title", "")):
            continue
        try:
            posted = datetime.fromisoformat(j["postingDate"].replace("Z", "+00:00"))
        except Exception:
            continue
        if not is_recent(posted):
            continue
        jid = j.get("jobId", "")
        out.append(job(
            j.get("title", ""),
            "Microsoft",
            (j.get("properties") or {}).get("primaryLocation", ""),
            posted.strftime("%Y-%m-%d"),
            f"https://careers.microsoft.com/us/en/job/{jid}",
        ))
    if out:
        log.info(f"  ✓ Microsoft: {len(out)} role(s)")
    return out

# ── Meta ─────────────────────────────────────────────────────────────────────
def meta() -> List[Dict]:
    try:
        r = requests.post(
            "https://www.metacareers.com/graphql",
            headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "doc_id": "4027473364004692",
                "variables": json.dumps({
                    "search_input": {
                        "q": "product manager",
                        "divisions": ["Product Management"],
                        "sort_by_new": True,
                    }
                }),
            },
            timeout=20,
        )
        r.raise_for_status()
        jobs = r.json()["data"]["job_search"]["results"]
    except Exception as e:
        log.warning(f"Meta → {e}")
        return []
    out = []
    for j in jobs:
        if not is_pm(j.get("title", "")):
            continue
        ts = j.get("creation_time", 0)
        if not ts:
            continue
        posted = datetime.fromtimestamp(ts, tz=timezone.utc)
        if not is_recent(posted):
            continue
        locs  = j.get("locations", [])
        loc   = ", ".join(l.get("city", "") for l in locs if l.get("city"))
        jid   = j.get("id", "")
        out.append(job(
            j.get("title", ""),
            "Meta",
            loc,
            posted.strftime("%Y-%m-%d"),
            f"https://www.metacareers.com/jobs/{jid}/",
        ))
    if out:
        log.info(f"  ✓ Meta: {len(out)} role(s)")
    return out

# ── Workday (Adobe · Salesforce · PayPal) ────────────────────────────────────
_WD_RE = re.compile(r"(\d+)\s+day", re.I)

def _parse_wd_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    sl = s.lower()
    if "today" in sl or "0 days" in sl:
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
    r = _post(url, json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "product manager"})
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
            j.get("title", ""),
            company,
            j.get("locationsText", ""),
            posted.strftime("%Y-%m-%d"),
            f"https://{host}{path}",
        ))
    if out:
        log.info(f"  ✓ {company} (Workday): {len(out)} role(s)")
    return out

# ── Ashby ────────────────────────────────────────────────────────────────────
def ashby(company: str, slug: str) -> List[Dict]:
    """Public Ashby job board API – used by OpenAI, Mistral, etc."""
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
        locs = j.get("secondaryLocations", []) or []
        primary = j.get("primaryLocation", {}) or {}
        loc = primary.get("city", "") or (locs[0].get("city", "") if locs else "")
        out.append(job(
            j.get("title", ""),
            company,
            loc,
            posted.strftime("%Y-%m-%d"),
            j.get("jobUrl", ""),
        ))
    if out:
        log.info(f"  ✓ {company} (Ashby): {len(out)} role(s)")
    return out

# ── TikTok / ByteDance ───────────────────────────────────────────────────────
def tiktok() -> List[Dict]:
    r = _get(
        "https://jobs.bytedance.com/api/v1/search/job/posts",
        params={"keyword": "product manager", "page_size": 20, "page_index": 1, "portal": "true"},
    )
    if not r:
        return []
    out = []
    for j in r.json().get("data", {}).get("job_post_list", []):
        if not is_pm(j.get("title", "")):
            continue
        ts = j.get("publish_time", 0)
        try:
            posted = datetime.fromtimestamp(ts / 1000 if ts > 1e10 else ts, tz=timezone.utc)
        except Exception:
            continue
        if not is_recent(posted):
            continue
        jid = j.get("id", "")
        out.append(job(
            j.get("title", ""),
            "TikTok/ByteDance",
            j.get("city", ""),
            posted.strftime("%Y-%m-%d"),
            f"https://jobs.bytedance.com/en/position/{jid}" if jid else "",
        ))
    if out:
        log.info(f"  ✓ TikTok/ByteDance: {len(out)} role(s)")
    return out

# ── Uber ─────────────────────────────────────────────────────────────────────
def uber() -> List[Dict]:
    r = _post(
        "https://www.uber.com/api/loadSearchJobsResult",
        json={"params": {"query": "product manager", "department": ["Product"], "limit": 20, "page": 1}},
    )
    if not r:
        return []
    out = []
    for j in r.json().get("data", {}).get("results", []):
        if not is_pm(j.get("title", "")):
            continue
        try:
            posted = datetime.fromisoformat(j["publishedAt"].replace("Z", "+00:00"))
        except Exception:
            continue
        if not is_recent(posted):
            continue
        path = j.get("url", "")
        out.append(job(
            j.get("title", ""),
            "Uber",
            j.get("location", ""),
            posted.strftime("%Y-%m-%d"),
            path if path.startswith("http") else f"https://www.uber.com{path}",
        ))
    if out:
        log.info(f"  ✓ Uber: {len(out)} role(s)")
    return out

# ── Orchestration ────────────────────────────────────────────────────────────
GREENHOUSE_COMPANIES = [
    # (display name, board slug)
    ("Anthropic",     "anthropic"),
    ("Reddit",        "reddit"),
    ("Figma",         "figma"),
    ("Discord",       "discord"),
    ("Pinterest",     "pinterest"),
    ("Block",         "block"),
    ("Coinbase",      "coinbase"),
    ("Databricks",    "databricks"),
    ("Airbnb",        "airbnb"),
    ("Stripe",        "stripe"),
    ("Redfin",        "redfin"),
    ("Zillow",        "zillow"),
    ("Miro",          "miro"),
    ("LinkedIn",      "linkedin"),
    ("Notion",        "notion"),
]

LEVER_COMPANIES: list = []   # add lever board slugs here if needed

ASHBY_COMPANIES = [
    ("OpenAI",  "openai"),
    ("Shopify", "shopify"),
]

WORKDAY_COMPANIES = [
    # (display name, host, tenant, site-slug)
    ("Adobe",       "adobe.wd5.myworkdayjobs.com",       "adobe",      "ADBE_External"),
    ("Salesforce",  "salesforce.wd12.myworkdayjobs.com",  "Salesforce", "External_Career_Site"),
    ("PayPal",      "paypal.wd1.myworkdayjobs.com",       "paypal",     "jobs"),
    ("Snap",        "snap.wd1.myworkdayjobs.com",         "snap",       "External"),
    ("Atlassian",   "atlassian.wd5.myworkdayjobs.com",    "atlassian",  "atlassian"),
    ("Snowflake",   "snowflake.wd1.myworkdayjobs.com",    "snowflake",  "Snowflake-External-Careers"),
    ("DoorDash",    "doordash.wd5.myworkdayjobs.com",     "doordash",   "US-Careers"),
]

def run_all() -> List[Dict]:
    all_jobs: List[Dict] = []

    for name, board in GREENHOUSE_COMPANIES:
        try:
            all_jobs.extend(greenhouse(name, board))
        except Exception as e:
            log.error(f"  ✗ {name}: {e}")
        time.sleep(0.4)

    for name, board in LEVER_COMPANIES:
        try:
            all_jobs.extend(lever(name, board))
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

    for fn in (amazon, google, microsoft, meta, tiktok, uber):
        try:
            all_jobs.extend(fn())
        except Exception as e:
            log.error(f"  ✗ {fn.__name__}: {e}")
        time.sleep(0.5)

    # Deduplicate by URL
    seen, unique = set(), []
    for j in all_jobs:
        key = j["url"] or f"{j['company']}::{j['title']}"
        if key not in seen:
            seen.add(key)
            unique.append(j)

    return sorted(unique, key=lambda x: (x["posted"], x["company"]), reverse=True)

# ── Dashboard generator ──────────────────────────────────────────────────────
def load_all_results() -> Dict[str, List[Dict]]:
    """Load all JSON result files from the last 7 days."""
    cutoff7 = NOW - timedelta(days=7)
    data = {}
    for f in sorted(RESULTS_DIR.glob("*.json"), reverse=True):
        try:
            date_str = f.stem  # YYYY-MM-DD
            date_dt  = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if date_dt >= cutoff7:
                data[date_str] = json.loads(f.read_text())
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

    companies = sorted({j["company"] for j in all_jobs})
    run_dates = sorted(all_data.keys(), reverse=True)
    total     = len(all_jobs)

    json_blob = json.dumps(all_jobs, ensure_ascii=False)
    company_opts = "".join(
        f'<option value="{c}">{c}</option>' for c in companies
    )
    date_pills = ""
    for d in run_dates:
        cnt = len(all_data[d])
        date_pills += f'<button class="pill" data-date="{d}">{d} <span class="badge">{cnt}</span></button>\n'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Job Search — Phalguni Vatsa</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body {{ font-family: 'Inter', system-ui, sans-serif; background: #f8fafc; }}
    .pill {{
      display: inline-flex; align-items: center; gap: 6px;
      padding: 6px 14px; border-radius: 9999px; border: 1.5px solid #cbd5e1;
      font-size: .8rem; font-weight: 500; cursor: pointer; background: white;
      transition: all .15s;
    }}
    .pill.active {{ background: #1e40af; color: white; border-color: #1e40af; }}
    .pill:hover:not(.active) {{ border-color: #1e40af; color: #1e40af; }}
    .badge {{
      background: #e2e8f0; color: #475569; padding: 1px 7px;
      border-radius: 9999px; font-size: .72rem;
    }}
    .pill.active .badge {{ background: #3b82f6; color: white; }}
    .job-card {{
      background: white; border: 1px solid #e2e8f0; border-radius: 12px;
      padding: 18px 20px; transition: box-shadow .15s;
    }}
    .job-card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,.08); }}
    .company-badge {{
      display: inline-block; padding: 2px 10px; border-radius: 9999px;
      font-size: .72rem; font-weight: 600; background: #eff6ff; color: #1d4ed8;
    }}
    .apply-btn {{
      display: inline-flex; align-items: center; gap: 4px;
      padding: 7px 16px; background: #1e40af; color: white;
      border-radius: 8px; font-size: .82rem; font-weight: 500;
      text-decoration: none; transition: background .15s;
    }}
    .apply-btn:hover {{ background: #1d3a9e; }}
    #no-results {{ display: none; }}
  </style>
</head>
<body class="min-h-screen">

<!-- Header -->
<header class="bg-gradient-to-r from-blue-900 to-blue-700 text-white py-10 px-6">
  <div class="max-w-5xl mx-auto">
    <div class="flex items-start justify-between flex-wrap gap-4">
      <div>
        <h1 class="text-3xl font-bold tracking-tight">Job Search Dashboard</h1>
        <p class="mt-1 text-blue-200 text-sm">Phalguni Vatsa · Product Manager Roles · Updated automatically Mon–Thu</p>
      </div>
      <div class="text-right">
        <div class="text-4xl font-bold">{total}</div>
        <div class="text-blue-200 text-sm">roles found (last 7 days)</div>
      </div>
    </div>
  </div>
</header>

<!-- Controls -->
<div class="max-w-5xl mx-auto px-6 py-6 space-y-4">

  <!-- Run date pills -->
  <div class="flex flex-wrap gap-2 items-center">
    <span class="text-sm font-medium text-slate-500 mr-1">Run date:</span>
    <button class="pill active" data-date="all">All dates</button>
    {date_pills}
  </div>

  <!-- Search + company filter row -->
  <div class="flex flex-wrap gap-3">
    <input id="search" type="text" placeholder="Search roles…"
      class="flex-1 min-w-[200px] border border-slate-200 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"/>
    <select id="company-filter"
      class="border border-slate-200 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white">
      <option value="">All companies</option>
      {company_opts}
    </select>
  </div>

  <!-- Results count -->
  <p id="results-count" class="text-sm text-slate-400"></p>
</div>

<!-- Job list -->
<main class="max-w-5xl mx-auto px-6 pb-16">
  <div id="job-list" class="grid gap-3"></div>
  <div id="no-results" class="py-20 text-center text-slate-400">
    <div class="text-5xl mb-4">🔍</div>
    <p class="font-medium">No matching roles found</p>
    <p class="text-sm mt-1">Try adjusting filters or wait for the next automated run</p>
  </div>
</main>

<script>
const JOBS = {json_blob};

let activeDate = "all";
let searchQ    = "";
let company    = "";

const listEl   = document.getElementById("job-list");
const countEl  = document.getElementById("results-count");
const noResEl  = document.getElementById("no-results");

function render() {{
  const filtered = JOBS.filter(j => {{
    if (activeDate !== "all" && j.run_date !== activeDate) return false;
    if (company && j.company !== company) return false;
    if (searchQ) {{
      const q = searchQ.toLowerCase();
      if (!j.title.toLowerCase().includes(q) &&
          !j.company.toLowerCase().includes(q) &&
          !j.location.toLowerCase().includes(q)) return false;
    }}
    return true;
  }});

  listEl.innerHTML = filtered.map(j => `
    <div class="job-card">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="flex-1 min-w-0">
          <div class="flex flex-wrap items-center gap-2 mb-1">
            <span class="company-badge">${{j.company}}</span>
            <span class="text-xs text-slate-400">${{j.posted}}</span>
            ${{j.location ? `<span class="text-xs text-slate-400">📍 ${{j.location}}</span>` : ""}}
          </div>
          <h3 class="font-semibold text-slate-800 text-base leading-snug">${{j.title}}</h3>
        </div>
        ${{j.url ? `<a href="${{j.url}}" target="_blank" rel="noopener" class="apply-btn shrink-0">Apply ↗</a>` : ""}}
      </div>
    </div>
  `).join("");

  noResEl.style.display = filtered.length === 0 ? "block" : "none";
  countEl.textContent   = `Showing ${{filtered.length}} of ${{JOBS.length}} roles`;
}}

// Date pills
document.querySelectorAll(".pill[data-date]").forEach(btn => {{
  btn.addEventListener("click", () => {{
    document.querySelectorAll(".pill[data-date]").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    activeDate = btn.dataset.date;
    render();
  }});
}});

// Search
document.getElementById("search").addEventListener("input", e => {{
  searchQ = e.target.value.trim();
  render();
}});

// Company filter
document.getElementById("company-filter").addEventListener("change", e => {{
  company = e.target.value;
  render();
}});

render();
</script>
</body>
</html>"""

    DASHBOARD.write_text(html, encoding="utf-8")
    log.info(f"Dashboard written → {DASHBOARD}")

# ── Entry point ──────────────────────────────────────────────────────────────
def main():
    today = NOW.strftime("%Y-%m-%d")
    log.info(f"=== Job Search Run: {today} ===")

    jobs = run_all()

    result_file = RESULTS_DIR / f"{today}.json"
    result_file.write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"Saved {len(jobs)} role(s) → {result_file}")

    all_data = load_all_results()
    generate_dashboard(all_data)

    log.info(f"Done. {len(jobs)} PM role(s) found today.")
    return jobs

if __name__ == "__main__":
    main()
