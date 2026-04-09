"""
Tests for config.py (load_env_config, get_readiness) and the doctor CLI command.

Covers:
- load_env_config reads env vars correctly when set / unset
- get_readiness: all-clear, Twilio blocked, Discord blocked, everything blocked
- cmd_doctor output: prints mode readiness and actionable missing items
- cmd_doctor handles empty identity registries gracefully

No real credentials required. No filesystem state mutated.
"""

import argparse
import os
import pytest

import grocery_assistant.cli as cli_module
from grocery_assistant.config import load_env_config, get_readiness, EnvConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FULL_SMS = {"+12065550001": "cara", "+12065550002": "vern"}
FULL_DISCORD = {"111111111111111111": "vern", "222222222222222222": "cara"}
EMPTY = {}

def _base_cfg(**overrides) -> EnvConfig:
    """Return an EnvConfig with all fields empty/False, with optional overrides."""
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
# load_env_config tests
# ---------------------------------------------------------------------------

class TestLoadEnvConfig:
    def test_empty_env_returns_defaults(self, monkeypatch):
        """All optional vars unset -- returns empty strings and False."""
        for var in (
            "TWILIO_AUTH_TOKEN", "TWILIO_VALIDATE_SIGNATURE", "TWILIO_WEBHOOK_URL",
            "DISCORD_BOT_TOKEN", "GROCERY_DISCORD_CHANNEL_ID",
            "GROCERY_DB_PATH", "GROCERY_PORT", "GROCERY_SERVER_URL",
        ):
            monkeypatch.delenv(var, raising=False)

        cfg = load_env_config()

        assert cfg.twilio_auth_token == ""
        assert cfg.twilio_validate_signature is False
        assert cfg.twilio_webhook_url == ""
        assert cfg.discord_bot_token == ""
        assert cfg.discord_channel_id == ""
        assert cfg.db_path == ""
        assert cfg.port == 5000
        assert cfg.server_url == "http://127.0.0.1:5000"

    def test_twilio_vars_read(self, monkeypatch):
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "testtoken123")
        monkeypatch.setenv("TWILIO_VALIDATE_SIGNATURE", "1")
        monkeypatch.setenv("TWILIO_WEBHOOK_URL", "https://example.ngrok.io/sms/webhook")

        cfg = load_env_config()

        assert cfg.twilio_auth_token == "testtoken123"
        assert cfg.twilio_validate_signature is True
        assert cfg.twilio_webhook_url == "https://example.ngrok.io/sms/webhook"

    def test_discord_vars_read(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "bottoken456")
        monkeypatch.setenv("GROCERY_DISCORD_CHANNEL_ID", "987654321")

        cfg = load_env_config()

        assert cfg.discord_bot_token == "bottoken456"
        assert cfg.discord_channel_id == "987654321"

    def test_app_vars_read(self, monkeypatch):
        monkeypatch.setenv("GROCERY_DB_PATH", "/tmp/test.db")
        monkeypatch.setenv("GROCERY_PORT", "8080")
        monkeypatch.setenv("GROCERY_SERVER_URL", "http://10.0.0.1:9000")

        cfg = load_env_config()

        assert cfg.db_path == "/tmp/test.db"
        assert cfg.port == 8080
        assert cfg.server_url == "http://10.0.0.1:9000"

    def test_validate_signature_empty_string_is_false(self, monkeypatch):
        monkeypatch.setenv("TWILIO_VALIDATE_SIGNATURE", "")
        cfg = load_env_config()
        assert cfg.twilio_validate_signature is False

    def test_validate_signature_zero_is_false(self, monkeypatch):
        monkeypatch.setenv("TWILIO_VALIDATE_SIGNATURE", "0")
        cfg = load_env_config()
        assert cfg.twilio_validate_signature is False

    def test_validate_signature_true_variants(self, monkeypatch):
        for value in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("TWILIO_VALIDATE_SIGNATURE", value)
            cfg = load_env_config()
            assert cfg.twilio_validate_signature is True

    def test_validate_signature_false_variants(self, monkeypatch):
        for value in ("", "0", "false", "FALSE", "no", "off", "random"):
            monkeypatch.setenv("TWILIO_VALIDATE_SIGNATURE", value)
            cfg = load_env_config()
            assert cfg.twilio_validate_signature is False


# ---------------------------------------------------------------------------
# get_readiness tests
# ---------------------------------------------------------------------------

