# Grocery Assistant

Household grocery assistant with Discord + SMS intake, shared grocery list, Instacart draft generation, and a hard approval gate that blocks all ordering unless Vern explicitly approves.

## Status

Phase 2 shopping handoff is now implemented on top of the mobile web UI. Approved drafts can now open a phone-friendly Instacart handoff page with per-item deep links, and Vern can manually mark the draft ordered after checkout so those items leave the active grocery list.

## What It Does

- Accepts grocery items from Discord and SMS via webhook-ready adapters
- Validates sender identity against a trusted sender registry before accepting anything
- Parses and normalizes item text ("don't forget dish soap", "ground turkey 2 lb", "bananas, eggs, oat milk")
- Deduplicates by canonical name while preserving all source links and provenance
- Categorizes items (produce, protein, dairy, pantry, frozen, household, other)
- Flags ambiguous items ("milk", "bread", "chips") without silently guessing
- Resolves ambiguous items via CLI or API with a full audit log
- Supports household preference rules: preferred forms, substitution policy, notes per canonical item
- Shows preference notes in draft output and during ambiguity resolution
- Shows items added since the previous draft (draft diff)
- Generates an Instacart-ready order draft
- Enforces a hard approval gate: only Vern can approve, only explicit phrases count, per session only
- Gives approved drafts a mobile shopping handoff page with per-item Instacart search links
- Lets Vern manually mark a shopping session ordered after Instacart checkout, moving linked items off the active list

## Safety Rules

- No order is ever submitted automatically
- No auto-checkout path exists in the codebase
- Approval is per order session, not stored globally
- Only Vern can approve
- Phrases like "looks good", "nice", "thumbs up", or "yes" do not count as approval
- Approval is blocked if any ambiguous items remain in the draft

## Setup

Requires Python 3.11+. Flask is the only runtime dependency.

```bash
# Install Flask if needed
pip install flask
# or: sudo apt-get install python3-flask

# Register the package (run once from repo root)
bash setup.sh
```

`setup.sh` auto-detects your Python version, registers the package, initializes the database, and confirms the CLI works.

**Manual alternative:**

```bash
pip install -e .
# or: echo "$(pwd)/src" > ~/.local/lib/python3.12/site-packages/grocery-assistant.pth
```

Verify:

```bash
python3 -m grocery_assistant.cli --help
```

No real Twilio account or Discord bot token required for local operation.

## Running Tests

```bash
python3 -m pytest tests/ -v
```

Expected: 432 passed.

## Readiness Check

Run this before attempting any live hookup. It checks imports, database, trusted sender registries, and all required env vars, then reports which modes are ready.

```bash
python3 -m grocery_assistant.cli doctor
```

Example output:

```
Grocery Assistant -- Setup Check
====================================

  [OK]    grocery_assistant: importable
  [OK]    flask: importable
  [OK]    Database: grocery.db (48 KB)
  [WARN]  Trusted SMS senders: 0 configured  (Add real phone numbers to TRUSTED_SMS_SENDERS in identity.py)
  [WARN]  Trusted Discord users: 0 configured  (Add real user IDs to TRUSTED_DISCORD_USERS in identity.py)
  [MISS]  TWILIO_AUTH_TOKEN  (not set -- required for live Twilio hookup)
  [WARN]  TWILIO_VALIDATE_SIGNATURE  (not set -- dev mode, signature check disabled)
  [MISS]  TWILIO_WEBHOOK_URL  (not set -- required when running behind ngrok or a reverse proxy)
  [MISS]  DISCORD_BOT_TOKEN  (not set -- required to run the Discord bot bridge)
  [OK]    GROCERY_DISCORD_CHANNEL_ID  (not set -- bot will listen on all channels)

Modes:
  Local simulation :   READY
  Twilio live      :   BLOCKED  (missing: trusted SMS numbers in identity.py, TWILIO_AUTH_TOKEN, TWILIO_WEBHOOK_URL)
  Discord live     :   BLOCKED  (missing: trusted Discord users in identity.py, DISCORD_BOT_TOKEN)
```

## CLI Commands

