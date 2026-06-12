"""
Google OAuth2 helper for Gmail API integration (Approach B) - stateless.
"""

import os
import time
import hmac
import hashlib
import base64
import json
from google_auth_oauthlib.flow import Flow

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/google/callback")

# Secret used to sign the OAuth `state` param (set a strong random value in prod)
STATE_SECRET = os.getenv("OAUTH_STATE_SECRET", "dev-insecure-change-me")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    raise ValueError("Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in environment variables")

if os.getenv("ENV", "development") == "development":
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")


def _client_config(redirect_uri: str) -> dict:
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def get_flow(redirect_uri: str = None) -> Flow:
    redirect_uri = redirect_uri or GOOGLE_REDIRECT_URI
    flow = Flow.from_client_config(
        _client_config(redirect_uri),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    # Confidential client (has client_secret) - disable PKCE to avoid
    # code_verifier mismatch between the /login flow object and the
    # /callback flow object (they are different instances).
    flow.autogenerate_code_verifier = False
    flow.code_verifier = None
    return flow


# ----------------------------------------------------------------
# Stateless signed state token: payload = {"u": user_email, "ts": time}
# ----------------------------------------------------------------
def _sign(payload: str) -> str:
    return hmac.new(STATE_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_state(user_email: str) -> str:
    payload = json.dumps({"u": user_email, "ts": int(time.time())})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = _sign(payload_b64)
    return f"{payload_b64}.{sig}"


def verify_state(state: str, max_age_seconds: int = 600) -> str:
    """Returns user_email if valid, raises ValueError otherwise."""
    try:
        payload_b64, sig = state.split(".", 1)
    except ValueError:
        raise ValueError("Malformed state")

    expected_sig = _sign(payload_b64)
    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError("State signature mismatch")

    payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode())
    if time.time() - payload["ts"] > max_age_seconds:
        raise ValueError("State expired")

    return payload["u"]


def get_auth_url(user_email: str, redirect_uri: str = None):
    """Return authorization_url with a signed, stateless state param."""
    flow = get_flow(redirect_uri)
    state = create_state(user_email)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return authorization_url, state


def fetch_tokens(code: str, redirect_uri: str = None):
    flow = get_flow(redirect_uri)
    flow.fetch_token(code=code)
    return flow.credentials


def get_user_info(credentials):
    from googleapiclient.discovery import build

    service = build("oauth2", "v2", credentials=credentials)
    return service.userinfo().get().execute()