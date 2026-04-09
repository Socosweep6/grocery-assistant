"""
Base intake adapter interface.

All intake sources (Discord, SMS) implement this interface.
The service layer calls process() and never touches source-specific details.
"""

import sqlite3
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Optional

from ..grocery_list import add_from_message


class IntakeAdapter(ABC):
    """Abstract base for intake adapters."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Identifier for this channel (e.g. 'discord', 'sms')."""
        ...

    def process(self, raw_text: str, sender: str,
                 timestamp: Optional[datetime] = None) -> dict:
        """
        Accept a raw message and persist it to the grocery list.
        Returns summary from add_from_message.
        """
        return add_from_message(
            self.conn,
            raw_text=raw_text,
            source_channel=self.channel_name,
            sender=sender,
            timestamp=timestamp,
        )

    def receive(self) -> list[dict]:
        """
        Fetch new messages from the source.
        Returns list of {raw_text, sender, timestamp} dicts.
        Override in polling adapters. Webhook adapters use their own entry point.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement polling. "
            "Use the adapter-specific webhook/event method instead."
        )
