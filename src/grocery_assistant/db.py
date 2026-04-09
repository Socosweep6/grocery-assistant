"""SQLite connection and schema initialization."""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "grocery.db"
SCHEMA_PATH = Path(__file__).parent.parent.parent / "schema.sql"


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    schema = SCHEMA_PATH.read_text()
    with get_connection(db_path) as conn:
        conn.executescript(schema)


def insert_intake_event(conn: sqlite3.Connection, raw_text: str,
                         source_channel: str, sender: str,
                         timestamp: Optional[datetime] = None) -> int:
    ts = (timestamp or datetime.utcnow()).isoformat()
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
    ts = (created_at or datetime.utcnow()).isoformat()
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
    ts = (created_at or datetime.utcnow()).isoformat()
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
    ts = (timestamp or datetime.utcnow()).isoformat()
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
