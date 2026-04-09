"""
Tests for the operator CLI.

Tests call CLI command functions directly with a patched _get_conn to avoid
touching the filesystem. Output is captured via capsys.

Covers:
- list: empty list, grouped output with categories
- flagged: no flagged items, flagged items with IDs and names
- by-sender: correct items, empty result
- by-channel: correct items, empty result
- draft: creates session, prints session ID, optional --json output
- resolve: happy path output, error on bad item
- history: no history, history after resolution

No subprocess required. No real DB files touched.
"""

import argparse
import sqlite3
import pytest
from pathlib import Path

from grocery_assistant.grocery_list import add_from_message
from grocery_assistant.clarification import list_ambiguous
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
    """Patch cli._get_conn to return the test DB connection."""
    monkeypatch.setattr(cli_module, "_get_conn", lambda: conn)
    return conn


def ns(**kwargs) -> argparse.Namespace:
    """Build a minimal argparse.Namespace with given kwargs."""
    return argparse.Namespace(**kwargs)


# ---------------------------------------------------------------------------
# cmd_list
# ---------------------------------------------------------------------------

class TestCmdList:
    def test_empty_list_output(self, patched_conn, capsys):
        cli_module.cmd_list(ns())
        out = capsys.readouterr().out
        assert "empty" in out.lower()

    def test_list_shows_added_item(self, patched_conn, capsys):
        add_from_message(patched_conn, "bananas", "discord", "vern")
        cli_module.cmd_list(ns())
        out = capsys.readouterr().out
        assert "bananas" in out

    def test_list_groups_by_category(self, patched_conn, capsys):
        add_from_message(patched_conn, "bananas, oat milk, dish soap", "discord", "vern")
        cli_module.cmd_list(ns())
        out = capsys.readouterr().out
        # Category headers should appear
        assert "PRODUCE" in out or "produce" in out.lower()

    def test_list_marks_ambiguous_items(self, patched_conn, capsys):
        add_from_message(patched_conn, "milk", "sms", "cara")
        cli_module.cmd_list(ns())
        out = capsys.readouterr().out
        assert "[?]" in out


# ---------------------------------------------------------------------------
# cmd_flagged
# ---------------------------------------------------------------------------

class TestCmdFlagged:
    def test_flagged_empty_message(self, patched_conn, capsys):
        cli_module.cmd_flagged(ns())
        out = capsys.readouterr().out
        assert "No flagged" in out

    def test_flagged_shows_ambiguous_item(self, patched_conn, capsys):
        add_from_message(patched_conn, "milk", "sms", "cara")
        cli_module.cmd_flagged(ns())
        out = capsys.readouterr().out
        assert "milk" in out

    def test_flagged_shows_item_id(self, patched_conn, capsys):
        add_from_message(patched_conn, "bread", "sms", "cara")
        cli_module.cmd_flagged(ns())
        out = capsys.readouterr().out
        # Item ID is shown in brackets
        assert "[" in out

    def test_flagged_shows_resolve_hint(self, patched_conn, capsys):
        add_from_message(patched_conn, "chips", "discord", "vern")
        cli_module.cmd_flagged(ns())
        out = capsys.readouterr().out
        assert "resolve" in out.lower()

    def test_flagged_count_in_header(self, patched_conn, capsys):
        add_from_message(patched_conn, "milk", "sms", "cara")
        add_from_message(patched_conn, "bread", "discord", "vern")
        cli_module.cmd_flagged(ns())
        out = capsys.readouterr().out
        assert "2" in out


# ---------------------------------------------------------------------------
# cmd_by_sender
# ---------------------------------------------------------------------------

class TestCmdBySender:
    def test_by_sender_shows_items(self, patched_conn, capsys):
        add_from_message(patched_conn, "bananas", "discord", "vern")
        add_from_message(patched_conn, "oat milk", "sms", "cara")
        cli_module.cmd_by_sender(ns(sender="cara"))
        out = capsys.readouterr().out
        assert "oat milk" in out
        assert "bananas" not in out

    def test_by_sender_empty_result(self, patched_conn, capsys):
        cli_module.cmd_by_sender(ns(sender="nobody"))
        out = capsys.readouterr().out
        assert "No pending" in out

    def test_by_sender_marks_ambiguous(self, patched_conn, capsys):
        add_from_message(patched_conn, "milk", "sms", "cara")
        cli_module.cmd_by_sender(ns(sender="cara"))
        out = capsys.readouterr().out
        assert "[?]" in out


# ---------------------------------------------------------------------------
# cmd_by_channel
# ---------------------------------------------------------------------------

class TestCmdByChannel:
    def test_by_channel_sms(self, patched_conn, capsys):
        add_from_message(patched_conn, "oat milk", "sms", "cara")
        add_from_message(patched_conn, "eggs", "discord", "vern")
        cli_module.cmd_by_channel(ns(channel="sms"))
        out = capsys.readouterr().out
        assert "oat milk" in out
        assert "eggs" not in out

    def test_by_channel_discord(self, patched_conn, capsys):
        add_from_message(patched_conn, "oat milk", "sms", "cara")
        add_from_message(patched_conn, "eggs", "discord", "vern")
        cli_module.cmd_by_channel(ns(channel="discord"))
        out = capsys.readouterr().out
        assert "eggs" in out
        assert "oat milk" not in out

    def test_by_channel_empty(self, patched_conn, capsys):
        cli_module.cmd_by_channel(ns(channel="fax"))
        out = capsys.readouterr().out
        assert "No pending" in out


# ---------------------------------------------------------------------------
# cmd_draft
# ---------------------------------------------------------------------------

