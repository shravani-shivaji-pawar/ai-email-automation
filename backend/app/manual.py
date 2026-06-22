from typing import Any, Dict, List, Optional


def _send_one(email: dict, sender_info: dict | None, smtp_settings) -> None:
    """
    Send a single email using Gmail API (if connected) or SMTP fallback.

    sender_info : the active_sender dict  {"email": ..., "password": ...}  or None
    smtp_settings : a pre-built email_ssl_service.SMTPSettings (env fallback) or None
    """
    to_addr = email["to"]
    subject = email["subject"]
    body = email["body"]
    attachments = email.get("attachments", [])

    # ── 1. Gmail API (priority) ───────────────────────────────────────────────
    if sender_info and sender_info.get("email"):
        try:
            from app.database import is_gmail_connected
            if is_gmail_connected(sender_info["email"]):
                from app.gmail_service import send_email_gmail
                send_email_gmail(sender_info["email"], to_addr, subject, body)
                print(f"✅ [Manual] Sent via Gmail API → {to_addr}")
                return
        except Exception as gmail_err:
            # Gmail API failed; fall through to SMTP
            print(f"⚠️ [Manual] Gmail API failed ({gmail_err}), falling back to SMTP")

    # ── 2. SMTP with active sender credentials ────────────────────────────────
    if sender_info and sender_info.get("email"):
        from app.email_ssl_service import SMTPSettings, send_email_smtp
        # Only use password-based SMTP if a password is actually stored
        password = (sender_info.get("password") or "").strip()
        if password:
            smtp = SMTPSettings(
                host="smtp.gmail.com",
                port=465,
                user=sender_info["email"],
                password=password,
                from_addr=sender_info["email"],
                use_tls=True,
            )
            print(f"⚠️ [Manual] Sending via SMTP (SSL) as {sender_info['email']} → {to_addr}")
            send_email_smtp(to_addr, subject, body, smtp, attachments or None)
            return
        else:
            print(f"⚠️ [Manual] Active sender has no password stored; skipping SMTP for {sender_info['email']}")

    # ── 3. Env-based SMTP fallback (no active sender or no password) ──────────
    if smtp_settings is not None:
        from app.email_ssl_service import send_email_smtp
        send_email_smtp(to_addr, subject, body, smtp_settings, attachments or None)
        return

    raise RuntimeError(
        "No sender configured — connect Gmail OAuth or add a sender account with a password, "
        "or set SMTP env vars (SMTP_HOST, SMTP_FROM, SMTP_USER, SMTP_PASSWORD)."
    )


class ManualEmailSender:
    def __init__(
        self,
        emails: List[Dict],
        sender_info: dict | None,
        smtp_settings,
        state,
    ):
        """
        emails        – list of {to, subject, body, attachments}
        sender_info   – active_sender dict {"email": ..., "password": ...} or None
        smtp_settings – email_ssl_service.SMTPSettings (env fallback) or None
        state         – app state (kept for compatibility)
        """
        self.emails = emails
        self.sender_info = sender_info
        self.smtp_settings = smtp_settings
        self.state = state
        self.index = 0
        self.current_index = 0
        self._sent_indices: set = set()
        self._skipped_indices: set = set()

    def preview_next(self) -> Optional[Dict]:
        if self.index >= len(self.emails):
            return None
        return self.emails[self.index]

    def send_next(self) -> Dict:
        if self.index >= len(self.emails):
            return {"message": "All emails sent"}

        email = self.emails[self.index]

        try:
            _send_one(email, self.sender_info, self.smtp_settings)
            result = {
                "to": email["to"],
                "status": "sent",
                "index": self.index,
            }
            self._sent_indices.add(self.index)
            self.index += 1
            self.current_index = self.index
            return result

        except Exception as e:
            print(f"❌ [Manual] send_next failed for {email['to']}: {e}")
            return {"to": email["to"], "status": "failed", "error": str(e)}

    def skip_next(self):
        if self.index < len(self.emails):
            skipped = self.emails[self.index]["to"]
            self._skipped_indices.add(self.index)
            self.index += 1
            self.current_index = self.index
            return {"message": f"Skipped {skipped}"}
        return {"message": "Nothing to skip"}

    def status(self):
        return {
            "total": len(self.emails),
            "current_index": self.index,
            "remaining": len(self.emails) - self.index,
            "sent": len(self._sent_indices),
            "skipped": len(self._skipped_indices),
        }

    def has_more(self) -> bool:
        return self.index < len(self.emails)

    def peek_at(self, index: int) -> dict:
        if not self.emails:
            return {"message": "No emails loaded"}
        idx = max(0, min(index, len(self.emails) - 1))
        e = self.emails[idx]
        return {
            "index": idx,
            "total": len(self.emails),
            "to": e["to"],
            "subject": e["subject"],
            "body": e["body"],
            "status": (
                "sent" if idx in self._sent_indices
                else "skipped" if idx in self._skipped_indices
                else "pending"
            ),
        }

    def go_prev(self) -> dict:
        if self.current_index > 0:
            self.current_index -= 1
        return self.peek_at(self.current_index)

    def go_next(self) -> dict:
        if self.current_index < len(self.emails) - 1:
            self.current_index += 1
        return self.peek_at(self.current_index)

    def send_by_index(self, index: int, subject: str = None, body: str = None) -> Dict:
        if index < 0 or index >= len(self.emails):
            return {"message": "Invalid index"}
        email = dict(self.emails[index])
        if subject is not None:
            email["subject"] = subject
        if body is not None:
            email["body"] = body
        try:
            _send_one(email, self.sender_info, self.smtp_settings)
            self._sent_indices.add(index)
            return {"to": email["to"], "status": "sent", "index": index}
        except Exception as e:
            print(f"❌ [Manual] send_by_index failed for {email['to']}: {e}")
            return {"to": email["to"], "status": "failed", "error": str(e)}

    def skip_by_index(self, index: int) -> Dict:
        if index < 0 or index >= len(self.emails):
            return {"message": "Invalid index"}
        email = self.emails[index]
        self._skipped_indices.add(index)
        return {"to": email["to"], "status": "skipped", "index": index}

    def list_all(self) -> dict:
        return {
            "current_index": self.current_index,
            "total": len(self.emails),
            "contacts": [
                {
                    "index": i,
                    "to": e["to"],
                    "subject": e["subject"],
                    "body": e["body"],
                    "status": (
                        "sent" if i in self._sent_indices
                        else "skipped" if i in self._skipped_indices
                        else "pending"
                    ),
                    "is_current": i == self.current_index,
                }
                for i, e in enumerate(self.emails)
            ],
        }