```bash
# Show grocery list grouped by category
python3 -m grocery_assistant.cli list

# Show ambiguous items that need clarification
python3 -m grocery_assistant.cli flagged

# Show items added by a specific sender
python3 -m grocery_assistant.cli by-sender cara
python3 -m grocery_assistant.cli by-sender vern

# Show items by intake channel
python3 -m grocery_assistant.cli by-channel sms
python3 -m grocery_assistant.cli by-channel discord

# Create a draft from all pending items
python3 -m grocery_assistant.cli draft
python3 -m grocery_assistant.cli draft --json

# Resolve an ambiguous item (get item_id from 'flagged' output)
python3 -m grocery_assistant.cli resolve <item_id> "oat milk"

# Show clarification history for an item
python3 -m grocery_assistant.cli history <item_id>

# Show full details and source events for an item
python3 -m grocery_assistant.cli inspect <item_id>

# Safely remove an item (marks removed, preserves audit trail)
python3 -m grocery_assistant.cli remove <item_id>
python3 -m grocery_assistant.cli remove <item_id> --reason "duplicate"

# Manage household preferences
python3 -m grocery_assistant.cli prefs list
python3 -m grocery_assistant.cli prefs set milk --prefer "oat milk"
python3 -m grocery_assistant.cli prefs set eggs --subs-ok
python3 -m grocery_assistant.cli prefs set bread --prefer "sourdough" --note "bakery section"
python3 -m grocery_assistant.cli prefs remove milk
```

Override the database path:

```bash
GROCERY_DB_PATH=/path/to/grocery.db python3 -m grocery_assistant.cli list
```

## Running the Web Server

```bash
python3 -m grocery_assistant.web
# Starts on http://127.0.0.1:5000

# Override port or DB path
GROCERY_PORT=8080 python3 -m grocery_assistant.web
GROCERY_DB_PATH=/path/to/grocery.db python3 -m grocery_assistant.web
```

## Mobile Browser UI

The web server includes a phone-friendly browser interface. All pages are server-rendered HTML — no JavaScript framework required.

### Start with browser auth enabled

```bash
BROWSER_TOKEN=your-secret-token FLASK_SECRET_KEY=your-secret-key python3 -m grocery_assistant.web
```

`BROWSER_TOKEN` is a shared household password. Set it to any strong random string. If unset, write actions (draft creation, approval, and marking a session ordered) are blocked.

`FLASK_SECRET_KEY` keeps browser sessions valid across server restarts. If unset, a random key is generated each restart (sessions invalidated on restart).

### Browser URLs

| URL | What you see | Auth required |
|---|---|---|
| `http://localhost:5000/` | Dashboard: item count, flagged count, quick links | No |
| `http://localhost:5000/list` | Grocery list grouped by category | No |
| `http://localhost:5000/flagged` | Items needing clarification | No |
| `http://localhost:5000/drafts/new` | Preview pending items before creating a draft | No (read) / Yes (create) |
| `http://localhost:5000/drafts/<id>` | Draft detail and approve button | No (read) / Yes (approve) |
| `http://localhost:5000/drafts/<id>/shop` | Shopping handoff with Instacart search links | No (read) / Yes (mark ordered) |
| `http://localhost:5000/login` | Token login | No |

### Approval + shopping handoff flow in the browser

1. Go to `/drafts/new`, review the list, tap **Create draft**.
2. On the draft detail page, if status is `awaiting_approval`, tap **Approve order**.
3. The existing four-check gate runs: approver must be Vern, session must exist, status must be `awaiting_approval`, phrase must match. All checks are enforced server-side regardless of what the browser sends.
4. After approval, open `/drafts/<id>/shop` or tap **Open shopping handoff** from the draft page.
5. Use the per-item Instacart links on phone, then complete product selection and checkout manually inside Instacart.
6. Return to the shopping handoff page and tap **I finished checkout — mark ordered**.
7. Linked grocery items move to `ordered` and disappear from the active grocery list.

Items flagged as ambiguous still block approval until resolved via CLI or API. No Instacart checkout is ever auto-submitted from this app.

### Via ngrok (share with phone on another network)

```bash
ngrok http 5000
# Copy the https://*.ngrok.io URL and open it on your phone
```

Set `BROWSER_TOKEN` before exposing via ngrok. The token is the only protection against public access.

### Auth model tradeoffs

- Single shared token, not per-user. It asserts "this is the household operator" (Vern).
- No CSRF tokens. Same-origin form POSTs on a household-only tool.
- Token replay from browser history is possible on a shared device. Acceptable risk for a local household tool.
- For stronger isolation: replace the session cookie check with HTTP Basic Auth, or add `ngrok http --basic-auth="vern:token" 5000`.

## Using Preferences

Preferences map canonical item names to a preferred form, substitution policy, and optional notes. They appear in draft output and during ambiguity resolution.

The preferences table starts empty. Add rules at runtime:

