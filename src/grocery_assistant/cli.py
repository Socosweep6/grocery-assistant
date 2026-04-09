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

    return parser


COMMANDS = {
    "list": cmd_list,
    "flagged": cmd_flagged,
    "by-sender": cmd_by_sender,
    "by-channel": cmd_by_channel,
    "draft": cmd_draft,
    "resolve": cmd_resolve,
    "history": cmd_history,
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
