"""
Tests for source traceability and dedupe/merge behavior.

Covers:
- Adding an item creates a grocery_item_sources link
- Duplicate items link the new source event without creating a second item
- Merged duplicates preserve all source events
- Quantity is promoted when existing item has none
- Quantity is NOT overwritten when existing item has one and new differs
- get_items_by_sender: what Cara added vs what Vern added
- get_items_by_channel: SMS vs Discord items
- get_source_events_for_item: full provenance chain
"""

import sqlite3
import pytest
from pathlib import Path

from grocery_assistant.db import (
    get_items_by_sender,
    get_items_by_channel,
    get_source_events_for_item,
    find_item_by_canonical,
)
from grocery_assistant.grocery_list import add_from_message, get_by_sender, get_by_channel


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
# Source link creation
# ---------------------------------------------------------------------------

def test_new_item_creates_source_link(conn):
    result = add_from_message(conn, "bananas", "discord", "vern")
    item = find_item_by_canonical(conn, "bananas")
    sources = get_source_events_for_item(conn, item["id"])
    assert len(sources) == 1
    assert sources[0]["id"] == result["event_id"]


def test_new_item_source_has_correct_sender(conn):
    add_from_message(conn, "eggs", "sms", "cara")
    item = find_item_by_canonical(conn, "eggs")
    sources = get_source_events_for_item(conn, item["id"])
    assert sources[0]["sender"] == "cara"
    assert sources[0]["source_channel"] == "sms"


# ---------------------------------------------------------------------------
# Duplicate handling
# ---------------------------------------------------------------------------

def test_duplicate_does_not_create_second_item(conn):
    add_from_message(conn, "bananas", "discord", "vern")
    add_from_message(conn, "bananas", "sms", "cara")

    rows = conn.execute(
        "SELECT COUNT(*) AS c FROM grocery_items WHERE canonical = 'bananas'"
    ).fetchone()
    assert rows["c"] == 1


def test_duplicate_returns_in_merged_not_added(conn):
    add_from_message(conn, "bananas", "discord", "vern")
    result = add_from_message(conn, "bananas", "sms", "cara")
    assert "bananas" in result["merged"]
    assert "bananas" not in result["added"]


def test_duplicate_adds_second_source_link(conn):
    r1 = add_from_message(conn, "eggs", "discord", "vern")
    r2 = add_from_message(conn, "eggs", "sms", "cara")

    item = find_item_by_canonical(conn, "eggs")
    sources = get_source_events_for_item(conn, item["id"])
    event_ids = {s["id"] for s in sources}

    assert r1["event_id"] in event_ids
    assert r2["event_id"] in event_ids
    assert len(sources) == 2


def test_multiple_duplicates_accumulate_sources(conn):
    add_from_message(conn, "bananas", "discord", "vern")
    add_from_message(conn, "bananas", "sms", "cara")
    add_from_message(conn, "bananas", "discord", "vern")

    item = find_item_by_canonical(conn, "bananas")
    sources = get_source_events_for_item(conn, item["id"])
    assert len(sources) == 3


# ---------------------------------------------------------------------------
# Quantity merge rules
# ---------------------------------------------------------------------------

def test_quantity_promoted_when_existing_has_none(conn):
    add_from_message(conn, "chicken breast", "discord", "vern")
    item_before = find_item_by_canonical(conn, "chicken breast")
    assert item_before["quantity"] is None

    add_from_message(conn, "chicken breast 2 lb", "sms", "cara")
    item_after = find_item_by_canonical(conn, "chicken breast")
    assert item_after["quantity"] == "2"
    assert item_after["unit"] == "lb"


def test_quantity_not_overwritten_when_existing_has_one(conn):
    add_from_message(conn, "ground turkey 2 lb", "discord", "vern")
    item_before = find_item_by_canonical(conn, "turkey ground")
    assert item_before["quantity"] == "2"

    # Different quantity - should not overwrite
    add_from_message(conn, "ground turkey 3 lb", "sms", "cara")
    item_after = find_item_by_canonical(conn, "turkey ground")
    assert item_after["quantity"] == "2"  # original preserved