class TestGetReadiness:
    def test_all_clear(self):
        """All vars set, all senders populated -- all modes ready."""
        cfg = _base_cfg(
            twilio_auth_token="tok",
            twilio_validate_signature=True,
            twilio_webhook_url="https://example.ngrok.io/sms/webhook",
            discord_bot_token="bottoken",
        )
        result = get_readiness(cfg, FULL_SMS, FULL_DISCORD)

        assert result["modes"]["local_simulation"]["ready"] is True
        assert result["modes"]["twilio_live"]["ready"] is True
        assert result["modes"]["discord_live"]["ready"] is True
        assert result["modes"]["twilio_live"]["missing"] == []
        assert result["modes"]["discord_live"]["missing"] == []

    def test_twilio_blocked_missing_token_and_url(self):
        cfg = _base_cfg()  # no twilio vars
        result = get_readiness(cfg, FULL_SMS, FULL_DISCORD)

        assert result["modes"]["twilio_live"]["ready"] is False
        missing = result["modes"]["twilio_live"]["missing"]
        assert "TWILIO_AUTH_TOKEN" in missing
        assert "TWILIO_WEBHOOK_URL" in missing

    def test_twilio_blocked_missing_trusted_senders(self):
        cfg = _base_cfg(
            twilio_auth_token="tok",
            twilio_webhook_url="https://example.ngrok.io/sms/webhook",
        )
        result = get_readiness(cfg, EMPTY, FULL_DISCORD)

        assert result["modes"]["twilio_live"]["ready"] is False
        assert any("trusted SMS" in m for m in result["modes"]["twilio_live"]["missing"])

    def test_discord_blocked_missing_token(self):
        cfg = _base_cfg()
        result = get_readiness(cfg, FULL_SMS, FULL_DISCORD)

        assert result["modes"]["discord_live"]["ready"] is False
        assert "DISCORD_BOT_TOKEN" in result["modes"]["discord_live"]["missing"]

    def test_discord_blocked_missing_trusted_users(self):
        cfg = _base_cfg(discord_bot_token="bottoken")
        result = get_readiness(cfg, FULL_SMS, EMPTY)

        assert result["modes"]["discord_live"]["ready"] is False
        assert any("trusted Discord" in m for m in result["modes"]["discord_live"]["missing"])

    def test_local_simulation_always_ready(self):
        """Local simulation is always ready regardless of env vars."""
        cfg = _base_cfg()  # nothing configured
        result = get_readiness(cfg, EMPTY, EMPTY)
        assert result["modes"]["local_simulation"]["ready"] is True

    def test_checks_include_sms_warn_when_empty(self):
        cfg = _base_cfg()
        result = get_readiness(cfg, EMPTY, EMPTY)
        sms_checks = [c for c in result["checks"] if "SMS senders" in c["label"]]
        assert len(sms_checks) == 1
        assert sms_checks[0]["status"] == "warn"

    def test_checks_include_sms_ok_when_populated(self):
        cfg = _base_cfg()
        result = get_readiness(cfg, FULL_SMS, EMPTY)
        sms_checks = [c for c in result["checks"] if "SMS senders" in c["label"]]
        assert sms_checks[0]["status"] == "ok"

    def test_checks_include_discord_warn_when_empty(self):
        cfg = _base_cfg()
        result = get_readiness(cfg, EMPTY, EMPTY)
        discord_checks = [c for c in result["checks"] if "Discord users" in c["label"]]
        assert discord_checks[0]["status"] == "warn"

    def test_validate_sig_missing_is_warn(self):
        cfg = _base_cfg(twilio_validate_signature=False)
        result = get_readiness(cfg, EMPTY, EMPTY)
        sig_checks = [c for c in result["checks"] if "TWILIO_VALIDATE_SIGNATURE" in c["label"]]
        assert sig_checks[0]["status"] == "warn"

    def test_channel_id_not_set_is_ok(self):
        """Missing GROCERY_DISCORD_CHANNEL_ID is OK (optional)."""
        cfg = _base_cfg(discord_channel_id="")
        result = get_readiness(cfg, EMPTY, EMPTY)
        channel_checks = [c for c in result["checks"] if "CHANNEL_ID" in c["label"]]
        assert channel_checks[0]["status"] == "ok"


