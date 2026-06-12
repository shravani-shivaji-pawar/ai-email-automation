import os
import smtplib
import time
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from imap_tools import MailBox

load_dotenv()

# ================= SMTP =================
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM")

# ================= IMAP =================
IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_USER = os.getenv("SMTP_USER")
IMAP_PASS = os.getenv("SMTP_PASSWORD")


# ================= SEND EMAIL =================
def send_email(to_email: str):
    print(f"\n📤 Sending to {to_email}")

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = "Test Email Bounce Detection"

    body = "This is a test email for bounce detection."
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())

        print("✅ Sent successfully (accepted by server)")

    except Exception as e:
        print("❌ Send failed:", str(e))


# ================= EXTRACT EMAIL =================
def extract_email(text: str):
    match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    return match.group(0) if match else None


# ================= CHECK BOUNCES =================
from datetime import datetime, timedelta, timezone

BOUNCE_SENDERS = [
    "mailer-daemon@googlemail.com",
    "mailer-daemon@gmail.com",
    "postmaster@gmail.com",
    "postmaster@googlemail.com",
    "noreply@googlemail.com",
    "noreply@gmail.com",
    "google-noreply@google.com"
]

BOUNCE_KEYWORDS = [
    "delivery status notification",
    "undelivered",
    "mail delivery subsystem",
    "failure",
    "returned to sender",
    "address not found",
    "550",
    "5.1.1",
    "recipient address rejected",
    "user unknown",
    "host not found",
    "mailbox unavailable",
    "bounce",
    "delivery failed"
]

# from datetime import datetime, timedelta, timezone

# def check_bounces():
#     print("\n📥 Checking recent bounce emails (SMART MODE)...")

#     bounced = []
#     cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)

#     with MailBox(IMAP_HOST).login(IMAP_USER, IMAP_PASS) as mailbox:

#         for msg in mailbox.fetch('(FROM "mailer-daemon@googlemail.com")', limit=50):

#             if msg.date < cutoff:
#                 continue

#             print(f"📧 {msg.subject}")

#             body = msg.text or msg.html or ""
#             email = extract_email(body)

#             if email:
#                 bounced.append({
#                     "email": email,
#                     "reason": msg.subject,
#                     "date": msg.date.isoformat()
#                 })

#     return bounced

# ================= CHECK BOUNCES =================
from datetime import datetime, timedelta, timezone

# ================= CHECK BOUNCES =================
def check_bounces(imap_host=None, imap_user=None, imap_pass=None):
    print("\n📥 Checking recent bounce emails in ALL folders (INBOX + SPAM + more)...")

    # resolve params
    _host = imap_host or IMAP_HOST
    _user = imap_user or IMAP_USER
    _pass = imap_pass or IMAP_PASS

    bounced = []

    # only recent emails (last 30 mins)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)

    with MailBox(_host).login(_user, _pass) as mailbox:

        # Get all available folders
        all_folders = mailbox.folder.list()
        
        # Priority folders to scan first
        priority_folders = ["INBOX", "[Gmail]/Spam", "Spam", "Junk", "[Gmail]/Trash", "Trash"]
        
        # Build folder list: priority folders first, then any others that might contain bounces
        folders_to_scan = []
        for pf in priority_folders:
            for f in all_folders:
                if f.name.lower() == pf.lower() or pf.lower() in f.name.lower():
                    folders_to_scan.append(f.name)
                    break
        
        # Also add any folder that might contain bounce-related emails
        for f in all_folders:
            if f.name not in folders_to_scan:
                fname_lower = f.name.lower()
                if any(kw in fname_lower for kw in ["spam", "junk", "bounce", "mail delivery", "postmaster"]):
                    folders_to_scan.append(f.name)
        
        # Deduplicate
        folders_to_scan = list(dict.fromkeys(folders_to_scan))
        
        # If no folders found, fallback to INBOX and Spam
        if not folders_to_scan:
            folders_to_scan = ["INBOX", "[Gmail]/Spam", "Spam"]

        # Bounce-specific search criteria
        bounce_from_patterns = [
            "mailer-daemon",
            "mail delivery subsystem",
            "postmaster",
            "noreply",
            "mail delivery",
            "delivery status",
            "daemon",
        ]

        seen_uids = set()

        for folder in folders_to_scan:

            try:
                mailbox.folder.set(folder)
                print(f"\n📂 Scanning folder: {folder}")

            except Exception as e:
                print(f"❌ Cannot open {folder}: {e}")
                continue

            # Fetch recent unread emails (no FROM filter to catch all potential bounces)
            for msg in mailbox.fetch("UNSEEN", limit=100):

                try:
                    # skip old mails
                    if not msg.date or msg.date < cutoff:
                        continue

                    subject = (msg.subject or "").lower()
                    body = (msg.text or msg.html or "").lower()
                    sender = (msg.from_ or "").lower()

                    # Check if this is a bounce email by looking for:
                    # 1. "Mail Delivery Subsystem" in sender or subject
                    # 2. Bounce sender patterns
                    # 3. Bounce keywords in subject/body
                    
                    is_mail_delivery_subsystem = (
                        "mail delivery subsystem" in sender
                        or "mail delivery subsystem" in subject
                        or "mail delivery subsystem" in body
                    )

                    is_bounce_sender = any(
                        pattern in sender for pattern in bounce_from_patterns
                    )

                    is_bounce_keyword = any(
                        kw in subject or kw in body
                        for kw in BOUNCE_KEYWORDS
                    )

                    # Also check for common bounce indicators
                    is_bounce_indicator = (
                        "delivery status notification" in subject
                        or "undeliverable" in subject
                        or "failure notice" in subject
                        or "returned mail" in subject
                        or "mail could not be delivered" in body
                        or "the following address" in body
                        or "permanent error" in body
                        or "temporary error" in body
                    )

                    if is_mail_delivery_subsystem or is_bounce_sender or is_bounce_keyword or is_bounce_indicator:

                        failed_email = extract_email(body)

                        # Skip if we already processed this UID
                        msg_uid = getattr(msg, 'uid', None)
                        if msg_uid and msg_uid in seen_uids:
                            continue
                        if msg_uid:
                            seen_uids.add(msg_uid)

                        print("\n🚨 BOUNCE FOUND")
                        print("FOLDER:", folder)
                        print("FROM:", sender)
                        print("SUBJECT:", msg.subject)
                        print("FAILED EMAIL:", failed_email)

                        if (
                            failed_email
                            and failed_email not in [b["email"] for b in bounced]
                        ):
                            bounced.append({
                                "email": failed_email,
                                "reason": msg.subject,
                                "folder": folder,
                                "date": msg.date.isoformat()
                            })

                except Exception as e:
                    print("❌ Error reading message:", e)

    return bounced
    

# ================= MAIN TEST =================
if __name__ == "__main__":

    test_emails = [
        # "test@example.com",
        "invalid-email-1234567890@nonexistent-domain-99999.com",
        # "bounce@testdomainxyz12345.com"
    ]

    print("🚀 Starting bounce detection test...")
    print(f"📧 Sending {len(test_emails)} test emails...")

    for email in test_emails:
        send_email(email)

    print("\n⏳ Waiting 15 seconds for bounces to arrive...")
    time.sleep(15)

    print("\n🔍 Scanning INBOX and Spam folders for bounces...")
    results = check_bounces()

    print("\n📊 Bounce Results:")
    for r in results:
        print(r)

    if not results:
        print("⚠️ No bounce emails detected yet")