class TestCmdDraft:
    def test_draft_prints_session_id(self, patched_conn, capsys):
        add_from_message(patched_conn, "bananas", "discord", "vern")
        cli_module.cmd_draft(ns(json=False))
        out = capsys.readouterr().out
        assert "Session ID" in out

    def test_draft_shows_status(self, patched_conn, capsys):
        add_from_message(patched_conn, "bananas", "discord", "vern")
        cli_module.cmd_draft(ns(json=False))
        out = capsys.readouterr().out
        assert "awaiting_approval" in out

    def test_draft_needs_clarification_when_ambiguous(self, patched_conn, capsys):
        add_from_message(patched_conn, "milk", "sms", "cara")
        cli_module.cmd_draft(ns(json=False))
        out = capsys.readouterr().out
        assert "needs_clarification" in out

    def test_draft_json_flag_includes_json(self, patched_conn, capsys):
        add_from_message(patched_conn, "eggs", "discord", "vern")
        cli_module.cmd_draft(ns(json=True))
        out = capsys.readouterr().out
        assert "session_id" in out
        assert "{" in out

    def test_draft_prints_no_submit_warning(self, patched_conn, capsys):
        cli_module.cmd_draft(ns(json=False))
        out = capsys.readouterr().out
        assert "No order has been placed" in out


# ---------------------------------------------------------------------------
# cmd_resolve
# ---------------------------------------------------------------------------

class TestCmdResolve:
    @pytest.fixture
    def ambiguous_id(self, patched_conn):
        add_from_message(patched_conn, "milk", "sms", "cara")
        items = list_ambiguous(patched_conn)
        return items[0]["id"]

    def test_resolve_happy_path_output(self, patched_conn, ambiguous_id, capsys):
        cli_module.cmd_resolve(ns(item_id=ambiguous_id, new_name="oat milk"))
        out = capsys.readouterr().out
        assert "Resolved item" in out
        assert "oat milk" in out

    def test_resolve_shows_before_and_after(self, patched_conn, ambiguous_id, capsys):
        cli_module.cmd_resolve(ns(item_id=ambiguous_id, new_name="oat milk"))
        out = capsys.readouterr().out
        assert "Before:" in out
        assert "After:" in out

    def test_resolve_bad_item_id_exits(self, patched_conn, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_module.cmd_resolve(ns(item_id=9999, new_name="oat milk"))
        assert exc_info.value.code == 1

    def test_resolve_still_ambiguous_name_exits(self, patched_conn, ambiguous_id, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli_module.cmd_resolve(ns(item_id=ambiguous_id, new_name="milk"))
        assert exc_info.value.code == 1

    def test_resolve_shows_promoted_sessions(self, patched_conn, ambiguous_id, capsys):
        from grocery_assistant.db import create_cart_session, add_item_to_session, update_session_status
        sid = create_cart_session(patched_conn)
        add_item_to_session(patched_conn, sid, ambiguous_id)
        update_session_status(patched_conn, sid, "needs_clarification")

        cli_module.cmd_resolve(ns(item_id=ambiguous_id, new_name="oat milk"))
        out = capsys.readouterr().out
        assert "awaiting_approval" in out


# ---------------------------------------------------------------------------
# cmd_history
# ---------------------------------------------------------------------------

class TestCmdHistory:
    @pytest.fixture
    def ambiguous_id(self, patched_conn):
        add_from_message(patched_conn, "milk", "sms", "cara")
        items = list_ambiguous(patched_conn)
        return items[0]["id"]

    def test_history_empty_before_resolution(self, patched_conn, ambiguous_id, capsys):
        cli_module.cmd_history(ns(item_id=ambiguous_id))
        out = capsys.readouterr().out
        assert "No clarification history" in out

    def test_history_shows_resolution(self, patched_conn, ambiguous_id, capsys):
        cli_module.cmd_resolve(ns(item_id=ambiguous_id, new_name="oat milk"))
        capsys.readouterr()  # clear resolve output
        cli_module.cmd_history(ns(item_id=ambiguous_id))
        out = capsys.readouterr().out
        assert "oat milk" in out
        assert "operator" in out

    def test_history_unknown_item(self, patched_conn, capsys):
        cli_module.cmd_history(ns(item_id=9999))
        out = capsys.readouterr().out
        assert "No clarification history" in out


# ---------------------------------------------------------------------------
# build_parser / argument structure
# ---------------------------------------------------------------------------

class TestParser:
    def test_list_command_parseable(self):
        parser = cli_module.build_parser()
        args = parser.parse_args(["list"])
        assert args.command == "list"

    def test_flagged_command_parseable(self):
        parser = cli_module.build_parser()
        args = parser.parse_args(["flagged"])
        assert args.command == "flagged"

    def test_by_sender_requires_name(self):
        parser = cli_module.build_parser()
        args = parser.parse_args(["by-sender", "cara"])
        assert args.sender == "cara"

    def test_by_channel_requires_channel(self):
        parser = cli_module.build_parser()
        args = parser.parse_args(["by-channel", "sms"])
        assert args.channel == "sms"

    def test_draft_has_json_flag(self):
        parser = cli_module.build_parser()
        args = parser.parse_args(["draft", "--json"])
        assert args.json is True

    def test_resolve_requires_item_id_and_name(self):
        parser = cli_module.build_parser()
        args = parser.parse_args(["resolve", "42", "oat milk"])
        assert args.item_id == 42
        assert args.new_name == "oat milk"

    def test_history_requires_item_id(self):
        parser = cli_module.build_parser()
        args = parser.parse_args(["history", "7"])
        assert args.item_id == 7

    def test_no_command_exits(self):
        parser = cli_module.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])
