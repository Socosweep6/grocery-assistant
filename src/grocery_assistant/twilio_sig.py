"""
Twilio inbound request signature verification.

Implements the Twilio signature validation algorithm using Python stdlib only.
No Twilio SDK or external dependency required.

Twilio signs every request it sends using your auth token and HMAC-SHA1.
Verifying the signature proves the request came from Twilio, not an impersonator.

Algorithm (per Twilio docs):
  1. Take the full URL of the webhook endpoint (e.g. https://yourdomain.ngrok.io/sms/webhook)
  2. If it's a POST with form parameters, sort the params alphabetically by key
     and append each key+value pair to the URL (no separator between pairs)
  3. Sign the resulting string with HMAC-SHA1 using the auth token as the key
  4. Base64-encode the digest
  5. Compare the result to the X-Twilio-Signature header value

Enabling signature verification:
  Set both env vars before starting the web server:
    TWILIO_AUTH_TOKEN=your_auth_token_here
    TWILIO_VALIDATE_SIGNATURE=1

  Also set TWILIO_WEBHOOK_URL to your public-facing URL (required when running
  behind ngrok or a reverse proxy, since Flask sees the internal URL):
    TWILIO_WEBHOOK_URL=https://abc123.ngrok.io/sms/webhook

  If TWILIO_AUTH_TOKEN is empty or TWILIO_VALIDATE_SIGNATURE is not set,
  verification is skipped (dev/local mode).

Reference:
  https://www.twilio.com/docs/usage/security#validating-signatures-from-twilio
"""

import base64
import hashlib
import hmac
from typing import Mapping


def compute_signature(auth_token: str, url: str,
                       params: Mapping[str, str]) -> str:
    """
    Compute the expected Twilio signature for a request.

    Args:
        auth_token: Your Twilio auth token (from console.twilio.com).
        url: The full URL of the webhook endpoint as Twilio sees it.
        params: POST form parameters from the Twilio request.

    Returns:
        Base64-encoded HMAC-SHA1 signature string.
    """
    # Build the validation string: URL + sorted(key+value pairs)
    s = url
    for key in sorted(params.keys()):
        s += key + (params[key] or "")

    mac = hmac.new(
        auth_token.encode("utf-8"),
        s.encode("utf-8"),
        hashlib.sha1,
    )
    return base64.b64encode(mac.digest()).decode("utf-8")


def verify_signature(auth_token: str, url: str,
                      params: Mapping[str, str],
                      signature: str) -> bool:
    """
    Verify a Twilio request signature.

    Returns True if the signature matches, or if auth_token is empty
    (dev/local mode bypass).

    Args:
        auth_token: Your Twilio auth token. Empty string skips verification.
        url: Full URL of the webhook endpoint as Twilio sees it.
        params: POST form parameters from the Twilio request.
        signature: Value of the X-Twilio-Signature request header.

    Returns:
        True if the signature is valid (or verification is disabled).
        False if the signature does not match.
    """
    if not auth_token:
        return True  # dev mode -- no token configured, skip check

    if not signature:
        return False

    expected = compute_signature(auth_token, url, params)
    return hmac.compare_digest(expected.encode("utf-8"), signature.encode("utf-8"))
