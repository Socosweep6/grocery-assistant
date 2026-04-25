"""Tests for cart-fill run bookkeeping and state transitions."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from grocery_assistant.approval import submit_approval
from grocery_assistant.cart_fill import (
    CartFillError,
    get_cart_fill_status,
    prepare_cart_fill_run,
    transition_cart_fill_run,
)
from grocery_assistant.draft import create_draft
from grocery_assistant.grocery_list import add_from_message


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema = (Path(__file__).parent.parent / "schema.sql").read_text()
    conn.executescript(schema)
    return conn


def _approved_session(conn) -> int:
    add_from_message(conn, "bananas", "discord", "vern")
    draft = create_draft(conn)
    submit_approval(conn, draft["session_id"], approver="vern", phrase="approve order")
    return draft["session_id"]


def test_prepare_cart_fill_run_blocks_when_saved_session_file_missing(conn):
    session_id = _approved_session(conn)

    result = prepare_cart_fill_run(conn, session_id, session_path="/tmp/does-not-exist.json")

    assert result["latest_run"]["status"] == "blocked"
    assert "session file missing" in result["latest_run"]["status_detail"].lower()
    assert len(result["history"]) == 1


def test_prepare_cart_fill_run_queues_when_saved_session_file_exists(conn, tmp_path):
    session_id = _approved_session(conn)
    session_file = tmp_path / "instacart-state.json"
    session_file.write_text("{}")

    result = prepare_cart_fill_run(conn, session_id, session_path=str(session_file))

    assert result["latest_run"]["status"] == "queued"
    assert result["latest_run"]["session_path"] == str(session_file)


def test_prepare_cart_fill_run_requires_approved_session(conn):
    add_from_message(conn, "bananas", "discord", "vern")
    draft = create_draft(conn)

    with pytest.raises(CartFillError, match="Only approved drafts"):
        prepare_cart_fill_run(conn, draft["session_id"])


def test_prepare_cart_fill_run_rejects_second_active_run(conn):
    session_id = _approved_session(conn)

    first = prepare_cart_fill_run(conn, session_id)
    assert first["latest_run"]["status"] == "blocked"

    with pytest.raises(CartFillError, match="already has an active cart-fill run"):
        prepare_cart_fill_run(conn, session_id)


def test_transition_cart_fill_run_tracks_started_and_finished_timestamps(conn, tmp_path):
    session_id = _approved_session(conn)
    session_file = tmp_path / "instacart-state.json"
    session_file.write_text("{}")
    prepared = prepare_cart_fill_run(conn, session_id, session_path=str(session_file))
    run_id = prepared["run_id"]
    started = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
    finished = datetime(2026, 4, 10, 12, 5, tzinfo=UTC)

    running = transition_cart_fill_run(conn, run_id, new_status="running", timestamp=started)
    partial = transition_cart_fill_run(
        conn,
        run_id,
        new_status="partial",
        status_detail="2 items not found",
        timestamp=finished,
    )

    assert running["started_at"] == started.isoformat()
    assert partial["finished_at"] == finished.isoformat()
    status = get_cart_fill_status(conn, session_id, include_history=True)
    assert status["latest_run"]["status"] == "partial"
    assert status["history"][0]["status_detail"] == "2 items not found"


def test_transition_cart_fill_run_rejects_invalid_transition(conn):
    session_id = _approved_session(conn)
    prepared = prepare_cart_fill_run(conn, session_id)

    with pytest.raises(CartFillError, match="Cannot move"):
        transition_cart_fill_run(conn, prepared["run_id"], new_status="succeeded")
