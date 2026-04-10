"""Tests for Phase 2 shopping handoff helpers and ordered state transitions."""

import sqlite3
from pathlib import Path

import pytest

from grocery_assistant.approval import can_submit, submit_approval
from grocery_assistant.draft import create_draft
from grocery_assistant.grocery_list import add_from_message, get_list
from grocery_assistant.preferences import set_preference
from grocery_assistant.shopping import (
    ShoppingHandoffError,
    build_search_term,
    build_shopping_handoff,
    complete_shopping_handoff,
)


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema = (Path(__file__).parent.parent / "schema.sql").read_text()
    conn.executescript(schema)
    return conn


def test_build_search_term_prefers_preferred_form_and_notes():
    term = build_search_term(
        {"name": "milk", "notes": "unsweetened", "canonical": "milk"},
        {"preferred_form": "oat milk"},
    )
    assert term == "oat milk milk unsweetened"


def test_build_shopping_handoff_requires_approved_session(conn):
    add_from_message(conn, "bananas", "discord", "vern")
    draft = create_draft(conn)

    with pytest.raises(ShoppingHandoffError, match="Approve this draft"):
        build_shopping_handoff(conn, draft["session_id"])


def test_build_shopping_handoff_includes_instacart_links(conn):
    add_from_message(conn, "milk", "discord", "vern")
    item_id = conn.execute("SELECT id FROM grocery_items").fetchone()["id"]
    conn.execute(
        "UPDATE grocery_items SET ambiguous = 0, name = ?, canonical = ? WHERE id = ?",
        ("oat milk", "milk oat", item_id),
    )
    conn.commit()
    set_preference(conn, "milk oat", preferred_form="oat milk", note="unsweetened")

    draft = create_draft(conn)
    submit_approval(conn, draft["session_id"], approver="vern", phrase="approve order")
    handoff = build_shopping_handoff(conn, draft["session_id"])

    assert handoff["items"][0]["search_term"] == "oat milk unsweetened"
    assert "instacart.com/store/search_v3/term?term=oat+milk+unsweetened" in handoff["items"][0]["instacart_url"]


def test_complete_shopping_handoff_moves_items_off_active_list(conn):
    add_from_message(conn, "bananas, eggs", "discord", "vern")
    draft = create_draft(conn)
    submit_approval(conn, draft["session_id"], approver="vern", phrase="approve order")

    result = complete_shopping_handoff(conn, draft["session_id"])
    session = conn.execute("SELECT * FROM cart_sessions WHERE id = ?", (draft["session_id"],)).fetchone()
    statuses = [row["status"] for row in conn.execute("SELECT status FROM grocery_items ORDER BY id").fetchall()]

    assert result["updated_items"] == 2
    assert session["ordered_at"] is not None
    assert statuses == ["ordered", "ordered"]
    assert get_list(conn) == []


def test_complete_shopping_handoff_is_idempotent(conn):
    add_from_message(conn, "bananas", "discord", "vern")
    draft = create_draft(conn)
    submit_approval(conn, draft["session_id"], approver="vern", phrase="approve order")

    first = complete_shopping_handoff(conn, draft["session_id"])
    second = complete_shopping_handoff(conn, draft["session_id"])

    assert first["already_ordered"] is False
    assert second["already_ordered"] is True
    assert second["updated_items"] == 0


def test_can_submit_false_after_manual_checkout(conn):
    add_from_message(conn, "bananas", "discord", "vern")
    draft = create_draft(conn)
    submit_approval(conn, draft["session_id"], approver="vern", phrase="approve order")

    assert can_submit(conn, draft["session_id"]) is True
    complete_shopping_handoff(conn, draft["session_id"])
    assert can_submit(conn, draft["session_id"]) is False
