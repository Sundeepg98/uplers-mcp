"""Static configuration for the Uplers reader.

Everything here is a constant or an environment override. No secrets: the
endpoints this server uses are unauthenticated and explicitly Allow-ed in
https://platform.uplers.com/robots.txt.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_URL = "https://platform.uplers.com"
RECORD_PATH = "/api/single-hr-public"
SITEMAP_PATH = "/sitemap.xml"

# Public job page, useful for handing a human a link.
OPPORTUNITY_URL = BASE_URL + "/talent/all-opportunities/{hr_number}"

# --- Politeness -----------------------------------------------------------
# The service advertises X-RateLimit-Limit: 500. We stay far below it.
MAX_CONCURRENCY = 4
REQUEST_DELAY_SECONDS = 0.4
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 3

# Back off hard when the server says its budget is running out.
RATELIMIT_SLOW_BELOW = 100      # start pausing between requests
RATELIMIT_ABORT_BELOW = 20      # stop entirely and say so
RATELIMIT_SLOW_SLEEP_SECONDS = 3.0

# --- Caching --------------------------------------------------------------
RECORD_TTL_SECONDS = 24 * 3600          # a cached job record older than this is stale
SITEMAP_MIN_INTERVAL_SECONDS = 300      # do not re-pull a 4.8 MB sitemap more often

# Upper bound on records fetched by one uplers_sync_index() call.
DEFAULT_SYNC_FETCH_BUDGET = 300

# --- Storage --------------------------------------------------------------
_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR = Path(os.environ.get("UPLERS_DATA_DIR", _DEFAULT_DATA_DIR))
DB_PATH = DATA_DIR / "uplers.sqlite3"

# --- Record shaping -------------------------------------------------------
# Job descriptions are HTML and can run to several thousand words. Truncate
# for token economy; uplers_get_opportunity can be asked for the full text.
DESCRIPTION_PREVIEW_CHARS = 4000
COMPANY_ABOUT_PREVIEW_CHARS = 1200
