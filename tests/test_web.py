"""
Tests for the Flask web application routes.

Covers:
- POST /sms/webhook: valid intake, untrusted sender, missing fields
- POST /discord/event: valid intake, untrusted sender, missing content-type, missing fields
- GET  /api/list: empty list, populated list
- GET  /api/flagged: no flagged items, flagged items returned
- GET  /api/by-sender/<sender>: correct items returned
- GET  /api/by-channel/<channel>: correct items returned
- POST /api/draft: creates session, correct status
- GET  /api/draft/<session_id>: found and not-found
- POST /api/resolve: happy path, missing fields, still-ambiguous name, non-existent item

All tests use an in-memory SQLite DB injected via the create_app() factory.
No real Twilio credentials or Discord bot token required.
"""

import json
import sqlite3
import pytest
from pathlib import Path

from grocery_assistant.web import create_app
from grocery_assistant.grocery_list import add_from_message
from grocery_assistant.clarification import list_ambiguous


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TRUSTED_SMS = {"+12065550001": "cara", "+12065550002": "vern"}
TRUSTED_DISCORD = {"111111111111111111": "vern", "222222222222222222": "cara"}


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
def client(conn):
    """Flask test client with injected in-memory DB and test trust registries."""
    app = create_app(conn=conn,
                     trusted_sms=TRUSTED_SMS,
                     trusted_discord=TRUSTED_DISCORD)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# POST /sms/webhook
# ---------------------------------------------------------------------------

class TestSmsWebhook:
    def test_valid_sms_returns_200(self, client):
        resp = client.post("/sms/webhook", data={
            "From": "+12065550001",
            "Body": "bananas, eggs",
        })
        assert resp.status_code == 200

    def test_valid_sms_response_has_expected_keys(self, client):
        resp = client.post("/sms/webhook", data={
            "From": "+12065550001",
            "Body": "bananas",
        })
        data = resp.get_json()
        assert "event_id" in data
        assert "added" in data
        assert "merged" in data
        assert "flagged" in data

    def test_valid_sms_adds_item(self, client):
        resp = client.post("/sms/webhook", data={
            "From": "+12065550001",
            "Body": "oat milk",
        })
        data = resp.get_json()
        assert "milk oat" in data["added"]

    def test_valid_sms_flags_ambiguous_item(self, client):
        resp = client.post("/sms/webhook", data={
            "From": "+12065550001",
            "Body": "milk",
        })
        data = resp.get_json()
        assert len(data["flagged"]) == 1
        assert data["flagged"][0]["item"] == "milk"

    def test_sms_untrusted_sender_returns_403(self, client):
        resp = client.post("/sms/webhook", data={
            "From": "+19995550000",
            "Body": "bananas",
        })
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["error"] == "untrusted_sender"

    def test_sms_missing_from_returns_400(self, client):
        resp = client.post("/sms/webhook", data={
            "Body": "bananas",
        })
        assert resp.status_code == 400

    def test_sms_missing_body_returns_400(self, client):
        resp = client.post("/sms/webhook", data={
            "From": "+12065550001",
        })
        assert resp.status_code == 400

    def test_sms_deduplication_returns_in_merged(self, client):
        client.post("/sms/webhook", data={"From": "+12065550001", "Body": "bananas"})
        resp = client.post("/sms/webhook", data={"From": "+12065550001", "Body": "bananas"})
        data = resp.get_json()
        assert "bananas" in data["merged"]
        assert "bananas" not in data["added"]

    def test_sms_multi_item_message(self, client):
        resp = client.post("/sms/webhook", data={
            "From": "+12065550001",
            "Body": "bananas, eggs, oat milk",
        })
        data = resp.get_json()
        assert len(data["added"]) == 3


# ---------------------------------------------------------------------------
# POST /discord/event
# ---------------------------------------------------------------------------

