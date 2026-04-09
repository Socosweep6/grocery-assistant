"""
Local web application for Grocery Assistant.

Provides two intake routes that match real webhook shapes:
  POST /sms/webhook       -- Twilio inbound SMS (form data: From, Body, ...)
  POST /discord/event     -- Discord MESSAGE_CREATE-style event (JSON)

Provides an operator API (JSON) for local review and management:
  GET  /api/list                   -- all pending grocery items
  GET  /api/flagged                -- ambiguous items needing clarification
  GET  /api/by-sender/<sender>     -- items added by a specific sender
  GET  /api/by-channel/<channel>   -- items from sms or discord
  POST /api/draft                  -- create a new order draft
  POST /api/resolve                -- resolve an ambiguous item
  GET  /api/draft/<session_id>     -- fetch a specific draft/session

All routes are thin. Business logic lives in the service modules.

Usage (local development):
    python -m grocery_assistant.web

This starts on http://127.0.0.1:5000 by default.
Set GROCERY_DB_PATH env var to override the database file path.
"""

import os
import sqlite3
from pathlib import Path

from flask import Flask, request, jsonify, g

from .db import (
    get_connection,
    get_session,
    get_session_items,
    get_item_by_id,
    remove_item,
    insert_removal_log,
)
from .grocery_list import (
    format_list,
    get_list,
    get_flagged,
    get_by_sender,
    get_by_channel,
)
from .draft import create_draft, format_draft
from .clarification import promote_cleared_sessions
from .intake.sms_adapter import SmsAdapter
from .intake.discord_adapter import DiscordAdapter
from .identity import UntrustedSenderError, TRUSTED_SMS_SENDERS, TRUSTED_DISCORD_USERS
from .clarification import (
    list_ambiguous,
    resolve_item,
    ClarificationError,
)
from .twilio_sig import verify_signature as twilio_verify_signature


def _check_twilio_signature() -> bool:
    """
    Verify the Twilio request signature if validation is enabled.

    Enabled when TWILIO_AUTH_TOKEN and TWILIO_VALIDATE_SIGNATURE=1 are set.
    Returns True if valid (or validation is disabled). Returns False on failure.

    Set TWILIO_WEBHOOK_URL to your public-facing URL when running behind a proxy
    (e.g. ngrok), since Flask sees the internal URL, not the signed URL.
    """
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not auth_token or not os.environ.get("TWILIO_VALIDATE_SIGNATURE"):
        return True  # dev mode -- skip

    signature = request.headers.get("X-Twilio-Signature", "")
    url = os.environ.get("TWILIO_WEBHOOK_URL", request.url)
    return twilio_verify_signature(auth_token, url, request.form, signature)