```bash
# Prefer oat milk, no substitutions
python3 -m grocery_assistant.cli prefs set milk --prefer "oat milk"

# Eggs: substitutions are okay
python3 -m grocery_assistant.cli prefs set eggs --subs-ok

# Bread: preferred form and a note
python3 -m grocery_assistant.cli prefs set bread --prefer "sourdough" --note "bakery section"

# List all preferences
python3 -m grocery_assistant.cli prefs list

# Remove a rule
python3 -m grocery_assistant.cli prefs remove milk
```

Or via the API:

```bash
curl -X POST http://127.0.0.1:5000/api/preferences \
  -H "Content-Type: application/json" \
  -d '{"canonical": "milk", "preferred_form": "oat milk"}'

curl http://127.0.0.1:5000/api/preferences

curl -X DELETE http://127.0.0.1:5000/api/preferences/milk
```

Draft output will show:
```
  #3    [dairy     ] milk  [pref: prefer: oat milk | exact item preferred]
```

## Simulating SMS Intake Locally

```bash
# Start the web server first
python3 -m grocery_assistant.web

# Simulate a Twilio inbound SMS
curl -X POST http://127.0.0.1:5000/sms/webhook \
  -d "From=%2B12065550001&Body=bananas%2C+eggs%2C+oat+milk"
```

Returns TwiML XML (what Twilio expects). The `From` field must match a number in `TRUSTED_SMS_SENDERS` in `identity.py`. Untrusted numbers return 403.

## Simulating Discord Intake Locally

```bash
curl -X POST http://127.0.0.1:5000/discord/event \
  -H "Content-Type: application/json" \
  -d '{"author": {"id": "123456789012345678"}, "content": "ground turkey 2 lb"}'
```

The `author.id` must match an entry in `TRUSTED_DISCORD_USERS` in `identity.py`. Untrusted IDs return 403.

## Twilio Hookup

What Vern will need to fill in before going live:

| What | Where |
|------|-------|
| Twilio phone number (E.164, e.g. `+12065551234`) | `TRUSTED_SMS_SENDERS` in `src/grocery_assistant/identity.py` |
| Twilio Auth Token | `TWILIO_AUTH_TOKEN` in your shell / `.env` |
| Public webhook URL (ngrok or tunnel) | `TWILIO_WEBHOOK_URL` in your shell / `.env` |

Steps:

1. Buy/provision a number at twilio.com/console
2. Copy `env.example` to `.env` and fill in `TWILIO_AUTH_TOKEN`, `TWILIO_VALIDATE_SIGNATURE=1`, and `TWILIO_WEBHOOK_URL`
3. `source .env`
4. Add the phone number to `TRUSTED_SMS_SENDERS` in `src/grocery_assistant/identity.py`
5. Start ngrok: `ngrok http 5000`
6. Update `TWILIO_WEBHOOK_URL` with the ngrok URL
7. Point the Twilio number's inbound SMS webhook to: `https://your-ngrok-url/sms/webhook`
8. Run: `python3 -m grocery_assistant.cli doctor` -- confirm Twilio live shows READY
9. Start the web server: `python3 -m grocery_assistant.web`

The `/sms/webhook` route returns TwiML XML on success, which Twilio uses to send a reply SMS.

Signature verification is optional in dev (skipped when `TWILIO_VALIDATE_SIGNATURE` is unset). Set it to `1` before exposing the webhook publicly.

## Discord Bot Hookup

What Vern will need to fill in before going live:

| What | Where |
|------|-------|
| Discord user snowflake IDs (18-digit integers) | `TRUSTED_DISCORD_USERS` in `src/grocery_assistant/identity.py` |
| Discord bot token | `DISCORD_BOT_TOKEN` in your shell / `.env` |
| (Optional) channel ID to restrict the bot | `GROCERY_DISCORD_CHANNEL_ID` in your shell / `.env` |

Steps:

1. Create an application at discord.com/developers/applications
2. Create a Bot under your application
3. Enable the MESSAGE_CONTENT intent (Bot -> Privileged Gateway Intents)
4. Invite the bot to your server with Send Messages + Read Message History permissions
5. Find each trusted user's snowflake ID (right-click their name -> Copy User ID with Developer Mode on)
6. Add IDs to `TRUSTED_DISCORD_USERS` in `src/grocery_assistant/identity.py`
7. Copy `env.example` to `.env`, fill in `DISCORD_BOT_TOKEN`, then `source .env`
8. Run: `python3 -m grocery_assistant.cli doctor` -- confirm Discord live shows READY
9. Start the web server and bridge:

