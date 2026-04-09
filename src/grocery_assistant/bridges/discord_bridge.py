"""
Discord bridge for Grocery Assistant.

Forwards Discord MESSAGE_CREATE events to the local intake endpoint.
Two wiring approaches are supported:

  Approach A -- HTTP bridge (bot runs as a separate process)
    The bot calls forward_message_event() which POSTs to the local web server.
    Requires the web server to be running (python -m grocery_assistant.web).

  Approach B -- Direct adapter (bot calls the adapter in-process)
    The bot imports DiscordAdapter and calls receive_event() directly.
    No HTTP overhead. Suitable when running everything in one process.

This module implements Approach A. Approach B is shown in the example at the
bottom of this file.

Environment variables:
  GROCERY_SERVER_URL           -- base URL of the local web server
                                  (default: http://127.0.0.1:5000)
  DISCORD_BOT_TOKEN            -- your bot token from discord.com/developers
  GROCERY_DISCORD_CHANNEL_ID   -- restrict intake to one channel (optional)

Discord Bot Setup:
  1. Create an application at discord.com/developers/applications
  2. Create a Bot under your application
  3. Enable MESSAGE_CONTENT intent (required to read message text)
  4. Invite the bot to your server with Send Messages + Read Message History permissions
  5. Add the Discord user IDs for trusted senders to TRUSTED_DISCORD_USERS in identity.py
  6. Set DISCORD_BOT_TOKEN=your_bot_token
  7. Optionally set GROCERY_DISCORD_CHANNEL_ID=channel_id to restrict to one channel
  8. Run: pip install discord.py && python -m grocery_assistant.bridges.discord_bridge

Local simulation (no bot token needed):
  curl -X POST http://127.0.0.1:5000/discord/event \\
    -H "Content-Type: application/json" \\
    -d '{"author": {"id": "YOUR_USER_ID"}, "content": "bananas, eggs"}'

Identity notes:
  - Identity is resolved from author.id (Discord snowflake), NOT author.username
  - Usernames can be changed; snowflake IDs are permanent
  - Only IDs listed in TRUSTED_DISCORD_USERS are accepted
"""

import json
import os
import urllib.error
import urllib.request

GROCERY_SERVER_URL = os.environ.get("GROCERY_SERVER_URL", "http://127.0.0.1:5000")


def forward_message_event(event: dict) -> dict:
    """
    Forward a Discord MESSAGE_CREATE event to the local intake endpoint.

    Sends only the fields the intake route needs (author.id, content).
    Extra Discord fields (guild_id, channel_id, attachments, etc.) are ignored.

    Args:
        event: Discord MESSAGE_CREATE event dict. Must contain:
               - event["author"]["id"]: snowflake user ID (string)
               - event["content"]: message text

    Returns:
        Response dict from the intake endpoint:
        {"event_id": int, "added": [...], "merged": [...], "flagged": [...]}

    Raises:
        urllib.error.URLError: if the web server is unreachable.
        ValueError: if the server returns a non-200 response.
    """
    payload = {
        "author": {"id": str(event.get("author", {}).get("id", ""))},
        "content": event.get("content", ""),
    }

    url = f"{GROCERY_SERVER_URL}/discord/event"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ValueError(
            f"Intake endpoint returned {exc.code}: {body}"
        ) from exc


# ---------------------------------------------------------------------------
# discord.py bot example (Approach A -- HTTP bridge)
# ---------------------------------------------------------------------------
#
# To use this as a real Discord bot:
#
#   pip install discord.py
#
# Then run this file directly:
#   DISCORD_BOT_TOKEN=your_token python -m grocery_assistant.bridges.discord_bridge
#
# Or import and call setup_bot() in your own bot process.
# ---------------------------------------------------------------------------

def setup_bot():
    """
    Create and return a discord.py Bot wired to forward grocery messages.

    Requires discord.py to be installed:
        pip install discord.py

    Usage:
        bot = setup_bot()
        bot.run(os.environ["DISCORD_BOT_TOKEN"])

    Channel filtering:
        Set GROCERY_DISCORD_CHANNEL_ID to restrict intake to one channel.
        Leave unset to accept messages from any channel the bot can see.
        Always filter by trusted user ID (configured in identity.py).
    """
    try:
        import discord
    except ImportError as exc:
        raise ImportError(
            "discord.py is required for the bot bridge. "
            "Install it with: pip install discord.py"
        ) from exc

    channel_id_str = os.environ.get("GROCERY_DISCORD_CHANNEL_ID", "")
    allowed_channel_id = int(channel_id_str) if channel_id_str else None

    intents = discord.Intents.default()
    intents.message_content = True
    bot = discord.Client(intents=intents)

    @bot.event
    async def on_ready():
        print(f"Grocery bot connected as {bot.user}")
        if allowed_channel_id:
            print(f"Listening on channel ID: {allowed_channel_id}")
        else:
            print("Listening on all channels (set GROCERY_DISCORD_CHANNEL_ID to restrict)")

    @bot.event
    async def on_message(message):
        # Ignore the bot's own messages
        if message.author == bot.user:
            return

        # Optional channel filter
        if allowed_channel_id and message.channel.id != allowed_channel_id:
            return

        # Ignore empty messages or messages that are only attachments/embeds
        if not message.content.strip():
            return

        event = {
            "author": {"id": str(message.author.id)},
            "content": message.content,
        }

        try:
            result = forward_message_event(event)
            added = result.get("added", [])
            flagged = result.get("flagged", [])
            merged = result.get("merged", [])

            parts = []
            if added:
                parts.append(f"Added: {', '.join(added)}")
            if merged:
                parts.append(f"Already on list: {', '.join(merged)}")
            if flagged:
                names = [f["item"] for f in flagged]
                parts.append(f"Flagged (needs clarification): {', '.join(names)}")

            if parts:
                await message.add_reaction("\N{WHITE HEAVY CHECK MARK}")
                # Uncomment to send a reply in the channel:
                # await message.reply("\n".join(parts), mention_author=False)

        except ValueError as exc:
            print(f"[bridge] Intake rejected message: {exc}")
            await message.add_reaction("\N{CROSS MARK}")

        except Exception as exc:
            print(f"[bridge] Unexpected error forwarding message: {exc}")

    return bot


if __name__ == "__main__":
    import sys

    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        print(
            "DISCORD_BOT_TOKEN is not set.\n"
            "For local simulation without a bot token, use curl directly:\n\n"
            "  curl -X POST http://127.0.0.1:5000/discord/event \\\n"
            "    -H 'Content-Type: application/json' \\\n"
            "    -d '{\"author\": {\"id\": \"YOUR_USER_ID\"}, \"content\": \"bananas, eggs\"}'",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        bot = setup_bot()
    except ImportError as exc:
        print(
            f"[error] {exc}\n\n"
            "Install discord.py first:\n"
            "  pip install discord.py\n\n"
            "Then re-run:\n"
            "  python -m grocery_assistant.bridges.discord_bridge",
            file=sys.stderr,
        )
        sys.exit(1)

    bot.run(token)
