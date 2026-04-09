"""SQLite connection and schema initialization."""

import sqlite3
from pathlib import Path
from datetime import UTC, datetime
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "grocery.db"
SCHEMA_PATH = Path(__file__).parent.parent.parent / "schema.sql"


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_migrations(conn)
    return conn


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Run additive schema migrations.

    Safe to call on both new and existing databases. Each statement uses
    CREATE TABLE IF NOT EXISTS so it is idempotent.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preferences (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical       TEXT    NOT NULL UNIQUE,
            preferred_form  TEXT,
            substitutions_ok INTEGER NOT NULL DEFAULT 0,
            note            TEXT,
            updated_at      TEXT    NOT NULL
        )
        """
    )
    conn.commit()


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    schema = SCHEMA_PATH.read_text()
    with get_connection(db_path) as conn:
        conn.executescript(schema)


def insert_intake_event(conn: sqlite3.Connection, raw_text: str,
                         source_channel: str, sender: str,
                         timestamp: Optional[datetime] = None) -> int:
    ts = (timestamp or datetime.now(UTC)).isoformat()
    cur = conn.execute(
        "INSERT INTO intake_events (raw_text, source_channel, sender, timestamp)"
        " VALUES (?, ?, ?, ?)",
        (raw_text, source_channel, sender, ts),
    )
    conn.commit()
    return cur.lastrowid


def insert_grocery_item(conn: sqlite3.Connection, name: str, canonical: str,
                         category: str = "other", quantity: Optional[str] = None,
                         unit: Optional[str] = None, notes: Optional[str] = None,
                         ambiguous: bool = False,
                         created_at: Optional[datetime] = None) -> int:
    ts = (created_at or datetime.now(UTC)).isoformat()
    cur = conn.execute(
        "INSERT INTO grocery_items"
        " (name, canonical, category, quantity, unit, notes, ambiguous, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, canonical, category, quantity, unit, notes, int(ambiguous), ts),
    )
    conn.commit()
    return cur.lastrowid


def find_item_by_canonical(conn: sqlite3.Connection, canonical: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM grocery_items WHERE canonical = ? AND status = 'pending' LIMIT 1",
        (canonical,),
    ).fetchone()


def get_pending_items(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM grocery_items WHERE status = 'pending' ORDER BY category, canonical"
    ).fetchall()


def get_ambiguous_items(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM grocery_items WHERE ambiguous = 1 AND status = 'pending'"
    ).fetchall()


def create_cart_session(conn: sqlite3.Connection,
                         created_at: Optional[datetime] = None) -> int:
    ts = (created_at or datetime.now(UTC)).isoformat()
    cur = conn.execute(
        "INSERT INTO cart_sessions (created_at, status) VALUES (?, 'draft')",
        (ts,),
    )
    conn.commit()
    return cur.lastrowid


def add_item_to_session(conn: sqlite3.Connection,
                         session_id: int, item_id: int) -> None:
    conn.execute(
        "INSERT INTO cart_session_items (session_id, item_id) VALUES (?, ?)",
        (session_id, item_id),
    )
    conn.commit()


def update_session_status(conn: sqlite3.Connection,
                           session_id: int, status: str) -> None:
    conn.execute(
        "UPDATE cart_sessions SET status = ? WHERE id = ?",
        (status, session_id),
    )
    conn.commit()


def get_session(conn: sqlite3.Connection, session_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM cart_sessions WHERE id = ?", (session_id,)
    ).fetchone()


def record_approval(conn: sqlite3.Connection, session_id: int,
                     approved_by: str, approval_phrase: str,
                     timestamp: Optional[datetime] = None) -> int:
    ts = (timestamp or datetime.now(UTC)).isoformat()
    cur = conn.execute(
        "INSERT INTO approvals (session_id, approved_by, approval_phrase, timestamp)"
        " VALUES (?, ?, ?, ?)",
        (session_id, approved_by, approval_phrase, ts),
    )
    conn.commit()
    return cur.lastrowid


def get_session_items(conn: sqlite3.Connection,
                       session_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT gi.* FROM grocery_items gi"
        " JOIN cart_session_items csi ON gi.id = csi.item_id"
        " WHERE csi.session_id = ?",
        (session_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Source traceability
# ---------------------------------------------------------------------------

def insert_item_source(conn: sqlite3.Connection,
                        item_id: int, event_id: int) -> None:
    """Link a grocery item to the intake event that requested it."""
    conn.execute(
        "INSERT INTO grocery_item_sources (item_id, event_id) VALUES (?, ?)",
        (item_id, event_id),
    )
    conn.commit()


def get_items_by_sender(conn: sqlite3.Connection,
                         sender: str) -> list[sqlite3.Row]:
    """Return distinct pending items that were requested by a given sender."""
    return conn.execute(
        "SELECT DISTINCT gi.* FROM grocery_items gi"
        " JOIN grocery_item_sources gis ON gi.id = gis.item_id"
        " JOIN intake_events ie ON gis.event_id = ie.id"
        " WHERE LOWER(ie.sender) = LOWER(?)"
        " AND gi.status = 'pending'"
        " ORDER BY gi.category, gi.canonical",
        (sender,),
    ).fetchall()


def get_items_by_channel(conn: sqlite3.Connection,
                          source_channel: str) -> list[sqlite3.Row]:
    """Return distinct pending items that arrived via a given source channel."""
    return conn.execute(
        "SELECT DISTINCT gi.* FROM grocery_items gi"
        " JOIN grocery_item_sources gis ON gi.id = gis.item_id"
        " JOIN intake_events ie ON gis.event_id = ie.id"
        " WHERE ie.source_channel = ?"
        " AND gi.status = 'pending'"
        " ORDER BY gi.category, gi.canonical",
        (source_channel,),
    ).fetchall()


def get_source_events_for_item(conn: sqlite3.Connection,
                                item_id: int) -> list[sqlite3.Row]:
    """Return all intake events that contributed to a given grocery item."""
    return conn.execute(
        "SELECT ie.* FROM intake_events ie"
        " JOIN grocery_item_sources gis ON ie.id = gis.event_id"
        " WHERE gis.item_id = ?"
        " ORDER BY ie.timestamp",
        (item_id,),
    ).fetchall()


def update_item_quantity(conn: sqlite3.Connection,
                          item_id: int, quantity: str,
                          unit: str | None) -> None:
    """Update the quantity and unit for an existing grocery item."""
    conn.execute(
        "UPDATE grocery_items SET quantity = ?, unit = ? WHERE id = ?",
        (quantity, unit, item_id),
    )
    conn.commit()


def update_item_resolved(conn: sqlite3.Connection,
                          item_id: int, new_name: str,
                          new_canonical: str) -> None:
    """Clear ambiguous flag and update name/canonical after clarification."""
    conn.execute(
        "UPDATE grocery_items SET name = ?, canonical = ?, ambiguous = 0 WHERE id = ?",
        (new_name, new_canonical, item_id),
    )
    conn.commit()


def get_item_by_id(conn: sqlite3.Connection,
                    item_id: int) -> Optional[sqlite3.Row]:
    """Return a single grocery item by primary key."""
    return conn.execute(
        "SELECT * FROM grocery_items WHERE id = ?", (item_id,)
    ).fetchone()


def insert_clarification_log(conn: sqlite3.Connection,
                               item_id: int,
                               original_name: str, original_canonical: str,
                               resolved_name: str, resolved_canonical: str,
                               resolved_by: str,
                               timestamp: Optional[datetime] = None) -> int:
    """Record the resolution of an ambiguous item."""
    ts = (timestamp or datetime.now(UTC)).isoformat()
    cur = conn.execute(
        "INSERT INTO clarification_log"
        " (item_id, original_name, original_canonical,"
        "  resolved_name, resolved_canonical, resolved_by, timestamp)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (item_id, original_name, original_canonical,
         resolved_name, resolved_canonical, resolved_by, ts),
    )
    conn.commit()
    return cur.lastrowid


def get_clarification_log(conn: sqlite3.Connection,
                           item_id: int) -> list[sqlite3.Row]:
    """Return all clarification history for an item."""
    return conn.execute(
        "SELECT * FROM clarification_log WHERE item_id = ? ORDER BY timestamp",
        (item_id,),
    ).fetchall()


def remove_item(conn: sqlite3.Connection, item_id: int) -> None:
    """Set an item's status to 'removed'. Does not delete the row (auditability)."""
    conn.execute(
        "UPDATE grocery_items SET status = 'removed' WHERE id = ?",
        (item_id,),
    )
    conn.commit()


