import json
import urllib.request
import urllib.error
import time
import re
import os
from imap_tools import MailBox
from dotenv import load_dotenv

load_dotenv()

SMTP2GO_API_URL = "https://api.smtp2go.com/v3/single_sender_emails/add"

VERIFY_SENDER = "ticket@smtp2go.com"
VERIFY_KEYWORDS = ["verify", "confirm", "activate", "smtp2go"]


def add_sender_via_api(api_key: str, email: str) -> dict:
    payload = json.dumps({"email_address": email}).encode("utf-8")
    req = urllib.request.Request(
        SMTP2GO_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Smtp2go-Api-Key": api_key,
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return {"success": True, "request_id": body.get("request_id")}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"SMTP2GO API error {e.code}: {error_body}")
    except Exception as e:
        raise RuntimeError(f"SMTP2GO API call failed: {e}")


def _extract_verify_url(text: str) -> str | None:
    if not text:
        return None
    urls = re.findall(r'https?://[^\s"\'<>]+', text)
    for url in urls:
        if any(kw in url.lower() for kw in VERIFY_KEYWORDS):
            return url
    return None


def _click_url(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


def auto_verify_sender(
    sender_email: str,
    imap_host: str | None = None,
    imap_user: str | None = None,
    imap_pass: str | None = None,
    timeout: int = 90,
) -> dict:
    _host = imap_host or os.getenv("IMAP_HOST", "")
    _user = imap_user or os.getenv("SMTP_USER", "")
    _pass = imap_pass or os.getenv("SMTP_PASSWORD", "")

    if not _host or not _user or not _pass:
        return {"verified": False, "method": "none", "detail": "No IMAP credentials available"}

    deadline = time.time() + timeout
    poll_interval = 5

    while time.time() < deadline:
        try:
            with MailBox(_host).login(_user, _pass, "INBOX") as mailbox:
                for msg in mailbox.fetch(limit=20, reverse=True):
                    from_addr = (msg.from_ or "").strip().lower()
                    if VERIFY_SENDER not in from_addr:
                        continue
                    body_text = msg.text or msg.html or ""
                    url = _extract_verify_url(body_text)
                    if url:
                        if _click_url(url):
                            return {"verified": True, "method": "imap", "detail": "Verification link clicked"}
                        return {"verified": False, "method": "imap", "detail": "Failed to click verification link"}
            remaining = max(1, int(deadline - time.time()))
            time.sleep(min(poll_interval, remaining))
        except Exception as e:
            return {"verified": False, "method": "imap", "detail": f"IMAP error: {e}"}

    return {"verified": False, "method": "imap", "detail": "Verification email not found within timeout"}
