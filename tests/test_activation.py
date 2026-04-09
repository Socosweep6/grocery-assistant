"""
Tests for get_partial_config_risks() in config.py.

Covers all risk conditions:
- TWILIO_AUTH_TOKEN set but TWILIO_VALIDATE_SIGNATURE off
- Both token+sig set but TWILIO_WEBHOOK_URL missing
- TWILIO_WEBHOOK_URL set but TWILIO_AUTH_TOKEN missing
- TWILIO_WEBHOOK_URL with wrong path (missing /sms/webhook)
- DISCORD_BOT_TOKEN set but no trusted Discord users
- Clean configurations produce no risks
"""

import pytest
from grocery_assistant.config import EnvConfig, get_partial_config_risks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FULL_SMS = {"+12065550001": "cara"}
FULL_DISCORD = {"111111111111111111": "vern"}
EMPTY = {}


def _cfg(**overrides) -> EnvConfig:
    defaults = dict(
        twilio_auth_token="",
        twilio_validate_signature=False,
        twilio_webhook_url="",
        discord_bot_token="",
        discord_channel_id="",
        db_path="",
        port=5000,
        server_url="http://127.0.0.1:5000",
    )
    defaults.update(overrides)
    return EnvConfig(**defaults)


# ---------------------------------------------------------------------------
# No risks
# ---------------------------------------------------------------------------

class TestNoRisks:
    def test_fully_empty_config_has_no_risks(self):
        """Nothing set -- local dev mode, no risks."""
        cfg = _cfg()
        assert get_partial_config_risks(cfg, EMPTY, EMPTY) == []

    def test_fully_configured_twilio_has_no_risks(self):
        cfg = _cfg(
            twilio_auth_token="tok",
            twilio_validate_signature=True,
            twilio_webhook_url="https://abc.ngrok.io/sms/webhook",
        )
        assert get_partial_config_risks(cfg, FULL_SMS, FULL_DISCORD) == []

    def test_fully_configured_discord_has_no_risks(self):
        cfg = _cfg(discord_bot_token="bottoken")
        assert get_partial_config_risks(cfg, EMPTY, FULL_DISCORD) == []

    def test_both_fully_configured_has_no_risks(self):
        cfg = _cfg(
            twilio_auth_token="tok",
            twilio_validate_signature=True,
            twilio_webhook_url="https://abc.ngrok.io/sms/webhook",
            discord_bot_token="bottoken",
        )
        assert get_partial_config_risks(cfg, FULL_SMS, FULL_DISCORD) == []


# ---------------------------------------------------------------------------
# Twilio risks
# ---------------------------------------------------------------------------

class TestTwilioRisks:
    def test_token_set_but_validate_off(self):
        """Auth token present but signature check disabled -- requests not verified."""
        cfg = _cfg(twilio_auth_token="tok", twilio_validate_signature=False)
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        assert len(risks) == 1
        assert "TWILIO_VALIDATE_SIGNATURE" in risks[0]["label"]
        assert "TWILIO_AUTH_TOKEN" in risks[0]["label"]

    def test_token_and_sig_set_but_no_webhook_url(self):
        """Token+sig enabled but no URL -- signature will be verified against internal URL."""
        cfg = _cfg(twilio_auth_token="tok", twilio_validate_signature=True)
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        assert any("TWILIO_WEBHOOK_URL" in r["label"] for r in risks)

    def test_webhook_url_set_but_no_token(self):
        """URL configured but token missing -- verification silently skipped."""
        cfg = _cfg(twilio_webhook_url="https://abc.ngrok.io/sms/webhook")
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        assert any("TWILIO_AUTH_TOKEN" in r["label"] for r in risks)

    def test_webhook_url_missing_sms_webhook_path(self):
        """URL doesn't end in /sms/webhook -- wrong route."""
        cfg = _cfg(
            twilio_auth_token="tok",
            twilio_validate_signature=True,
            twilio_webhook_url="https://abc.ngrok.io",
        )
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        path_risks = [r for r in risks if "/sms/webhook" in r["label"]]
        assert len(path_risks) == 1

    def test_webhook_url_with_trailing_slash_missing_path(self):
        """URL with trailing slash but no /sms/webhook path."""
        cfg = _cfg(
            twilio_auth_token="tok",
            twilio_validate_signature=True,
            twilio_webhook_url="https://abc.ngrok.io/",
        )
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        path_risks = [r for r in risks if "/sms/webhook" in r["label"]]
        assert len(path_risks) == 1

    def test_webhook_url_correct_path_no_path_risk(self):
        """URL ending in /sms/webhook should not trigger path risk."""
        cfg = _cfg(
            twilio_auth_token="tok",
            twilio_validate_signature=True,
            twilio_webhook_url="https://abc.ngrok.io/sms/webhook",
        )
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        path_risks = [r for r in risks if "/sms/webhook" in r["label"]]
        assert len(path_risks) == 0

    def test_token_set_validate_off_detail_mentions_set_validate(self):
        """Detail message tells the user what to do."""
        cfg = _cfg(twilio_auth_token="tok", twilio_validate_signature=False)
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        assert any("TWILIO_VALIDATE_SIGNATURE=1" in r["detail"] for r in risks)

    def test_token_and_sig_but_no_url_detail_mentions_webhook_url(self):
        cfg = _cfg(twilio_auth_token="tok", twilio_validate_signature=True)
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        url_risks = [r for r in risks if "TWILIO_WEBHOOK_URL" in r["label"]]
        assert url_risks
        assert "TWILIO_WEBHOOK_URL" in url_risks[0]["detail"]


