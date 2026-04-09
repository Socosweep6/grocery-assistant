"""
Discord intake adapter stub.

Phase 1: accepts messages directly (no real Discord API).
Phase 2: wire up discord.py bot or webhook listener.
"""

import sqlite3
from .base import IntakeAdapter


class DiscordIntake(IntakeAdapter):
    """Stub Discord intake. Phase 1 accepts messages directly via process()."""

    @property
    def channel_name(self) -> str:
        return "discord"

    def receive(self) -> list[dict]:
        # Not implemented in phase 1.
        # Phase 2: poll Discord channel or handle webhook events here.
        raise NotImplementedError(
            "Discord receive() is not implemented in phase 1. "
            "Use process() to inject messages directly."
        )
