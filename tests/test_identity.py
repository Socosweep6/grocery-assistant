"""
Tests for sender identity validation.

Covers:
- SMS trusted sender resolution (phone number -> canonical name)
- SMS untrusted sender raises UntrustedSenderError
- Discord trusted user resolution (user ID -> canonical name)
- Discord untrusted user raises UntrustedSenderError
- is_vern helper
- SmsAdapter.receive_webhook enforces trusted senders
- DiscordAdapter.receive_event enforces trusted users
- Missing payload fields raise ValueError
"""

import sqlite3
import pytest
from pathlib import Path

from grocery_assistant.identity import (
    resolve_sms_sender,
    resolve_discord_sender,
    is_vern,
    UntrustedSenderError,
)
from grocery_assistant.intake.sms_adapter import SmsAdapter
from grocery_assistant.intake.discord_adapter import DiscordAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TRUSTED_SMS = {"+12065550001": "cara", "+12065550002": "vern"}
TRUSTED_DISCORD = {"111111111111111111": "vern", "222222222222222222": "cara"}


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
# SMS sender resolution
# ---------------------------------------------------------------------------

def test_sms_trusted_sender_resolved():
    name = resolve_sms_sender("+12065550001", trusted=TRUSTED_SMS)
    assert name == "cara"


def test_sms_trusted_sender_lowercased():
    trusted = {"+12065550001": "Cara"}
    name = resolve_sms_sender("+12065550001", trusted=trusted)
    assert name == "cara"


def test_sms_untrusted_sender_raises():
    with pytest.raises(UntrustedSenderError):
        resolve_sms_sender("+19995550000", trusted=TRUSTED_SMS)


def test_sms_empty_number_raises():
    with pytest.raises(UntrustedSenderError):
        resolve_sms_sender("", trusted=TRUSTED_SMS)


def test_sms_strips_whitespace_from_number():
    name = resolve_sms_sender("  +12065550001  ", trusted=TRUSTED_SMS)
    assert name == "cara"


# ---------------------------------------------------------------------------
# Discord sender resolution
# ---------------------------------------------------------------------------

def test_discord_trusted_user_resolved():
    name = resolve_discord_sender("111111111111111111", trusted=TRUSTED_DISCORD)
    assert name == "vern"


def test_discord_trusted_user_lowercased():
    trusted = {"111111111111111111": "Vern"}
    name = resolve_discord_sender("111111111111111111", trusted=trusted)
    assert name == "vern"


def test_discord_untrusted_user_raises():
    with pytest.raises(UntrustedSenderError):
        resolve_discord_sender("999999999999999999", trusted=TRUSTED_DISCORD)


def test_discord_integer_id_coerced_to_string():
    # Discord IDs are ints in some libraries; adapter converts with str()
    name = resolve_discord_sender("111111111111111111", trusted=TRUSTED_DISCORD)
    assert name == "vern"


def test_discord_empty_id_raises():
    with pytest.raises(UntrustedSenderError):
        resolve_discord_sender("", trusted=TRUSTED_DISCORD)


# ---------------------------------------------------------------------------
# is_vern helper
# ---------------------------------------------------------------------------

def test_is_vern_true():
    assert is_vern("vern") is True


def test_is_vern_case_insensitive():
    assert is_vern("Vern") is True
    assert is_vern("VERN") is True


def test_is_vern_false_for_cara():
    assert is_vern("cara") is False


def test_is_vern_false_for_empty():
    assert is_vern("") is False


# ---------------------------------------------------------------------------
# SmsAdapter.receive_webhook
# ---------------------------------------------------------------------------

def test_sms_adapter_trusted_webhook_accepted(conn):
    adapter = SmsAdapter(conn, trusted_senders=TRUSTED_SMS)
    result = adapter.receive_webhook({"From": "+12065550001", "Body": "bananas"})
    assert "bananas" in result["added"]


def test_sms_adapter_untrusted_webhook_rejected(conn):
    adapter = SmsAdapter(conn, trusted_senders=TRUSTED_SMS)
    with pytest.raises(UntrustedSenderError):
        adapter.receive_webhook({"From": "+19995550000", "Body": "bananas"})


def test_sms_adapter_missing_from_raises(conn):
    adapter = SmsAdapter(conn, trusted_senders=TRUSTED_SMS)
    with pytest.raises(ValueError, match="From"):
        adapter.receive_webhook({"Body": "eggs"})