# ---------------------------------------------------------------------------
# cmd_doctor integration tests
# ---------------------------------------------------------------------------

class TestCmdDoctor:
    def _run_doctor(self, monkeypatch, capsys, sms=None, discord=None, env_overrides=None):
        """Helper: patch identity registries and env vars, run doctor, return stdout."""
        if sms is None:
            sms = {}
        if discord is None:
            discord = {}
        env_overrides = env_overrides or {}

        # Clear all relevant env vars first
        for var in (
            "TWILIO_AUTH_TOKEN", "TWILIO_VALIDATE_SIGNATURE", "TWILIO_WEBHOOK_URL",
            "DISCORD_BOT_TOKEN", "GROCERY_DISCORD_CHANNEL_ID",
            "GROCERY_DB_PATH", "GROCERY_PORT", "GROCERY_SERVER_URL",
        ):
            monkeypatch.delenv(var, raising=False)

        for k, v in env_overrides.items():
            monkeypatch.setenv(k, v)

        import grocery_assistant.identity as identity_mod
        monkeypatch.setattr(identity_mod, "TRUSTED_SMS_SENDERS", sms)
        monkeypatch.setattr(identity_mod, "TRUSTED_DISCORD_USERS", discord)

        args = argparse.Namespace(command="doctor")
        cli_module.cmd_doctor(args)
        return capsys.readouterr().out

    def test_doctor_prints_header(self, monkeypatch, capsys):
        out = self._run_doctor(monkeypatch, capsys)
        assert "Setup Check" in out

    def test_doctor_local_simulation_always_ready(self, monkeypatch, capsys):
        out = self._run_doctor(monkeypatch, capsys)
        assert "Local simulation" in out
        assert "READY" in out

    def test_doctor_twilio_blocked_when_empty(self, monkeypatch, capsys):
        out = self._run_doctor(monkeypatch, capsys)
        assert "Twilio live" in out
        assert "BLOCKED" in out
        assert "TWILIO_AUTH_TOKEN" in out

    def test_doctor_discord_blocked_when_empty(self, monkeypatch, capsys):
        out = self._run_doctor(monkeypatch, capsys)
        assert "Discord live" in out
        assert "BLOCKED" in out
        assert "DISCORD_BOT_TOKEN" in out

    def test_doctor_twilio_ready_when_configured(self, monkeypatch, capsys):
        out = self._run_doctor(
            monkeypatch, capsys,
            sms=FULL_SMS,
            env_overrides={
                "TWILIO_AUTH_TOKEN": "tok",
                "TWILIO_VALIDATE_SIGNATURE": "1",
                "TWILIO_WEBHOOK_URL": "https://example.ngrok.io/sms/webhook",
            },
        )
        lines = [l for l in out.splitlines() if "Twilio live" in l]
        assert any("READY" in l for l in lines)

    def test_doctor_discord_ready_when_configured(self, monkeypatch, capsys):
        out = self._run_doctor(
            monkeypatch, capsys,
            discord=FULL_DISCORD,
            env_overrides={"DISCORD_BOT_TOKEN": "bottoken"},
        )
        lines = [l for l in out.splitlines() if "Discord live" in l]
        assert any("READY" in l for l in lines)

    def test_doctor_shows_go_live_steps_when_blocked(self, monkeypatch, capsys):
        out = self._run_doctor(monkeypatch, capsys)
        assert "env.example" in out
        assert "identity.py" in out

    def test_doctor_no_go_live_steps_when_all_ready(self, monkeypatch, capsys):
        out = self._run_doctor(
            monkeypatch, capsys,
            sms=FULL_SMS,
            discord=FULL_DISCORD,
            env_overrides={
                "TWILIO_AUTH_TOKEN": "tok",
                "TWILIO_WEBHOOK_URL": "https://example.ngrok.io/sms/webhook",
                "DISCORD_BOT_TOKEN": "bottoken",
            },
        )
        assert "env.example" not in out
        assert "Everything looks configured" in out

    def test_doctor_shows_sms_count(self, monkeypatch, capsys):
        out = self._run_doctor(monkeypatch, capsys, sms=FULL_SMS)
        assert "2" in out  # 2 trusted SMS senders

    def test_doctor_shows_discord_count(self, monkeypatch, capsys):
        out = self._run_doctor(monkeypatch, capsys, discord=FULL_DISCORD)
        assert "2" in out  # 2 trusted Discord users
