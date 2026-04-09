"""
Hard approval gate for order sessions.

Design rules (from PRD):
- No automatic checkout submission
- No stored blanket permission
- Approval is required per order session
- Only Vern can approve
- Vague acknowledgments do not count

Enforcement:
- APPROVED_PHRASES is the whitelist. Any phrase not on it is rejected.
- REJECTED_PHRASES catches common false positives and raises with a clear message.
- Approver must be 'vern' (case-insensitive). Any other user is rejected.
- A session can only be approved once (once approved, further calls no-op or error).
"""

import sqlite3
from datetime import datetime
from typing import Optional

from .db import (
    get_session,
    update_session_status,
    record_approval,
)


APPROVED_PHRASES: frozenset[str] = frozenset({
    "approve order",
    "place this order",
    "go ahead and submit",
    "submit the order",
    "confirm order",
    "yes place the order",
    "yes, place the order",
})

# Phrases that sound like approval but are NOT
REJECTED_PHRASES: frozenset[str] = frozenset({
    "looks good",
    "nice",
    "ok",
    "okay",
    "sounds good",
    "great",
    "good",
    "perfect",
    "sure",
    "yes",
    "yep",
    "yeah",
    "fine",
    "alright",
    "thumbs up",
    "approved",   # too vague without the word "order"
})

APPROVER_NAME = "vern"


class ApprovalError(Exception):
    """Raised when approval is denied or invalid."""
    pass


def _normalize_phrase(phrase: str) -> str:
    return phrase.lower().strip().rstrip(".")


def is_approval_phrase(phrase: str) -> bool:
    """Return True if the phrase is an explicit, approved form."""
    normalized = _normalize_phrase(phrase)
    return normalized in APPROVED_PHRASES


def is_rejected_phrase(phrase: str) -> bool:
    normalized = _normalize_phrase(phrase)
    return normalized in REJECTED_PHRASES


def submit_approval(conn: sqlite3.Connection, session_id: int,
                     approver: str, phrase: str,
                     timestamp: Optional[datetime] = None) -> dict:
    """
    Attempt to approve a cart session.

    Raises ApprovalError with a clear reason if approval is denied.
    Returns approval record dict on success.

    Checks (in order):
    1. Approver must be Vern.
    2. Session must exist.
    3. Session must not already be approved or cancelled.
    4. Phrase must be an explicit approval phrase.
    """
    # 1. Approver identity
    if approver.lower().strip() != APPROVER_NAME:
        raise ApprovalError(
            f"Only Vern can approve orders. '{approver}' is not authorized."
        )

    # 2. Session existence
    session = get_session(conn, session_id)
    if session is None:
        raise ApprovalError(f"Cart session {session_id} does not exist.")

    # 3. Session state
    if session["status"] == "approved":
        raise ApprovalError(
            f"Session {session_id} is already approved. "
            "Each session requires a fresh approval."
        )
    if session["status"] == "cancelled":
        raise ApprovalError(
            f"Session {session_id} is cancelled and cannot be approved."
        )

    # 4. Phrase check -- check rejected list first for clear error messages
    normalized = _normalize_phrase(phrase)
    if normalized in REJECTED_PHRASES:
        raise ApprovalError(
            f"'{phrase}' is not an explicit approval. "
            "Use a phrase like: 'approve order', 'place this order', "
            "or 'go ahead and submit'."
        )

    if not is_approval_phrase(phrase):
        raise ApprovalError(
            f"'{phrase}' is not a recognized approval phrase. "
            "Use one of: " + ", ".join(sorted(APPROVED_PHRASES))
        )

    # All checks passed -- record and update
    ts = timestamp or datetime.utcnow()
    approval_id = record_approval(conn, session_id, approver, phrase, ts)
    update_session_status(conn, session_id, "approved")

    return {
        "approved": True,
        "session_id": session_id,
        "approved_by": approver,
        "phrase": phrase,
        "timestamp": ts.isoformat(),
        "approval_id": approval_id,
    }


def can_submit(conn: sqlite3.Connection, session_id: int) -> bool:
    """
    Return True only if session exists and is in 'approved' status.
    This is the enforcement point for any downstream submission attempt.
    """
    session = get_session(conn, session_id)
    if session is None:
        return False
    return session["status"] == "approved"
