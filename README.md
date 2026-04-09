# Grocery Assistant

Household grocery assistant for Discord + SMS intake with Instacart draft prep and a hard approval gate.

## Status

Phase 3 complete. Twilio-shape webhook route, Discord event ingestion route, ambiguity resolution workflow, and a full operator surface (CLI + JSON API). 240 tests passing.

## What This Does

- Accepts grocery items from Discord and SMS via webhook-ready adapters
- Validates sender identity against a trusted sender registry before accepting any message
- Parses and normalizes item text ("don't forget dish soap", "ground turkey 2 lb", "bananas, eggs, oat milk")
- Deduplicates by canonical name while preserving all source links and provenance
- Categorizes items (produce, protein, dairy, pantry, frozen, household, other)
- Flags ambiguous items (bare "milk", "bread", "chips") without guessing
- Resolves ambiguous items via CLI or API with full audit log
- Promotes sessions from `needs_clarification` to `awaiting_approval` once all ambiguities are cleared
- Generates an Instacart-ready order draft
- Enforces a hard approval gate: only Vern can approve, only explicit phrases count, per session, no blanket permission

## Non-negotiable Safety Rules

- No order is ever submitted automatically
- No auto-checkout path exists in the codebase
- Approval is per order session, not stored globally
- Only Vern can approve
- Phrases like "looks good", "nice", "thumbs up", or "yes" do not count
- Approval is blocked if any ambiguous items remain in the draft

## Architecture

```
Intake (SMS / Discord)
    |
    v
Identity validation (identity.py)
    |-- SMS: E.164 phone number -> trusted name
    `-- Discord: user ID (snowflake) -> trusted name
    |
    v
Grocery list service (grocery_list.py)
    |-- parse_message() -> ParsedItem list
    |-- insert or link source to existing item
    `-- safe quantity merge on dedup
    |
    v
SQLite persistence (schema.sql, db.py)
    |-- intake_events: raw message log
    |-- grocery_items: canonical item state
    |-- grocery_item_sources: item <-> event links (traceability)
    |-- clarification_log: ambiguity resolution audit trail
    |-- cart_sessions + cart_session_items
    `-- approvals
    |
    v
Clarification service (clarification.py)
    |-- list_ambiguous(): pending flagged items
    |-- resolve_item(): validate, normalize, log, promote sessions
    `-- get_resolution_history(): per-item audit trail
    |
    v
Draft generation (draft.py)
    |-- status: needs_clarification | awaiting_approval
    |
    v
Approval gate (approval.py)
    `-- only Vern, only explicit phrase, only awaiting_approval sessions
    |
    v
Operator surface
    |-- CLI: python -m grocery_assistant.cli <command>
    `-- API: python -m grocery_assistant.web (http://127.0.0.1:5000)
```

## Setup

Requires Python 3.11+. Flask is the only runtime dependency beyond the standard library.

```bash
# Ubuntu / WSL
sudo apt-get install python3-flask

# Or via pip if available
python3 -m pip install flask
```

No real Twilio account or Discord bot token is required for local operation.

## Run Tests

```bash
cd /mnt/c/Users/bryce/projects/grocery-assistant
python3 -m pytest tests/ -v
```

Expected: 240 passed.

## Local Operator Surface

### Option A: CLI

```bash
# Show full grocery list grouped by category
python3 -m grocery_assistant.cli list

# Show items flagged as ambiguous (need clarification before draft can be approved)
python3 -m grocery_assistant.cli flagged

# Show what Cara added
python3 -m grocery_assistant.cli by-sender cara

# Show what Vern added
python3 -m grocery_assistant.cli by-sender vern

# Show what came from SMS
python3 -m grocery_assistant.cli by-channel sms

# Show what came from Discord
python3 -m grocery_assistant.cli by-channel discord

# Create a draft from all pending items
python3 -m grocery_assistant.cli draft

# Create a draft and also print raw JSON
python3 -m grocery_assistant.cli draft --json

# Resolve an ambiguous item (get item_id from 'flagged' output)
python3 -m grocery_assistant.cli resolve <item_id> "oat milk"

# Show clarification history for an item
python3 -m grocery_assistant.cli history <item_id>
```

