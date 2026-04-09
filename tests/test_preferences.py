"""
Tests for the preferences module.

Covers:
- set_preference() insert and upsert behavior
- get_preference() hit and miss
- list_preferences() ordering
- delete_preference() delete and no-op
- format_preference_note() formatting variants
- draft includes preference_note per item
- format_draft() shows preference note in output
- resolve_item() includes preference_note when preference exists
"""

import sqlite3
import pytest
from pathlib import Path

from grocery_assistant.preferences import (
    set_preference,
    get_preference,
    list_preferences,
    delete_preference,
    format_preference_note,
)
from grocery_assistant.draft import create_draft, format_draft
from grocery_assistant.clarification import resolve_item
from grocery_assistant.grocery_list import add_from_message


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    schema = (Path(__file__).parent.parent / "schema.sql").read_text()
    c.executescript(schema)
    return c


# ---------------------------------------------------------------------------
# set_preference()
# ---------------------------------------------------------------------------

class TestSetPreference:
    def test_insert_new_preference(self, conn):
        pref = set_preference(conn, "milk", preferred_form="oat milk")
        assert pref["canonical"] == "milk"
        assert pref["preferred_form"] == "oat milk"
        assert pref["substitutions_ok"] is False
        assert pref["note"] is None

    def test_insert_with_all_fields(self, conn):
        pref = set_preference(conn, "eggs", preferred_form=None,
                               substitutions_ok=True, note="large only")
        assert pref["substitutions_ok"] is True
        assert pref["note"] == "large only"

    def test_upsert_updates_existing_row(self, conn):
        set_preference(conn, "milk", preferred_form="whole milk")
        updated = set_preference(conn, "milk", preferred_form="oat milk",
                                  substitutions_ok=True)
        assert updated["preferred_form"] == "oat milk"
        assert updated["substitutions_ok"] is True

    def test_upsert_does_not_create_duplicate(self, conn):
        set_preference(conn, "milk")
        set_preference(conn, "milk", preferred_form="oat milk")
        prefs = list_preferences(conn)
        milk_prefs = [p for p in prefs if p["canonical"] == "milk"]
        assert len(milk_prefs) == 1

    def test_returns_dict_with_updated_at(self, conn):
        pref = set_preference(conn, "bread")
        assert "updated_at" in pref
        assert pref["updated_at"]


# ---------------------------------------------------------------------------
# get_preference()
# ---------------------------------------------------------------------------

class TestGetPreference:
    def test_returns_none_when_not_set(self, conn):
        result = get_preference(conn, "nonexistent")
        assert result is None

    def test_returns_dict_when_set(self, conn):
        set_preference(conn, "milk", preferred_form="oat milk")
        pref = get_preference(conn, "milk")
        assert pref is not None
        assert pref["canonical"] == "milk"
        assert pref["preferred_form"] == "oat milk"

    def test_returns_none_for_different_canonical(self, conn):
        set_preference(conn, "milk")
        assert get_preference(conn, "eggs") is None


# ---------------------------------------------------------------------------
# list_preferences()
# ---------------------------------------------------------------------------

class TestListPreferences:
    def test_empty_when_no_preferences(self, conn):
        assert list_preferences(conn) == []

    def test_returns_all_preferences(self, conn):
        set_preference(conn, "eggs")
        set_preference(conn, "milk")
        set_preference(conn, "bread")
        prefs = list_preferences(conn)
        assert len(prefs) == 3

    def test_ordered_by_canonical(self, conn):
        set_preference(conn, "milk")
        set_preference(conn, "apples")
        set_preference(conn, "bread")
        prefs = list_preferences(conn)
        canonicals = [p["canonical"] for p in prefs]
        assert canonicals == sorted(canonicals)


# ---------------------------------------------------------------------------
# delete_preference()
# ---------------------------------------------------------------------------

