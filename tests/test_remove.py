"""
Tests for the safe item removal workflow.

Covers:
- db.remove_item: sets status to 'removed', item disappears from pending queries
- db.insert_removal_log / get_removal_log: audit trail is written and retrievable
- CLI cmd_remove: happy path, already-removed, nonexistent item
- CLI cmd_inspect: shows item details, source events, clarification and removal history
- API POST /api/item/<id>/remove: happy path, not_found, already_removed
- Parser: inspect and remove commands are parseable
"""

import argparse
import json
import sqlite3
import pytest
from pathlib import Path

from grocery_assistant.grocery_list import add_from_message
from grocery_assistant.db import (
    get_item_by_id,
    get_pending_items,
    remove_item,
    insert_removal_log,
    get_removal_log,
    count_ambiguous_in_session,
    get_session,
)
from grocery_assistant.draft import create_draft
from grocery_assistant.clarification import promote_cleared_sessions
from grocery_assistant.web import create_app
import grocery_assistant.cli as cli_module


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
def patched_conn(conn, monkeypatch):
    monkeypatch.setattr(cli_module, "_get_conn", lambda: conn)
    return conn


@pytest.fixture
def client(conn):
    app = create_app(conn=conn)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


# ---------------------------------------------------------------------------
# db-level remove
# ---------------------------------------------------------------------------

