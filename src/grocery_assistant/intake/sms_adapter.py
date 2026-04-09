"""
SMS intake adapter for Twilio inbound webhook payloads.

Thin wrapper around IntakeAdapter. Business logic stays in grocery_list.py.
This module only handles Twilio payload parsing and sender identity resolution.

Twilio inbound SMS webhook delivers a POST with form fields including:
  From        - sender's E.164 phone number (e.g. '+12065550001')
  Body        - message text
  MessageSid  - unique message ID
  To          - your Twilio number

Usage (from a web framework route handler):
    adapter = SmsAdapter(conn, trusted_senders={"+12065550001": "cara"})
    result = adapter.receive_webhook(request.form)

In tests, pass a plain dict with at minimum {'From': ..., 'Body': ...}.
No Twilio credentials are required to instantiate or test this class.
"""

import sqlite3
from typing import Optional

from .base import IntakeAdapter
from ..identity import resolve_sms_sender, UntrustedSenderError


class SmsAdapter(IntakeAdapter):
    """
    SMS intake adapter with trusted sender enforcement.

    Parses Twilio webhook payloads and routes them to the grocery list service.
    Rejects messages from unrecognized phone numbers before they reach the DB.
    """

    def __init__(self, conn: sqlite3.Connection,
                 trusted_senders: Optional[dict[str, str]] = None):
        """
        Args:
            conn: SQLite connection.
            trusted_senders: phone-to-name mapping for this instance.
                             None uses the module-level TRUSTED_SMS_SENDERS default.
                             Pass an explicit dict in tests.
        """
        super().__init__(conn)
        self._trusted = trusted_senders

    @property
    def channel_name(self) -> str:
        return "sms"

    def receive_webhook(self, payload: dict) -> dict:
        """
        Process a Twilio inbound SMS webhook payload.

        Args:
            payload: dict with at minimum 'From' (E.164) and 'Body' (message text).
                     Matches Twilio's webhook POST form fields.

        Returns:
            Summary dict from add_from_message:
            {"event_id": int, "added": [...], "merged": [...], "flagged": [...]}

        Raises:
            UntrustedSenderError: if the From number is not in the trusted registry.
            ValueError: if From or Body is missing/empty.
        """
        from_number = (payload.get("From") or "").strip()
        body = (payload.get("Body") or "").strip()

        if not from_number:
            raise ValueError("Twilio webhook payload missing 'From' field.")
        if not body:
            raise ValueError("Twilio webhook payload missing or empty 'Body' field.")

        sender = resolve_sms_sender(from_number, self._trusted)
        return self.process(raw_text=body, sender=sender)

    def receive(self) -> list[dict]:
        raise NotImplementedError(
            "SMS polling is not implemented. "
            "Use receive_webhook() for Twilio webhook ingestion."
        )
