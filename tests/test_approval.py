"""
Tests for approval gating.

Covers:
- Only Vern can approve
- Only explicit phrases count
- Vague phrases are rejected with a clear error
- Per-session enforcement (no double approval)
- Cancelled sessions cannot be approved
- can_submit returns True only after explicit approval
"""

import sqlite3
import pytest
from pathlib import Path

from grocery_assistant.db import init_db, create_cart_session, get_session
from grocery_assistant.approval import (
    ApprovalError,
    submit_approval,
    can_submit,
    is_approval_phrase,
    is_rejected_phrase,
    APPROVED_PHRASES,
    REJECTED_PHRASES,
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


@pytest.fixture
def session_id(conn):
    return create_cart_session(conn)


# ---------------------------------------------------------------------------
# Phrase classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", sorted(APPROVED_PHRASES))
def test_approved_phrases_recognized(phrase):
    assert is_approval_phrase(phrase) is True


@pytest.mark.parametrize("phrase", sorted(REJECTED_PHRASES))
def test_rejected_phrases_not_approved(phrase):
    assert is_approval_phrase(phrase) is False


def test_approved_phrase_case_insensitive():
    assert is_approval_phrase("APPROVE ORDER") is True
    assert is_approval_phrase("Approve Order") is True


def test_rejected_phrase_detected():
    assert is_rejected_phrase("looks good") is True
    assert is_rejected_phrase("nice") is True
    assert is_rejected_phrase("thumbs up") is True


def test_unknown_phrase_not_approved():
    assert is_approval_phrase("sure thing") is False
    assert is_approval_phrase("do it") is False


# ---------------------------------------------------------------------------
# Identity enforcement
# ---------------------------------------------------------------------------

def test_only_vern_can_approve(conn, session_id):
    with pytest.raises(ApprovalError, match="Only Vern"):
        submit_approval(conn, session_id, approver="cara", phrase="approve order")


def test_vern_case_insensitive(conn, session_id):
    result = submit_approval(conn, session_id, approver="Vern", phrase="approve order")
    assert result["approved"] is True


def test_vern_lower(conn, session_id):
    result = submit_approval(conn, session_id, approver="vern", phrase="approve order")
    assert result["approved"] is True


# ---------------------------------------------------------------------------
# Phrase enforcement
# ---------------------------------------------------------------------------

def test_vague_phrase_rejected(conn, session_id):
    with pytest.raises(ApprovalError, match="not an explicit approval"):
        submit_approval(conn, session_id, approver="vern", phrase="looks good")


def test_thumbs_up_rejected(conn, session_id):
    with pytest.raises(ApprovalError):
        submit_approval(conn, session_id, approver="vern", phrase="thumbs up")


def test_yes_alone_rejected(conn, session_id):
    with pytest.raises(ApprovalError):
        submit_approval(conn, session_id, approver="vern", phrase="yes")


def test_unknown_phrase_raises(conn, session_id):
    with pytest.raises(ApprovalError, match="not a recognized approval phrase"):
        submit_approval(conn, session_id, approver="vern", phrase="sure thing boss")


@pytest.mark.parametrize("phrase", [
    "approve order",
    "place this order",
    "go ahead and submit",
    "submit the order",
    "confirm order",
])
def test_valid_phrases_accepted(conn, phrase):
    sid = create_cart_session(conn)
    result = submit_approval(conn, sid, approver="vern", phrase=phrase)
    assert result["approved"] is True


# ---------------------------------------------------------------------------
# Per-session enforcement
# ---------------------------------------------------------------------------

def test_session_not_double_approvable(conn, session_id):
    submit_approval(conn, session_id, approver="vern", phrase="approve order")
    with pytest.raises(ApprovalError, match="already approved"):
        submit_approval(conn, session_id, approver="vern", phrase="approve order")


def test_cancelled_session_not_approvable(conn, conn_raw=None):
    from grocery_assistant.db import update_session_status
    sid = create_cart_session(conn)
    update_session_status(conn, sid, "cancelled")
    with pytest.raises(ApprovalError, match="cancelled"):
        submit_approval(conn, sid, approver="vern", phrase="approve order")


def test_nonexistent_session_raises(conn):
    with pytest.raises(ApprovalError, match="does not exist"):
        submit_approval(conn, session_id=9999, approver="vern", phrase="approve order")


# ---------------------------------------------------------------------------
# can_submit gate
# ---------------------------------------------------------------------------

def test_can_submit_false_before_approval(conn, session_id):
    assert can_submit(conn, session_id) is False


def test_can_submit_true_after_approval(conn, session_id):
    submit_approval(conn, session_id, approver="vern", phrase="approve order")
    assert can_submit(conn, session_id) is True


def test_can_submit_false_for_nonexistent(conn):
    assert can_submit(conn, 9999) is False


def test_can_submit_false_for_cancelled(conn):
    from grocery_assistant.db import update_session_status
    sid = create_cart_session(conn)
    update_session_status(conn, sid, "cancelled")
    assert can_submit(conn, sid) is False


# ---------------------------------------------------------------------------
# Approval record
# ---------------------------------------------------------------------------

def test_approval_result_contains_expected_fields(conn, session_id):
    result = submit_approval(conn, session_id, approver="vern", phrase="approve order")
    assert result["session_id"] == session_id
    assert result["approved_by"] == "vern"
    assert result["phrase"] == "approve order"
    assert "timestamp" in result
    assert result["approval_id"] is not None


def test_session_status_updated_to_approved(conn, session_id):
    submit_approval(conn, session_id, approver="vern", phrase="approve order")
    session = get_session(conn, session_id)
    assert session["status"] == "approved"
