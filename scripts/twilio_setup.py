#!/usr/bin/env python3
"""
Twilio Activation Checklist

Validates current environment for live Twilio SMS hookup and prints the exact
webhook URL to paste into the Twilio console.

Usage:
    python3 scripts/twilio_setup.py

Run from the repo root. No dependencies beyond Python 3.11+.
"""

import os
import sys

# Allow importing grocery_assistant without pip install when run from repo root
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_repo_root, "src"))


def _load_trusted_sms():
    try:
        from grocery_assistant.identity import TRUSTED_SMS_SENDERS
        return TRUSTED_SMS_SENDERS, None
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
    print("Twilio Activation Checklist")
    print("=" * 44)
    print()

    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    validate_sig = os.environ.get("TWILIO_VALIDATE_SIGNATURE", "").strip().lower()
    sig_enabled = validate_sig in ("1", "true", "yes", "on")
    webhook_url = os.environ.get("TWILIO_WEBHOOK_URL", "").strip()

    trusted_sms, import_err = _load_trusted_sms()
    sms_count = len(trusted_sms)

    all_ok = True

    # 1. Auth token
    ok = _check(
        f"TWILIO_AUTH_TOKEN set ({_mask(auth_token) if auth_token else 'not set'})",
        bool(auth_token),
        "Get from: console.twilio.com -> Account -> Auth Token",
    )
    all_ok = all_ok and ok

    # 2. Signature verification
    ok = _check(
        "TWILIO_VALIDATE_SIGNATURE=1",
        sig_enabled,
        "Set this to 1 before exposing the webhook publicly -- prevents spoofed requests",
    )
    all_ok = all_ok and ok

    # 3. Webhook URL
    ok = _check(
        f"TWILIO_WEBHOOK_URL set ({webhook_url or 'not set'})",
        bool(webhook_url),
        "Set to https://your-ngrok-url/sms/webhook (the public URL Twilio will POST to)",
    )
    all_ok = all_ok and ok

    # 4. Trusted SMS senders
    if import_err:
        _check("Trusted SMS senders (identity.py)", False,
               f"Could not import identity.py: {import_err}")
        all_ok = False
    else:
        ok = _check(
            f"Trusted SMS senders: {sms_count} configured",
            sms_count > 0,
            "Add Cara's phone number (E.164 format, e.g. +12065550001) to "
            "TRUSTED_SMS_SENDERS in src/grocery_assistant/identity.py",
        )
        all_ok = all_ok and ok

    # 5. Partial-config risks
    print()
    risks = []
    if auth_token and not sig_enabled:
        risks.append(
            "TWILIO_AUTH_TOKEN is set but TWILIO_VALIDATE_SIGNATURE is off -- "
            "requests reach /sms/webhook without signature check"
        )
    if auth_token and sig_enabled and not webhook_url:
        risks.append(
            "Signature verification is on but TWILIO_WEBHOOK_URL is missing -- "
            "Flask's internal URL will be used for verification and every real request will 403"
        )
    if webhook_url and not auth_token:
        risks.append(
            "TWILIO_WEBHOOK_URL is set but TWILIO_AUTH_TOKEN is missing -- "
            "signature verification will be silently skipped"
        )
    if webhook_url:
        url = webhook_url.rstrip("/")
        if not url.endswith("/sms/webhook"):
            risks.append(
                f"TWILIO_WEBHOOK_URL does not end in /sms/webhook -- "
                f"current: {webhook_url!r}"
            )
    if risks:
        print("Risks:")
        for r in risks:
            print(f"  [RISK]  {r}")
        print()

    # 6. Webhook URL for Twilio console
    if webhook_url:
        url = webhook_url.rstrip("/")
        if not url.endswith("/sms/webhook"):
            url = url + "/sms/webhook"
        print("Twilio console -- paste this as your webhook URL:")
        print("-" * 44)
        print()
        print(f"    {url}")
        print()
        print("Where to paste:")
        print("  twilio.com/console")
        print("  -> Phone Numbers -> Manage -> Active Numbers")
        print("  -> click your number")
        print("  -> Messaging -> A message comes in -> Webhook")
        print("  -> paste the URL above, method: HTTP POST")
        print()
    else:
        print("Set TWILIO_WEBHOOK_URL to generate the console paste value.")
        print()

    # 7. Next step hint
    if not all_ok:
        print("Fix the items above, then re-run:")
        print("  python3 scripts/twilio_setup.py")
        print()
        print("Or run the full doctor check:")
        print("  python3 -m grocery_assistant.cli doctor")
    else:
        print("All checks passed.")
        print()
        print("Final steps:")
        print("  1. Start ngrok:        ngrok http 5000")
        print("  2. Update TWILIO_WEBHOOK_URL with the ngrok https URL, then re-run this script")
        print("  3. Paste the URL above into the Twilio console")
        print("  4. Start the server:   python3 -m grocery_assistant.web")
        print("  5. Send a test SMS from a trusted number")

    print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
