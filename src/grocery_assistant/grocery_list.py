"""
Master grocery list management.

Handles adding items from intake events, deduplication, and list queries.
Dedup is canonical-based: if an item with the same canonical name is already
pending, we skip insertion (or update quantity if provided).
"""

import sqlite3
from datetime import datetime
from typing import Optional

from .db import (
    insert_intake_event,
    insert_grocery_item,
    find_item_by_canonical,
    get_pending_items,
    get_ambiguous_items,
)
from .models import IntakeEvent, GroceryItem, ParsedItem
from .normalizer import parse_message


def add_from_message(conn: sqlite3.Connection, raw_text: str,
                      source_channel: str, sender: str,
                      timestamp: Optional[datetime] = None) -> dict:
    """
    Process a raw intake message: parse, dedup, persist.
    Returns a summary dict of what was added vs skipped.
    """
    ts = timestamp or datetime.utcnow()

    event_id = insert_intake_event(conn, raw_text, source_channel, sender, ts)
    parsed_items = parse_message(raw_text)

    added: list[str] = []
    skipped: list[str] = []
    flagged: list[dict] = []

    for item in parsed_items:
        existing = find_item_by_canonical(conn, item.canonical)
        if existing:
            skipped.append(item.canonical)
            continue

        insert_grocery_item(
            conn,
            name=item.raw,
            canonical=item.canonical,
            category=item.category,
            quantity=item.quantity,
            unit=item.unit,
            notes=item.notes,
            ambiguous=item.ambiguous,
            created_at=ts,
        )
        added.append(item.canonical)

        if item.ambiguous:
            flagged.append({
                "item": item.canonical,
                "reason": item.ambiguity_reason,
            })

    return {
        "event_id": event_id,
        "added": added,
        "skipped": skipped,
        "flagged": flagged,
    }


def get_list(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all pending grocery items ordered by category."""
    return get_pending_items(conn)


def get_list_by_category(conn: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    """Return pending items grouped by category."""
    items = get_pending_items(conn)
    result: dict[str, list] = {}
    for item in items:
        cat = item["category"]
        result.setdefault(cat, []).append(item)
    return result


def get_flagged(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return items flagged as ambiguous."""
    return get_ambiguous_items(conn)


def format_list(conn: sqlite3.Connection) -> str:
    """Human-readable grocery list grouped by category."""
    by_cat = get_list_by_category(conn)
    if not by_cat:
        return "Grocery list is empty."

    lines = ["=== Grocery List ==="]
    for cat, items in sorted(by_cat.items()):
        lines.append(f"\n[{cat.upper()}]")
        for item in items:
            qty_str = ""
            if item["quantity"]:
                qty_str = f" {item['quantity']}"
                if item["unit"]:
                    qty_str += f" {item['unit']}"
            flag = " [?]" if item["ambiguous"] else ""
            lines.append(f"  - {item['name']}{qty_str}{flag}")

    flagged = get_flagged(conn)
    if flagged:
        lines.append("\n[AMBIGUOUS - needs clarification]")
        for item in flagged:
            lines.append(f"  - {item['name']}")

    return "\n".join(lines)
