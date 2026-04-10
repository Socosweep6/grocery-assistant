"""
Tests for browser UI routes (Phase 1 mobile web).

Covers:
- GET  /               -- dashboard
- GET  /list           -- grocery list
- GET  /flagged        -- flagged / ambiguous items
- GET  /drafts/new     -- draft preview page
- POST /drafts/new     -- create draft (auth required)
- GET  /drafts/<id>    -- draft detail
- POST /drafts/<id>/approve -- approve draft (auth required)
- GET  /drafts/<id>/shop -- shopping handoff page for approved drafts
- POST /drafts/<id>/ordered -- mark manual checkout complete (auth required)
- GET  /login          -- login page
- POST /login          -- token submit
- GET  /logout         -- clear session

All tests use an in-memory SQLite DB injected via create_app().
No real Twilio credentials or Discord token required.
"""

import sqlite3
from pathlib import Path

import pytest

from grocery_assistant.web import create_app
from grocery_assistant.grocery_list import add_from_message


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TRUSTED_SMS = {"+12065550001": "cara", "+12065550002": "vern"}
TRUSTED_DISCORD = {"111111111111111111": "vern"}
BROWSER_TOKEN = "testtoken"
SECRET_KEY = b"test-secret-key"


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
    app = create_app(
        conn=conn,
        trusted_sms=TRUSTED_SMS,
        trusted_discord=TRUSTED_DISCORD,
        browser_token=BROWSER_TOKEN,
        secret_key=SECRET_KEY,
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def authed_client(client):
    """Test client with the browser session already logged in."""
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    return client


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

class TestUiIndex:
    def test_get_index_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_get_index_shows_zero_count_when_empty(self, client):
        resp = client.get("/")
        assert b"0" in resp.data

    def test_get_index_shows_item_count(self, client, conn):
        add_from_message(conn, "bananas, eggs", "discord", "vern")
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"2" in resp.data

    def test_get_index_shows_flagged_count(self, client, conn):
        add_from_message(conn, "milk", "sms", "cara")  # ambiguous
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"1" in resp.data


# ---------------------------------------------------------------------------
# GET /list
# ---------------------------------------------------------------------------

class TestUiList:
    def test_get_list_returns_200(self, client):
        resp = client.get("/list")
        assert resp.status_code == 200

    def test_get_list_shows_empty_state_when_no_items(self, client):
        resp = client.get("/list")
        assert b"No items" in resp.data

    def test_get_list_shows_items(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        resp = client.get("/list")
        assert resp.status_code == 200
        assert b"bananas" in resp.data

    def test_get_list_groups_by_category(self, client, conn):
        add_from_message(conn, "bananas, chicken breast", "discord", "vern")
        resp = client.get("/list")
        # Both category labels should appear somewhere in the page
        assert resp.status_code == 200
        assert b"produce" in resp.data.lower() or b"protein" in resp.data.lower()

    def test_get_list_shows_needs_clarification_badge(self, client, conn):
        add_from_message(conn, "milk", "sms", "cara")  # ambiguous
        resp = client.get("/list")
        assert b"needs clarification" in resp.data


# ---------------------------------------------------------------------------
# GET /flagged
# ---------------------------------------------------------------------------

class TestUiFlagged:
    def test_get_flagged_returns_200(self, client):
        resp = client.get("/flagged")
        assert resp.status_code == 200

    def test_get_flagged_shows_empty_state(self, client):
        resp = client.get("/flagged")
        assert b"No flagged" in resp.data

    def test_get_flagged_shows_ambiguous_items(self, client, conn):
        add_from_message(conn, "milk", "sms", "cara")
        resp = client.get("/flagged")
        assert resp.status_code == 200
        assert b"milk" in resp.data

    def test_get_flagged_does_not_show_clear_items(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")  # not ambiguous
        resp = client.get("/flagged")
        assert b"bananas" not in resp.data


# ---------------------------------------------------------------------------
# GET/POST /drafts/new
# ---------------------------------------------------------------------------

class TestUiDraftNew:
    def test_get_draft_new_returns_200(self, client):
        resp = client.get("/drafts/new")
        assert resp.status_code == 200

    def test_get_draft_new_shows_items(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        resp = client.get("/drafts/new")
        assert b"bananas" in resp.data

    def test_get_draft_new_shows_empty_state_when_no_items(self, client):
        resp = client.get("/drafts/new")
        assert b"No pending items" in resp.data

    def test_post_draft_new_unauthenticated_redirects_to_login(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        resp = client.post("/drafts/new", follow_redirects=False)
        assert resp.status_code == 302
        assert "login" in resp.headers["Location"]

    def test_post_draft_new_authenticated_redirects_to_draft(self, authed_client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        resp = authed_client.post("/drafts/new", follow_redirects=False)
        assert resp.status_code == 302
        assert "/drafts/" in resp.headers["Location"]

    def test_post_draft_new_authenticated_creates_draft(self, authed_client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        resp = authed_client.post("/drafts/new", follow_redirects=True)
        assert resp.status_code == 200
        # Redirected to draft detail page
        assert b"Draft #" in resp.data


# ---------------------------------------------------------------------------
# GET /drafts/<id>
# ---------------------------------------------------------------------------

class TestUiDraftDetail:
    def test_get_draft_detail_returns_200(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = client.post("/api/draft").get_json()
        resp = client.get(f"/drafts/{draft['session_id']}")
        assert resp.status_code == 200

    def test_get_draft_detail_nonexistent_returns_404(self, client):
        resp = client.get("/drafts/9999")
        assert resp.status_code == 404

    def test_get_draft_detail_shows_session_id(self, client, conn):
        add_from_message(conn, "eggs", "discord", "vern")
        draft = client.post("/api/draft").get_json()
        sid = draft["session_id"]
        resp = client.get(f"/drafts/{sid}")
        assert f"Draft #{sid}".encode() in resp.data

    def test_get_draft_detail_shows_items(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = client.post("/api/draft").get_json()
        resp = client.get(f"/drafts/{draft['session_id']}")
        assert b"bananas" in resp.data

    def test_get_draft_detail_awaiting_shows_approve_button(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = client.post("/api/draft").get_json()
        assert draft["status"] == "awaiting_approval"
        resp = client.get(f"/drafts/{draft['session_id']}")
        assert b"Approve order" in resp.data

    def test_get_draft_detail_approved_shows_shopping_handoff_link(self, authed_client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = authed_client.post("/api/draft").get_json()
        sid = draft["session_id"]
        authed_client.post(f"/drafts/{sid}/approve")
        resp = authed_client.get(f"/drafts/{sid}")
        assert b"Open shopping handoff" in resp.data
        assert f"/drafts/{sid}/shop".encode() in resp.data

    def test_get_draft_detail_needs_clarification_no_approve_button(self, client, conn):
        add_from_message(conn, "milk", "sms", "cara")  # ambiguous
        draft = client.post("/api/draft").get_json()
        assert draft["status"] == "needs_clarification"
        resp = client.get(f"/drafts/{draft['session_id']}")
        assert b"Approve order" not in resp.data
        assert b"clarification" in resp.data.lower()


# ---------------------------------------------------------------------------
# POST /drafts/<id>/approve
# ---------------------------------------------------------------------------

class TestUiDraftApprove:
    def test_post_approve_unauthenticated_redirects_to_login(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = client.post("/api/draft").get_json()
        resp = client.post(f"/drafts/{draft['session_id']}/approve",
                           follow_redirects=False)
        assert resp.status_code == 302
        assert "login" in resp.headers["Location"]

    def test_post_approve_authenticated_approves_draft(self, authed_client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = authed_client.post("/api/draft").get_json()
        assert draft["status"] == "awaiting_approval"
        sid = draft["session_id"]
        resp = authed_client.post(f"/drafts/{sid}/approve", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Order approved" in resp.data

    def test_post_approve_sets_session_status_to_approved(self, authed_client, conn):
        add_from_message(conn, "eggs", "discord", "vern")
        draft = authed_client.post("/api/draft").get_json()
        sid = draft["session_id"]
        authed_client.post(f"/drafts/{sid}/approve")
        # Verify via API
        detail = authed_client.get(f"/api/draft/{sid}").get_json()
        assert detail["session"]["status"] == "approved"

    def test_post_approve_already_approved_shows_error(self, authed_client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = authed_client.post("/api/draft").get_json()
        sid = draft["session_id"]
        authed_client.post(f"/drafts/{sid}/approve")  # first approval
        resp = authed_client.post(f"/drafts/{sid}/approve", follow_redirects=True)
        assert resp.status_code == 200
        assert b"already approved" in resp.data.lower()

    def test_post_approve_needs_clarification_shows_error(self, authed_client, conn):
        add_from_message(conn, "milk", "sms", "cara")  # ambiguous
        draft = authed_client.post("/api/draft").get_json()
        assert draft["status"] == "needs_clarification"
        sid = draft["session_id"]
        resp = authed_client.post(f"/drafts/{sid}/approve", follow_redirects=True)
        assert resp.status_code == 200
        assert b"unresolved" in resp.data.lower() or b"clarif" in resp.data.lower()

    def test_post_approve_nonexistent_session_shows_error(self, authed_client):
        resp = authed_client.post("/drafts/9999/approve", follow_redirects=True)
        # Route tries to redirect to draft detail, which 404s or shows error flash
        assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# GET /drafts/<id>/shop  /  POST /drafts/<id>/ordered
# ---------------------------------------------------------------------------

class TestUiDraftShop:
    def test_get_shop_requires_approved_draft(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = client.post("/api/draft").get_json()
        resp = client.get(f"/drafts/{draft['session_id']}/shop", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Approve this draft before opening the shopping handoff" in resp.data

    def test_get_shop_for_approved_draft_shows_instacart_link(self, authed_client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = authed_client.post("/api/draft").get_json()
        sid = draft["session_id"]
        authed_client.post(f"/drafts/{sid}/approve")
        resp = authed_client.get(f"/drafts/{sid}/shop")
        assert resp.status_code == 200
        assert b"Open Instacart search" in resp.data
        assert b"instacart.com/store/search_v3/term?term=bananas" in resp.data
        assert b"never submits the Instacart order for you" in resp.data

    def test_post_ordered_unauthenticated_redirects_to_login(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = client.post("/api/draft").get_json()
        resp = client.post(f"/drafts/{draft['session_id']}/ordered", follow_redirects=False)
        assert resp.status_code == 302
        assert "login" in resp.headers["Location"]

    def test_post_ordered_authenticated_moves_items_off_active_list(self, authed_client, conn):
        add_from_message(conn, "bananas, eggs", "discord", "vern")
        draft = authed_client.post("/api/draft").get_json()
        sid = draft["session_id"]
        authed_client.post(f"/drafts/{sid}/approve")
        resp = authed_client.post(f"/drafts/{sid}/ordered", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Draft marked ordered" in resp.data
        assert authed_client.get("/api/list").get_json() == []
        detail = authed_client.get(f"/api/draft/{sid}").get_json()
        assert detail["session"]["ordered_at"] is not None
        assert all(item["status"] == "ordered" for item in detail["items"])

    def test_post_ordered_second_time_is_safe(self, authed_client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = authed_client.post("/api/draft").get_json()
        sid = draft["session_id"]
        authed_client.post(f"/drafts/{sid}/approve")
        authed_client.post(f"/drafts/{sid}/ordered")
        resp = authed_client.post(f"/drafts/{sid}/ordered", follow_redirects=True)
        assert resp.status_code == 200
        assert b"already marked ordered" in resp.data.lower()


# ---------------------------------------------------------------------------
# Cart-fill prep groundwork
# ---------------------------------------------------------------------------

class TestUiCartFillPrep:
    def test_approved_draft_detail_shows_cart_fill_prep_panel(self, authed_client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = authed_client.post("/api/draft").get_json()
        sid = draft["session_id"]
        authed_client.post(f"/drafts/{sid}/approve")

        resp = authed_client.get(f"/drafts/{sid}")

        assert resp.status_code == 200
        assert b"Automatic cart-fill prep" in resp.data
        assert b"Prepare automatic cart fill" in resp.data

    def test_prepare_cart_fill_requires_login(self, client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = client.post("/api/draft").get_json()
        sid = draft["session_id"]
        client.post(f"/drafts/{sid}/approve")

        resp = client.post(f"/drafts/{sid}/cart-fill/prepare", follow_redirects=False)

        assert resp.status_code == 302
        assert "login" in resp.headers["Location"]

    def test_prepare_cart_fill_records_blocked_run_when_session_file_missing(self, authed_client, conn):
        add_from_message(conn, "bananas", "discord", "vern")
        draft = authed_client.post("/api/draft").get_json()
        sid = draft["session_id"]
        authed_client.post(f"/drafts/{sid}/approve")

        resp = authed_client.post(f"/drafts/{sid}/cart-fill/prepare", follow_redirects=True)

        assert resp.status_code == 200
        assert b"status-blocked" in resp.data.lower()
        payload = authed_client.get(f"/api/draft/{sid}/cart-fill").get_json()
        assert payload["latest_run"]["status"] == "blocked"

    def test_prepare_cart_fill_records_queued_run_when_session_file_exists(self, conn, tmp_path):
        app = create_app(
            conn=conn,
            trusted_sms=TRUSTED_SMS,
            trusted_discord=TRUSTED_DISCORD,
            browser_token=BROWSER_TOKEN,
            secret_key=SECRET_KEY,
        )
        app.config["TESTING"] = True
        session_file = tmp_path / "instacart-session.json"
        session_file.write_text("{}")
        app.config["INSTACART_SESSION_FILE"] = str(session_file)

        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["logged_in"] = True
            add_from_message(conn, "bananas", "discord", "vern")
            draft = c.post("/api/draft").get_json()
            sid = draft["session_id"]
            c.post(f"/drafts/{sid}/approve")

            resp = c.post(f"/drafts/{sid}/cart-fill/prepare", follow_redirects=True)
            payload = c.get(f"/api/draft/{sid}/cart-fill").get_json()

        assert resp.status_code == 200
        assert b"status-queued" in resp.data.lower()
        assert payload["latest_run"]["status"] == "queued"


# ---------------------------------------------------------------------------
# GET /login  /  POST /login  /  GET /logout
# ---------------------------------------------------------------------------

class TestUiLogin:
    def test_get_login_returns_200(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_get_login_shows_form(self, client):
        resp = client.get("/login")
        assert b"token" in resp.data.lower()

    def test_post_login_correct_token_redirects_home(self, client):
        resp = client.post("/login", data={"token": BROWSER_TOKEN},
                           follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/")

    def test_post_login_correct_token_sets_session(self, client):
        client.post("/login", data={"token": BROWSER_TOKEN})
        with client.session_transaction() as sess:
            assert sess.get("logged_in") is True

    def test_post_login_wrong_token_stays_on_login(self, client):
        resp = client.post("/login", data={"token": "wrongtoken"},
                           follow_redirects=True)
        assert b"Incorrect token" in resp.data

    def test_post_login_wrong_token_does_not_set_session(self, client):
        client.post("/login", data={"token": "wrongtoken"})
        with client.session_transaction() as sess:
            assert not sess.get("logged_in")

    def test_post_login_no_token_configured_shows_error(self, conn):
        """With no BROWSER_TOKEN configured, login is blocked."""
        app = create_app(
            conn=conn,
            trusted_sms=TRUSTED_SMS,
            trusted_discord=TRUSTED_DISCORD,
            browser_token="",  # no token configured
            secret_key=SECRET_KEY,
        )
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.post("/login", data={"token": "anything"},
                          follow_redirects=True)
            assert b"not configured" in resp.data.lower()

    def test_get_logout_clears_session(self, authed_client):
        with authed_client.session_transaction() as sess:
            assert sess.get("logged_in") is True
        authed_client.get("/logout")
        with authed_client.session_transaction() as sess:
            assert not sess.get("logged_in")

    def test_get_logout_redirects_to_home(self, authed_client):
        resp = authed_client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