Use `GROCERY_DB_PATH` to point at a specific database file:

```bash
GROCERY_DB_PATH=/path/to/grocery.db python3 -m grocery_assistant.cli list
```

### Option B: Local Web Server + JSON API

Start the server:

```bash
python3 -m grocery_assistant.web
# Starts on http://127.0.0.1:5000
# Override port: GROCERY_PORT=8080 python3 -m grocery_assistant.web
# Override DB: GROCERY_DB_PATH=/path/to/grocery.db python3 -m grocery_assistant.web
```

API endpoints:

```bash
# Show full grocery list
curl http://127.0.0.1:5000/api/list

# Show flagged ambiguous items
curl http://127.0.0.1:5000/api/flagged

# Show items by sender
curl http://127.0.0.1:5000/api/by-sender/cara

# Show items by channel
curl http://127.0.0.1:5000/api/by-channel/sms
curl http://127.0.0.1:5000/api/by-channel/discord

# Create a draft
curl -X POST http://127.0.0.1:5000/api/draft

# Get a specific session
curl http://127.0.0.1:5000/api/draft/1

# Resolve an ambiguous item
curl -X POST http://127.0.0.1:5000/api/resolve \
  -H "Content-Type: application/json" \
  -d '{"item_id": 1, "new_name": "oat milk", "resolved_by": "operator"}'
```

## Simulating Intake Locally

### Simulate Twilio SMS (no real credentials needed)

```bash
# Start the web server first
python3 -m grocery_assistant.web

# In another terminal, POST a Twilio-shape inbound SMS
curl -X POST http://127.0.0.1:5000/sms/webhook \
  -d "From=%2B12065550001&Body=bananas%2C+eggs%2C+oat+milk"
```

The `From` field must match a number in `TRUSTED_SMS_SENDERS` (configured in `identity.py`). Untrusted numbers get a 403.

### Simulate Discord MESSAGE_CREATE (no bot token needed)

```bash
curl -X POST http://127.0.0.1:5000/discord/event \
  -H "Content-Type: application/json" \
  -d '{"author": {"id": "123456789012345678"}, "content": "ground turkey 2 lb"}'
```

The `author.id` must match an entry in `TRUSTED_DISCORD_USERS` (configured in `identity.py`). Untrusted IDs get a 403.

## Trusted Sender Configuration

Configure trusted senders in `src/grocery_assistant/identity.py`:

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

Messages from unrecognized senders are rejected with `UntrustedSenderError` before anything is written to the DB.

For tests or local injection, pass the trusted dict directly:

```python
adapter = SmsAdapter(conn, trusted_senders={"+12065550001": "cara"})
adapter = DiscordAdapter(conn, trusted_users={"111111111111111111": "vern"})
```

## Ambiguity Resolution Workflow

Items flagged as ambiguous block approval until resolved. Workflow:

1. Add items: `milk` is flagged, `oat milk` is not.
2. Check flagged: `python3 -m grocery_assistant.cli flagged`
3. Resolve: `python3 -m grocery_assistant.cli resolve 1 "oat milk"`
4. Session auto-promotes from `needs_clarification` to `awaiting_approval` when last ambiguity is cleared.
5. Create draft: `python3 -m grocery_assistant.cli draft`

Resolution is audited in `clarification_log`. View history with:
```bash
python3 -m grocery_assistant.cli history <item_id>
```

## Source Traceability

Every grocery item is linked to every intake event that requested it via `grocery_item_sources`.

```python
from grocery_assistant.grocery_list import get_by_sender, get_by_channel
from grocery_assistant.db import get_source_events_for_item

cara_items = get_by_sender(conn, "cara")
sms_items  = get_by_channel(conn, "sms")
events     = get_source_events_for_item(conn, item_id)
```

## Draft Status Model

| Status | Meaning |
|---|---|
| `draft` | Session created, not yet finalized |
| `needs_clarification` | At least one ambiguous item; approval blocked |
| `awaiting_approval` | All items clear; Vern may approve |
| `approved` | Vern has explicitly approved |
| `cancelled` | Session cancelled |

