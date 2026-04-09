"""
Trusted sender identity configuration and validation.

SMS senders are identified by E.164 phone numbers (e.g. '+12065550001').
Discord senders are identified by user IDs (integer snowflakes, stored as strings).
Both map to canonical lowercase names used throughout the system.

Configuration:
  Populate TRUSTED_SMS_SENDERS and TRUSTED_DISCORD_USERS before running real adapters.
  In tests, pass explicit dicts to resolve_sms_sender / resolve_discord_sender instead.

Example (production):
  TRUSTED_SMS_SENDERS = {"+12065550001": "cara"}
  TRUSTED_DISCORD_USERS = {"123456789012345678": "vern", "987654321098765432": "cara"}
"""

# ---------------------------------------------------------------------------
# Trusted sender registries
# Replace placeholder comments with real identifiers before deployment.
# ---------------------------------------------------------------------------

TRUSTED_SMS_SENDERS: dict[str, str] = {
    # "+12065550001": "cara",
}

TRUSTED_DISCORD_USERS: dict[str, str] = {
    # "123456789012345678": "vern",
    # "987654321098765432": "cara",
}

# Canonical name that is allowed to approve orders (case-insensitive match)
VERN_NAME = "vern"


class UntrustedSenderError(ValueError):
    """Raised when an incoming sender is not in the trusted registry."""
    pass


def resolve_sms_sender(from_number: str,
                        trusted: dict[str, str] | None = None) -> str:
    """
    Resolve an E.164 phone number to a canonical sender name.

    Args:
        from_number: E.164 phone number string (e.g. '+12065550001').
        trusted: override registry for testing; None uses module-level default.

    Returns:
        Lowercase canonical name (e.g. 'cara').

    Raises:
        UntrustedSenderError: if the number is not in the trusted registry.
    """
    registry = trusted if trusted is not None else TRUSTED_SMS_SENDERS
    name = registry.get(from_number.strip())
    if name is None:
        raise UntrustedSenderError(
            f"Untrusted SMS sender: {from_number!r}. "
            "Add the number to TRUSTED_SMS_SENDERS to allow this sender."
        )
    return name.lower().strip()


def resolve_discord_sender(user_id: str,
                            trusted: dict[str, str] | None = None) -> str:
    """
    Resolve a Discord user ID to a canonical sender name.

    Args:
        user_id: Discord snowflake user ID as a string.
        trusted: override registry for testing; None uses module-level default.

    Returns:
        Lowercase canonical name (e.g. 'vern').

    Raises:
        UntrustedSenderError: if the user ID is not in the trusted registry.
    """
    registry = trusted if trusted is not None else TRUSTED_DISCORD_USERS
    name = registry.get(str(user_id).strip())
    if name is None:
        raise UntrustedSenderError(
            f"Untrusted Discord user: {user_id!r}. "
            "Add the user ID to TRUSTED_DISCORD_USERS to allow this sender."
        )
    return name.lower().strip()


def is_vern(sender: str) -> bool:
    """Return True if the resolved sender name matches Vern's canonical name."""
    return sender.strip().lower() == VERN_NAME
