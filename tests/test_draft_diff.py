"""
Tests for the draft diff feature (new_since_last_draft).

Covers:
- new_since_last_draft is empty when there's no previous draft
- new_since_last_draft contains items added after the previous draft's timestamp
- format_draft() shows "New since last draft" section when items exist
"""

import sqlite3
import pytest
from pathlib import Path
from datetime import UTC, datetime, timedelta

from grocery_assistant.draft import create_draft, format_draft
from grocery_assistant.grocery_list import add_from_message
from grocery_assistant.db import get_last_session_time, insert_grocery_item


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    schema = (Path(__file__).parent.parent / "schema.sql").read_text()
    c.executescript(schema)
    return c


class TestNewSinceLastDraft:
    def test_first_draft_has_empty_new_since(self, conn):
        add_from_message(conn, "bananas", "sms", "cara")
        draft = create_draft(conn)
        assert draft["new_since_last_draft"] == []

    def test_second_draft_contains_newly_added_items(self, conn):
        # Add item and create first draft
        t0 = datetime.now(UTC) - timedelta(seconds=10)
        insert_grocery_item(conn, "bananas", "bananas", created_at=t0)
        first_draft = create_draft(conn)
        first_session_id = first_draft["session_id"]

        # Add a new item after the first draft
        t1 = datetime.now(UTC)
        insert_grocery_item(conn, "eggs", "eggs", created_at=t1)

        second_draft = create_draft(conn)
        new_items = second_draft["new_since_last_draft"]
        new_names = [i["search_term"] for i in new_items]
        assert "eggs" in new_names

    def test_old_items_not_in_new_since(self, conn):
        # Add item before first draft
        t0 = datetime.now(UTC) - timedelta(seconds=20)
        insert_grocery_item(conn, "bananas", "bananas", created_at=t0)
        create_draft(conn)

        # Add newer item
        t1 = datetime.now(UTC)
        insert_grocery_item(conn, "eggs", "eggs", created_at=t1)

        second_draft = create_draft(conn)
        new_items = second_draft["new_since_last_draft"]
        new_names = [i["search_term"] for i in new_items]
        assert "bananas" not in new_names
        assert "eggs" in new_names

    def test_format_draft_shows_new_since_section(self, conn):
        # First draft
        t0 = datetime.now(UTC) - timedelta(seconds=10)
        insert_grocery_item(conn, "bananas", "bananas", created_at=t0)
        create_draft(conn)

        # New item after first draft
        t1 = datetime.now(UTC)
        insert_grocery_item(conn, "eggs", "eggs", created_at=t1)

        second_draft = create_draft(conn)
        output = format_draft(second_draft)
        assert "New since last draft" in output
        assert "eggs" in output

    def test_format_draft_no_new_since_section_on_first_draft(self, conn):
        add_from_message(conn, "bananas", "sms", "cara")
        draft = create_draft(conn)
        output = format_draft(draft)
        assert "New since last draft" not in output


# ---------------------------------------------------------------------------
# get_last_session_time()
# ---------------------------------------------------------------------------

class TestGetLastSessionTime:
    def test_returns_none_when_no_sessions(self, conn):
        result = get_last_session_time(conn)
        assert result is None

    def test_returns_none_when_no_prior_sessions(self, conn):
        # Create one session, ask for last before it
        add_from_message(conn, "bananas", "sms", "cara")
        draft = create_draft(conn)
        sid = draft["session_id"]
        result = get_last_session_time(conn, before_session_id=sid)
        assert result is None

    def test_returns_previous_session_time(self, conn):
        add_from_message(conn, "bananas", "sms", "cara")
        first_draft = create_draft(conn)
        first_sid = first_draft["session_id"]

        add_from_message(conn, "eggs", "sms", "cara")
        second_draft = create_draft(conn)
        second_sid = second_draft["session_id"]

        t = get_last_session_time(conn, before_session_id=second_sid)
        assert t is not None
