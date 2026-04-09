"""
Tests for draft status behavior and approval gating with ambiguous items.

Covers:
- Draft with no ambiguous items -> status 'awaiting_approval'
- Draft with ambiguous items -> status 'needs_clarification'
- Approval blocked for needs_clarification sessions
- Approval allowed for awaiting_approval sessions (Vern only)
- can_submit returns False for needs_clarification
- can_submit returns True only after explicit approval
- Mixed drafts: some clear, some ambiguous -> needs_clarification overall
"""

import sqlite3
import pytest
from pathlib import Path

from grocery_assistant.db import (
    create_cart_session,
    update_session_status,
    get_session,
)
from grocery_assistant.grocery_list import add_from_message
from grocery_assistant.draft import create_draft
from grocery_assistant.approval import (
    submit_approval,
    can_submit,
    ApprovalError,
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


# ---------------------------------------------------------------------------
# Draft status assignment
# ---------------------------------------------------------------------------

def test_draft_with_clear_items_is_awaiting_approval(conn):
    add_from_message(conn, "bananas", "discord", "vern")
    add_from_message(conn, "eggs", "discord", "vern")
    draft = create_draft(conn)
    assert draft["status"] == "awaiting_approval"
    assert draft["flagged_count"] == 0


def test_draft_with_ambiguous_items_is_needs_clarification(conn):
    add_from_message(conn, "milk", "discord", "vern")  # ambiguous - no type
    draft = create_draft(conn)
    assert draft["status"] == "needs_clarification"
    assert draft["flagged_count"] == 1


def test_draft_status_persisted_in_db(conn):
    add_from_message(conn, "milk", "sms", "cara")
    draft = create_draft(conn)
    session = get_session(conn, draft["session_id"])
    assert session["status"] == "needs_clarification"


def test_draft_mixed_items_status_is_needs_clarification(conn):
    add_from_message(conn, "bananas", "discord", "vern")   # clear
    add_from_message(conn, "bread", "discord", "vern")     # ambiguous
    draft = create_draft(conn)
    assert draft["status"] == "needs_clarification"
    assert draft["item_count"] == 1      # bananas
    assert draft["flagged_count"] == 1   # bread


def test_draft_ambiguous_items_listed_separately(conn):
    add_from_message(conn, "chips", "discord", "vern")     # ambiguous
    add_from_message(conn, "eggs", "discord", "vern")      # clear
    draft = create_draft(conn)
    ambig_names = [i["display_name"] for i in draft["ambiguous"]]
    clear_names = [i["display_name"] for i in draft["items"]]
    assert any("chips" in n.lower() for n in ambig_names)
    assert "eggs" in clear_names


# ---------------------------------------------------------------------------
# Approval gate with needs_clarification
# ---------------------------------------------------------------------------

def test_approval_blocked_for_needs_clarification(conn):
    add_from_message(conn, "milk", "discord", "vern")
    draft = create_draft(conn)
    assert draft["status"] == "needs_clarification"

    with pytest.raises(ApprovalError, match="ambiguous"):
        submit_approval(conn, draft["session_id"], approver="vern",
                        phrase="approve order")


def test_can_submit_false_for_needs_clarification(conn):
    add_from_message(conn, "bread", "discord", "vern")
    draft = create_draft(conn)
    assert can_submit(conn, draft["session_id"]) is False


def test_approval_works_for_awaiting_approval_session(conn):
    add_from_message(conn, "bananas", "discord", "vern")
    draft = create_draft(conn)
    assert draft["status"] == "awaiting_approval"

    result = submit_approval(conn, draft["session_id"], approver="vern",
                             phrase="approve order")
    assert result["approved"] is True


def test_can_submit_true_after_approval_of_clear_draft(conn):
    add_from_message(conn, "eggs", "discord", "vern")
    draft = create_draft(conn)
    submit_approval(conn, draft["session_id"], approver="vern",
                    phrase="approve order")
    assert can_submit(conn, draft["session_id"]) is True


# ---------------------------------------------------------------------------
# Approval identity enforcement still applies
# ---------------------------------------------------------------------------

def test_cara_cannot_approve_clear_draft(conn):
    add_from_message(conn, "eggs", "discord", "vern")
    draft = create_draft(conn)
    with pytest.raises(ApprovalError, match="Only Vern"):
        submit_approval(conn, draft["session_id"], approver="cara",
                        phrase="approve order")


def test_vague_phrase_still_rejected_for_clear_draft(conn):
    add_from_message(conn, "eggs", "discord", "vern")
    draft = create_draft(conn)
    with pytest.raises(ApprovalError):
        submit_approval(conn, draft["session_id"], approver="vern",
                        phrase="looks good")


# ---------------------------------------------------------------------------
# Edge: empty draft
# ---------------------------------------------------------------------------

def test_empty_draft_is_awaiting_approval(conn):
    # No items added - draft should still be awaiting_approval (nothing ambiguous)
    draft = create_draft(conn)
    assert draft["status"] == "awaiting_approval"
    assert draft["item_count"] == 0
    assert draft["flagged_count"] == 0
