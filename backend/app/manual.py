from typing import Any, Dict, List, Optional
from app.email_brevo_service import BrevoSettings, send_email_brevo


class ManualEmailSender:
    def __init__(self, emails: List[Dict], settings: BrevoSettings | None, state):
        self.emails = emails
        self.settings = settings
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
            if self.settings:
                send_email_brevo(
                    to_addr=email["to"],
                    subject=email["subject"],
                    body=email["body"],
                    settings=self.settings,
                    attachments=email.get("attachments", []),
                )

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
            "status": "sent" if idx in self._sent_indices else "skipped" if idx in self._skipped_indices else "pending",
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
        email = self.emails[index]
        send_subject = subject if subject is not None else email["subject"]
        send_body = body if body is not None else email["body"]
        try:
            if self.settings:
                send_email_brevo(
                    to_addr=email["to"],
                    subject=send_subject,
                    body=send_body,
                    settings=self.settings,
                    attachments=email.get("attachments", []),
                )
            self._sent_indices.add(index)
            return {
                "to": email["to"],
                "status": "sent",
                "index": index,
            }
        except Exception as e:
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
                    "status": "sent" if i in self._sent_indices else "skipped" if i in self._skipped_indices else "pending",
                    "is_current": i == self.current_index,
                }
                for i, e in enumerate(self.emails)
            ],
        }
