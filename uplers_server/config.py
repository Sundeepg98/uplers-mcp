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

# --- Storage tuning -------------------------------------------------------
# Two MCP clients open this file at once; a lock collision should be a short
# wait, not an error.
SQLITE_TIMEOUT_SECONDS = 15.0
SQLITE_BUSY_TIMEOUT_MS = 10000

# --- Profile --------------------------------------------------------------
# Seed source for the candidate profile. Override with UPLERS_RESUME.
DEFAULT_RESUME_PATH = Path(__file__).resolve().parent.parent.parent.parent / "resumes" / "Sundeep_Resume.md"

# --- Background freshness --------------------------------------------------
# Four syncs a day is ample: the native cohort turns over slowly (235 live
# requisitions), and every run is a guest on somebody's public endpoint.
AUTO_SYNC_INTERVAL_SECONDS = 6 * 3600
# How often the loop wakes to ask "is a sync due yet". Short enough that a
# laptop reopened after two days catches up in minutes, cheap enough to ignore.
AUTO_SYNC_POLL_SECONDS = 900
# Long enough to cover a full 235-record sync, short enough that a killed
# process frees the duty for the other MCP client quickly.
AUTO_SYNC_LEASE_TTL_SECONDS = 900
# Floor between sync ATTEMPTS, independent of whether one succeeded. A failed
# sync leaves last_sync untouched, so without this a broken endpoint would be
# retried on every poll forever.
AUTO_SYNC_RETRY_SECONDS = 1800
# Cap per background run, so a day's worth of expired records is spread over
# several runs instead of arriving as one 235-request burst.
AUTO_SYNC_FETCH_BUDGET = 120
# Let the server finish starting and answer its first tool call before any
# background network work begins.
AUTO_SYNC_STARTUP_DELAY_SECONDS = 10.0

# --- Follow-up -------------------------------------------------------------
# An application sitting in an active status this long is worth a nudge.
FOLLOW_UP_STALE_DAYS = 7
# Beyond this the local index is old enough that the brief should say so.
INDEX_STALE_HOURS = 36
