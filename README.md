# Grocery Assistant

Household grocery assistant for Discord + SMS intake with Instacart draft prep and a hard approval gate.

## Status

Phase 2A complete. Real intake adapters, source traceability, safe dedupe, and tighter state model.

## What This Does

- Accepts grocery items from Discord and SMS via webhook-ready adapters
- Validates sender identity against a trusted sender registry before accepting any message
- Parses and normalizes item text ("don't forget dish soap", "ground turkey 2 lb", "bananas, eggs, oat milk")
- Deduplicates by canonical name while preserving all source links and provenance
- Categorizes items (produce, protein, dairy, pantry, frozen, household, other)
- Flags ambiguous items (bare "milk", "bread", "chips") without guessing
- Generates an Instacart-ready order draft
- Sets draft to `needs_clarification` if any ambiguous items are present; blocks approval until resolved
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
    |-- cart_sessions + cart_session_items
    `-- approvals
    |
    v
Draft generation (draft.py)
    |-- status: needs_clarification | awaiting_approval
    |
    v
Approval gate (approval.py)
    `-- only Vern, only explicit phrase, only awaiting_approval sessions
```

## Source Traceability

Every grocery item is linked to every intake event that requested it via `grocery_item_sources`.
This is written on both new insertions and duplicate merges, so no request is ever lost.

Supported queries:

```python
from grocery_assistant.grocery_list import get_by_sender, get_by_channel
from grocery_assistant.db import get_source_events_for_item

# What did Cara add?
cara_items = get_by_sender(conn, "cara")

# What did Vern add?
vern_items = get_by_sender(conn, "vern")

# What came from SMS?
sms_items = get_by_channel(conn, "sms")

# What came from Discord?
discord_items = get_by_channel(conn, "discord")

# Full event history for a specific item
events = get_source_events_for_item(conn, item_id)
```

## Trusted Sender Configuration

Senders are validated before any message reaches the grocery list.
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

## Intake Adapters

### SMS (Twilio webhook)

```python
from grocery_assistant.intake.sms_adapter import SmsAdapter

adapter = SmsAdapter(conn, trusted_senders=TRUSTED_SMS_SENDERS)
result = adapter.receive_webhook(request.form)
# result: {"event_id": int, "added": [...], "merged": [...], "flagged": [...]}
```

`receive_webhook()` expects keys `From` (E.164) and `Body` (text), matching Twilio's inbound SMS POST format.

### Discord (message event)

```python
from grocery_assistant.intake.discord_adapter import DiscordAdapter

adapter = DiscordAdapter(conn, trusted_users=TRUSTED_DISCORD_USERS)
result = adapter.receive_event(event)
```

`receive_event()` expects `{"author": {"id": "..."}, "content": "..."}`, matching Discord's MESSAGE_CREATE event structure.
Identity is resolved from `author.id` (snowflake), never from `author.username`.

## Dedupe / Merge Behavior

When the same canonical item is requested more than once:

| Scenario | Behavior |
|---|---|
| Same item, no existing quantity | Promote new quantity if present |
| Same item, existing quantity matches new | No change (idempotent) |
| Same item, quantities differ | Keep existing, track new source link |
| Any duplicate | Always write a new `grocery_item_sources` row |

The `add_from_message` result distinguishes `added` (new items) from `merged` (deduped items with source preserved).

## Draft Status Model

| Status | Meaning |
|---|---|
| `draft` | Session created, not yet finalized |
| `needs_clarification` | At least one ambiguous item; approval blocked |
| `awaiting_approval` | All items clear; Vern may approve |
| `approved` | Vern has explicitly approved |
| `cancelled` | Session cancelled |

A draft moves directly to `needs_clarification` if any ambiguous items are present.
Approval is blocked at the gate layer until the session is `awaiting_approval`.

## Project Layout

```
grocery-assistant/
  src/grocery_assistant/
    db.py             # SQLite queries: insert, find, source linking, sender/channel views
    models.py         # Dataclasses: IntakeEvent, GroceryItem, CartSession, Approval
    normalizer.py     # Parse, normalize, categorize, flag ambiguity
    identity.py       # Trusted sender registry and resolution (SMS + Discord)
    grocery_list.py   # Add items from messages, safe dedupe, list views, source queries
    approval.py       # Hard approval gate with phrase allowlist
    draft.py          # Instacart-ready draft generation with status logic
    intake/
      base.py              # IntakeAdapter interface
      sms_adapter.py       # Twilio webhook adapter (phase 2A)
      discord_adapter.py   # Discord message event adapter (phase 2A)
      sms_stub.py          # Phase 1 direct-injection stub (still works)
      discord_stub.py      # Phase 1 direct-injection stub (still works)
  tests/
    test_normalizer.py     # Parse, normalize, categorize, ambiguity
    test_approval.py       # Approval gate enforcement
    test_sources.py        # Source traceability, dedupe, sender/channel queries
    test_identity.py       # Trusted sender validation, adapter enforcement
    test_draft_status.py   # Draft status and approval gate with ambiguous items
  schema.sql          # SQLite schema
  pyproject.toml      # pytest config and package setup
```

## Setup

Requires Python 3.11+. No external dependencies beyond pytest.

```bash
# Install pytest (Ubuntu/WSL)
pip install pytest

# Or system package
sudo apt-get install python3-pytest
```

## Run Tests

```bash
cd /mnt/c/Users/bryce/projects/grocery-assistant
python3 -m pytest tests/ -v
```

Expected: 136 passed, no warnings.

## Quick Smoke Test

```python
import sqlite3
from pathlib import Path
from grocery_assistant.db import get_connection
from grocery_assistant.grocery_list import add_from_message, get_by_sender, format_list
from grocery_assistant.draft import create_draft, format_draft
from grocery_assistant.approval import submit_approval, can_submit

conn = get_connection(Path(":memory:"))
schema = Path("schema.sql").read_text()
conn.executescript(schema)

# Add items from different sources
add_from_message(conn, "bananas, eggs, oat milk", "discord", "vern")
add_from_message(conn, "don't forget dish soap", "sms", "cara")
add_from_message(conn, "ground turkey 2 lb", "discord", "vern")

# Dedupe with source preserved
add_from_message(conn, "bananas", "sms", "cara")  # merged, not duplicated

# Source queries
print([r["canonical"] for r in get_by_sender(conn, "cara")])

# Draft and approval
draft = create_draft(conn)
print(format_draft(draft))
result = submit_approval(conn, draft["session_id"], "vern", "approve order")
print(can_submit(conn, draft["session_id"]))  # True
```

## Phase 3 (Not Implemented)

- Ambiguity resolution flow (Vern replies to clarify, item updated in place)
- Browser-assisted Instacart cart drafting (stops before final submit)
- Substitution preferences per item
- Recurring staples list
- Real Twilio webhook endpoint (Flask or FastAPI, thin)
- Real Discord bot wiring (discord.py, responds in channel)

## Project Path

Windows: `C:\Users\bryce\projects\grocery-assistant`
WSL: `/mnt/c/Users/bryce/projects/grocery-assistant`
