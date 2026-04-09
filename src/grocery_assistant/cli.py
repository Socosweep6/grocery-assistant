"""
Operator CLI for Grocery Assistant.

Provides local commands for reviewing the grocery list, resolving flagged items,
and generating order drafts without running the web server.

Usage:
    python -m grocery_assistant.cli <command> [options]

Commands:
    list                        Show full grocery list (grouped by category)
    flagged                     Show ambiguous items that need clarification
    by-sender <name>            Show items added by a specific sender (e.g. cara, vern)
    by-channel <channel>        Show items from a specific channel (sms or discord)
    draft                       Create a new order draft from pending items
    resolve <item_id> <name>    Resolve an ambiguous item with a refined name
    history <item_id>           Show clarification history for an item
    inspect <item_id>           Show full details and source events for an item
    remove <item_id>            Safely remove an item (marks removed, preserves audit trail)
    doctor                      Check setup readiness (Twilio, Discord, DB, trusted senders)

All commands use the default database (grocery.db) unless GROCERY_DB_PATH is set.
"""

import argparse
import json
import os
import sys
from pathlib import Path


def _get_conn():
    from .db import get_connection, DEFAULT_DB_PATH, SCHEMA_PATH
    db_path_str = os.environ.get("GROCERY_DB_PATH", "")
    db_path = Path(db_path_str) if db_path_str else DEFAULT_DB_PATH

    if not db_path.exists():
        schema = SCHEMA_PATH.read_text()
        conn = get_connection(db_path)
        conn.executescript(schema)
        print(f"[info] Initialized new database at {db_path}", file=sys.stderr)
        return conn

    return get_connection(db_path)


def cmd_list(args: argparse.Namespace) -> None:
    from .grocery_list import format_list
    conn = _get_conn()
    print(format_list(conn))


def cmd_flagged(args: argparse.Namespace) -> None:
    from .clarification import list_ambiguous
    conn = _get_conn()
    items = list_ambiguous(conn)
    if not items:
        print("No flagged items. List is ready for draft.")
        return
    print(f"Flagged items ({len(items)}):")
    for item in items:
        print(f"  [{item['id']:4}] {item['name']!r:30}  canonical: {item['canonical']}")
    print()
    print("Resolve with: python -m grocery_assistant.cli resolve <item_id> <refined name>")


def cmd_by_sender(args: argparse.Namespace) -> None:
    from .grocery_list import get_by_sender
    conn = _get_conn()
    rows = get_by_sender(conn, args.sender)
    if not rows:
        print(f"No pending items from sender '{args.sender}'.")
        return
    print(f"Items added by '{args.sender}':")
    for row in rows:
        flag = " [?]" if row["ambiguous"] else ""
        print(f"  [{row['id']:4}] {row['name']}{flag}")


def cmd_by_channel(args: argparse.Namespace) -> None:
    from .grocery_list import get_by_channel
    conn = _get_conn()
    rows = get_by_channel(conn, args.channel)
    if not rows:
        print(f"No pending items from channel '{args.channel}'.")
        return
    print(f"Items from '{args.channel}':")
    for row in rows:
        flag = " [?]" if row["ambiguous"] else ""
        print(f"  [{row['id']:4}] {row['name']}{flag}")


def cmd_draft(args: argparse.Namespace) -> None:
    from .draft import create_draft, format_draft
    conn = _get_conn()
    draft = create_draft(conn)
    print(format_draft(draft))
    print()
    print(f"Session ID: {draft['session_id']}")
    if args.json:
        print()
        print(json.dumps(draft, indent=2))


def cmd_resolve(args: argparse.Namespace) -> None:
    from .clarification import resolve_item, ClarificationError
    conn = _get_conn()
    try:
        result = resolve_item(conn, args.item_id, args.new_name, resolved_by="operator")
    except ClarificationError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Resolved item {result['item_id']}:")
    print(f"  Before: {result['original_name']!r}")
    print(f"  After:  {result['resolved_name']!r}")
    if result["promoted_sessions"]:
        print(f"  Sessions promoted to awaiting_approval: {result['promoted_sessions']}")
    else:
        print("  No sessions promoted (ambiguous items may still remain).")


