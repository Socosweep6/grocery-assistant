# Grocery Assistant: Phase Definitions

## Phase 1 - Mobile Web UI (this branch)

**Goal:** Add a phone-friendly browser experience to the existing Flask app so Vern can review the grocery list, create a draft, and approve it from a mobile browser without touching the CLI.

### What ships

| Route | Description |
|---|---|
| `GET /` | Dashboard: item count, flagged count, quick links |
| `GET /list` | Current grocery list grouped by category |
| `GET /flagged` | Items flagged as ambiguous / needing clarification |
| `GET /drafts/new` | Preview pending items before creating a draft |
| `POST /drafts/new` | Create a draft session; redirects to `/drafts/<id>` |
| `GET /drafts/<id>` | View a draft with all items and status |
| `POST /drafts/<id>/approve` | Approve a draft from the browser |
| `GET /login` | Token login page |
| `POST /login` | Validate token and set session cookie |
| `GET /logout` | Clear session |

All existing JSON API routes (`/api/*`) and CLI commands stay fully intact.

### Browser auth model

**Decision:** Single shared access token, set via `BROWSER_TOKEN` environment variable.

- Read-only pages (`/`, `/list`, `/flagged`, `GET /drafts/*`) need no login.
- Write actions (`POST /drafts/new`, `POST /drafts/<id>/approve`) require an active session.
- Login: enter the token at `/login`; Flask sets a session cookie valid for the browser session.
- No token set (`BROWSER_TOKEN` unset or empty): all write actions are blocked.

**Tradeoff accepted:** This is a single shared household secret, not per-user auth. It asserts "this is the household operator" (i.e., Vern). The approval route still calls the existing `submit_approval()` gate with `approver="vern"` and phrase `"approve order"`, so all four hard safety checks remain in force:

1. Approver must be Vern.
2. Session must exist.
3. Session must be in `awaiting_approval` status (not already approved, cancelled, or needs clarification).
4. Phrase must be in `APPROVED_PHRASES`.

**What this does NOT protect against:** token replay from browser history or shared device. For a household tool on a local network or behind ngrok with Vern as the sole user, that risk is acceptable. If you want stronger isolation, replace the session cookie check with HTTP Basic Auth or a per-device cookie.

**CSRF:** No CSRF tokens. Same-origin form POSTs on a household-only tool. Not worth the complexity at this scope.

### Implementation notes

- Server-rendered Jinja2 templates. No JS framework.
- Minimal CSS in `static/style.css`: mobile viewport, large touch targets, system font stack.
- Templates in `src/grocery_assistant/templates/`.
- Set `FLASK_SECRET_KEY` in your environment for stable sessions across restarts. If unset, a random key is generated at startup (sessions invalidated on restart).
- Set `BROWSER_TOKEN` to a strong random string before exposing via ngrok.

### How to run and verify

```bash
# Start the server (port 5000 default)
BROWSER_TOKEN=your-secret-token python3 -m grocery_assistant.web

# Or set in .env and source it:
source .env && python3 -m grocery_assistant.web
```

Open on phone (or browser):

| URL | What you see |
|---|---|
| `http://localhost:5000/` | Dashboard |
| `http://localhost:5000/list` | Grocery list by category |
| `http://localhost:5000/flagged` | Flagged / ambiguous items |
| `http://localhost:5000/drafts/new` | Preview list + create draft |
| `http://localhost:5000/drafts/<id>` | Draft detail + approve button |
| `http://localhost:5000/login` | Token login |

Via ngrok:
```bash
ngrok http 5000
# share the https://*.ngrok.io URL with household
```

### Tests

New test file: `tests/test_web_ui.py`

Run:
```bash
python3 -m pytest tests/test_web_ui.py -v
python3 -m pytest tests/ -v   # full suite
```

---

## Phase 2 - Shopping Handoff / Instacart Cart Fill

**Goal:** After Vern approves a draft in the browser, give her a frictionless path to Instacart. The household still places the actual order manually in Instacart; automation fills the cart so Vern only has to review and tap "Place order."

**Status: Planned only. Not implemented.**

### Problem statement

Phase 1 ends with an approved draft in the DB. To buy the items, Vern currently has to:
1. Open Instacart.
2. Search for each item manually.
3. Add to cart one by one.
4. Review and place order.

Phase 2 eliminates steps 2-3.

### Proposed architecture

**Option A: Instacart deep links (preferred for MVP)**

Instacart supports URL-based item search:
`https://www.instacart.com/store/search_v3/term?term=<query>`

The approved draft page (`GET /drafts/<id>`) could render a "Go shopping" section with:
- A list of tappable Instacart search links, one per item.
- Each link opens the Instacart search results for that item in a new tab/browser.

Pros: No automation, no API keys, no headless browser, no Terms of Service risk. Works on mobile Safari immediately.
Cons: Vern still taps each item individually. Reduces friction but doesn't fully automate cart fill.

**Option B: Playwright/Puppeteer cart automation (heavier)**

A background worker reads the approved session's items and drives a headless browser to:
1. Log in to Instacart (or use a saved session cookie).
2. Search each item and add the first result to cart.
3. Flag mismatches or out-of-stock items back to the app.

Pros: Fully automated cart fill. Vern only reviews and taps "Place order."
Cons: Brittle against Instacart UI changes. Requires storing Instacart credentials. May violate ToS. Needs careful error handling and retry logic.

### Recommended Phase 2 scope

Start with Option A (deep links) since it ships value immediately with zero infra:

1. Add a `GET /drafts/<id>/shop` page that lists all approved items as Instacart search links.
2. Or embed the shopping links directly in the approved draft view.
3. Add a "Mark as ordered" button so Vern can close out a session after placing the Instacart order manually.
4. Update item statuses to `ordered` when a session is marked complete.

Option B (automation) should be a separate follow-on phase if deep links prove insufficient.

### Open questions before planning Phase 2

1. Does Vern want to fill one item at a time (Option A) or fully automated cart (Option B)?
2. Is there a preferred Instacart store/retailer that affects the deep link format?
3. Should "mark as ordered" clear the grocery list (move items to `ordered` status) or just close the session?
4. Any preference on whether shopping links open in the same tab or new tab on mobile?
