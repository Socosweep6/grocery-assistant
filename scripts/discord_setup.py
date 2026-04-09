#!/usr/bin/env python3
"""
Discord Activation Checklist

Validates current environment for live Discord bot hookup.

Usage:
    python3 scripts/discord_setup.py

Run from the repo root. No dependencies beyond Python 3.11+.
"""

import os
import sys

# Allow importing grocery_assistant without pip install when run from repo root
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_repo_root, "src"))


def _load_trusted_discord():
    try:
        from grocery_assistant.identity import TRUSTED_DISCORD_USERS
        return TRUSTED_DISCORD_USERS, None
    except Exception as exc:
        return {}, str(exc)


def _mask(token: str) -> str:
    if len(token) > 8:
        return token[:4] + "..." + token[-4:]
    return "***"


def _check(label: str, ok: bool, hint: str = "") -> bool:
    sym = "[OK] " if ok else "[MISS]"
    suffix = f"\n         hint: {hint}" if hint and not ok else ""
    print(f"  {sym}  {label}{suffix}")
    return ok


def main() -> int:
    print()
    print("Discord Activation Checklist")
    print("=" * 44)
    print()

    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    channel_id = os.environ.get("GROCERY_DISCORD_CHANNEL_ID", "").strip()
    server_url = os.environ.get("GROCERY_SERVER_URL", "http://127.0.0.1:5000").strip()

    trusted_discord, import_err = _load_trusted_discord()
    discord_count = len(trusted_discord)

    all_ok = True

    # 1. Bot token
    ok = _check(
        f"DISCORD_BOT_TOKEN set ({_mask(bot_token) if bot_token else 'not set'})",
        bool(bot_token),
        "Get from: discord.com/developers/applications -> your app -> Bot -> Token",
    )
    all_ok = all_ok and ok

    # 2. Trusted Discord users
    if import_err:
        _check("Trusted Discord users (identity.py)", False,
               f"Could not import identity.py: {import_err}")
        all_ok = False
    else:
        ok = _check(
            f"Trusted Discord users: {discord_count} configured",
            discord_count > 0,
            "Add Vern's and Cara's Discord user IDs (18-digit snowflakes) to "
            "TRUSTED_DISCORD_USERS in src/grocery_assistant/identity.py. "
            "Enable Developer Mode in Discord (Settings -> Advanced), then "
            "right-click a username -> Copy User ID.",
        )
        all_ok = all_ok and ok

    # 3. discord.py installed (optional check)
    try:
        import importlib
        importlib.import_module("discord")
        _check("discord.py installed", True)
    except ImportError:
        _check(
            "discord.py installed",
            False,
            "Run: pip install discord.py  (required to run the bot bridge)",
        )
        all_ok = False

    # 4. Channel restriction (optional)
    print()
    if channel_id:
        print(f"  [OK]   GROCERY_DISCORD_CHANNEL_ID={channel_id}  (bot restricted to this channel)")
    else:
        print("  [INFO] GROCERY_DISCORD_CHANNEL_ID not set -- bot listens on all channels")
        print("         Set it to restrict intake to one channel (optional but recommended)")

    # 5. Web server URL
    print(f"  [INFO] GROCERY_SERVER_URL={server_url}")
    print("         Bridge POSTs Discord events here. Change if your web server is elsewhere.")

    # 6. Partial-config risks
    risks = []
    if bot_token and discord_count == 0:
        risks.append(
            "DISCORD_BOT_TOKEN is set but no trusted Discord users are configured -- "
            "bot will connect but reject every message with 403"
        )
    if risks:
        print()
        print("Risks:")
        for r in risks:
            print(f"  [RISK]  {r}")

    print()

    if not all_ok:
        print("Fix the items above, then re-run:")
        print("  python3 scripts/discord_setup.py")
        print()
        print("Or run the full doctor check:")
        print("  python3 -m grocery_assistant.cli doctor")
    else:
        print("All checks passed.")
        print()
        print("Final steps:")
        print("  1. Complete bot setup in the Discord developer portal (if not done):")
        print("       discord.com/developers/applications -> your app")
        print("       -> Bot -> enable MESSAGE_CONTENT under Privileged Gateway Intents")
        print("       -> OAuth2 -> URL Generator -> scopes: bot")
        print("         permissions: Send Messages + Read Message History")
        print("       -> copy the invite URL and add the bot to your server")
        print()
        print("  2. Start the web server:   python3 -m grocery_assistant.web")
        print()
        print("  3. Start the bridge:       python3 -m grocery_assistant.bridges.discord_bridge")
        print()
        print("  4. Send a test message from a trusted Discord user")

    print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
