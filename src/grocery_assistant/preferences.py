"""
Household preference and substitution rules.

Each entry maps a canonical item name to a preferred form and/or substitution policy.
Used in draft output and during ambiguity resolution to surface helpful notes.

Examples:
  milk          -> prefer oat milk, no substitutions
  bread         -> prefer sourdough
  eggs          -> substitutions okay
  oat milk      -> exact item preferred

The preferences table starts empty. Add rules at runtime via CLI or API:

  # CLI
  python -m grocery_assistant.cli prefs set milk --prefer "oat milk"
  python -m grocery_assistant.cli prefs set eggs --subs-ok
  python -m grocery_assistant.cli prefs list

  # API
  POST /api/preferences  {"canonical": "milk", "preferred_form": "oat milk"}
  GET  /api/preferences
  DELETE /api/preferences/milk
"""

import sqlite3
from datetime import UTC, datetime

from .db import get_connection


def set_preference(conn: sqlite3.Connection, canonical: str,
                   preferred_form: str | None = None,
                   substitutions_ok: bool = False,
                   note: str | None = None) -> dict:
    """Insert or update a preference rule for a canonical item name."""
    ts = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO preferences (canonical, preferred_form, substitutions_ok, note, updated_at)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(canonical) DO UPDATE SET"
        "  preferred_form = excluded.preferred_form,"
        "  substitutions_ok = excluded.substitutions_ok,"
        "  note = excluded.note,"
        "  updated_at = excluded.updated_at",
        (canonical, preferred_form, int(substitutions_ok), note, ts),
    )
    conn.commit()
    return get_preference(conn, canonical)


def get_preference(conn: sqlite3.Connection, canonical: str) -> dict | None:
    """Return preference for a canonical item name, or None if no rule exists."""
    row = conn.execute(
        "SELECT * FROM preferences WHERE canonical = ?", (canonical,)
    ).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def list_preferences(conn: sqlite3.Connection) -> list[dict]:
    """Return all preference rules, ordered by canonical name."""
    rows = conn.execute(
        "SELECT * FROM preferences ORDER BY canonical"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_preference(conn: sqlite3.Connection, canonical: str) -> bool:
    """Remove a preference rule. Returns True if a row was deleted."""
    cur = conn.execute("DELETE FROM preferences WHERE canonical = ?", (canonical,))
    conn.commit()
    return cur.rowcount > 0


def get_preference_for_item(conn: sqlite3.Connection, canonical: str) -> dict | None:
    """Return preference for item. Tries exact canonical, then falls back to None."""
    return get_preference(conn, canonical)


def format_preference_note(pref: dict) -> str:
    """Return a short human-readable note for displaying in draft/resolve output."""
    parts = []
    if pref.get("preferred_form"):
        parts.append(f"prefer: {pref['preferred_form']}")
    if pref.get("substitutions_ok"):
        parts.append("substitutions OK")
    else:
        parts.append("exact item preferred")
    if pref.get("note"):
        parts.append(pref["note"])
    return " | ".join(parts)


def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "canonical": row["canonical"],
        "preferred_form": row["preferred_form"],
        "substitutions_ok": bool(row["substitutions_ok"]),
        "note": row["note"],
        "updated_at": row["updated_at"],
    }