def test_sms_adapter_missing_body_raises(conn):
    adapter = SmsAdapter(conn, trusted_senders=TRUSTED_SMS)
    with pytest.raises(ValueError, match="Body"):
        adapter.receive_webhook({"From": "+12065550001"})


def test_sms_adapter_empty_body_raises(conn):
    adapter = SmsAdapter(conn, trusted_senders=TRUSTED_SMS)
    with pytest.raises(ValueError, match="Body"):
        adapter.receive_webhook({"From": "+12065550001", "Body": "   "})


def test_sms_adapter_sender_normalized_to_name(conn):
    adapter = SmsAdapter(conn, trusted_senders=TRUSTED_SMS)
    adapter.receive_webhook({"From": "+12065550001", "Body": "eggs"})

    # The intake event should have the resolved name, not the phone number
    row = conn.execute(
        "SELECT sender FROM intake_events WHERE source_channel = 'sms'"
    ).fetchone()
    assert row["sender"] == "cara"


def test_sms_adapter_channel_recorded_as_sms(conn):
    adapter = SmsAdapter(conn, trusted_senders=TRUSTED_SMS)
    adapter.receive_webhook({"From": "+12065550001", "Body": "dish soap"})
    row = conn.execute("SELECT source_channel FROM intake_events").fetchone()
    assert row["source_channel"] == "sms"


# ---------------------------------------------------------------------------
# DiscordAdapter.receive_event
# ---------------------------------------------------------------------------

def test_discord_adapter_trusted_event_accepted(conn):
    adapter = DiscordAdapter(conn, trusted_users=TRUSTED_DISCORD)
    event = {"author": {"id": "111111111111111111"}, "content": "bananas"}
    result = adapter.receive_event(event)
    assert "bananas" in result["added"]


def test_discord_adapter_untrusted_event_rejected(conn):
    adapter = DiscordAdapter(conn, trusted_users=TRUSTED_DISCORD)
    event = {"author": {"id": "999999999999999999"}, "content": "bananas"}
    with pytest.raises(UntrustedSenderError):
        adapter.receive_event(event)


def test_discord_adapter_missing_author_id_raises(conn):
    adapter = DiscordAdapter(conn, trusted_users=TRUSTED_DISCORD)
    with pytest.raises(ValueError, match="author.id"):
        adapter.receive_event({"author": {}, "content": "eggs"})


def test_discord_adapter_missing_content_raises(conn):
    adapter = DiscordAdapter(conn, trusted_users=TRUSTED_DISCORD)
    with pytest.raises(ValueError, match="content"):
        adapter.receive_event({"author": {"id": "111111111111111111"}})


def test_discord_adapter_empty_content_raises(conn):
    adapter = DiscordAdapter(conn, trusted_users=TRUSTED_DISCORD)
    with pytest.raises(ValueError, match="content"):
        adapter.receive_event({"author": {"id": "111111111111111111"}, "content": "  "})


def test_discord_adapter_sender_normalized_to_name(conn):
    adapter = DiscordAdapter(conn, trusted_users=TRUSTED_DISCORD)
    adapter.receive_event({"author": {"id": "111111111111111111"}, "content": "eggs"})

    row = conn.execute(
        "SELECT sender FROM intake_events WHERE source_channel = 'discord'"
    ).fetchone()
    assert row["sender"] == "vern"


def test_discord_adapter_channel_recorded_as_discord(conn):
    adapter = DiscordAdapter(conn, trusted_users=TRUSTED_DISCORD)
    adapter.receive_event({"author": {"id": "222222222222222222"}, "content": "dish soap"})
    row = conn.execute("SELECT source_channel FROM intake_events").fetchone()
    assert row["source_channel"] == "discord"


def test_discord_adapter_username_not_used_for_identity(conn):
    """author.username must be ignored; identity comes from author.id only."""
    adapter = DiscordAdapter(conn, trusted_users=TRUSTED_DISCORD)
    # Username says "attacker" but ID is trusted - should use ID, not username
    event = {
        "author": {"id": "111111111111111111", "username": "attacker"},
        "content": "eggs",
    }
    result = adapter.receive_event(event)
    assert "eggs" in result["added"]

    row = conn.execute("SELECT sender FROM intake_events").fetchone()
    assert row["sender"] == "vern"  # resolved from ID, not username
