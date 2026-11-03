"""Mint the GMAIL_CREDENTIALS_B64 value.

Runs the Google OAuth consent flow once, pickles the resulting credential, and
prints it base64-encoded so it can be pasted into the project's single `.env`.

    python scripts/mint_gmail_token.py

Before running it, once, in the Google Cloud console:

  1. Create (or pick) a project and enable the **Gmail API**.
  2. APIs & Services -> OAuth consent screen. Add yourself as a test user.
     **Publish the app** when you are done testing: while the consent screen is in
     "Testing", Google expires every refresh token it issues after 7 days, and the
     failure shows up later as an opaque `invalid_grant`.
  3. Credentials -> Create credentials -> **OAuth client ID** -> *Desktop app*.
  4. Download the JSON and save it as `backend/credentials.json`
     (or pass the path as the first argument).

The scope requested is `gmail.send` and nothing else, so the credential cannot
read the mailbox it sends from.
"""

from __future__ import annotations

import base64
import pickle
import sys
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:  # pragma: no cover - a setup problem, not a runtime one
    sys.exit(
        "google-auth-oauthlib is not installed.\n"
        "  pip install google-auth-oauthlib"
    )

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
DEFAULT_CLIENT_SECRET = Path(__file__).resolve().parent.parent / "credentials.json"


def main() -> int:
    client_secret = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CLIENT_SECRET

    if not client_secret.exists():
        sys.exit(
            f"OAuth client file not found: {client_secret}\n\n"
            "Download it from Google Cloud console -> Credentials -> OAuth client ID\n"
            "(Desktop app), then save it there or pass the path as an argument."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    # access_type=offline + prompt=consent is what makes Google return a *refresh*
    # token. Without them a repeat authorisation returns only an access token, and
    # the credential dies in an hour.
    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
    )

    if not creds.refresh_token:
        sys.exit(
            "Google returned no refresh token. Revoke this app's access at\n"
            "https://myaccount.google.com/permissions and run this again."
        )

    blob = base64.b64encode(pickle.dumps(creds)).decode("ascii")

    print("\n" + "=" * 72)
    print("Paste this into the project's .env as a single line:\n")
    print(f"GMAIL_CREDENTIALS_B64={blob}")
    print("\nAnd set the mailbox it sends from, so the From header carries a name:\n")
    print("GMAIL_SENDER=you@yourdomain.com")
    print("=" * 72 + "\n")
    print(f"({len(blob)} characters. Restart the backend to pick it up.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