def create_app(conn: sqlite3.Connection | None = None,
               trusted_sms: dict | None = None,
               trusted_discord: dict | None = None) -> Flask:
    """
    Flask application factory.

    Args:
        conn: SQLite connection to use for all requests. When None, the app
              opens its own connection using GROCERY_DB_PATH (or the default
              grocery.db file) at startup.
        trusted_sms: Phone-to-name mapping for SMS intake. None uses the
                     module-level default from identity.py.
        trusted_discord: User-ID-to-name mapping for Discord intake. None uses
                         the module-level default from identity.py.
    """
    app = Flask(__name__)

    _trusted_sms = trusted_sms if trusted_sms is not None else TRUSTED_SMS_SENDERS
    _trusted_discord = trusted_discord if trusted_discord is not None else TRUSTED_DISCORD_USERS

    # If a shared connection is provided (e.g. in tests), use it for all requests.
    # Otherwise open a per-request connection from the DB path.
    _shared_conn = conn

    def _get_conn() -> sqlite3.Connection:
        if _shared_conn is not None:
            return _shared_conn
        if "db" not in g:
            db_path_str = os.environ.get("GROCERY_DB_PATH", "")
            db_path = Path(db_path_str) if db_path_str else None
            from .db import DEFAULT_DB_PATH
            g.db = get_connection(db_path or DEFAULT_DB_PATH)
        return g.db

    @app.teardown_appcontext
    def close_db(exc: BaseException | None) -> None:
        db = g.pop("db", None)
        if db is not None and db is not _shared_conn:
            db.close()

    # ------------------------------------------------------------------
    # SMS intake
    # ------------------------------------------------------------------

    @app.route("/sms/webhook", methods=["POST"])
    def sms_webhook():
        """
        Twilio inbound SMS webhook endpoint.

        Expects form-encoded POST with at minimum:
          From  -- sender E.164 phone number
          Body  -- message text

        Returns JSON summary of what was added/merged/flagged.
        Returns 400 on missing fields, 403 on untrusted sender.
        """
        if not _check_twilio_signature():
            return jsonify({"error": "forbidden",
                            "detail": "Twilio signature verification failed."}), 403
        conn_ = _get_conn()
        adapter = SmsAdapter(conn_, trusted_senders=_trusted_sms)
        try:
            result = adapter.receive_webhook(request.form)
        except UntrustedSenderError as exc:
            return jsonify({"error": "untrusted_sender", "detail": str(exc)}), 403
        except ValueError as exc:
            return jsonify({"error": "bad_request", "detail": str(exc)}), 400
        return jsonify(result), 200

    # ------------------------------------------------------------------
    # Discord intake
    # ------------------------------------------------------------------

    @app.route("/discord/event", methods=["POST"])
    def discord_event():
        """
        Discord MESSAGE_CREATE-style event endpoint.

        Expects JSON body matching Discord's event structure:
          {
            "author": {"id": "<snowflake>"},
            "content": "<message text>"
          }

        No real Discord bot token is required. Send requests directly for
        local simulation or webhook bridge use.

        Returns JSON summary of what was added/merged/flagged.
        Returns 400 on missing fields, 403 on untrusted sender.
        """
        conn_ = _get_conn()
        if not request.is_json:
            return jsonify({"error": "bad_request",
                            "detail": "Content-Type must be application/json"}), 400

        event = request.get_json(force=True, silent=True) or {}
        adapter = DiscordAdapter(conn_, trusted_users=_trusted_discord)
        try:
            result = adapter.receive_event(event)
        except UntrustedSenderError as exc:
            return jsonify({"error": "untrusted_sender", "detail": str(exc)}), 403
        except ValueError as exc:
            return jsonify({"error": "bad_request", "detail": str(exc)}), 400
        return jsonify(result), 200

    # ------------------------------------------------------------------
    # Operator API
    # ------------------------------------------------------------------

    @app.route("/api/list", methods=["GET"])
    def api_list():
        """Return all pending grocery items as JSON."""
        conn_ = _get_conn()
        rows = get_list(conn_)
        return jsonify([dict(r) for r in rows]), 200

    @app.route("/api/flagged", methods=["GET"])
    def api_flagged():
        """Return items currently flagged as ambiguous."""
        conn_ = _get_conn()
        return jsonify(list_ambiguous(conn_)), 200

    @app.route("/api/by-sender/<sender>", methods=["GET"])
    def api_by_sender(sender: str):
        """Return pending items added by a specific sender."""
        conn_ = _get_conn()
        rows = get_by_sender(conn_, sender)
        return jsonify([dict(r) for r in rows]), 200

    @app.route("/api/by-channel/<channel>", methods=["GET"])
    def api_by_channel(channel: str):
        """Return pending items that arrived via a specific channel (sms or discord)."""
        conn_ = _get_conn()
        rows = get_by_channel(conn_, channel)
        return jsonify([dict(r) for r in rows]), 200

    @app.route("/api/draft", methods=["POST"])
    def api_create_draft():
        """
        Create a new order draft from all pending items.

        Returns the draft dict including session_id, status, items, and
        any ambiguous items that still need clarification.
        """
        conn_ = _get_conn()
        draft = create_draft(conn_)
        return jsonify(draft), 200

    @app.route("/api/draft/<int:session_id>", methods=["GET"])
    def api_get_draft(session_id: int):
        """Fetch a previously created cart session."""
        conn_ = _get_conn()
        session = get_session(conn_, session_id)
        if session is None:
            return jsonify({"error": "not_found",
                            "detail": f"Session {session_id} does not exist."}), 404
        items = get_session_items(conn_, session_id)
        return jsonify({
            "session": dict(session),
            "items": [dict(i) for i in items],
        }), 200

    @app.route("/api/item/<int:item_id>/remove", methods=["POST"])
    def api_remove_item(item_id: int):
        """
        Safely remove a pending grocery item.

        Sets the item's status to 'removed' and writes a removal_log entry.
        The row is preserved for auditability -- nothing is hard-deleted.

        Expects JSON body (all fields optional):
          {
            "removed_by": "<operator name>",   (default: "operator")
            "reason":     "<why it was removed>"
          }

        Returns 404 if the item does not exist.
        Returns 400 if the item is already removed.
        """
        conn_ = _get_conn()
        item = get_item_by_id(conn_, item_id)
        if item is None:
            return jsonify({"error": "not_found",
                            "detail": f"Item {item_id} does not exist."}), 404
        if item["status"] == "removed":
            return jsonify({"error": "bad_request",
                            "detail": f"Item {item_id} is already removed."}), 400

        body = {}
        if request.is_json:
            body = request.get_json(force=True, silent=True) or {}
        removed_by = (body.get("removed_by") or "operator").strip() or "operator"
        reason = (body.get("reason") or "").strip() or None

        insert_removal_log(conn_, item_id, item["name"], removed_by=removed_by, reason=reason)
        remove_item(conn_, item_id)
        promoted = promote_cleared_sessions(conn_)

        return jsonify({
            "item_id": item_id,
            "item_name": item["name"],
            "removed_by": removed_by,
            "reason": reason,
            "status": "removed",
            "promoted_sessions": promoted,
        }), 200

    @app.route("/api/resolve", methods=["POST"])
    def api_resolve():
        """
        Resolve an ambiguous grocery item.

        Expects JSON body:
          {
            "item_id":   <int>,
            "new_name":  "<refined item name>",
            "resolved_by": "<operator name>"  (optional, default: "operator")
          }

        Returns the resolution record and any sessions that were promoted
        from needs_clarification to awaiting_approval.

        Returns 400 if validation fails (item not found, still ambiguous, etc.).
        """
        conn_ = _get_conn()
        if not request.is_json:
            return jsonify({"error": "bad_request",
                            "detail": "Content-Type must be application/json"}), 400

        body = request.get_json(force=True, silent=True) or {}
        item_id = body.get("item_id")
        new_name = body.get("new_name", "").strip()
        resolved_by = body.get("resolved_by", "operator").strip() or "operator"

        if item_id is None:
            return jsonify({"error": "bad_request",
                            "detail": "item_id is required"}), 400
        if not new_name:
            return jsonify({"error": "bad_request",
                            "detail": "new_name is required"}), 400

        try:
            result = resolve_item(conn_, int(item_id), new_name, resolved_by)
        except ClarificationError as exc:
            return jsonify({"error": "clarification_error", "detail": str(exc)}), 400

        return jsonify(result), 200

    return app


if __name__ == "__main__":
    import sys
    from .db import DEFAULT_DB_PATH, SCHEMA_PATH, get_connection

    db_path_str = os.environ.get("GROCERY_DB_PATH", "")
    db_path = Path(db_path_str) if db_path_str else DEFAULT_DB_PATH

    if not db_path.exists() or str(db_path) == ":memory:":
        schema = SCHEMA_PATH.read_text()
        _conn = get_connection(db_path)
        _conn.executescript(schema)
        print(f"Initialized new database at {db_path}", file=sys.stderr)
    else:
        _conn = get_connection(db_path)

    port = int(os.environ.get("GROCERY_PORT", 5000))
    print(f"Starting Grocery Assistant on http://127.0.0.1:{port}", file=sys.stderr)
    print(f"Database: {db_path}", file=sys.stderr)
    app = create_app(conn=_conn)
    app.run(host="127.0.0.1", port=port, debug=True)
