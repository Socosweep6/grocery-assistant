# Grocery Assistant: Phase Definitions

## Phase 1 - Mobile Web UI

**Status:** Implemented.

Phase 1 shipped the phone-friendly Flask UI for reviewing the list, creating drafts, and approving drafts from a browser with the existing shared-token browser auth.

## Phase 2 - Shopping Handoff / Deep Links

**Status:** Implemented on `feat/shopping-handoff-phase2`.

### Goal

Once Vern approves a draft, give her a practical mobile path into Instacart tonight without brittle browser automation.

### Product decision

Ship the deep-link handoff now. Do **not** automate Instacart login, cart fill, or checkout.

### What ships

| Route | Description |
|---|---|
| `GET /drafts/<id>/shop` | Mobile-friendly shopping handoff page for approved drafts |
| `POST /drafts/<id>/ordered` | Manual completion step after checkout in Instacart |

### Flow

1. Review pending items in the browser.
2. Create a draft.
3. Approve the draft with the existing Vern-only approval gate.
4. Open the shopping handoff page.
5. Tap per-item Instacart search links on phone.
6. Manually choose products and complete checkout in Instacart.
7. Tap **mark ordered** back in Grocery Assistant.
8. Linked grocery items move to `ordered` and leave the active grocery list.

### Implementation notes

- Instacart links are simple search URLs in the form:
  `https://www.instacart.com/store/search_v3/term?term=<query>`
- Search terms prefer household preferences when available, then fall back to the item name / notes.
- The handoff page stays server-rendered. No JavaScript framework.
- Write actions still require the shared browser session token.
- Approval safety is unchanged: only Vern, explicit phrase, per-session approval, no approval for unresolved drafts.
- No auto-submit path was added.

### Ordered state

- `cart_sessions` now record `ordered_at` when manual checkout is complete.
- Marking ordered updates linked grocery items to `ordered`.
- Ordered items no longer appear in the active grocery list.
- An ordered session is no longer eligible for downstream submission checks.

### Tests

Run:

```bash
python3 -m pytest tests/test_shopping.py tests/test_web_ui.py -v
python3 -m pytest tests/ -v
```

### Remaining gap vs full automation

This phase still requires Vern to:
- open each Instacart search result,
- pick the correct product,
- add it in Instacart,
- and complete checkout manually.

A true automated cart-fill phase would still need retailer/session automation or a supported Instacart integration, which is intentionally out of scope here.