def cmd_inspect(args: argparse.Namespace) -> None:
    from .db import get_item_by_id, get_source_events_for_item, get_clarification_log, get_removal_log
    conn = _get_conn()
    item = get_item_by_id(conn, args.item_id)
    if item is None:
        print(f"[error] Item {args.item_id} does not exist.", file=sys.stderr)
        sys.exit(1)

    ambig_label = "yes (needs clarification)" if item["ambiguous"] else "no"
    qty_str = ""
    if item["quantity"]:
        qty_str = f" {item['quantity']}"
        if item["unit"]:
            qty_str += f" {item['unit']}"

    print(f"Item #{item['id']}: {item['name']}{qty_str}")
    print(f"  Canonical  : {item['canonical']}")
    print(f"  Category   : {item['category']}")
    print(f"  Status     : {item['status']}")
    print(f"  Ambiguous  : {ambig_label}")
    print(f"  Created at : {item['created_at']}")

    sources = get_source_events_for_item(conn, args.item_id)
    print()
    if sources:
        print(f"Source events ({len(sources)}):")
        for ev in sources:
            print(f"  [{ev['id']}] {ev['timestamp']}  via {ev['source_channel']} from {ev['sender']}")
            print(f"       {ev['raw_text']!r}")
    else:
        print("Source events: (none recorded)")

    clog = get_clarification_log(conn, args.item_id)
    print()
    if clog:
        print(f"Clarification history ({len(clog)}):")
        for entry in clog:
            print(f"  [{entry['timestamp']}] by {entry['resolved_by']}")
            print(f"    {entry['original_name']!r} -> {entry['resolved_name']!r}")
    else:
        print("Clarification history: (none)")

    rlog = get_removal_log(conn, args.item_id)
    if rlog:
        print()
        print(f"Removal log ({len(rlog)}):")
        for entry in rlog:
            reason_str = f" -- {entry['reason']}" if entry["reason"] else ""
            print(f"  [{entry['timestamp']}] by {entry['removed_by']}{reason_str}")


def cmd_remove(args: argparse.Namespace) -> None:
    from .db import get_item_by_id, remove_item, insert_removal_log
    from .clarification import promote_cleared_sessions
    conn = _get_conn()
    item = get_item_by_id(conn, args.item_id)
    if item is None:
        print(f"[error] Item {args.item_id} does not exist.", file=sys.stderr)
        sys.exit(1)
    if item["status"] == "removed":
        print(f"[error] Item {args.item_id} ('{item['name']}') is already removed.", file=sys.stderr)
        sys.exit(1)

    reason = args.reason or None
    insert_removal_log(conn, item["id"], item["name"], removed_by="operator", reason=reason)
    remove_item(conn, item["id"])

    promoted = promote_cleared_sessions(conn)

    print(f"Removed item #{item['id']} '{item['name']}'.")
    if reason:
        print(f"  Reason: {reason}")
    print("  Audit entry recorded. Item will no longer appear in the list.")
    print("  To re-add it, send a new message with the correct item name.")
    if promoted:
        print(f"  Sessions promoted to awaiting_approval: {promoted}")


def cmd_prefs(args: argparse.Namespace) -> None:
    from .preferences import (
        list_preferences,
        set_preference,
        delete_preference,
        format_preference_note,
    )
    conn = _get_conn()

    if args.prefs_cmd == "list":
        prefs = list_preferences(conn)
        if not prefs:
            print("No preferences set. Use 'prefs set' to add one.")
            return
        print(f"Preferences ({len(prefs)}):")
        for p in prefs:
            note = format_preference_note(p)
            print(f"  {p['canonical']:20} {note}")

    elif args.prefs_cmd == "set":
        pref = set_preference(
            conn,
            canonical=args.canonical,
            preferred_form=args.prefer or None,
            substitutions_ok=args.subs_ok,
            note=args.note or None,
        )
        print(f"Preference set for '{pref['canonical']}':")
        print(f"  {format_preference_note(pref)}")

    elif args.prefs_cmd == "remove":
        deleted = delete_preference(conn, args.canonical)
        if deleted:
            print(f"Removed preference for '{args.canonical}'.")
        else:
            print(f"No preference found for '{args.canonical}'.")

    else:
        print("Unknown prefs subcommand.", file=sys.stderr)
        sys.exit(1)


def cmd_doctor(args: argparse.Namespace) -> None:
    """Check setup readiness: Twilio, Discord, DB, trusted senders, importability."""
    import importlib
    from pathlib import Path
    from .config import load_env_config, get_readiness
    from .identity import TRUSTED_SMS_SENDERS, TRUSTED_DISCORD_USERS
    from .db import DEFAULT_DB_PATH

    cfg = load_env_config()

    # --- importability checks ---
    import_checks = []
    for mod in ("grocery_assistant", "flask"):
        try:
            importlib.import_module(mod)
            import_checks.append(("ok", f"{mod}: importable"))
        except ImportError as exc:
            import_checks.append(("miss", f"{mod}: import failed -- {exc}"))

    # --- DB check ---
    db_path_str = cfg.db_path
    db_path = Path(db_path_str) if db_path_str else DEFAULT_DB_PATH
    if db_path.exists():
        size_kb = db_path.stat().st_size // 1024
        db_check = ("ok", f"Database: {db_path} ({size_kb} KB)")
    else:
        db_check = ("warn", f"Database: {db_path} -- not found, will be created on first use")

    # --- env / identity checks ---
    result = get_readiness(cfg, TRUSTED_SMS_SENDERS, TRUSTED_DISCORD_USERS)

    # --- print report ---
    SYMBOLS = {"ok": "[OK]  ", "warn": "[WARN]", "miss": "[MISS]"}

    print("Grocery Assistant -- Setup Check")
    print("=" * 36)
    print()

    for status, label in import_checks:
        print(f"  {SYMBOLS[status]}  {label}")

    status, label = db_check
    print(f"  {SYMBOLS[status]}  {label}")

    for check in result["checks"]:
        sym = SYMBOLS[check["status"]]
        detail = f"  ({check['detail']})" if check["detail"] else ""
        print(f"  {sym}  {check['label']}{detail}")

    print()
    print("Modes:")

    modes = result["modes"]

    local = modes["local_simulation"]
    print(f"  Local simulation :   {'READY' if local['ready'] else 'NOT READY'}")

    twilio = modes["twilio_live"]
    if twilio["ready"]:
        print("  Twilio live      :   READY")
    else:
        missing = ", ".join(twilio["missing"])
        print(f"  Twilio live      :   BLOCKED  (missing: {missing})")

    discord = modes["discord_live"]
    if discord["ready"]:
        print("  Discord live     :   READY")
    else:
        missing = ", ".join(discord["missing"])
        print(f"  Discord live     :   BLOCKED  (missing: {missing})")

    print()

    any_blocked = not twilio["ready"] or not discord["ready"]
    if any_blocked:
        print("To go live:")
        print("  1. Copy env.example to .env and fill in real values")
        print("  2. Edit src/grocery_assistant/identity.py with real phone numbers / Discord user IDs")
        print("  3. source .env  (or export vars in your shell)")
        print("  4. python3 -m grocery_assistant.cli doctor")
    else:
        print("Everything looks configured. Run the web server and test a real webhook.")


