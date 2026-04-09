"""
Tests for the clarification service (ambiguity resolution workflow).

Covers:
- list_ambiguous returns only pending ambiguous items
- resolve_item: happy path, audit log, session promotion
- resolve_item: rejects non-existent item, non-ambiguous item, still-ambiguous name
- get_resolution_history returns ordered audit trail
- all_resolved returns correct state
- Session promoted from needs_clarification to awaiting_approval when last ambiguity cleared
- Multiple ambiguous items: session only promoted when ALL are resolved
"""

import sqlite3
import pytest
from pathlib import Path
from datetime import UTC, datetime

from grocery_assistant.db import (
    get_connection,
    create_cart_session,
    update_session_status,
    get_session,
    add_item_to_session,
)
from grocery_assistant.grocery_list import add_from_message
from grocery_assistant.clarification import (
    list_ambiguous,
    resolve_item,
    get_resolution_history,
    all_resolved,
    ClarificationError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    schema = (Path(__file__).parent.parent / "schema.sql").read_text()
    c.executescript(schema)
    return c


@pytest.fixture
def conn_with_ambiguous(conn):
    """Connection with one ambiguous item (bare 'milk') and one clear item (bananas)."""
    add_from_message(conn, "milk", "sms", "cara")
    add_from_message(conn, "bananas", "discord", "vern")
    return conn


@pytest.fixture
def ambiguous_item_id(conn_with_ambiguous):
    """Return the item ID of the ambiguous 'milk' item."""
    items = list_ambiguous(conn_with_ambiguous)
    assert len(items) == 1
    return items[0]["id"]


# ---------------------------------------------------------------------------
# list_ambiguous
# ---------------------------------------------------------------------------

def test_list_ambiguous_empty_when_no_items(conn):
    assert list_ambiguous(conn) == []


def test_list_ambiguous_returns_only_ambiguous(conn_with_ambiguous):
    items = list_ambiguous(conn_with_ambiguous)
    assert len(items) == 1
    assert items[0]["canonical"] == "milk"


def test_list_ambiguous_includes_required_fields(conn_with_ambiguous):
    items = list_ambiguous(conn_with_ambiguous)
    item = items[0]
    assert "id" in item
    assert "name" in item
    assert "canonical" in item
    assert "category" in item


def test_list_ambiguous_multiple(conn):
    add_from_message(conn, "milk", "sms", "cara")
    add_from_message(conn, "bread", "discord", "vern")
    add_from_message(conn, "chips", "sms", "cara")
    items = list_ambiguous(conn)
    canonicals = {i["canonical"] for i in items}
    assert "milk" in canonicals
    assert "bread" in canonicals
    assert "chips" in canonicals


# ---------------------------------------------------------------------------
# resolve_item: validation errors
# ---------------------------------------------------------------------------

def test_resolve_nonexistent_item_raises(conn):
    with pytest.raises(ClarificationError, match="does not exist"):
        resolve_item(conn, 9999, "oat milk", "operator")


def test_resolve_non_ambiguous_item_raises(conn):
    add_from_message(conn, "bananas", "discord", "vern")
    # bananas is not ambiguous
    items = list_ambiguous(conn)
    assert len(items) == 0
    # get the bananas item id
    row = conn.execute(
        "SELECT id FROM grocery_items WHERE canonical = 'bananas'"
    ).fetchone()
    assert row is not None
    with pytest.raises(ClarificationError, match="not flagged as ambiguous"):
        resolve_item(conn, row["id"], "bananas", "operator")


def test_resolve_still_ambiguous_name_raises(conn, conn_with_ambiguous, ambiguous_item_id):
    # "milk" is still ambiguous even as the new name
    with pytest.raises(ClarificationError, match="still ambiguous"):
        resolve_item(conn_with_ambiguous, ambiguous_item_id, "milk", "operator")


def test_resolve_empty_new_name_raises(conn_with_ambiguous, ambiguous_item_id):
    with pytest.raises(ClarificationError, match="not be empty"):
        resolve_item(conn_with_ambiguous, ambiguous_item_id, "  ", "operator")


# ---------------------------------------------------------------------------
# resolve_item: happy path
# ---------------------------------------------------------------------------

def test_resolve_item_returns_result_dict(conn_with_ambiguous, ambiguous_item_id):
    result = resolve_item(conn_with_ambiguous, ambiguous_item_id, "oat milk", "operator")
    assert result["item_id"] == ambiguous_item_id
    assert result["resolved_name"] == "oat milk"
    assert result["resolved_canonical"] == "milk oat"
    assert result["resolved_by"] == "operator"
    assert "original_name" in result
    assert "original_canonical" in result
    assert "timestamp" in result
    assert "promoted_sessions" in result


def test_resolve_item_clears_ambiguous_flag(conn_with_ambiguous, ambiguous_item_id):
    resolve_item(conn_with_ambiguous, ambiguous_item_id, "oat milk", "operator")
    row = conn_with_ambiguous.execute(
        "SELECT ambiguous FROM grocery_items WHERE id = ?", (ambiguous_item_id,)
    ).fetchone()
    assert row["ambiguous"] == 0


def test_resolve_item_updates_name_and_canonical(conn_with_ambiguous, ambiguous_item_id):
    resolve_item(conn_with_ambiguous, ambiguous_item_id, "oat milk", "operator")
    row = conn_with_ambiguous.execute(
        "SELECT name, canonical FROM grocery_items WHERE id = ?", (ambiguous_item_id,)
    ).fetchone()
    assert row["name"] == "oat milk"
    assert row["canonical"] == "milk oat"


def test_resolve_item_writes_clarification_log(conn_with_ambiguous, ambiguous_item_id):
    resolve_item(conn_with_ambiguous, ambiguous_item_id, "oat milk", "operator")
    log = get_resolution_history(conn_with_ambiguous, ambiguous_item_id)
    assert len(log) == 1
    entry = log[0]
    assert entry["item_id"] == ambiguous_item_id
    assert entry["resolved_name"] == "oat milk"
    assert entry["resolved_canonical"] == "milk oat"
    assert entry["resolved_by"] == "operator"


def test_resolve_item_log_preserves_original(conn_with_ambiguous, ambiguous_item_id):
    item_before = list_ambiguous(conn_with_ambiguous)[0]
    resolve_item(conn_with_ambiguous, ambiguous_item_id, "oat milk", "operator")
    log = get_resolution_history(conn_with_ambiguous, ambiguous_item_id)[0]
    assert log["original_name"] == item_before["name"]
    assert log["original_canonical"] == item_before["canonical"]


def test_resolve_item_list_ambiguous_now_empty(conn_with_ambiguous, ambiguous_item_id):
    resolve_item(conn_with_ambiguous, ambiguous_item_id, "oat milk", "operator")
    assert list_ambiguous(conn_with_ambiguous) == []


# ---------------------------------------------------------------------------
# Session promotion
# ---------------------------------------------------------------------------

def test_resolve_promotes_needs_clarification_session(conn_with_ambiguous, ambiguous_item_id):
    # Create a session in needs_clarification that includes the ambiguous item
    sid = create_cart_session(conn_with_ambiguous)
    add_item_to_session(conn_with_ambiguous, sid, ambiguous_item_id)
    update_session_status(conn_with_ambiguous, sid, "needs_clarification")

    result = resolve_item(conn_with_ambiguous, ambiguous_item_id, "oat milk", "operator")
    assert sid in result["promoted_sessions"]

    session = get_session(conn_with_ambiguous, sid)
    assert session["status"] == "awaiting_approval"


def test_resolve_does_not_promote_if_other_ambiguous_remain(conn):
    """Session with two ambiguous items is not promoted until both are resolved."""
    add_from_message(conn, "milk", "sms", "cara")
    add_from_message(conn, "bread", "discord", "vern")

    ambiguous = list_ambiguous(conn)
    assert len(ambiguous) == 2

    milk_id = next(i["id"] for i in ambiguous if i["canonical"] == "milk")
    bread_id = next(i["id"] for i in ambiguous if i["canonical"] == "bread")

    sid = create_cart_session(conn)
    add_item_to_session(conn, sid, milk_id)
    add_item_to_session(conn, sid, bread_id)
    update_session_status(conn, sid, "needs_clarification")

    # Resolve only milk
    result = resolve_item(conn, milk_id, "oat milk", "operator")
    assert sid not in result["promoted_sessions"]
    session = get_session(conn, sid)
    assert session["status"] == "needs_clarification"

    # Resolve bread too
    result2 = resolve_item(conn, bread_id, "sourdough bread", "operator")
    assert sid in result2["promoted_sessions"]
    session = get_session(conn, sid)
    assert session["status"] == "awaiting_approval"


def test_resolve_does_not_promote_approved_or_cancelled_sessions(conn):
    add_from_message(conn, "milk", "sms", "cara")
    ambiguous = list_ambiguous(conn)
    milk_id = ambiguous[0]["id"]

    # approved session should not be touched
    sid_approved = create_cart_session(conn)
    add_item_to_session(conn, sid_approved, milk_id)
    update_session_status(conn, sid_approved, "approved")

    # cancelled session should not be touched
    sid_cancelled = create_cart_session(conn)
    add_item_to_session(conn, sid_cancelled, milk_id)
    update_session_status(conn, sid_cancelled, "cancelled")

    result = resolve_item(conn, milk_id, "oat milk", "operator")
    # Neither session should appear in promoted list
    assert sid_approved not in result["promoted_sessions"]
    assert sid_cancelled not in result["promoted_sessions"]

    # Statuses should not change
    assert get_session(conn, sid_approved)["status"] == "approved"
    assert get_session(conn, sid_cancelled)["status"] == "cancelled"


# ---------------------------------------------------------------------------
# get_resolution_history
# ---------------------------------------------------------------------------

def test_resolution_history_empty_for_unresolved(conn_with_ambiguous, ambiguous_item_id):
    history = get_resolution_history(conn_with_ambiguous, ambiguous_item_id)
    assert history == []


def test_resolution_history_empty_for_unknown_item(conn):
    assert get_resolution_history(conn, 9999) == []


def test_resolution_history_returns_all_fields(conn_with_ambiguous, ambiguous_item_id):
    resolve_item(conn_with_ambiguous, ambiguous_item_id, "oat milk", "operator")
    history = get_resolution_history(conn_with_ambiguous, ambiguous_item_id)
    entry = history[0]
    required = {
        "id", "item_id", "original_name", "original_canonical",
        "resolved_name", "resolved_canonical", "resolved_by", "timestamp",
    }
    assert required.issubset(entry.keys())


def test_resolution_history_resolved_by_preserved(conn_with_ambiguous, ambiguous_item_id):
    resolve_item(conn_with_ambiguous, ambiguous_item_id, "oat milk", "vern")
    history = get_resolution_history(conn_with_ambiguous, ambiguous_item_id)
    assert history[0]["resolved_by"] == "vern"


# ---------------------------------------------------------------------------
# all_resolved
# ---------------------------------------------------------------------------

def test_all_resolved_true_when_empty(conn):
    assert all_resolved(conn) is True


def test_all_resolved_false_when_ambiguous_present(conn_with_ambiguous):
    assert all_resolved(conn_with_ambiguous) is False


def test_all_resolved_true_after_resolution(conn_with_ambiguous, ambiguous_item_id):
    resolve_item(conn_with_ambiguous, ambiguous_item_id, "oat milk", "operator")
    assert all_resolved(conn_with_ambiguous) is True
