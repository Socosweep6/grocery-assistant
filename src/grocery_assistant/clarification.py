"""
Ambiguity resolution service.

Handles the workflow for resolving flagged grocery items:
  1. List items that are still ambiguous.
  2. Resolve an item by supplying a refined name (e.g. "milk" -> "oat milk").
  3. Log the resolution for auditability.
  4. Promote any needs_clarification cart session to awaiting_approval once all
     ambiguous items in that session are cleared.

This module contains zero HTTP or CLI logic. Those live in web.py and cli.py.
"""

import sqlite3
from datetime import UTC, datetime
from typing import Optional

from .normalizer import normalize_item
from .db import (
    get_ambiguous_items,
    get_item_by_id,
    update_item_resolved,
    insert_clarification_log,
    get_clarification_log,
    get_sessions_needing_clarification,
    count_ambiguous_in_session,
    update_session_status,
)


class ClarificationError(ValueError):
    """Raised when a resolution attempt is invalid."""
    pass


def list_ambiguous(conn: sqlite3.Connection) -> list[dict]:
    """
    Return all pending items that are still flagged as ambiguous.

    Each entry includes the item ID, name, and canonical so the operator
    knows what to supply a refinement for.
    """
    rows = get_ambiguous_items(conn)
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "canonical": row["canonical"],
            "category": row["category"],
        }
        for row in rows
    ]


def promote_cleared_sessions(conn: sqlite3.Connection) -> list[int]:
    """Promote any needs_clarification sessions that now have zero ambiguous pending items.

    Called after both item resolution and item removal, since either action can
    be the last step that unblocks a session.

    Returns a list of session IDs that were promoted to awaiting_approval.
    """
    promoted: list[int] = []
    for session in get_sessions_needing_clarification(conn):
        sid = session["id"]
        if count_ambiguous_in_session(conn, sid) == 0:
            update_session_status(conn, sid, "awaiting_approval")
            promoted.append(sid)
    return promoted


def resolve_item(conn: sqlite3.Connection,
                  item_id: int,
                  new_name: str,
                  resolved_by: str,
                  timestamp: Optional[datetime] = None) -> dict:
    """
    Resolve an ambiguous grocery item by replacing it with a refined name.

    Steps:
      1. Validate the item exists and is currently ambiguous.
      2. Normalize the new name through the existing normalizer.
      3. Reject if the normalized form is still ambiguous.
      4. Log the resolution (original -> resolved) in clarification_log.
      5. Update the item row: new name, new canonical, ambiguous = 0.
      6. Check every needs_clarification session -- promote any that are now clear.

    Args:
        conn: SQLite connection.
        item_id: Primary key of the grocery_items row to resolve.
        new_name: Refined item description (e.g. "oat milk", "sourdough bread").
        resolved_by: Name of the operator or sender providing the clarification.
        timestamp: Override for audit log timestamp (default: now UTC).

    Returns:
        Dict with resolution details and promoted_sessions list.

    Raises:
        ClarificationError: item not found, not ambiguous, or new name still ambiguous.
    """
    item = get_item_by_id(conn, item_id)
    if item is None:
        raise ClarificationError(f"Item {item_id} does not exist.")
    if not item["ambiguous"]:
        raise ClarificationError(
            f"Item {item_id} ('{item['name']}') is not flagged as ambiguous. "
            "Nothing to resolve."
        )

    new_name = new_name.strip()
    if not new_name:
        raise ClarificationError("New name must not be empty.")

    parsed = normalize_item(new_name)
    if parsed.ambiguous:
        raise ClarificationError(
            f"'{new_name}' is still ambiguous: {parsed.ambiguity_reason}. "
            "Provide a more specific name."
        )

    ts = timestamp or datetime.now(UTC)

    insert_clarification_log(
        conn,
        item_id=item_id,
        original_name=item["name"],
        original_canonical=item["canonical"],
        resolved_name=parsed.raw,
        resolved_canonical=parsed.canonical,
        resolved_by=resolved_by,
        timestamp=ts,
    )

    update_item_resolved(conn, item_id, parsed.raw, parsed.canonical)

    promoted = promote_cleared_sessions(conn)

    return {
        "item_id": item_id,
        "original_name": item["name"],
        "original_canonical": item["canonical"],
        "resolved_name": parsed.raw,
        "resolved_canonical": parsed.canonical,
        "resolved_by": resolved_by,
        "timestamp": ts.isoformat(),
        "promoted_sessions": promoted,
    }


def get_resolution_history(conn: sqlite3.Connection, item_id: int) -> list[dict]:
    """
    Return the clarification history for a specific item.

    Useful for auditing how an ambiguous item evolved.
    """
    rows = get_clarification_log(conn, item_id)
    return [
        {
            "id": row["id"],
            "item_id": row["item_id"],
            "original_name": row["original_name"],
            "original_canonical": row["original_canonical"],
            "resolved_name": row["resolved_name"],
            "resolved_canonical": row["resolved_canonical"],
            "resolved_by": row["resolved_by"],
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]


def all_resolved(conn: sqlite3.Connection) -> bool:
    """Return True if no pending items are currently ambiguous."""
    return len(get_ambiguous_items(conn)) == 0