def cmd_history(args: argparse.Namespace) -> None:
    from .clarification import get_resolution_history
    conn = _get_conn()
    history = get_resolution_history(conn, args.item_id)
    if not history:
        print(f"No clarification history for item {args.item_id}.")
        return
    print(f"Clarification history for item {args.item_id}:")
    for entry in history:
        print(f"  [{entry['timestamp']}] by {entry['resolved_by']}")
        print(f"    {entry['original_name']!r} -> {entry['resolved_name']!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m grocery_assistant.cli",
        description="Grocery Assistant operator CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    sub.add_parser("list", help="Show full grocery list grouped by category")

    # flagged
    sub.add_parser("flagged", help="Show ambiguous items that need clarification")

    # by-sender
    p_sender = sub.add_parser("by-sender", help="Show items added by a specific sender")
    p_sender.add_argument("sender", help="Sender name (e.g. cara, vern)")

    # by-channel
    p_channel = sub.add_parser("by-channel", help="Show items from a specific channel")
    p_channel.add_argument("channel", help="Channel name: sms or discord")

    # draft
    p_draft = sub.add_parser("draft", help="Create a new order draft from pending items")
    p_draft.add_argument("--json", action="store_true", help="Also print JSON output")

    # resolve
    p_resolve = sub.add_parser("resolve", help="Resolve an ambiguous item")
    p_resolve.add_argument("item_id", type=int, help="Item ID from 'flagged' output")
    p_resolve.add_argument("new_name", help="Refined item name (e.g. 'oat milk')")

    # history
    p_history = sub.add_parser("history", help="Show clarification history for an item")
    p_history.add_argument("item_id", type=int, help="Item ID")

    # inspect
    p_inspect = sub.add_parser("inspect", help="Show full details and source events for an item")
    p_inspect.add_argument("item_id", type=int, help="Item ID")

    # remove
    p_remove = sub.add_parser("remove", help="Safely remove an item (marks removed, preserves audit trail)")
    p_remove.add_argument("item_id", type=int, help="Item ID")
    p_remove.add_argument("--reason", default="", help="Optional reason for removal")

    # prefs
    p_prefs = sub.add_parser("prefs", help="Manage household item preferences")
    prefs_sub = p_prefs.add_subparsers(dest="prefs_cmd", required=True)

    prefs_sub.add_parser("list", help="List all preference rules")

    p_prefs_set = prefs_sub.add_parser("set", help="Set a preference rule for a canonical item")
    p_prefs_set.add_argument("canonical", help="Canonical item name (e.g. milk)")
    p_prefs_set.add_argument("--prefer", default="", metavar="FORM",
                              help="Preferred form (e.g. 'oat milk')")
    p_prefs_set.add_argument("--subs-ok", action="store_true",
                              help="Allow substitutions for this item")
    p_prefs_set.add_argument("--note", default="", metavar="TEXT",
                              help="Optional free-text note")

    p_prefs_remove = prefs_sub.add_parser("remove", help="Delete a preference rule")
    p_prefs_remove.add_argument("canonical", help="Canonical item name to remove")

    # doctor
    sub.add_parser(
        "doctor",
        help="Check setup readiness (Twilio, Discord, DB, trusted senders)",
    )

    return parser


COMMANDS = {
    "list": cmd_list,
    "flagged": cmd_flagged,
    "by-sender": cmd_by_sender,
    "by-channel": cmd_by_channel,
    "draft": cmd_draft,
    "resolve": cmd_resolve,
    "history": cmd_history,
    "inspect": cmd_inspect,
    "remove": cmd_remove,
    "prefs": cmd_prefs,
    "doctor": cmd_doctor,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    fn = COMMANDS.get(args.command)
    if fn is None:
        parser.print_help()
        sys.exit(1)
    fn(args)


if __name__ == "__main__":
    main()
