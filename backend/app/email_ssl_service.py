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
    to_addr: str,
    subject: str,
    body: str,
    settings: SMTPSettings,
    attachments=None
) -> None:
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