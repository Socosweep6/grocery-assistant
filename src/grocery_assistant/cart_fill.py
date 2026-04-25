"""Cart-fill run state machine for upcoming Instacart automation."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .db import (
    get_cart_fill_run,
    get_latest_cart_fill_run_for_session,
    get_session,
    insert_cart_fill_run,
    list_cart_fill_runs_for_session,
    update_cart_fill_run,
)

ACTIVE_FILL_STATUSES = frozenset({"queued", "blocked", "running"})
TERMINAL_FILL_STATUSES = frozenset({"succeeded", "partial", "failed", "cancelled"})
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"blocked", "running", "cancelled", "failed"},
    "blocked": {"queued", "cancelled", "failed"},
    "running": {"succeeded", "partial", "failed", "cancelled"},
    "succeeded": set(),
    "partial": set(),
    "failed": set(),
    "cancelled": set(),
}


class CartFillError(Exception):
    """Raised when a cart-fill run is invalid or cannot transition."""


def _serialize_run(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def prepare_cart_fill_run(conn: sqlite3.Connection,
                          session_id: int,
                          *,
                          requested_by: str = "vern",
                          session_path: str | None = None,
                          created_at: datetime | None = None) -> dict:
    """Create the first automation run record for an approved draft.

    This slice stops at bookkeeping. If the saved browser session file is not
    present, the run is immediately marked blocked. If it is present, the run is
    queued for a future worker slice.
    """
    session = get_session(conn, session_id)
    if session is None:
        raise CartFillError(f"Draft {session_id} does not exist.")
    if session["ordered_at"]:
        raise CartFillError(
            f"Draft {session_id} is already marked ordered and cannot start cart fill."
        )
    if session["status"] != "approved":
        raise CartFillError(
            "Only approved drafts can prepare an automatic cart-fill run."
        )

    latest = get_latest_cart_fill_run_for_session(conn, session_id)
    if latest is not None and latest["status"] in ACTIVE_FILL_STATUSES:
        raise CartFillError(
            f"Draft {session_id} already has an active cart-fill run in status '{latest['status']}'."
        )

    status = "queued"
    status_detail = "Run recorded. Automation worker lands in the next slice."
    if not session_path or not Path(session_path).exists():
        status = "blocked"
        status_detail = (
            "Saved Instacart session file missing. Capture login state before running browser automation."
        )

    run_id = insert_cart_fill_run(
        conn,
        session_id=session_id,
        requested_by=requested_by,
        status=status,
        status_detail=status_detail,
        session_path=session_path,
        created_at=created_at,
    )
    return get_cart_fill_status(conn, session_id, include_history=True) | {"run_id": run_id}


def transition_cart_fill_run(conn: sqlite3.Connection,
                             run_id: int,
                             *,
                             new_status: str,
                             status_detail: str | None = None,
                             timestamp: datetime | None = None) -> dict:
    row = get_cart_fill_run(conn, run_id)
    if row is None:
        raise CartFillError(f"Cart-fill run {run_id} does not exist.")

    current_status = row["status"]
    if new_status == current_status:
        return dict(get_cart_fill_run(conn, run_id))

    allowed = ALLOWED_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise CartFillError(
            f"Cannot move cart-fill run {run_id} from '{current_status}' to '{new_status}'."
        )

    ts = timestamp or datetime.now(UTC)
    started_at = ts if new_status == "running" and not row["started_at"] else None
    finished_at = ts if new_status in TERMINAL_FILL_STATUSES else None
    update_cart_fill_run(
        conn,
        run_id,
        status=new_status,
        status_detail=status_detail,
        started_at=started_at,
        finished_at=finished_at,
    )
    updated = get_cart_fill_run(conn, run_id)
    return dict(updated) if updated is not None else {}


def get_cart_fill_status(conn: sqlite3.Connection,
                         session_id: int,
                         *,
                         include_history: bool = False) -> dict:
    session = get_session(conn, session_id)
    if session is None:
        raise CartFillError(f"Draft {session_id} does not exist.")

    latest = get_latest_cart_fill_run_for_session(conn, session_id)
    history = [_serialize_run(row) for row in list_cart_fill_runs_for_session(conn, session_id)]
    payload = {
        "session_id": session_id,
        "eligible": session["status"] == "approved" and not session["ordered_at"],
        "latest_run": _serialize_run(latest),
    }
    if include_history:
        payload["history"] = history
    return payload
