"""Route constants and enums for the authenticated talent API.

Every constant here was extracted from Uplers' own production React bundle
(`/build/apptalent/js/app.js` plus its 85 lazy chunks, 13.4 MB total) on
2026-08-21 and cross-checked against a live unauthenticated probe. The full
evidence, with verbatim call-site excerpts, is in
`mcp-servers/_audit/2026-08-21-uplers-bundle-callsites.md`.

Three facts drive everything downstream, and all three CORRECT the earlier
route-map research in `tools/uplers-api-research.md`:

1.  **Auth is a bearer token, not a cookie session.** Every call site does
    ``Authorization: Bearer <localStorage["token"] ?? localStorage["guest_token"]>``.
    The `uplers_session` cookie exists but the SPA never relies on it, and
    `X-XSRF-TOKEN` is never attached by application code - the only occurrences
    in the bundle are inside axios's own bundled default config.

2.  **The logged-out signal is a 401, not a 302.** MEASURED live: with
    ``Accept: application/json`` every ``talent/*`` route answers
    ``401 {"message":"Unauthenticated."}``; without it Laravel's
    `Authenticate` middleware redirects to `/console/login` with an HTML body.
    Since this client always asks for JSON, 401 is the normal signal - but the
    302 is still handled, because a middleware change should not read as
    "logged in".

3.  **`hr_id` names two different identifier spaces.** See IDENTIFIER_SPACES.
    Sending the wrong one is a silent no-op or a 422, not an obvious error.
"""

from __future__ import annotations

from . import config

# Absolute base for every authenticated call. The SPA sets no axios baseURL and
# builds absolute URLs by string concatenation, so this mirrors it exactly.
API_BASE = config.BASE_URL + "/api/"

# Where an unauthenticated browser-shaped request gets redirected. Seeing this
# in a Location header means "not logged in", never "moved".
LOGIN_REDIRECT = config.BASE_URL + "/console/login"

# The page a human signs in on. NOT the same as LOGIN_REDIRECT: the API
# redirects unauthenticated browser-shaped requests to /console/login, but the
# talent-facing sign-in page is /login, and it is the one carrying Google SSO.
# Conflating the two opened the wrong page and the operator could not sign in.
LOGIN_URL = config.BASE_URL + "/login"

# --- Reads ----------------------------------------------------------------

EP_OPPORTUNITIES = "talent/hr/opportunities"          # GET, query string
EP_MY_OPPORTUNITIES = "talent/hr/my-opportunities"    # GET, query string
EP_SINGLE_HR = "talent/hr/single-hr"                  # GET, ?hr_number=
EP_TAILOR_JOBS = "talent/hr/tailor-jobs"              # POST JSON {HR_Number}
EP_PROFILE = "talent/profile"                         # GET (POST upserts)
EP_ACCOUNT_STATUS = "talent/account/status"           # GET, no params

EP_ROLE_MASTER = "talent/hr/all-opp-role-master"
EP_SKILL_MASTER = "talent/hr/all-opp-skill-master"
EP_LOCATION_MASTER = "talent/hr/all-opp-location-master"
EP_COMPANY_MASTER = "talent/hr/all-opp-company-master"

#: Read-only list of the operator's own interviews.
#:
#: NAMESPACE NOTE, deliberate and flagged: this sits under ``talent/outreach/``,
#: which is otherwise excluded from this server because that prefix is where
#: Uplers' paid outreach-agent product lives. This one route is a plain GET of
#: the operator's OWN interview schedule - reading your own calendar is using
#: the platform normally, not reimplementing a SKU. The write half of the pair
#: (``talent/outreach/interview-feedback``) is deliberately NOT built.
EP_INTERVIEW_LIST = "talent/outreach/interview-list"  # GET, ?detailed=true

# The route used to prove a session is real. Chosen because its 401-when-logged-out
# behaviour was MEASURED live on 2026-08-21, not assumed.
EP_AUTH_PROBE = EP_PROFILE
AUTH_PROBE_NOTE = 'GET /api/talent/profile (401 {"message":"Unauthenticated."} when logged out)'

