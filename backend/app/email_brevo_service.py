import os
import json
import urllib.request
import urllib.error
from typing import NamedTuple
from dotenv import load_dotenv

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

load_dotenv()
class BrevoSettings(NamedTuple):
    api_key: str
    from_email: str
    from_name: str


def load_brevo_settings() -> "BrevoSettings | None":
    api_key = os.getenv("BREVO")
    
    from_email = os.getenv("BREVO_FROM_EMAIL", "").strip()
    from_name = os.getenv("BREVO_FROM_NAME", "Email Sender").strip()
    
    if not api_key or not from_email:
        return None
    return BrevoSettings(api_key=api_key, from_email=from_email, from_name=from_name)


def send_email_brevo(
    to_addr: str,
    subject: str,
    body: str,
    settings: BrevoSettings,
    attachments: list | None = None,
) -> None:
    payload: dict = {
        "sender": {"email": settings.from_email, "name": settings.from_name},
        "to": [{"email": to_addr}],
        "subject": subject,
        "textContent": body,
    }

    if attachments:
        payload["attachment"] = []
        for file in attachments or []:
            import base64
            encoded = base64.b64encode(file["content"]).decode("utf-8")
            payload["attachment"].append({
                "name": file["filename"],
                "content": encoded,
            })

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BREVO_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "api-key": settings.api_key,
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"✅ Brevo email sent to {to_addr} (status {resp.status})")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        print(f"❌ Brevo HTTP {e.code}: {error_body}")
        raise RuntimeError(f"Brevo API error {e.code}: {error_body}") from e
    except Exception as e:
        print(f"❌ Brevo send failed: {e}")
        raise

if __name__ == "__main__":
    settings = load_brevo_settings()

    if not settings:
        print("❌ Missing Brevo configuration")
        print("Make sure these env variables exist:")
    
        print("BREVO_FROM_EMAIL")
        print("BREVO_FROM_NAME")
        exit()

    try:
        send_email_brevo(
            to_addr="jariljohnson136@gmail.com",   # change this
            subject="Brevo Test Email",
            body="Hello! This is a test email from Python using Brevo API.",
            settings=settings,
        )

        print("✅ Test email sent successfully!")

    except Exception as e:
        print("❌ Failed to send test email")
        print(e)