```bash
# Terminal 1
python3 -m grocery_assistant.web

# Terminal 2
pip install discord.py
python3 -m grocery_assistant.bridges.discord_bridge
```

Identity is resolved from author snowflake ID, not username. Usernames can change; IDs are permanent.

## Reviewing a Draft

```bash
# Generate a draft
python3 -m grocery_assistant.cli draft

# Example output:
# === Instacart Order Draft ===
# Session ID : 1
# Status     : awaiting_approval
# Items      : 3  (1 dairy, 2 produce)
# Flagged    : 0
#
# -- New since last draft --   <- items added since last draft
#   #4    eggs
#
# -- Items to order --
#   #1    [dairy     ] milk  [pref: prefer: oat milk | exact item preferred]
#   #2    [produce   ] bananas
#   #3    [produce   ] eggs
```

The draft does not submit anything. Vern must approve with an explicit phrase.

## API Reference

```bash
# Grocery list
curl http://127.0.0.1:5000/api/list
curl http://127.0.0.1:5000/api/flagged
curl http://127.0.0.1:5000/api/by-sender/cara
curl http://127.0.0.1:5000/api/by-channel/sms

# Draft and session
curl -X POST http://127.0.0.1:5000/api/draft
curl http://127.0.0.1:5000/api/draft/1

# Resolve ambiguity
curl -X POST http://127.0.0.1:5000/api/resolve \
  -H "Content-Type: application/json" \
  -d '{"item_id": 1, "new_name": "oat milk"}'

# Remove an item
curl -X POST http://127.0.0.1:5000/api/item/1/remove \
  -H "Content-Type: application/json" \
  -d '{"removed_by": "operator", "reason": "duplicate"}'

# Preferences
curl http://127.0.0.1:5000/api/preferences
curl -X POST http://127.0.0.1:5000/api/preferences \
  -H "Content-Type: application/json" \
  -d '{"canonical": "milk", "preferred_form": "oat milk"}'
curl -X DELETE http://127.0.0.1:5000/api/preferences/milk
```

## Trusted Sender Configuration

Edit `src/grocery_assistant/identity.py`:

```python
# SMS: E.164 phone number -> canonical name
TRUSTED_SMS_SENDERS: dict[str, str] = {
    "+12065550001": "cara",
}

# Discord: snowflake user ID (string) -> canonical name
TRUSTED_DISCORD_USERS: dict[str, str] = {
    "123456789012345678": "vern",
    "987654321098765432": "cara",
}
```

Messages from unrecognized senders are rejected before anything is written to the DB.

## Project Layout

```
grocery-assistant/
  schema.sql                  # SQLite schema (8 tables + preferences)
  env.example                 # Copy to .env and fill in real values
  src/grocery_assistant/
    config.py                 # Centralized env var reading + readiness logic
    db.py                     # All SQLite queries + apply_migrations()
    models.py                 # Dataclasses: IntakeEvent, GroceryItem, CartSession, Approval
    normalizer.py             # Parse, normalize, categorize, flag ambiguity
    identity.py               # Trusted sender registry (SMS + Discord)
    grocery_list.py           # Add items, dedupe, list views, source queries
    clarification.py          # Ambiguity resolution with audit log
    approval.py               # Hard approval gate with phrase allowlist
    draft.py                  # Draft generation: preference notes, draft diff
    preferences.py            # Preference rules: set/get/list/delete/format
    cli.py                    # Operator CLI (10 commands including prefs + doctor)
    web.py                    # Flask app: Twilio/Discord routes + operator API
    twilio_sig.py             # HMAC-SHA1 Twilio signature verification
    intake/
      base.py                 # IntakeAdapter interface
      sms_adapter.py          # Twilio webhook adapter
      discord_adapter.py      # Discord message event adapter
    bridges/
      discord_bridge.py       # discord.py bot wiring (Approach A)
  tests/
    test_normalizer.py
    test_approval.py
    test_sources.py
    test_identity.py
    test_draft_status.py
    test_clarification.py
    test_web.py
    test_cli.py
    test_twilio_sig.py
    test_preferences.py
    test_draft_diff.py
    test_doctor.py            # config.py and doctor command tests
```

## What Is Not Implemented

- **Browser-assisted Instacart cart drafting**: Draft output is Instacart-ready but no browser automation exists. Intentional for MVP.
- **Order submission**: Not implemented. Will not be implemented without an explicit new phase and safety review.
- **Recurring staples list**: Not implemented.
- **Push notifications**: No outbound SMS/Discord messages on list changes (Twilio TwiML ack only).