# --- Writes (shapes recorded; only job-not-interested is built) ------------

EP_INTRESTED = "talent/hr/intrested"                  # POST multipart - THIS IS APPLY
EP_NOT_INTERESTED = "talent/hr/job-not-interested"    # POST JSON, reversible

#: THE ONLY ROUTE IN THIS SERVER THAT CHANGES WHO HE IS. Everything else writes
#: to a requisition; this writes to him.
#:
#: **REPLACEMENT SEMANTICS - an omitted skill is DELETED.** Body is
#: ``{"field": "skills", "value": [<EVERY skill>], "tid"?}`` and the response
#: `res.data.data` is the saved ARRAY.
#:
#: This is a DIFFERENT route from `talent/profile`, and the difference is the
#: dangerous part. `talent/profile` POST carries a section-keyed SINGULAR
#: envelope (`{experience: {...}}`, `{achievmentsNew: {...}}`) - a per-entity
#: upsert, paired with `talent/profile/delete-details` for removal. This one
#: carries `{field, value}` and replaces the whole field. Confusing the two
#: means sending one skill to a route that treats it as the complete list.
#:
#: VERIFIED: chunk 196 module 30196 @122419, resolved through app.js module
#: 26878 (`P7`) to module 81935 (`Imf`). The proof that removal is an omission
#: rather than a delete call is their own remove handler at @126363, which
#: splices the local array and issues no request. Skills is also the only
#: profile section with NO delete route - all six siblings have one. Full
#: evidence: `_audit/2026-08-21-uplers-skills-write-shape.md`.
EP_PROFILE_UPSERT = "talent/profile-upsert"           # POST JSON {field, value}
EP_CANCEL_OPPORTUNITY = "talent/hr/cancel-opportunity"  # POST JSON, dead code in this build
EP_UPDATE_SAVED_HR = "talent/hr/update-saved-hr"      # POST JSON {hr_id: enc_id, type}

# --- Enums, verbatim from bundle module 22000 -----------------------------

SORT_FIELDS = ("relevance", "created_at")

#: Experience filter values are "min,max" RANGE STRINGS, not numbers.
EXPERIENCE_BANDS = (
    "0,2", "2,4", "4,6", "6,8", "8,10", "10,12", "12,14",
)

#: `engagements` is a JSON-encoded array of objects: [{"type": "Remote"}].
ENGAGEMENT_MODES = ("Onsite", "Hybrid", "Remote")

#: The only `company_type` value appearing anywhere in 13.4 MB of bundle.
DEFAULT_COMPANY_TYPE = "maang"

# --- Identifier spaces ----------------------------------------------------

#: Three identifiers name the same requisition, and the API is not consistent
#: about which it wants. Getting this wrong is the most likely silent bug in
#: any client of this API, so it is written down rather than remembered.
IDENTIFIER_SPACES = {
    "id": "Plain numeric id. Sent as `hr_id` by intrested and cancel-opportunity.",
    "enc_id": "Encrypted id. Sent as `hr_id` by update-saved-hr and assign-assessment.",
    "HR_Number": (
        "The public 'HR...' string. Used by single-hr (?hr_number=), "
        "my-opportunities (activeJob=), job-not-interested (hr_number) and "
        "everything in this server's public tier."
    ),
}

# --- Response envelopes ---------------------------------------------------

#: Laravel paginator routes: rows live at res["hrs"]["data"].
PAGINATED_ROUTES = (EP_OPPORTUNITIES, EP_MY_OPPORTUNITIES)

#: Uplers uses BOTH a string and a numeric success flag, on different routes.
#: update-saved-hr checks `status === "success"`; recommendations checks
#: `status === 1`. Never write one check for both.
SUCCESS_STRING = "success"
SUCCESS_NUMERIC = 1