class TestDbRemove:
    def test_remove_sets_status(self, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        pending = get_pending_items(conn)
        item_id = pending[0]["id"]

        remove_item(conn, item_id)

        item = get_item_by_id(conn, item_id)
        assert item["status"] == "removed"

    def test_removed_item_not_in_pending(self, conn):
        add_from_message(conn, "oat milk", "sms", "cara")
        pending = get_pending_items(conn)
        item_id = pending[0]["id"]

        remove_item(conn, item_id)

        remaining = get_pending_items(conn)
        assert all(r["id"] != item_id for r in remaining)

    def test_removal_log_written(self, conn):
        add_from_message(conn, "eggs", "discord", "vern")
        item_id = get_pending_items(conn)[0]["id"]

        insert_removal_log(conn, item_id, "eggs", removed_by="operator", reason="duplicate")
        remove_item(conn, item_id)

        log = get_removal_log(conn, item_id)
        assert len(log) == 1
        assert log[0]["item_name"] == "eggs"
        assert log[0]["removed_by"] == "operator"
        assert log[0]["reason"] == "duplicate"

    def test_removal_log_reason_optional(self, conn):
        add_from_message(conn, "dish soap", "sms", "cara")
        item_id = get_pending_items(conn)[0]["id"]
        insert_removal_log(conn, item_id, "dish soap", removed_by="operator")
        log = get_removal_log(conn, item_id)
        assert log[0]["reason"] is None

    def test_item_row_preserved_after_remove(self, conn):
        add_from_message(conn, "chicken", "discord", "vern")
        item_id = get_pending_items(conn)[0]["id"]
        remove_item(conn, item_id)

        # Row is still retrievable -- not hard deleted
        item = get_item_by_id(conn, item_id)
        assert item is not None
        assert item["status"] == "removed"


# ---------------------------------------------------------------------------
# CLI cmd_remove
# ---------------------------------------------------------------------------

class TestCmdRemove:
    @pytest.fixture
    def item_id(self, patched_conn):
        add_from_message(patched_conn, "bananas", "discord", "vern")
        return get_pending_items(patched_conn)[0]["id"]

    def test_remove_happy_path(self, patched_conn, item_id, capsys):
        cli_module.cmd_remove(ns(item_id=item_id, reason=""))
        out = capsys.readouterr().out
        assert "Removed item" in out
        assert "bananas" in out

    def test_remove_writes_audit_message(self, patched_conn, item_id, capsys):
        cli_module.cmd_remove(ns(item_id=item_id, reason=""))
        out = capsys.readouterr().out
        assert "Audit entry recorded" in out

    def test_remove_with_reason(self, patched_conn, item_id, capsys):
        cli_module.cmd_remove(ns(item_id=item_id, reason="duplicate"))
        out = capsys.readouterr().out
        assert "duplicate" in out

    def test_remove_item_no_longer_in_list(self, patched_conn, item_id, capsys):
        cli_module.cmd_remove(ns(item_id=item_id, reason=""))
        capsys.readouterr()
        cli_module.cmd_list(ns())
        out = capsys.readouterr().out
        assert "bananas" not in out

    def test_remove_nonexistent_item_exits(self, patched_conn, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_module.cmd_remove(ns(item_id=9999, reason=""))
        assert exc_info.value.code == 1

    def test_remove_already_removed_exits(self, patched_conn, item_id, capsys):
        cli_module.cmd_remove(ns(item_id=item_id, reason=""))
        capsys.readouterr()
        with pytest.raises(SystemExit) as exc_info:
            cli_module.cmd_remove(ns(item_id=item_id, reason=""))
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# CLI cmd_inspect
# ---------------------------------------------------------------------------

class TestCmdInspect:
    @pytest.fixture
    def item_id(self, patched_conn):
        add_from_message(patched_conn, "oat milk", "sms", "cara")
        return get_pending_items(patched_conn)[0]["id"]

    def test_inspect_shows_item_name(self, patched_conn, item_id, capsys):
        cli_module.cmd_inspect(ns(item_id=item_id))
        out = capsys.readouterr().out
        assert "oat milk" in out

    def test_inspect_shows_canonical(self, patched_conn, item_id, capsys):
        cli_module.cmd_inspect(ns(item_id=item_id))
        out = capsys.readouterr().out
        assert "milk oat" in out

    def test_inspect_shows_category(self, patched_conn, item_id, capsys):
        cli_module.cmd_inspect(ns(item_id=item_id))
        out = capsys.readouterr().out
        assert "dairy" in out

    def test_inspect_shows_source_events(self, patched_conn, item_id, capsys):
        cli_module.cmd_inspect(ns(item_id=item_id))
        out = capsys.readouterr().out
        assert "sms" in out
        assert "cara" in out

    def test_inspect_shows_raw_text(self, patched_conn, item_id, capsys):
        cli_module.cmd_inspect(ns(item_id=item_id))
        out = capsys.readouterr().out
        assert "oat milk" in out

    def test_inspect_nonexistent_item_exits(self, patched_conn, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_module.cmd_inspect(ns(item_id=9999))
        assert exc_info.value.code == 1

    def test_inspect_shows_clarification_history(self, patched_conn, capsys):
        add_from_message(patched_conn, "milk", "sms", "cara")
        items = get_pending_items(patched_conn)
        milk_id = next(i["id"] for i in items if i["canonical"] == "milk")

        cli_module.cmd_resolve(ns(item_id=milk_id, new_name="oat milk"))
        capsys.readouterr()

        cli_module.cmd_inspect(ns(item_id=milk_id))
        out = capsys.readouterr().out
        assert "Clarification history" in out
        assert "oat milk" in out

    def test_inspect_shows_removal_log(self, patched_conn, item_id, capsys):
        cli_module.cmd_remove(ns(item_id=item_id, reason="test reason"))
        capsys.readouterr()

        cli_module.cmd_inspect(ns(item_id=item_id))
        out = capsys.readouterr().out
        assert "Removal log" in out
        assert "test reason" in out


# ---------------------------------------------------------------------------
# API /api/item/<id>/remove
# ---------------------------------------------------------------------------

class TestApiRemove:
    @pytest.fixture
    def item_id(self, client, conn):
        add_from_message(conn, "dish soap", "sms", "cara")
        return get_pending_items(conn)[0]["id"]

    def test_remove_happy_path_returns_200(self, client, item_id):
        resp = client.post(f"/api/item/{item_id}/remove",
                           data=json.dumps({}),
                           content_type="application/json")
        assert resp.status_code == 200

    def test_remove_response_has_expected_keys(self, client, item_id):
        resp = client.post(f"/api/item/{item_id}/remove",
                           data=json.dumps({}),
                           content_type="application/json")
        data = resp.get_json()
        assert data["item_id"] == item_id
        assert data["status"] == "removed"

    def test_remove_item_not_in_list_after(self, client, conn, item_id):
        client.post(f"/api/item/{item_id}/remove",
                    data=json.dumps({}),
                    content_type="application/json")
        list_resp = client.get("/api/list")
        items = list_resp.get_json()
        assert all(i["id"] != item_id for i in items)

    def test_remove_nonexistent_returns_404(self, client):
        resp = client.post("/api/item/9999/remove",
                           data=json.dumps({}),
                           content_type="application/json")
        assert resp.status_code == 404

    def test_remove_already_removed_returns_400(self, client, item_id):
        client.post(f"/api/item/{item_id}/remove",
                    data=json.dumps({}),
                    content_type="application/json")
        resp = client.post(f"/api/item/{item_id}/remove",
                           data=json.dumps({}),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_remove_with_reason(self, client, item_id):
        resp = client.post(f"/api/item/{item_id}/remove",
                           data=json.dumps({"reason": "misspelled", "removed_by": "vern"}),
                           content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["reason"] == "misspelled"
        assert data["removed_by"] == "vern"

    def test_remove_without_json_body_uses_defaults(self, client, item_id):
        resp = client.post(f"/api/item/{item_id}/remove")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["removed_by"] == "operator"


# ---------------------------------------------------------------------------
# Parser: new commands
# ---------------------------------------------------------------------------

class TestParserNewCommands:
    def test_inspect_command_parseable(self):
        parser = cli_module.build_parser()
        args = parser.parse_args(["inspect", "5"])
        assert args.command == "inspect"
        assert args.item_id == 5

    def test_remove_command_parseable(self):
        parser = cli_module.build_parser()
        args = parser.parse_args(["remove", "3"])
        assert args.command == "remove"
        assert args.item_id == 3

    def test_remove_accepts_reason_flag(self):
        parser = cli_module.build_parser()
        args = parser.parse_args(["remove", "3", "--reason", "duplicate"])
        assert args.reason == "duplicate"

    def test_remove_reason_defaults_empty(self):
        parser = cli_module.build_parser()
        args = parser.parse_args(["remove", "3"])
        assert args.reason == ""


# ---------------------------------------------------------------------------
# Session unblocking: removing an ambiguous item should unblock the session
# ---------------------------------------------------------------------------

class TestRemoveUnblocksSession:
    """
    Regression tests for the bug where removed ambiguous items kept a
    needs_clarification session permanently stuck.
    """

    def _add_ambiguous(self, conn, text="milk", sender="vern"):
        """Add a message that produces at least one ambiguous item."""
        return add_from_message(conn, text, "discord", sender)

    def test_removed_ambiguous_item_not_counted(self, conn):
        """count_ambiguous_in_session must exclude removed items."""
        self._add_ambiguous(conn)
        draft = create_draft(conn)
        session_id = draft["session_id"]
        assert draft["status"] == "needs_clarification"

        # Find the ambiguous item and remove it
        ambiguous_ids = [i["id"] for i in draft["ambiguous"]]
        assert ambiguous_ids, "test requires at least one ambiguous item"
        remove_item(conn, ambiguous_ids[0])

        assert count_ambiguous_in_session(conn, session_id) == 0

    def test_promote_cleared_sessions_after_remove(self, conn):
        """promote_cleared_sessions promotes the session once all ambiguous items removed."""
        self._add_ambiguous(conn)
        draft = create_draft(conn)
        session_id = draft["session_id"]
        assert draft["status"] == "needs_clarification"

        for item in draft["ambiguous"]:
            remove_item(conn, item["id"])

        promoted = promote_cleared_sessions(conn)
        assert session_id in promoted
        assert get_session(conn, session_id)["status"] == "awaiting_approval"

    def test_cli_remove_ambiguous_promotes_session(self, patched_conn, capsys):
        """cmd_remove should promote needs_clarification sessions automatically."""
        self._add_ambiguous(patched_conn)
        draft = create_draft(patched_conn)
        session_id = draft["session_id"]
        assert draft["status"] == "needs_clarification"

        item_id = draft["ambiguous"][0]["id"]
        cli_module.cmd_remove(argparse.Namespace(item_id=item_id, reason=""))
        out = capsys.readouterr().out

        assert "promoted" in out.lower() or str(session_id) in out
        assert get_session(patched_conn, session_id)["status"] == "awaiting_approval"

    def test_api_remove_ambiguous_promotes_session(self, client, conn):
        """POST /api/item/<id>/remove should promote the session and report it."""
        self._add_ambiguous(conn)
        draft = create_draft(conn)
        session_id = draft["session_id"]
        assert draft["status"] == "needs_clarification"

        item_id = draft["ambiguous"][0]["id"]
        resp = client.post(
            f"/api/item/{item_id}/remove",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert session_id in data["promoted_sessions"]
        assert get_session(conn, session_id)["status"] == "awaiting_approval"

    def test_partial_remove_does_not_promote_session(self, conn):
        """Removing one of two ambiguous items must NOT promote the session early."""
        # Add two separate ambiguous messages
        add_from_message(conn, "milk", "discord", "vern")
        add_from_message(conn, "juice", "discord", "vern")
        draft = create_draft(conn)
        session_id = draft["session_id"]

        ambiguous = draft["ambiguous"]
        if len(ambiguous) < 2:
            pytest.skip("Need at least 2 ambiguous items for this test")

        # Remove only the first one
        remove_item(conn, ambiguous[0]["id"])
        promoted = promote_cleared_sessions(conn)
        assert session_id not in promoted
        assert get_session(conn, session_id)["status"] == "needs_clarification"

    def test_non_ambiguous_remove_does_not_touch_session(self, conn):
        """Removing a non-ambiguous item from a stuck session should leave it stuck."""
        add_from_message(conn, "milk", "discord", "vern")    # ambiguous
        add_from_message(conn, "bananas", "discord", "vern")  # unambiguous
        draft = create_draft(conn)
        session_id = draft["session_id"]
        assert draft["status"] == "needs_clarification"

        # Find a non-ambiguous item in the session
        non_ambiguous = [i for i in draft["items"]]
        if not non_ambiguous:
            pytest.skip("No non-ambiguous items in session")

        remove_item(conn, non_ambiguous[0]["id"])
        promoted = promote_cleared_sessions(conn)
        assert session_id not in promoted
        assert get_session(conn, session_id)["status"] == "needs_clarification"
