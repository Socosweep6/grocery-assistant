"""
Discord intake adapter for Discord message event payloads.

Thin wrapper around IntakeAdapter. Business logic stays in grocery_list.py.
This module only handles Discord event parsing and sender identity resolution.

Discord message event structure (relevant subset):
  {
    "author": {
      "id":       "123456789012345678",   # snowflake user ID (use this, not username)
      "username": "vern"                  # display name only, not used for identity
    },
    "content":    "bananas, eggs, oat milk",
    "channel_id": "987654321098765432"
  }

Sender identity is resolved from author.id against TRUSTED_DISCORD_USERS.
Never trust author.username for identity - it can be changed by the user.

Usage (from a Discord gateway or webhook handler):
    adapter = DiscordAdapter(conn, trusted_users={"123456789": "vern"})
    result = adapter.receive_event(event)

In tests, pass a plain dict with the structure above.
No Discord bot token is required to instantiate or test this class.
"""

import sqlite3
from typing import Optional

from .base import IntakeAdapter
from ..identity import resolve_discord_sender, UntrustedSenderError


class DiscordAdapter(IntakeAdapter):
    """
    Discord intake adapter with trusted user ID enforcement.

    Parses Discord message event payloads and routes them to the grocery list service.
    Rejects messages from unrecognized user IDs before they reach the DB.
    Identity is resolved from author.id (snowflake), not author.username.
    """

    def __init__(self, conn: sqlite3.Connection,
                 trusted_users: Optional[dict[str, str]] = None):
        """
        Args:
            conn: SQLite connection.
            trusted_users: user_id-to-name mapping for this instance.
                           None uses the module-level TRUSTED_DISCORD_USERS default.
                           Pass an explicit dict in tests.
        """
        super().__init__(conn)
        self._trusted = trusted_users

    @property
    def channel_name(self) -> str:
        return "discord"

    def receive_event(self, event: dict) -> dict:
        """
        Process a Discord message event payload.

        Args:
            event: dict with 'author' (containing 'id') and 'content'.
                   Matches Discord gateway MESSAGE_CREATE event structure.

        Returns:
            Summary dict from add_from_message:
            {"event_id": int, "added": [...], "merged": [...], "flagged": [...]}

        Raises:
            UntrustedSenderError: if the author.id is not in the trusted registry.
            ValueError: if author.id or content is missing/empty.
        """
        author = event.get("author") or {}
        user_id = str(author.get("id") or "").strip()
        content = (event.get("content") or "").strip()

        if not user_id:
            raise ValueError("Discord event missing 'author.id' field.")
        if not content:
            raise ValueError("Discord event missing or empty 'content' field.")

        sender = resolve_discord_sender(user_id, self._trusted)
        return self.process(raw_text=content, sender=sender)

    def receive(self) -> list[dict]:
        raise NotImplementedError(
            "Discord polling is not implemented. "
            "Use receive_event() for Discord message event ingestion."
        )
