"""
Master grocery list management.

Handles adding items from intake events, deduplication, and list queries.

Dedup rules (safe merge):
  - Canonical name is the dedup key. If an item with the same canonical
    name already exists as pending, we do NOT create a second item.
  - We always link the new intake event to the existing item via
    grocery_item_sources, so provenance is never lost.
  - Quantity merge: if the existing item has no quantity and the new
    request specifies one, we promote it. If both have quantities and they
    differ, we leave the existing quantity unchanged (don't guess).
  - The result dict includes 'merged' for items that were deduplicated
    (with updated source link) vs 'added' for brand-new items.
"""

import sqlite3
from datetime import UTC, datetime
from typing import Optional

from .db import (
    insert_intake_event,
    insert_grocery_item,
    insert_item_source,
    update_item_quantity,
    find_item_by_canonical,
    get_pending_items,
    get_ambiguous_items,
    get_items_by_sender,
    get_items_by_channel,
)
from .normalizer import parse_message


def add_from_message(conn: sqlite3.Connection, raw_text: str,
                      source_channel: str, sender: str,
                      timestamp: Optional[datetime] = None) -> dict:
    """
    Process a raw intake message: parse, dedup, persist.

    Always records the intake event and always links source events to items,
    even for duplicates. Never silently drops provenance.

    Returns:
        {
            "event_id": int,
            "added":   [canonical, ...],   # new items inserted
            "merged":  [canonical, ...],   # duplicates; source linked, qty promoted if safe
            "flagged": [{"item": ..., "reason": ...}, ...],  # ambiguous new items
        }
    """
    ts = timestamp or datetime.now(UTC)

    event_id = insert_intake_event(conn, raw_text, source_channel, sender, ts)
    parsed_items = parse_message(raw_text)

    added: list[str] = []
    merged: list[str] = []
    flagged: list[dict] = []

    for item in parsed_items:
        existing = find_item_by_canonical(conn, item.canonical)

        if existing:
            # Preserve source link even on duplicate - never lose who asked
            insert_item_source(conn, existing["id"], event_id)

            # Safe quantity promotion: only promote if existing has none
            if item.quantity and not existing["quantity"]:
                update_item_quantity(conn, existing["id"], item.quantity, item.unit)

            merged.append(item.canonical)
            continue

        item_id = insert_grocery_item(
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
        insert_item_source(conn, item_id, event_id)
        added.append(item.canonical)

        if item.ambiguous:
            flagged.append({
                "item": item.canonical,
                "reason": item.ambiguity_reason,
            })

    return {
        "event_id": event_id,
        "added": added,
        "merged": merged,
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


def get_by_sender(conn: sqlite3.Connection, sender: str) -> list[sqlite3.Row]:
    """Return pending items that were requested by a specific sender."""
    return get_items_by_sender(conn, sender)


def get_by_channel(conn: sqlite3.Connection,
                    source_channel: str) -> list[sqlite3.Row]:
    """Return pending items that arrived via a specific source channel."""
    return get_items_by_channel(conn, source_channel)


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