class TestDeletePreference:
    def test_delete_existing_returns_true(self, conn):
        set_preference(conn, "milk")
        result = delete_preference(conn, "milk")
        assert result is True

    def test_delete_removes_the_row(self, conn):
        set_preference(conn, "milk")
        delete_preference(conn, "milk")
        assert get_preference(conn, "milk") is None

    def test_delete_nonexistent_returns_false(self, conn):
        result = delete_preference(conn, "nonexistent")
        assert result is False

    def test_delete_does_not_affect_other_prefs(self, conn):
        set_preference(conn, "milk")
        set_preference(conn, "eggs")
        delete_preference(conn, "milk")
        assert get_preference(conn, "eggs") is not None


# ---------------------------------------------------------------------------
# format_preference_note()
# ---------------------------------------------------------------------------

class TestFormatPreferenceNote:
    def test_with_preferred_form(self):
        pref = {"preferred_form": "oat milk", "substitutions_ok": False, "note": None}
        note = format_preference_note(pref)
        assert "prefer: oat milk" in note
        assert "exact item preferred" in note

    def test_with_substitutions_ok_true(self):
        pref = {"preferred_form": None, "substitutions_ok": True, "note": None}
        note = format_preference_note(pref)
        assert "substitutions OK" in note
        assert "exact item preferred" not in note

    def test_with_note_field(self):
        pref = {"preferred_form": None, "substitutions_ok": False, "note": "large only"}
        note = format_preference_note(pref)
        assert "large only" in note

    def test_all_fields_combined(self):
        pref = {
            "preferred_form": "sourdough",
            "substitutions_ok": True,
            "note": "from bakery section",
        }
        note = format_preference_note(pref)
        assert "prefer: sourdough" in note
        assert "substitutions OK" in note
        assert "from bakery section" in note

    def test_no_fields_set(self):
        pref = {"preferred_form": None, "substitutions_ok": False, "note": None}
        note = format_preference_note(pref)
        assert note == "exact item preferred"


# ---------------------------------------------------------------------------
# Draft includes preference_note
# ---------------------------------------------------------------------------

class TestDraftPreferenceNote:
    def test_draft_item_has_preference_note_field(self, conn):
        add_from_message(conn, "bananas", "sms", "cara")
        draft = create_draft(conn)
        assert "preference_note" in draft["items"][0]

    def test_draft_item_preference_note_is_none_when_no_pref(self, conn):
        add_from_message(conn, "bananas", "sms", "cara")
        draft = create_draft(conn)
        assert draft["items"][0]["preference_note"] is None

    def test_draft_item_preference_note_populated_when_pref_exists(self, conn):
        set_preference(conn, "bananas", preferred_form="organic bananas")
        add_from_message(conn, "bananas", "sms", "cara")
        draft = create_draft(conn)
        item = next(i for i in draft["items"] if i["search_term"] == "bananas")
        assert item["preference_note"] is not None
        assert "organic bananas" in item["preference_note"]

    def test_format_draft_shows_preference_note(self, conn):
        set_preference(conn, "bananas", preferred_form="organic bananas")
        add_from_message(conn, "bananas", "sms", "cara")
        draft = create_draft(conn)
        output = format_draft(draft)
        assert "organic bananas" in output
        assert "[pref:" in output


# ---------------------------------------------------------------------------
# resolve_item() surfaces preference_note
# ---------------------------------------------------------------------------

class TestResolveItemPreferenceNote:
    def test_resolve_includes_preference_note_when_pref_exists(self, conn):
        set_preference(conn, "milk", preferred_form="oat milk")
        add_from_message(conn, "milk", "sms", "cara")
        from grocery_assistant.clarification import list_ambiguous
        items = list_ambiguous(conn)
        item_id = items[0]["id"]
        result = resolve_item(conn, item_id, "oat milk", "operator")
        assert "preference_note" in result
        assert "oat milk" in result["preference_note"]

    def test_resolve_no_preference_note_when_no_pref(self, conn):
        add_from_message(conn, "milk", "sms", "cara")
        from grocery_assistant.clarification import list_ambiguous
        items = list_ambiguous(conn)
        item_id = items[0]["id"]
        result = resolve_item(conn, item_id, "oat milk", "operator")
        assert "preference_note" not in result
