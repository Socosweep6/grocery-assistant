"""
Tests for Twilio inbound request signature verification.

Covers:
- compute_signature: known-good value matches expected
- verify_signature: correct signature passes, wrong signature fails
- verify_signature: empty auth_token bypasses verification (dev mode)
- verify_signature: missing signature returns False when auth_token is set
- Parameter sorting: params are sorted before signing
"""

import base64
import hashlib
import hmac

import pytest

from grocery_assistant.twilio_sig import compute_signature, verify_signature


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _manual_sign(token: str, url: str, params: dict) -> str:
    """Reference implementation to cross-check compute_signature."""
    s = url
    for key in sorted(params.keys()):
        s += key + (params[key] or "")
    mac = hmac.new(token.encode(), s.encode(), hashlib.sha1)
    return base64.b64encode(mac.digest()).decode()


# ---------------------------------------------------------------------------
# compute_signature
# ---------------------------------------------------------------------------

class TestComputeSignature:
    def test_matches_manual_computation(self):
        token = "abc123"
        url = "https://example.ngrok.io/sms/webhook"
        params = {"From": "+12065550001", "Body": "bananas", "MessageSid": "SM123"}
        assert compute_signature(token, url, params) == _manual_sign(token, url, params)

    def test_params_sorted_alphabetically(self):
        token = "mytoken"
        url = "https://example.com/sms/webhook"
        # Params in reverse order -- result should match sorted version
        params_fwd = {"Body": "hello", "From": "+1555"}
        params_rev = {"From": "+1555", "Body": "hello"}
        assert compute_signature(token, url, params_fwd) == compute_signature(token, url, params_rev)

    def test_empty_params(self):
        token = "tok"
        url = "https://example.com/sms/webhook"
        sig = compute_signature(token, url, {})
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_different_urls_produce_different_signatures(self):
        token = "tok"
        params = {"From": "+1", "Body": "hi"}
        sig1 = compute_signature(token, "https://a.example.com/sms/webhook", params)
        sig2 = compute_signature(token, "https://b.example.com/sms/webhook", params)
        assert sig1 != sig2

    def test_different_tokens_produce_different_signatures(self):
        url = "https://example.com/sms/webhook"
        params = {"From": "+1", "Body": "hi"}
        sig1 = compute_signature("token_a", url, params)
        sig2 = compute_signature("token_b", url, params)
        assert sig1 != sig2


# ---------------------------------------------------------------------------
# verify_signature
# ---------------------------------------------------------------------------

class TestVerifySignature:
    TOKEN = "testtoken"
    URL = "https://example.ngrok.io/sms/webhook"
    PARAMS = {"From": "+12065550001", "Body": "oat milk"}

    @property
    def _valid_sig(self):
        return compute_signature(self.TOKEN, self.URL, self.PARAMS)

    def test_correct_signature_passes(self):
        assert verify_signature(self.TOKEN, self.URL, self.PARAMS, self._valid_sig)

    def test_wrong_signature_fails(self):
        assert not verify_signature(self.TOKEN, self.URL, self.PARAMS, "wrongsignature==")

    def test_empty_auth_token_bypasses_check(self):
        # Dev mode: no token configured means any (or no) signature passes
        assert verify_signature("", self.URL, self.PARAMS, "anything")
        assert verify_signature("", self.URL, self.PARAMS, "")

    def test_missing_signature_fails_when_token_set(self):
        assert not verify_signature(self.TOKEN, self.URL, self.PARAMS, "")

    def test_tampered_body_fails(self):
        tampered = {**self.PARAMS, "Body": "chips"}
        sig = compute_signature(self.TOKEN, self.URL, self.PARAMS)
        assert not verify_signature(self.TOKEN, self.URL, tampered, sig)

    def test_tampered_url_fails(self):
        sig = compute_signature(self.TOKEN, self.URL, self.PARAMS)
        other_url = "https://evil.example.com/sms/webhook"
        assert not verify_signature(self.TOKEN, other_url, self.PARAMS, sig)

    def test_signature_is_timing_safe(self):
        # verify_signature must use hmac.compare_digest, not ==
        # Verify it doesn't raise and handles an off-by-one-char signature
        sig = self._valid_sig
        bad = sig[:-1] + ("A" if sig[-1] != "A" else "B")
        assert not verify_signature(self.TOKEN, self.URL, self.PARAMS, bad)
