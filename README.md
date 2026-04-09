# Grocery Assistant

Household grocery assistant for Discord + SMS intake with Instacart draft prep and a hard approval gate.

## Status

Phase 1 complete. Core logic implemented and tested. No live Discord/SMS connections yet.

## What This Does

- Accepts grocery items from Discord and SMS (stubs in phase 1, real adapters in phase 2)
- Parses and normalizes item text ("don't forget dish soap", "ground turkey 2 lb", "bananas, eggs, oat milk")
- Deduplicates by canonical name
- Categorizes items (produce, protein, dairy, pantry, frozen, household, other)
- Flags ambiguous items (bare "milk", "bread", "chips") without guessing
- Generates an Instacart-ready order draft
- Enforces a hard approval gate: only Vern can approve, only explicit phrases count, per session, no blanket permission

## Non-negotiable Safety Rules

- No order is ever submitted automatically
- No auto-checkout path exists in the codebase
- Approval is per order session, not stored globally
- Only Vern can approve
- Phrases like "looks good", "nice", "thumbs up", or "yes" do not count

## Project Layout

```
grocery-assistant/
  src/grocery_assistant/
    db.py             # SQLite schema init and queries
    models.py         # Dataclasses: IntakeEvent, GroceryItem, CartSession, Approval
    normalizer.py     # Parse, normalize, categorize, flag ambiguity
    grocery_list.py   # Add items from messages, dedup, list views
    approval.py       # Hard approval gate with phrase allowlist
    draft.py          # Instacart-ready draft generation
    intake/
      base.py         # IntakeAdapter interface
      discord_stub.py # Discord stub (phase 1: inject messages directly)
      sms_stub.py     # SMS stub (phase 1: inject messages directly)
  tests/
    test_normalizer.py
    test_approval.py
  schema.sql          # SQLite schema
  pyproject.toml      # pytest config and package setup
  requirements.txt    # pytest only
```

## Setup

Requires Python 3.11+ and pytest. No other dependencies.

```bash
# Install pytest (Ubuntu/WSL)
sudo apt-get install python3-pytest

# Or if pip is available
pip install pytest
```

## Run Tests

```bash
cd /mnt/c/Users/bryce/projects/grocery-assistant
python3 -m pytest tests/ -v
```

Expected: 78 passed.

## Quick Smoke Test

```python
import sqlite3
from pathlib import Path
from grocery_assistant.db import init_db, get_connection
from grocery_assistant.grocery_list import add_from_message, format_list
from grocery_assistant.draft import create_draft, format_draft
from grocery_assistant.approval import submit_approval, can_submit

# Init DB
conn = get_connection(Path("grocery.db"))
from grocery_assistant.db import init_db
init_db()

# Add items
add_from_message(conn, "bananas, eggs, oat milk", "discord", "vern")
add_from_message(conn, "don't forget dish soap", "sms", "cara")
add_from_message(conn, "ground turkey 2 lb", "discord", "vern")

# View list
print(format_list(conn))

# Create draft
draft = create_draft(conn)
print(format_draft(draft))

# Approve (only Vern, only explicit phrase)
result = submit_approval(conn, draft["session_id"], "vern", "approve order")
print(result)

# Gate check -- True only after approval
print(can_submit(conn, draft["session_id"]))
```

## Phase 2 (Not Implemented)

- Real Discord bot intake (discord.py)
- Real SMS intake (Twilio webhook)
- Browser-assisted Instacart cart drafting (stops before final submit)
- Substitution preferences
- Recurring staples
- Improved ambiguity resolution flow

## Project Path

Windows: `C:\Users\bryce\projects\grocery-assistant`
WSL: `/mnt/c/Users/bryce/projects/grocery-assistant`