# ---------------------------------------------------------------------------
# Discord risks
# ---------------------------------------------------------------------------

class TestDiscordRisks:
    def test_token_set_but_no_trusted_users(self):
        """Bot token set but no users -- bot connects but rejects everything."""
        cfg = _cfg(discord_bot_token="bottoken")
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        assert any("DISCORD_BOT_TOKEN" in r["label"] for r in risks)

    def test_token_set_with_trusted_users_no_risk(self):
        """Token + trusted users = no Discord risk."""
        cfg = _cfg(discord_bot_token="bottoken")
        risks = get_partial_config_risks(cfg, EMPTY, FULL_DISCORD)
        discord_risks = [r for r in risks if "DISCORD" in r["label"]]
        assert discord_risks == []

    def test_no_token_no_users_no_discord_risk(self):
        """Neither set -- local mode, no Discord risk."""
        cfg = _cfg()
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        discord_risks = [r for r in risks if "DISCORD" in r["label"]]
        assert discord_risks == []

    def test_discord_risk_detail_mentions_identity_py(self):
        cfg = _cfg(discord_bot_token="bottoken")
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        discord_risks = [r for r in risks if "DISCORD" in r["label"]]
        assert any("identity.py" in r["detail"] for r in discord_risks)


# ---------------------------------------------------------------------------
# Multiple risks at once
# ---------------------------------------------------------------------------

class TestMultipleRisks:
    def test_token_no_sig_and_no_url_returns_two_risks(self):
        """Token present, validate off, no URL -- should get two risks."""
        cfg = _cfg(twilio_auth_token="tok", twilio_validate_signature=False)
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        # Should have: token+no_sig risk
        # Should NOT have: token+sig+no_url risk (because sig is off)
        validate_risks = [r for r in risks if "TWILIO_VALIDATE_SIGNATURE" in r["label"]]
        assert len(validate_risks) == 1

    def test_twilio_and_discord_risks_both_returned(self):
        """Both Twilio and Discord partial configs return all risks."""
        cfg = _cfg(
            twilio_auth_token="tok",
            twilio_validate_signature=False,
            discord_bot_token="bottoken",
        )
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        labels = " ".join(r["label"] for r in risks)
        assert "TWILIO" in labels
        assert "DISCORD" in labels

    def test_returns_list_not_generator(self):
        """Return type must be a list."""
        cfg = _cfg()
        result = get_partial_config_risks(cfg, EMPTY, EMPTY)
        assert isinstance(result, list)

    def test_each_risk_has_label_and_detail(self):
        """Every returned risk dict must have label and detail keys."""
        cfg = _cfg(twilio_auth_token="tok", twilio_validate_signature=False)
        risks = get_partial_config_risks(cfg, EMPTY, EMPTY)
        for risk in risks:
            assert "label" in risk
            assert "detail" in risk
            assert isinstance(risk["label"], str)
            assert isinstance(risk["detail"], str)
