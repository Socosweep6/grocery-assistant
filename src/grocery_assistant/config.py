"""
Centralized environment configuration for Grocery Assistant.

Reads all environment variables used by the app in one place.
Used by the doctor/readiness command to report what is configured and what is missing.

No magic: every variable is explicit. The rest of the app may still read env vars
directly -- this module does not replace that. It exists to give the doctor command
a single place to inspect and report.

Environment variables:
  TWILIO_AUTH_TOKEN           -- Twilio account auth token (from console.twilio.com)
  TWILIO_VALIDATE_SIGNATURE   -- Set to "1" to enable signature verification
  TWILIO_WEBHOOK_URL          -- Your public webhook URL (required when behind ngrok/proxy)
  DISCORD_BOT_TOKEN           -- Discord bot token (from discord.com/developers)
  GROCERY_DISCORD_CHANNEL_ID  -- Restrict bot to one channel ID (optional)
  GROCERY_DB_PATH             -- Override path to the SQLite database file
  GROCERY_PORT                -- Override the web server port (default: 5000)
  GROCERY_SERVER_URL          -- Base URL the discord bridge posts to (default: http://127.0.0.1:5000)
"""

import os
from dataclasses import dataclass


def _env_truthy(name: str) -> bool:
    """Interpret common env-style truthy values.

    True for: 1, true, yes, on (case-insensitive)
    False for unset, empty, 0, false, no, off, or anything else.
    """
    value = os.environ.get(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


@dataclass
class EnvConfig:
    # Twilio
    twilio_auth_token: str
    twilio_validate_signature: bool
    twilio_webhook_url: str

    # Discord
    discord_bot_token: str
    discord_channel_id: str

    # App
    db_path: str
    port: int
    server_url: str


def load_env_config() -> EnvConfig:
    """Read all relevant environment variables and return a structured config object.

    Returns an EnvConfig with empty strings for unset string fields and False
    for unset boolean fields. Never raises -- callers can inspect fields directly.
    """
    return EnvConfig(
        twilio_auth_token=os.environ.get("TWILIO_AUTH_TOKEN", ""),
        twilio_validate_signature=_env_truthy("TWILIO_VALIDATE_SIGNATURE"),
        twilio_webhook_url=os.environ.get("TWILIO_WEBHOOK_URL", ""),
        discord_bot_token=os.environ.get("DISCORD_BOT_TOKEN", ""),
        discord_channel_id=os.environ.get("GROCERY_DISCORD_CHANNEL_ID", ""),
        db_path=os.environ.get("GROCERY_DB_PATH", ""),
        port=int(os.environ.get("GROCERY_PORT", 5000)),
        server_url=os.environ.get("GROCERY_SERVER_URL", "http://127.0.0.1:5000"),
    )


def get_readiness(
    cfg: EnvConfig,
    trusted_sms: dict,
    trusted_discord: dict,
) -> dict:
    """
    Evaluate setup readiness for each operational mode.

    Args:
        cfg: EnvConfig from load_env_config().
        trusted_sms: TRUSTED_SMS_SENDERS dict from identity.py (or override for tests).
        trusted_discord: TRUSTED_DISCORD_USERS dict from identity.py (or override for tests).

    Returns a dict with:
        checks: list of {"label": str, "status": "ok"|"warn"|"miss", "detail": str}
        modes: dict of mode_name -> {"ready": bool, "missing": list[str]}
    """
    checks = []

    # --- Trusted senders ---
    sms_count = len(trusted_sms)
    discord_count = len(trusted_discord)

    if sms_count > 0:
        checks.append({
            "label": f"Trusted SMS senders: {sms_count} configured",
            "status": "ok",
            "detail": "",
        })
    else:
        checks.append({
            "label": "Trusted SMS senders: 0 configured",
            "status": "warn",
            "detail": "Add real phone numbers to TRUSTED_SMS_SENDERS in identity.py",
        })

    if discord_count > 0:
        checks.append({
            "label": f"Trusted Discord users: {discord_count} configured",
            "status": "ok",
            "detail": "",
        })
    else:
        checks.append({
            "label": "Trusted Discord users: 0 configured",
            "status": "warn",
            "detail": "Add real user IDs to TRUSTED_DISCORD_USERS in identity.py",
        })

    # --- Twilio env vars ---
    if cfg.twilio_auth_token:
        checks.append({"label": "TWILIO_AUTH_TOKEN", "status": "ok", "detail": "set"})
    else:
        checks.append({
            "label": "TWILIO_AUTH_TOKEN",
            "status": "miss",
            "detail": "not set -- required for live Twilio hookup",
        })

    if cfg.twilio_validate_signature:
        checks.append({
            "label": "TWILIO_VALIDATE_SIGNATURE",
            "status": "ok",
            "detail": "enabled -- signature checking active",
        })
    else:
        checks.append({
            "label": "TWILIO_VALIDATE_SIGNATURE",
            "status": "warn",
            "detail": "not set -- dev mode, signature check disabled (set to 1 for production)",
        })

    if cfg.twilio_webhook_url:
        checks.append({
            "label": "TWILIO_WEBHOOK_URL",
            "status": "ok",
            "detail": cfg.twilio_webhook_url,
        })
    else:
        checks.append({
            "label": "TWILIO_WEBHOOK_URL",
            "status": "miss",
            "detail": "not set -- required when running behind ngrok or a reverse proxy",
        })

    # --- Discord env vars ---
    if cfg.discord_bot_token:
        checks.append({"label": "DISCORD_BOT_TOKEN", "status": "ok", "detail": "set"})
    else:
        checks.append({
            "label": "DISCORD_BOT_TOKEN",
            "status": "miss",
            "detail": "not set -- required to run the Discord bot bridge",
        })

    if cfg.discord_channel_id:
        checks.append({
            "label": "GROCERY_DISCORD_CHANNEL_ID",
            "status": "ok",
            "detail": f"bot restricted to channel {cfg.discord_channel_id}",
        })
    else:
        checks.append({
            "label": "GROCERY_DISCORD_CHANNEL_ID",
            "status": "ok",
            "detail": "not set -- bot will listen on all channels (optional restriction)",
        })

    # --- Mode readiness ---
    twilio_missing = []
    if sms_count == 0:
        twilio_missing.append("trusted SMS numbers in identity.py")
    if not cfg.twilio_auth_token:
        twilio_missing.append("TWILIO_AUTH_TOKEN")
    if not cfg.twilio_webhook_url:
        twilio_missing.append("TWILIO_WEBHOOK_URL")

    discord_missing = []
    if discord_count == 0:
        discord_missing.append("trusted Discord users in identity.py")
    if not cfg.discord_bot_token:
        discord_missing.append("DISCORD_BOT_TOKEN")

    modes = {
        "local_simulation": {
            "ready": True,
            "missing": [],
        },
        "twilio_live": {
            "ready": len(twilio_missing) == 0,
            "missing": twilio_missing,
        },
        "discord_live": {
            "ready": len(discord_missing) == 0,
            "missing": discord_missing,
        },
    }

    return {"checks": checks, "modes": modes}
