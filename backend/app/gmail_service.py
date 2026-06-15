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
from googleapiclient.discovery import build

from app.auth_google import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SCOPES
from app.database import get_gmail_token, update_gmail_access_token


def _build_credentials(user_email: str) -> Credentials:
    token_row = get_gmail_token(user_email)
    if not token_row:
        raise ValueError(f"No Gmail account connected for {user_email}")

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
        creds.refresh(Request())
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
    """
    creds = _build_credentials(user_email)
    service = build("gmail", "v1", credentials=creds)

    message = _build_message(user_email, to_email, subject, body, html=html)
    result = service.users().messages().send(userId="me", body=message).execute()
    return result