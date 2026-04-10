"""Shopping handoff helpers for the mobile web UI."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from urllib.parse import quote_plus

from .db import get_session, get_session_items, mark_session_ordered as db_mark_session_ordered
from .preferences import get_preference_for_item, format_preference_note

INSTACART_SEARCH_BASE = "https://www.instacart.com/store/search_v3/term?term="


class ShoppingHandoffError(Exception):
    """Raised when a shopping handoff cannot proceed."""


def _compact_terms(*parts: str | None) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for part in parts:
        value = (part or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
    return cleaned


def build_search_term(item: dict, preference: dict | None = None) -> str:
    """Build a robust Instacart search term for a single item."""
    primary = preference.get("preferred_form") if preference else None
    preference_note = preference.get("note") if preference else None
    terms = _compact_terms(
        primary,
        item.get("name"),
        item.get("notes"),
        preference_note,
    )
    return " ".join(terms)


def build_instacart_search_url(search_term: str) -> str:
    return f"{INSTACART_SEARCH_BASE}{quote_plus(search_term)}"


def build_shopping_handoff(conn: sqlite3.Connection, session_id: int) -> dict:
    session = get_session(conn, session_id)
    if session is None:
        raise ShoppingHandoffError(f"Draft {session_id} does not exist.")

    ordered = bool(session["ordered_at"])
    if session["status"] != "approved" and not ordered:
        raise ShoppingHandoffError(
            "Approve this draft before opening the shopping handoff."
        )

    handoff_items: list[dict] = []
    for row in get_session_items(conn, session_id):
        item = dict(row)
        preference = get_preference_for_item(conn, item["canonical"])
        search_term = build_search_term(item, preference)
        handoff_items.append({
            **item,
            "search_term": search_term,
            "instacart_url": build_instacart_search_url(search_term),
            "preference_note": format_preference_note(preference) if preference else None,
        })

    return {
        "session": dict(session),
        "items": handoff_items,
        "ordered": ordered,
        "manual_checkout_note": (
            "Open each Instacart search, choose the right product in Instacart, "
            "and finish checkout there. This app never submits the Instacart order for you."
        ),
    }


def complete_shopping_handoff(conn: sqlite3.Connection,
                              session_id: int,
                              ordered_by: str = "vern",
                              timestamp: datetime | None = None) -> dict:
    session = get_session(conn, session_id)
    if session is None:
        raise ShoppingHandoffError(f"Draft {session_id} does not exist.")
    if session["ordered_at"]:
        return {
            "session_id": session_id,
            "ordered_at": session["ordered_at"],
            "updated_items": 0,
            "already_ordered": True,
            "ordered_by": ordered_by,
        }
    if session["status"] != "approved":
        raise ShoppingHandoffError(
            "Only approved drafts can be marked ordered after manual Instacart checkout."
        )

    ts = timestamp or datetime.now(UTC)
    updated_items = db_mark_session_ordered(conn, session_id, ts)
    return {
        "session_id": session_id,
        "ordered_at": ts.isoformat(),
        "updated_items": updated_items,
        "already_ordered": False,
        "ordered_by": ordered_by,
    }
