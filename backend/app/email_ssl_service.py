import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv
import os
from typing import NamedTuple


load_dotenv()

class SMTPSettings(NamedTuple):
    host: str
    port: int
    user: str | None
    password: str | None
    from_addr: str
    use_tls: bool


def load_smtp_settings() -> SMTPSettings | None:
    host = os.getenv("SMTP_HOST", "").strip()
    from_addr = os.getenv("SMTP_FROM", "").strip()
    if not host or not from_addr:
        return None

    port = 465
    user = os.getenv("SMTP_USER", "").strip() or None
    password = os.getenv("SMTP_PASSWORD", "").strip() or None

    return SMTPSettings(
        host=host,
        port=port,
        user=user,
        password=password,
        from_addr=from_addr,
        use_tls=True,
    )


def send_email_smtp(
    to_addr: str = None,
    subject: str = None,
    body: str = None,
    settings: SMTPSettings = None,
    attachments=None,
    # Legacy keyword-arg style used in bulk worker
    smtp_email: str = None,
    smtp_password: str = None,
    to_email: str = None,
    smtp_settings: SMTPSettings = None,
) -> None:
    # ── Normalise arguments ──────────────────────────────────────────────────
    # Support: send_email_smtp(to_addr, subject, body, settings, attachments)
    # Support: send_email_smtp(smtp_email=..., smtp_password=..., to_email=..., subject=..., body=...)
    # Support: send_email_smtp(smtp_settings=..., to_email=..., subject=..., body=...)
    if to_email and not to_addr:
        to_addr = to_email
    if smtp_settings and not settings:
        settings = smtp_settings
    if smtp_email and not settings:
        settings = SMTPSettings(
            host="smtp.gmail.com",
            port=465,
            user=smtp_email,
            password=smtp_password or "",
            from_addr=smtp_email,
            use_tls=True,
        )
    if not to_addr or not settings:
        raise ValueError("send_email_smtp requires to_addr and settings (or smtp_email/smtp_password)")
    print("🔌 Connecting to SMTP server (SSL mode, port 465)...")
    print(f"📤 Preparing to send email to: {to_addr}")

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = settings.from_addr
    msg["To"] = to_addr

    msg.attach(MIMEText(body, "plain", "utf-8"))

    if attachments:
        print(f"📎 Attaching {len(attachments)} files...")
        for file in attachments:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(file["content"])
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{file["filename"]}"'
            )
            msg.attach(part)

    try:
        is_ssl = settings.port == 465
        if is_ssl:
            with smtplib.SMTP_SSL(settings.host, settings.port, timeout=30) as server:
                print(f"✅ Connected via SSL (port {settings.port})")
                if settings.user and settings.password:
                    print(f"🔑 Logging in as: {settings.user}")
                    server.login(settings.user, settings.password)
                print("📨 Sending email...")
                server.sendmail(settings.from_addr, [to_addr], msg.as_string())
                print("🎉 Email sent successfully (SSL)")
        else:
            with smtplib.SMTP(settings.host, settings.port, timeout=30) as server:
                print(f"✅ Connected to SMTP (port {settings.port})")
                if settings.use_tls:
                    print("🔐 Starting TLS...")
                    server.starttls()
                if settings.user and settings.password:
                    print(f"🔑 Logging in as: {settings.user}")
                    server.login(settings.user, settings.password)
                print("📨 Sending email...")
                server.sendmail(settings.from_addr, [to_addr], msg.as_string())
                print("🎉 Email sent successfully (STARTTLS)")
    except Exception as e:
        print("❌ ERROR while sending email:", str(e))
        raise