"""
Instacart-ready order draft generation.

Produces a structured, reviewable draft from pending grocery items.
This module does NOT submit anything. It only generates output for review.

The draft format is designed to be:
- Human-readable for Vern to review before approving
- Structured enough to drive manual Instacart search in phase 2
"""

import sqlite3
from datetime import datetime
from typing import Optional

from .db import (
    create_cart_session,
    add_item_to_session,
    update_session_status,
    get_session_items,
    get_pending_items,
    get_ambiguous_items,
)


def create_draft(conn: sqlite3.Connection) -> dict:
    """
    Build an order draft from all pending grocery items.

    Returns a draft dict with:
    - session_id: the cart session ID (use this for approval)
    - items: list of item dicts ready for Instacart search
    - ambiguous: items that need clarification
    - status: always 'awaiting_approval' (never 'approved')
    - instructions: what Vern needs to do next
    """
    pending = get_pending_items(conn)
    ambiguous = get_ambiguous_items(conn)
    ambiguous_ids = {row["id"] for row in ambiguous}

    session_id = create_cart_session(conn)

    draft_items: list[dict] = []
    flagged_items: list[dict] = []

    for row in pending:
        add_item_to_session(conn, session_id, row["id"])

        item_dict = {
            "id": row["id"],
            "search_term": row["canonical"],
            "display_name": row["name"],
            "category": row["category"],
            "quantity": row["quantity"],
            "unit": row["unit"],
            "notes": row["notes"],
        }

        if row["id"] in ambiguous_ids:
            flagged_items.append(item_dict)
        else:
            draft_items.append(item_dict)

    update_session_status(conn, session_id, "awaiting_approval")

    return {
        "session_id": session_id,
        "created_at": datetime.utcnow().isoformat(),
        "status": "awaiting_approval",
        "items": draft_items,
        "ambiguous": flagged_items,
        "item_count": len(draft_items),
        "flagged_count": len(flagged_items),
        "instructions": (
            "Review the items below. Resolve any flagged ambiguities. "
            "To approve, say: 'approve order', 'place this order', "
            "or 'go ahead and submit'."
        ),
    }


def format_draft(draft: dict) -> str:
    """Human-readable draft for terminal review."""
    lines = [
        "=== Instacart Order Draft ===",
        f"Session ID : {draft['session_id']}",
        f"Status     : {draft['status']}",
        f"Items      : {draft['item_count']}",
        f"Flagged    : {draft['flagged_count']}",
        "",
        "-- Items to order --",
    ]

    if not draft["items"] and not draft["ambiguous"]:
        lines.append("  (no items)")
    else:
        for item in sorted(draft["items"], key=lambda x: x["category"]):
            qty_str = ""
            if item["quantity"]:
                qty_str = f" x{item['quantity']}"
                if item["unit"]:
                    qty_str += f" {item['unit']}"
            lines.append(
                f"  [{item['category']:10}] {item['display_name']}{qty_str}"
            )

    if draft["ambiguous"]:
        lines.append("")
        lines.append("-- Needs clarification before ordering --")
        for item in draft["ambiguous"]:
            lines.append(f"  [?] {item['display_name']}")

    lines.extend([
        "",
        draft["instructions"],
        "",
        "IMPORTANT: No order has been placed. Explicit approval required.",
    ])

    return "\n".join(lines)