A draft moves to `needs_clarification` if any ambiguous items are present. Approval is blocked until the session is `awaiting_approval`.

## Intake Adapters

### SMS (Twilio webhook shape)

```python
from grocery_assistant.intake.sms_adapter import SmsAdapter

adapter = SmsAdapter(conn, trusted_senders=TRUSTED_SMS_SENDERS)
result = adapter.receive_webhook(request.form)
# result: {"event_id": int, "added": [...], "merged": [...], "flagged": [...]}
```

`receive_webhook()` expects keys `From` (E.164) and `Body` (text), matching Twilio's inbound SMS POST format.

### Discord (MESSAGE_CREATE event shape)

```python
from grocery_assistant.intake.discord_adapter import DiscordAdapter

adapter = DiscordAdapter(conn, trusted_users=TRUSTED_DISCORD_USERS)
result = adapter.receive_event(event)
```

`receive_event()` expects `{"author": {"id": "..."}, "content": "..."}`, matching Discord's MESSAGE_CREATE event structure. Identity is resolved from `author.id` (snowflake), never from `author.username`.

## Dedupe / Merge Behavior

| Scenario | Behavior |
|---|---|
| Same item, no existing quantity | Promote new quantity if present |
| Same item, existing quantity matches new | No change (idempotent) |
| Same item, quantities differ | Keep existing, track new source link |
| Any duplicate | Always write a new `grocery_item_sources` row |

## Project Layout

```
grocery-assistant/
  src/grocery_assistant/
    db.py               # SQLite queries: insert, find, source linking, sender/channel views
    models.py           # Dataclasses: IntakeEvent, GroceryItem, CartSession, Approval
    normalizer.py       # Parse, normalize, categorize, flag ambiguity
    identity.py         # Trusted sender registry and resolution (SMS + Discord)
    grocery_list.py     # Add items from messages, safe dedupe, list views, source queries
    clarification.py    # Ambiguity resolution service with audit log
    approval.py         # Hard approval gate with phrase allowlist
    draft.py            # Instacart-ready draft generation with status logic
    cli.py              # Operator CLI (python -m grocery_assistant.cli)
    web.py              # Flask web app: Twilio/Discord routes + operator API
    intake/
      base.py              # IntakeAdapter interface
      sms_adapter.py       # Twilio webhook adapter
      discord_adapter.py   # Discord message event adapter
      sms_stub.py          # Phase 1 direct-injection stub (still works)
      discord_stub.py      # Phase 1 direct-injection stub (still works)
  tests/
    test_normalizer.py      # Parse, normalize, categorize, ambiguity
    test_approval.py        # Approval gate enforcement
    test_sources.py         # Source traceability, dedupe, sender/channel queries
    test_identity.py        # Trusted sender validation, adapter enforcement
    test_draft_status.py    # Draft status and approval gate with ambiguous items
    test_clarification.py   # Ambiguity resolution workflow, session promotion, audit log
    test_web.py             # Flask routes: SMS webhook, Discord event, operator API
    test_cli.py             # CLI operator surface, parser structure
  schema.sql          # SQLite schema (includes clarification_log table)
  pyproject.toml      # pytest config and package setup
```

## What Is Not Implemented Yet

- **Real Twilio credentials**: The webhook route shape is correct (`POST /sms/webhook` with `From`/`Body` form fields). Wiring a real Twilio phone number requires adding your number to `TRUSTED_SMS_SENDERS` and pointing a Twilio webhook at the local server (e.g. via ngrok). No code changes needed.
- **Real Discord bot login**: The event ingestion route (`POST /discord/event`) accepts Discord's MESSAGE_CREATE JSON shape. A real bot would authenticate with discord.py and forward events to this route. The integration layer is thin by design.
- **Browser-assisted Instacart cart drafting**: The draft output is Instacart-ready (canonical search terms, categories, quantities) but no browser automation exists. This is intentional for MVP.
- **Order submission**: Not implemented. Will never be implemented without an explicit new phase and a separate safety review.
- **Substitution preferences per item**: Not implemented.
- **Recurring staples list**: Not implemented.
