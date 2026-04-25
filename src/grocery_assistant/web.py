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
  GET  /api/preferences            -- list all preference rules
  POST /api/preferences            -- set/update a preference rule
  DELETE /api/preferences/<name>   -- delete a preference rule

All routes are thin. Business logic lives in the service modules.

Twilio Webhook Setup:
  1. Buy/provision a number in twilio.com/console
  2. Add the phone number to TRUSTED_SMS_SENDERS in identity.py
  3. Set TWILIO_AUTH_TOKEN in your environment
  4. Set TWILIO_VALIDATE_SIGNATURE=1 in your environment
  5. Set TWILIO_WEBHOOK_URL to your public ngrok/tunnel URL
  6. Point the Twilio number's inbound SMS webhook to: https://your-url/sms/webhook

Usage (local development):
    python -m grocery_assistant.web

This starts on http://127.0.0.1:5000 by default.
Set GROCERY_DB_PATH env var to override the database file path.
"""

import os
import sqlite3
from pathlib import Path

from flask import (
    Flask, request, jsonify, g, Response,
    render_template, redirect, url_for, session, flash, abort,
)

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
from .approval import submit_approval, ApprovalError
from .shopping import build_shopping_handoff, complete_shopping_handoff, ShoppingHandoffError
from .cart_fill import get_cart_fill_status, prepare_cart_fill_run, CartFillError
from .preferences import (
    list_preferences,
    set_preference,
    get_preference,
    delete_preference,
)


def twiml_response(text: str) -> Response:
    """Return a Flask Response with TwiML XML body and text/xml content type."""
    xml = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Message>{text}</Message></Response>"
    return Response(xml, status=200, mimetype="text/xml")


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
               trusted_discord: dict | None = None,
               browser_token: str | None = None,
               secret_key: bytes | str | None = None) -> Flask:
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

    _browser_token = (
        browser_token if browser_token is not None
        else os.environ.get("BROWSER_TOKEN", "")
    )
    _secret_key = (
        secret_key if secret_key is not None
        else (os.environ.get("FLASK_SECRET_KEY", "").encode() or os.urandom(24))
    )
    app.secret_key = _secret_key
    app.config["BROWSER_TOKEN"] = _browser_token
    app.config["INSTACART_SESSION_FILE"] = os.environ.get("INSTACART_SESSION_FILE", "").strip()

    def _logged_in() -> bool:
        return session.get("logged_in") is True

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
        # Twilio expects TwiML XML, not JSON
        added = result.get("added", [])
        flagged = result.get("flagged", [])
        if flagged:
            flag_names = ", ".join(f["item"] for f in flagged)
            msg = f"Got it - added to your list. Note: {flag_names} needs clarification."
        elif added:
            msg = "Got it - items added to your list."
        else:
            msg = "Got it - already on your list."
        return twiml_response(msg)

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

    # ------------------------------------------------------------------
    # Preferences API
    # ------------------------------------------------------------------

    @app.route("/api/preferences", methods=["GET"])
    def api_preferences_list():
        """Return all preference rules as JSON."""
        conn_ = _get_conn()
        return jsonify(list_preferences(conn_)), 200

    @app.route("/api/preferences", methods=["POST"])
    def api_preferences_set():
        """
        Set or update a preference rule.

        Expects JSON body:
          {
            "canonical":       "<canonical item name>",  (required)
            "preferred_form":  "<preferred form>",       (optional)
            "substitutions_ok": true/false,              (optional, default false)
            "note":            "<free-text note>"        (optional)
          }
        """
        conn_ = _get_conn()
        if not request.is_json:
            return jsonify({"error": "bad_request",
                            "detail": "Content-Type must be application/json"}), 400

        body = request.get_json(force=True, silent=True) or {}
        canonical = (body.get("canonical") or "").strip()
        if not canonical:
            return jsonify({"error": "bad_request",
                            "detail": "canonical is required"}), 400

        pref = set_preference(
            conn_,
            canonical=canonical,
            preferred_form=(body.get("preferred_form") or "").strip() or None,
            substitutions_ok=bool(body.get("substitutions_ok", False)),
            note=(body.get("note") or "").strip() or None,
        )
        return jsonify(pref), 200

    @app.route("/api/preferences/<canonical>", methods=["DELETE"])
    def api_preferences_delete(canonical: str):
        """Delete a preference rule by canonical name."""
        conn_ = _get_conn()
        deleted = delete_preference(conn_, canonical)
        if not deleted:
            return jsonify({"error": "not_found",
                            "detail": f"No preference for '{canonical}'."}), 404
        return jsonify({"deleted": True, "canonical": canonical}), 200

    # ------------------------------------------------------------------
    # Browser UI routes
    # ------------------------------------------------------------------

    @app.route("/", methods=["GET"])
    def index():
        conn_ = _get_conn()
        items = get_list(conn_)
        flagged = list_ambiguous(conn_)
        return render_template("index.html",
                               item_count=len(items),
                               flagged_count=len(flagged))

    @app.route("/list", methods=["GET"])
    def ui_list():
        conn_ = _get_conn()
        rows = get_list(conn_)
        by_category: dict[str, list] = {}
        for row in rows:
            cat = row["category"] or "other"
            by_category.setdefault(cat, []).append(dict(row))
        return render_template("list.html",
                               by_category=by_category,
                               item_count=len(rows))

    @app.route("/flagged", methods=["GET"])
    def ui_flagged():
        conn_ = _get_conn()
        items = list_ambiguous(conn_)
        return render_template("flagged.html", items=items)

    @app.route("/drafts/new", methods=["GET"])
    def ui_draft_new():
        conn_ = _get_conn()
        rows = get_list(conn_)
        flagged = list_ambiguous(conn_)
        items = [dict(r) for r in rows]
        return render_template("drafts_new.html", items=items, flagged=flagged)

    @app.route("/drafts/new", methods=["POST"])
    def ui_draft_create():
        if not _logged_in():
            flash("Login required to create a draft.", "error")
            return redirect(url_for("login"))
        conn_ = _get_conn()
        draft = create_draft(conn_)
        return redirect(url_for("ui_draft_detail", session_id=draft["session_id"]))

    @app.route("/drafts/<int:session_id>", methods=["GET"])
    def ui_draft_detail(session_id: int):
        conn_ = _get_conn()
        sess = get_session(conn_, session_id)
        if sess is None:
            abort(404)
        items = [dict(i) for i in get_session_items(conn_, session_id)]
        cart_fill = get_cart_fill_status(conn_, session_id, include_history=True)
        return render_template("draft.html", sess=dict(sess), items=items, cart_fill=cart_fill)

    @app.route("/drafts/<int:session_id>/approve", methods=["POST"])
    def ui_draft_approve(session_id: int):
        if not _logged_in():
            flash("Login required to approve a draft.", "error")
            return redirect(url_for("login"))
        conn_ = _get_conn()
        try:
            submit_approval(conn_, session_id, approver="vern", phrase="approve order")
            flash("Order approved.", "success")
        except ApprovalError as exc:
            flash(str(exc), "error")
        return redirect(url_for("ui_draft_detail", session_id=session_id))

    @app.route("/api/draft/<int:session_id>/cart-fill", methods=["GET"])
    def api_get_cart_fill_status(session_id: int):
        conn_ = _get_conn()
        try:
            return jsonify(get_cart_fill_status(conn_, session_id, include_history=True)), 200
        except CartFillError as exc:
            return jsonify({"error": "cart_fill_error", "detail": str(exc)}), 404

    @app.route("/drafts/<int:session_id>/cart-fill/prepare", methods=["POST"])
    def ui_prepare_cart_fill(session_id: int):
        if not _logged_in():
            flash("Login required to prepare automatic cart fill.", "error")
            return redirect(url_for("login"))
        conn_ = _get_conn()
        try:
            result = prepare_cart_fill_run(
                conn_,
                session_id,
                requested_by="vern",
                session_path=app.config.get("INSTACART_SESSION_FILE") or None,
            )
            latest = result.get("latest_run") or {}
            flash(
                f"Cart-fill prep recorded with status '{latest.get('status', 'unknown')}'. {latest.get('status_detail', '')}",
                "success" if latest.get("status") == "queued" else "warning",
            )
        except CartFillError as exc:
            flash(str(exc), "error")
        return redirect(url_for("ui_draft_detail", session_id=session_id))

    @app.route("/drafts/<int:session_id>/shop", methods=["GET"])
    def ui_draft_shop(session_id: int):
        conn_ = _get_conn()
        sess = get_session(conn_, session_id)
        if sess is None:
            abort(404)
        try:
            handoff = build_shopping_handoff(conn_, session_id)
        except ShoppingHandoffError as exc:
            flash(str(exc), "error")
            return redirect(url_for("ui_draft_detail", session_id=session_id))
        return render_template("shop.html", handoff=handoff)

    @app.route("/drafts/<int:session_id>/ordered", methods=["POST"])
    def ui_draft_mark_ordered(session_id: int):
        if not _logged_in():
            flash("Login required to mark a draft ordered.", "error")
            return redirect(url_for("login"))
        conn_ = _get_conn()
        try:
            result = complete_shopping_handoff(conn_, session_id, ordered_by="vern")
            if result["already_ordered"]:
                flash("Draft already marked ordered.", "success")
            else:
                flash(
                    f"Draft marked ordered. {result['updated_items']} items moved off the active grocery list.",
                    "success",
                )
        except ShoppingHandoffError as exc:
            flash(str(exc), "error")
            return redirect(url_for("ui_draft_detail", session_id=session_id))
        return redirect(url_for("ui_draft_shop", session_id=session_id))

    @app.route("/login", methods=["GET"])
    def login():
        return render_template("login.html")

    @app.route("/login", methods=["POST"])
    def login_post():
        token = request.form.get("token", "").strip()
        bt = app.config.get("BROWSER_TOKEN", "")
        if not bt:
            flash("Browser access is not configured (BROWSER_TOKEN not set).", "error")
            return redirect(url_for("login"))
        if token == bt:
            session["logged_in"] = True
            return redirect(url_for("index"))
        flash("Incorrect token.", "error")
        return redirect(url_for("login"))

    @app.route("/logout", methods=["GET"])
    def logout():
        session.clear()
        flash("Logged out.", "success")
        return redirect(url_for("index"))

    return app


if __name__ == "__main__":
    import sys
    from .db import DEFAULT_DB_PATH, SCHEMA_PATH, get_connection
    from .config import load_env_config, get_partial_config_risks
    from .identity import TRUSTED_SMS_SENDERS, TRUSTED_DISCORD_USERS

    db_path_str = os.environ.get("GROCERY_DB_PATH", "")
    db_path = Path(db_path_str) if db_path_str else DEFAULT_DB_PATH

    if not db_path.exists() or str(db_path) == ":memory:":
        schema = SCHEMA_PATH.read_text()
        init_conn = get_connection(db_path)
        init_conn.executescript(schema)
        init_conn.close()
        print(f"Initialized new database at {db_path}", file=sys.stderr)

    # Warn on risky partial configurations before starting.
    _cfg = load_env_config()
    _risks = get_partial_config_risks(_cfg, TRUSTED_SMS_SENDERS, TRUSTED_DISCORD_USERS)
    if _risks:
        print("[WARNING] Risky configuration detected:", file=sys.stderr)
        for _r in _risks:
            print(f"  [RISK]  {_r['label']}", file=sys.stderr)
            print(f"          {_r['detail']}", file=sys.stderr)
        print("  Run 'python3 -m grocery_assistant.cli doctor' for details.", file=sys.stderr)
        print(file=sys.stderr)

    port = int(os.environ.get("GROCERY_PORT", 5000))
    debug = os.environ.get("GROCERY_DEBUG", "").strip() == "1"
    print(f"Starting Grocery Assistant on http://127.0.0.1:{port}", file=sys.stderr)
    print(f"Database: {db_path}", file=sys.stderr)
    app = create_app()
    app.run(host="127.0.0.1", port=port, debug=debug, use_reloader=debug)