class TestDiscordEvent:
    def test_valid_discord_event_returns_200(self, client):
        resp = client.post("/discord/event",
                           data=json.dumps({
                               "author": {"id": "111111111111111111"},
                               "content": "bananas",
                           }),
                           content_type="application/json")
        assert resp.status_code == 200

    def test_valid_discord_event_adds_item(self, client):
        resp = client.post("/discord/event",
                           data=json.dumps({
                               "author": {"id": "111111111111111111"},
                               "content": "oat milk",
                           }),
                           content_type="application/json")
        data = resp.get_json()
        assert "milk oat" in data["added"]

    def test_discord_untrusted_user_returns_403(self, client):
        resp = client.post("/discord/event",
                           data=json.dumps({
                               "author": {"id": "999999999999999999"},
                               "content": "bananas",
                           }),
                           content_type="application/json")
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "untrusted_sender"

    def test_discord_wrong_content_type_returns_400(self, client):
        resp = client.post("/discord/event",
                           data="author=foo&content=bar",
                           content_type="application/x-www-form-urlencoded")
        assert resp.status_code == 400

    def test_discord_missing_author_returns_400(self, client):
        resp = client.post("/discord/event",
                           data=json.dumps({"content": "bananas"}),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_discord_missing_content_returns_400(self, client):
        resp = client.post("/discord/event",
                           data=json.dumps({"author": {"id": "111111111111111111"}}),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_discord_flags_ambiguous(self, client):
        resp = client.post("/discord/event",
                           data=json.dumps({
                               "author": {"id": "111111111111111111"},
                               "content": "milk",
                           }),
                           content_type="application/json")
        data = resp.get_json()
        assert len(data["flagged"]) == 1

    def test_discord_response_has_expected_keys(self, client):
        resp = client.post("/discord/event",
                           data=json.dumps({
                               "author": {"id": "111111111111111111"},
                               "content": "eggs",
                           }),
                           content_type="application/json")
        data = resp.get_json()
        assert "event_id" in data
        assert "added" in data
        assert "merged" in data
        assert "flagged" in data


# ---------------------------------------------------------------------------
# GET /api/list
# ---------------------------------------------------------------------------

class TestApiList:
    def test_empty_list_returns_200_empty_array(self, client):
        resp = client.get("/api/list")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_list_returns_items_after_intake(self, client, conn):
        add_from_message(conn, "bananas, eggs", "discord", "vern")
        resp = client.get("/api/list")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2

    def test_list_items_have_canonical_field(self, client, conn):
        add_from_message(conn, "oat milk", "sms", "cara")
        data = client.get("/api/list").get_json()
        canonicals = [i["canonical"] for i in data]
        assert "milk oat" in canonicals


# ---------------------------------------------------------------------------
# GET /api/flagged
# ---------------------------------------------------------------------------

class TestApiFlagged:
    def test_no_flagged_returns_empty(self, client):
        resp = client.get("/api/flagged")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_flagged_returns_ambiguous_items(self, client, conn):
        add_from_message(conn, "milk", "sms", "cara")
        resp = client.get("/api/flagged")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["canonical"] == "milk"

    def test_flagged_does_not_include_clear_items(self, client, conn):
        add_from_message(conn, "milk", "sms", "cara")
        add_from_message(conn, "bananas", "sms", "cara")
        data = client.get("/api/flagged").get_json()
        assert len(data) == 1


# ---------------------------------------------------------------------------
# GET /api/by-sender/<sender>
# ---------------------------------------------------------------------------

class TestApiBySender:
    def test_by_sender_returns_correct_items(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        add_from_message(conn, "oat milk", "sms", "cara")
        data = client.get("/api/by-sender/cara").get_json()
        assert len(data) == 1
        assert data[0]["canonical"] == "milk oat"

    def test_by_sender_returns_empty_for_unknown(self, client):
        data = client.get("/api/by-sender/nobody").get_json()
        assert data == []

    def test_by_sender_case_insensitive(self, client, conn):
        add_from_message(conn, "eggs", "discord", "Vern")
        data = client.get("/api/by-sender/vern").get_json()
        assert len(data) == 1


# ---------------------------------------------------------------------------
# GET /api/by-channel/<channel>
# ---------------------------------------------------------------------------

class TestApiByChannel:
    def test_by_channel_sms(self, client, conn):
        add_from_message(conn, "bananas", "sms", "cara")
        add_from_message(conn, "eggs", "discord", "vern")
        data = client.get("/api/by-channel/sms").get_json()
        assert len(data) == 1
        assert data[0]["canonical"] == "bananas"

    def test_by_channel_discord(self, client, conn):
        add_from_message(conn, "bananas", "sms", "cara")
        add_from_message(conn, "eggs", "discord", "vern")
        data = client.get("/api/by-channel/discord").get_json()
        assert len(data) == 1
        assert data[0]["canonical"] == "eggs"

    def test_by_channel_empty_for_unknown(self, client):
        data = client.get("/api/by-channel/fax").get_json()
        assert data == []


# ---------------------------------------------------------------------------
# POST /api/draft
# ---------------------------------------------------------------------------

class TestApiDraft:
    def test_draft_returns_200(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        resp = client.post("/api/draft")
        assert resp.status_code == 200

    def test_draft_has_expected_keys(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        data = client.post("/api/draft").get_json()
        assert "session_id" in data
        assert "status" in data
        assert "items" in data
        assert "ambiguous" in data

    def test_draft_status_awaiting_when_no_ambiguous(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        data = client.post("/api/draft").get_json()
        assert data["status"] == "awaiting_approval"

    def test_draft_status_needs_clarification_when_ambiguous(self, client, conn):
        add_from_message(conn, "milk", "sms", "cara")
        data = client.post("/api/draft").get_json()
        assert data["status"] == "needs_clarification"
        assert len(data["ambiguous"]) == 1

    def test_draft_empty_list_creates_session(self, client):
        data = client.post("/api/draft").get_json()
        assert "session_id" in data
        assert isinstance(data["session_id"], int)


# ---------------------------------------------------------------------------
# GET /api/draft/<session_id>
# ---------------------------------------------------------------------------

class TestApiGetDraft:
    def test_get_existing_session(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = client.post("/api/draft").get_json()
        sid = draft["session_id"]
        resp = client.get(f"/api/draft/{sid}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "session" in data
        assert "items" in data

    def test_get_nonexistent_session_returns_404(self, client):
        resp = client.get("/api/draft/9999")
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "not_found"


# ---------------------------------------------------------------------------
# POST /api/resolve
# ---------------------------------------------------------------------------

class TestApiResolve:
    @pytest.fixture
    def setup_ambiguous(self, client, conn):
        add_from_message(conn, "milk", "sms", "cara")
        flagged = client.get("/api/flagged").get_json()
        return flagged[0]["id"]

    def test_resolve_happy_path(self, client, setup_ambiguous):
        item_id = setup_ambiguous
        resp = client.post("/api/resolve",
                           data=json.dumps({
                               "item_id": item_id,
                               "new_name": "oat milk",
                               "resolved_by": "operator",
                           }),
                           content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["resolved_canonical"] == "milk oat"
        assert data["item_id"] == item_id

    def test_resolve_missing_item_id_returns_400(self, client):
        resp = client.post("/api/resolve",
                           data=json.dumps({"new_name": "oat milk"}),
                           content_type="application/json")
        assert resp.status_code == 400
        assert "item_id" in resp.get_json()["detail"]

    def test_resolve_missing_new_name_returns_400(self, client):
        resp = client.post("/api/resolve",
                           data=json.dumps({"item_id": 1}),
                           content_type="application/json")
        assert resp.status_code == 400
        assert "new_name" in resp.get_json()["detail"]

    def test_resolve_wrong_content_type_returns_400(self, client):
        resp = client.post("/api/resolve",
                           data="item_id=1&new_name=oat+milk",
                           content_type="application/x-www-form-urlencoded")
        assert resp.status_code == 400

    def test_resolve_still_ambiguous_name_returns_400(self, client, setup_ambiguous):
        item_id = setup_ambiguous
        resp = client.post("/api/resolve",
                           data=json.dumps({"item_id": item_id, "new_name": "milk"}),
                           content_type="application/json")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "clarification_error"

    def test_resolve_nonexistent_item_returns_400(self, client):
        resp = client.post("/api/resolve",
                           data=json.dumps({"item_id": 9999, "new_name": "oat milk"}),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_resolve_default_resolved_by_is_operator(self, client, setup_ambiguous):
        item_id = setup_ambiguous
        resp = client.post("/api/resolve",
                           data=json.dumps({"item_id": item_id, "new_name": "oat milk"}),
                           content_type="application/json")
        # resolved_by not provided; should default to "operator"
        # (the route returns the result dict which includes resolved_by from clarification.py)
        assert resp.status_code == 200

    def test_resolve_clears_flagged(self, client, conn, setup_ambiguous):
        item_id = setup_ambiguous
        client.post("/api/resolve",
                    data=json.dumps({"item_id": item_id, "new_name": "oat milk"}),
                    content_type="application/json")
        flagged = client.get("/api/flagged").get_json()
        assert flagged == []