def test_quantity_not_overwritten_when_same_value(conn):
    add_from_message(conn, "ground turkey 2 lb", "discord", "vern")
    add_from_message(conn, "ground turkey 2 lb", "discord", "vern")
    item = find_item_by_canonical(conn, "turkey ground")
    assert item["quantity"] == "2"


# ---------------------------------------------------------------------------
# Sender-based queries
# ---------------------------------------------------------------------------

def test_get_by_sender_returns_correct_items(conn):
    add_from_message(conn, "bananas", "discord", "vern")
    add_from_message(conn, "eggs", "sms", "cara")
    add_from_message(conn, "oat milk", "discord", "vern")

    vern_items = get_by_sender(conn, "vern")
    canonicals = [r["canonical"] for r in vern_items]
    assert "bananas" in canonicals
    assert "milk oat" in canonicals
    assert "eggs" not in canonicals


def test_get_by_sender_cara(conn):
    add_from_message(conn, "dish soap", "sms", "cara")
    add_from_message(conn, "bananas", "discord", "vern")

    cara_items = get_by_sender(conn, "cara")
    canonicals = [r["canonical"] for r in cara_items]
    assert "dish soap" in canonicals
    assert "bananas" not in canonicals


def test_get_by_sender_case_insensitive(conn):
    add_from_message(conn, "eggs", "discord", "Vern")
    items = get_by_sender(conn, "vern")
    canonicals = [r["canonical"] for r in items]
    assert "eggs" in canonicals


def test_get_by_sender_duplicate_appears_once(conn):
    # Cara added bananas, then Vern added bananas again
    # bananas should still appear in Cara's list, and once only
    add_from_message(conn, "bananas", "sms", "cara")
    add_from_message(conn, "bananas", "discord", "vern")

    cara_items = get_by_sender(conn, "cara")
    banana_rows = [r for r in cara_items if r["canonical"] == "bananas"]
    assert len(banana_rows) == 1


# ---------------------------------------------------------------------------
# Channel-based queries
# ---------------------------------------------------------------------------

def test_get_by_channel_sms(conn):
    add_from_message(conn, "dish soap", "sms", "cara")
    add_from_message(conn, "bananas", "discord", "vern")

    sms_items = get_by_channel(conn, "sms")
    canonicals = [r["canonical"] for r in sms_items]
    assert "dish soap" in canonicals
    assert "bananas" not in canonicals


def test_get_by_channel_discord(conn):
    add_from_message(conn, "dish soap", "sms", "cara")
    add_from_message(conn, "bananas", "discord", "vern")

    discord_items = get_by_channel(conn, "discord")
    canonicals = [r["canonical"] for r in discord_items]
    assert "bananas" in canonicals
    assert "dish soap" not in canonicals


def test_get_by_channel_duplicate_item_in_both(conn):
    # bananas added from SMS first, then from Discord
    add_from_message(conn, "bananas", "sms", "cara")
    add_from_message(conn, "bananas", "discord", "vern")

    sms_items = get_by_channel(conn, "sms")
    discord_items = get_by_channel(conn, "discord")

    sms_canonicals = [r["canonical"] for r in sms_items]
    discord_canonicals = [r["canonical"] for r in discord_items]

    # Item appears in both channel views because both events are linked
    assert "bananas" in sms_canonicals
    assert "bananas" in discord_canonicals


# ---------------------------------------------------------------------------
# Multi-item message source linking
# ---------------------------------------------------------------------------

def test_multi_item_message_links_all_to_same_event(conn):
    result = add_from_message(conn, "bananas, eggs, oat milk", "discord", "vern")
    event_id = result["event_id"]

    for canonical in ["bananas", "eggs", "milk oat"]:
        item = find_item_by_canonical(conn, canonical)
        sources = get_source_events_for_item(conn, item["id"])
        event_ids = [s["id"] for s in sources]
        assert event_id in event_ids, f"{canonical} not linked to event {event_id}"
