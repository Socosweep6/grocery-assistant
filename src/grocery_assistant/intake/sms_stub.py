"""
SMS intake adapter stub.

Phase 1: accepts messages directly (no real SMS API).
Phase 2: wire up Twilio webhook or polling.

Only Cara is expected to use SMS intake.
"""

import sqlite3
from .base import IntakeAdapter

ALLOWED_SMS_SENDERS = {"cara"}


class SmsIntake(IntakeAdapter):
    """Stub SMS intake. Phase 1 accepts messages directly via process()."""

    @property
    def channel_name(self) -> str:
        return "sms"

    def receive(self) -> list[dict]:
        # Not implemented in phase 1.
        # Phase 2: poll Twilio API or handle Twilio webhook here.
        raise NotImplementedError(
            "SMS receive() is not implemented in phase 1. "
            "Use process() to inject messages directly."
        )
