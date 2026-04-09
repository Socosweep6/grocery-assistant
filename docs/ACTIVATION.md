# Activation Runbook

How to go from local simulation to live SMS and Discord intake. Do Twilio first. Discord is independent.

---

## Before Either Integration

```bash
# Verify local setup is healthy
python3 -m grocery_assistant.cli doctor

# Expected: Local simulation: READY
# Twilio live: BLOCKED, Discord live: BLOCKED -- that's fine for now
```

---

## Twilio (Live SMS)

### What you need

| Item | Where |
|------|-------|
| Twilio Auth Token | console.twilio.com -> Account -> Auth Token |
| Twilio phone number | console.twilio.com -> Phone Numbers -> Buy a Number |
| Cara's phone number (E.164) | her real number, e.g. `+12065550001` |
| ngrok (or any tunnel) | ngrok.com or `brew install ngrok` |

### Steps

**1. Add Cara's number to the trusted sender registry**

```python
# src/grocery_assistant/identity.py
TRUSTED_SMS_SENDERS: dict[str, str] = {
    "+12065550001": "cara",   # replace with her real number
}
```

**2. Fill in env vars**

```bash
cp env.example .env
# Edit .env:
#   TWILIO_AUTH_TOKEN=your_auth_token_here
#   TWILIO_VALIDATE_SIGNATURE=1
#   TWILIO_WEBHOOK_URL=https://your-ngrok-url/sms/webhook
source .env
```

**3. Start ngrok**

```bash
ngrok http 5000
# Copy the https URL, e.g. https://abc123.ngrok.io
# Update TWILIO_WEBHOOK_URL=https://abc123.ngrok.io/sms/webhook in .env
# source .env again
```

**4. Run the activation helper**

```bash
python3 scripts/twilio_setup.py
# Prints current status + the exact URL to paste into Twilio console
```

**5. Configure Twilio console**

```
twilio.com/console
-> Phone Numbers -> Manage -> Active Numbers -> click your number
-> Messaging -> "A message comes in" -> Webhook
-> paste the URL from step 4, method: HTTP POST
-> Save
```

**6. Verify and start**

```bash
python3 -m grocery_assistant.cli doctor   # Twilio live should show READY
python3 -m grocery_assistant.web          # start the server
```

Send a test SMS from Cara's number. The server replies with TwiML and logs the item.

---

## Discord (Live Bot)

### What you need

| Item | Where |
|------|-------|
| Discord bot token | discord.com/developers -> your app -> Bot -> Token |
| Vern's Discord user ID | 18-digit snowflake (see below) |
| Cara's Discord user ID | 18-digit snowflake (see below) |

**How to find a user ID:** Enable Developer Mode in Discord (Settings -> Advanced -> Developer Mode). Right-click a username -> Copy User ID.

### Steps

**1. Create a bot in the Discord developer portal**

```
discord.com/developers/applications
-> New Application -> name it
-> Bot -> Add Bot
-> Privileged Gateway Intents -> enable MESSAGE_CONTENT
-> OAuth2 -> URL Generator
   scopes: bot
   permissions: Send Messages + Read Message History
-> copy the generated URL and open it to add the bot to your server
```

**2. Add trusted user IDs to the registry**

```python
# src/grocery_assistant/identity.py
TRUSTED_DISCORD_USERS: dict[str, str] = {
    "111111111111111111": "vern",   # replace with real snowflake IDs
    "222222222222222222": "cara",
}
```

**3. Fill in env vars**

```bash
# Edit .env:
#   DISCORD_BOT_TOKEN=your_bot_token_here
#   GROCERY_DISCORD_CHANNEL_ID=channel_id  (optional -- restrict to one channel)
source .env
```

**4. Run the activation helper**

```bash
pip install discord.py
python3 scripts/discord_setup.py
```

**5. Verify and start**

```bash
python3 -m grocery_assistant.cli doctor   # Discord live should show READY

# Terminal 1
python3 -m grocery_assistant.web

# Terminal 2
python3 -m grocery_assistant.bridges.discord_bridge
```

Send a test message from Vern or Cara in Discord. The bot adds a checkmark reaction on success.

---

## Quick Reference

```bash
# Run either activation helper at any time
python3 scripts/twilio_setup.py
python3 scripts/discord_setup.py

# Full readiness check
python3 -m grocery_assistant.cli doctor

# Simulate Twilio locally (no real token needed)
python3 -m grocery_assistant.web
curl -X POST http://127.0.0.1:5000/sms/webhook \
  -d "From=%2B12065550001&Body=bananas%2C+eggs"

# Simulate Discord locally (no bot token needed)
curl -X POST http://127.0.0.1:5000/discord/event \
  -H "Content-Type: application/json" \
  -d '{"author": {"id": "111111111111111111"}, "content": "ground turkey 2 lb"}'
```
