"""
Gmail API sending service (Approach B).

Uses a user's stored refresh token to obtain a fresh access token and
send email via the Gmail API (messages.send), instead of raw SMTP.
"""

import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.auth_google import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SCOPES
from app.database import get_gmail_token, update_gmail_access_token, delete_gmail_token


class GmailAuthError(Exception):
    """Raised when the stored Gmail credentials are invalid/expired and the
    user needs to reconnect their Google account."""
    pass


def _build_credentials(user_email: str) -> Credentials:
    token_row = get_gmail_token(user_email)
    if not token_row:
        raise GmailAuthError(
            f"No Gmail account connected for {user_email}. "
            f"Please connect your Google account first."
        )

    if not token_row.get("refresh_token"):
        raise GmailAuthError(
            f"No refresh token stored for {user_email}. "
            f"Please disconnect and reconnect your Google account."
        )

    creds = Credentials(
        token=token_row.get("access_token"),
        refresh_token=token_row["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )

    # Refresh if expired / no access token cached
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            # Refresh token is invalid/expired/revoked (common in OAuth
            # "Testing" mode where refresh tokens expire after 7 days, or
            # if the user revoked access, or client secret changed).
            # Clear the stale token so the UI shows "Not connected" and
            # the user can reconnect.
            delete_gmail_token(user_email)
            raise GmailAuthError(
                f"Gmail authorization for {user_email} has expired or was "
                f"revoked ({e}). Please reconnect your Google account."
            ) from e

        update_gmail_access_token(user_email, creds.token, creds.expiry)

    return creds


def _build_message(sender: str, to: str, subject: str, body: str, html: bool = False) -> dict:
    message = MIMEMultipart("alternative")
    message["to"] = to
    message["from"] = sender
    message["subject"] = subject

    mime_type = "html" if html else "plain"
    message.attach(MIMEText(body, mime_type))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": raw}


def send_email_gmail(user_email: str, to_email: str, subject: str, body: str, html: bool = False) -> dict:
    """
    Send an email via the Gmail API using the stored refresh token
    for `user_email` (the logged-in user's connected Gmail account).

    Raises:
        GmailAuthError: if the account isn't connected or the stored
            credentials are invalid/expired (user must reconnect).
        Exception: for other Gmail API errors (network, quota, etc.)
    """
    print(f"📡 Gmail API: building credentials for {user_email}")
    creds = _build_credentials(user_email)

    print(f"📡 Gmail API: sending to {to_email} as {user_email}")
    try:
        service = build("gmail", "v1", credentials=creds)
        message = _build_message(user_email, to_email, subject, body, html=html)
        result = service.users().messages().send(userId="me", body=message).execute()
        print(f"✅ Gmail API: sent (id={result.get('id')})")
        return result
    except HttpError as e:
        # Surface the actual Google API error (scopes, quota, etc.)
        status = getattr(e, "status_code", None) or (e.resp.status if hasattr(e, "resp") else None)
        print(f"❌ Gmail API HttpError (status={status}): {e}")
        if status == 403:
            raise GmailAuthError(
                f"Gmail API returned 403 for {user_email}. This usually means "
                f"the 'gmail.send' scope was not granted, or the Gmail API is "
                f"not enabled for this Google Cloud project, or the account "
                f"isn't allowed (check OAuth consent screen Test Users). "
                f"Details: {e}"
            ) from e
        raise
    except RefreshError as e:
        delete_gmail_token(user_email)
        raise GmailAuthError(
            f"Gmail authorization for {user_email} expired during send "
            f"({e}). Please reconnect your Google account."
        ) from e