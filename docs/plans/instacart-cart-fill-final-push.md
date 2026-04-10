# Instacart Cart Fill Final Push Plan

_Date: 2026-04-10_
_Branch: `feat/shopping-handoff-phase2`_

## Blunt read first

There is no supported public Instacart cart API here. The only realistic path is browser automation with a saved logged-in browser session. That means this phase is inherently brittle.

What will break eventually:
- Instacart selectors and page flow will change.
- The saved login session will expire.
- Cloudflare / bot checks may block headless automation.
- Search results will sometimes pick the wrong product.
- Store context can drift after session refresh or login.

This plan is still worth doing because it gets us from today's manual deep-link handoff to a practical local-first cart-fill assist, while keeping the final review and place-order step in Instacart on Vern's phone.

## Non-negotiable constraints

- No automatic checkout.
- No bypass around the existing Vern-only approval gate.
- Keep current Phase 1 and Phase 2 browser flow working.
- Keep the system runnable locally with optional automation dependencies.
- If automation is unhealthy or untrusted, fail loudly and hand control back to Vern.

---

## Phase 0 — Foundation: cart-fill runs, state machine, monitoring

### Task 0.1 — Persist cart-fill runs per approved draft
Add a `cart_fill_runs` table linked to `cart_sessions`.

Fields:
- `id`
- `session_id`
- `automation_target` (`instacart`)
- `requested_by`
- `status` (`queued`, `blocked`, `running`, `succeeded`, `partial`, `failed`, `cancelled`)
- `status_detail`
- `session_path`
- `created_at`
- `started_at`
- `finished_at`

Acceptance criteria:
- Existing databases migrate cleanly.
- A draft can have multiple historical runs.
- A run status is queryable without scraping logs.

### Task 0.2 — Add a real state machine service
Create one service module that owns allowed transitions and blocks nonsense transitions.

Acceptance criteria:
- Invalid transitions raise a clear error.
- Only approved, not-yet-ordered drafts can start a run.
- An active run blocks creating a second active run for the same draft.

### Task 0.3 — Add operator monitoring surface
Expose latest run + history on the draft detail page and via JSON.

Acceptance criteria:
- Approved draft page shows current automation prep state.
- Operator can inspect latest run detail in browser and API.
- UI copy is truthful that automation is not yet filling the Instacart cart.

---

## Phase 1 — Saved-session Playwright scaffolding

### Task 1.1 — Optional browser automation dependency
Add Playwright as an optional dependency and document exact install steps.

Acceptance criteria:
- Base app still runs without Playwright installed.
- Docs show exact install command and browser install command.
- Import errors are caught and surfaced clearly.

### Task 1.2 — Saved login capture script
Add a local script that opens a non-headless browser, lets Vern log into Instacart manually, then saves storage state to a configured file.

Acceptance criteria:
- Script creates a real saved-state JSON file.
- Script never attempts to automate login or 2FA.
- Docs clearly say login/session capture is manual.

### Task 1.3 — Session health check
Add a health-check script/helper that loads the saved session and verifies we are still logged in and on the expected store.

Acceptance criteria:
- Healthy session returns success.
- Expired session returns a clear failure reason.
- Store mismatch is treated as a failure, not ignored.

---

## Phase 2 — Instacart automation core

### Task 2.1 — Centralize selectors and page assumptions
All selectors and page heuristics live in one module.

Acceptance criteria:
- No hard-coded selectors spread across business logic.
- A selector update can be done in one place.

### Task 2.2 — Implement per-item add-to-cart flow
Given approved draft items, load Instacart, search each item, add the best available match, and record what happened.

Acceptance criteria:
- Run produces a structured per-item report.
- Missing items become `not_found` or `failed`, not silent drops.
- Duplicate reruns do not blindly double-add if the cart already contains the same requested item.

### Task 2.3 — Stop before checkout, always
Automation ends at cart fill.

Acceptance criteria:
- No code path clicks final place-order / checkout controls.
- Tests assert no checkout action exists in the automation command surface.
- Docs repeat that Vern still does final review and placement inside Instacart.

---

## Phase 3 — Worker integration and operator controls

### Task 3.1 — Run queued jobs locally
Add a local worker/runner that picks up queued runs, performs session health check, then executes cart fill.

Acceptance criteria:
- Queued run moves through `running` to a terminal status.
- Expired session moves to `blocked` or `failed` with a clear recovery message.
- No background worker is required for normal Phase 1/2 operation.

### Task 3.2 — Start/monitor from browser
Add an operator action to start cart fill from an approved draft and monitor status from phone.

Acceptance criteria:
- Start action is auth-protected.
- Status updates are visible without digging through server logs.
- Current manual shopping handoff remains available as fallback.

### Task 3.3 — Show actionable result summary
Display added/skipped/failed items with blunt copy telling Vern what still needs manual review.

Acceptance criteria:
- UI distinguishes success, partial success, and failure.
- Operator can see which requested items were not added.
- The Instacart review step remains explicit.

---

## Phase 4 — Recovery, hardening, and truth-telling docs

### Task 4.1 — Recovery path for dead sessions
Document and surface the exact operator step to recapture session state.

Acceptance criteria:
- Failure message points to the exact command or script to rerun.
- No silent retries loop forever.

### Task 4.2 — Local-first operational docs
Document setup, session capture, worker start, and failure modes.

Acceptance criteria:
- A local operator can reproduce setup from scratch.
- Docs explicitly call out browser/session fragility and maintenance cost.
- Docs explain the fallback path: use current Phase 2 manual handoff when automation is unhealthy.

### Task 4.3 — Safety regression coverage
Expand tests around approval gating, ordered state, and no-checkout guarantee.

Acceptance criteria:
- Existing approval and shopping-handoff tests still pass.
- New tests cover approval-before-automation and ordered-session rejection.
- No test or command suggests automatic checkout.

---

## Recommended implementation order

1. Phase 0 foundation.
2. Phase 1 saved-session scaffolding.
3. Phase 2 automation core in a CLI/test harness.
4. Phase 3 browser-triggered local worker.
5. Phase 4 hardening/docs.

## Biggest risks that remain even if we execute well

1. Instacart anti-bot changes can invalidate the approach with no warning.
2. Saved sessions are operationally fragile and will need periodic refresh.
3. Product matching is probabilistic; Vern still must review the cart in Instacart.
4. Single-store assumptions can drift after re-login or account changes.
5. Browser automation failures will be messy unless surfaced cleanly in-product.