def insert_removal_log(conn: sqlite3.Connection,
                        item_id: int,
                        item_name: str,
                        removed_by: str = "operator",
                        reason: str | None = None,
                        timestamp: datetime | None = None) -> int:
    """Record that an item was removed by an operator."""
    ts = (timestamp or datetime.now(UTC)).isoformat()
    cur = conn.execute(
        "INSERT INTO removal_log (item_id, item_name, removed_by, reason, timestamp)"
        " VALUES (?, ?, ?, ?, ?)",
        (item_id, item_name, removed_by, reason, ts),
    )
    conn.commit()
    return cur.lastrowid


def get_removal_log(conn: sqlite3.Connection,
                     item_id: int) -> list[sqlite3.Row]:
    """Return all removal log entries for a given item."""
    return conn.execute(
        "SELECT * FROM removal_log WHERE item_id = ? ORDER BY timestamp",
        (item_id,),
    ).fetchall()


def get_last_session_time(conn: sqlite3.Connection,
                           before_session_id: int | None = None) -> str | None:
    """Return the created_at of the most recent cart_session before before_session_id.

    If before_session_id is None, returns the most recent session overall.
    Returns None if no previous sessions exist.
    """
    if before_session_id is not None:
        row = conn.execute(
            "SELECT created_at FROM cart_sessions"
            " WHERE id < ? ORDER BY id DESC LIMIT 1",
            (before_session_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT created_at FROM cart_sessions ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row["created_at"] if row else None


def get_sessions_needing_clarification(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all cart sessions currently in needs_clarification status."""
    return conn.execute(
        "SELECT * FROM cart_sessions WHERE status = 'needs_clarification'"
    ).fetchall()


def count_ambiguous_in_session(conn: sqlite3.Connection,
                                 session_id: int) -> int:
    """Count how many ambiguous *pending* items remain in a given session.

    Removed items are excluded: removing an ambiguous item should unblock
    the session just as resolving it does.
    """
    row = conn.execute(
        "SELECT COUNT(*) as n FROM cart_session_items csi"
        " JOIN grocery_items gi ON csi.item_id = gi.id"
        " WHERE csi.session_id = ? AND gi.ambiguous = 1 AND gi.status = 'pending'",
        (session_id,),
    ).fetchone()
    return row["n"] if row else 0
