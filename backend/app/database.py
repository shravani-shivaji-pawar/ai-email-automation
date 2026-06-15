import os
import sqlite3
import hashlib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.getenv("DATABASE_URL", os.path.join(BASE_DIR, "users.db"))
if DB_NAME.startswith("sqlite:///"):
    DB_NAME = DB_NAME.replace("sqlite:///", "")

SMTP_PROVIDERS = {
    "smtp2go": {"host": "mail.smtp2go.com", "port": 587, "use_tls": True, "user_is_apikey": True},
    "sendgrid": {"host": "smtp.sendgrid.net", "port": 587, "use_tls": True, "user_is_apikey": True},
    "mailgun": {"host": "smtp.mailgun.org", "port": 587, "use_tls": True, "user_is_apikey": False},
    "gmail": {"host": "smtp.gmail.com", "port": 465, "use_tls": True, "user_is_apikey": False},
}

def resolve_smtp_config(provider: str, email: str, api_key_or_password: str, custom_host=None, custom_port=None):
    """Return (smtp_host, smtp_port, smtp_user, smtp_password, smtp_use_tls) from provider preset or custom."""
    prov = SMTP_PROVIDERS.get(provider)
    if prov:
        host = prov["host"]
        port = prov["port"]
        use_tls = prov["use_tls"]
        user = api_key_or_password if prov["user_is_apikey"] else email
        password = api_key_or_password
    else:
        host = custom_host or "smtp.gmail.com"
        port = custom_port or 465
        use_tls = True
        user = email
        password = api_key_or_password
    return host, port, user, password, use_tls


# =========================
# HASH PASSWORD
# =========================
def hash_password(password: str):
    if not password:
        return ""
    return hashlib.sha256(password.encode()).hexdigest()


# =========================
# INIT USERS TABLE
# =========================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            phone TEXT,
            password TEXT,
            role TEXT,
            app_password TEXT
        )
    """)

    # Backward-compatible migration: old DBs may not have app_password.
    cursor.execute("PRAGMA table_info(users)")
    cols = [row[1] for row in cursor.fetchall()]
    if "app_password" not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN app_password TEXT")

    conn.commit()
    conn.close()


# =========================
# CREATE USER
# =========================
def create_user(name, email, phone, password, role, app_password=None):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        hashed_password = hash_password(password)

        cursor.execute("""
            INSERT INTO users (name, email, phone, password, role, app_password)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            name,
            email,
            phone,
            hashed_password,
            role,
            app_password or None
        ))

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        print("DB ERROR:", e)
        return False


# =========================
# VERIFY USER LOGIN
# =========================
def verify_user(email, password):
    user = get_user_by_email(email)

    if not user:
        return None

    if user["password"] == hash_password(password):
        return user

    return None


# =========================
# GET USER
# =========================
def get_user_by_email(email):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "id": row[0],
            "name": row[1],
            "email": row[2],
            "phone": row[3],
            "password": row[4],
            "role": row[5],
            "app_password": row[6],
        }

    return None


# =========================
# CREATE SENDERS TABLE
# =========================
def create_senders_table():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS senders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            organization_name TEXT,
            email TEXT,
            password TEXT
        )
    """)

    cursor.execute("PRAGMA table_info(senders)")
    cols = [row[1] for row in cursor.fetchall()]
    if "smtp_host" not in cols:
        cursor.execute("ALTER TABLE senders ADD COLUMN smtp_host TEXT DEFAULT 'smtp.gmail.com'")
        cursor.execute("ALTER TABLE senders ADD COLUMN smtp_port INTEGER DEFAULT 465")
        cursor.execute("ALTER TABLE senders ADD COLUMN smtp_use_tls INTEGER DEFAULT 1")
    if "smtp2go_api_key" not in cols:
        cursor.execute("ALTER TABLE senders ADD COLUMN smtp2go_api_key TEXT")
    if "verified" not in cols:
        cursor.execute("ALTER TABLE senders ADD COLUMN verified INTEGER DEFAULT 0")

    conn.commit()
    conn.close()


# =========================
# ADD SENDER
# =========================
def add_sender(user_id, name, org_name, email, password, smtp_host=None, smtp_port=None, smtp_use_tls=None, smtp2go_api_key=None, verified=0):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO senders (user_id, name, organization_name, email, password, smtp_host, smtp_port, smtp_use_tls, smtp2go_api_key, verified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, name, org_name, email, password, smtp_host, smtp_port, smtp_use_tls, smtp2go_api_key, verified))

    conn.commit()
    conn.close()


# =========================
# GET SENDERS
# =========================
def get_senders(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, organization_name, email, verified
        FROM senders
        WHERE user_id = ?
    """, (user_id,))

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "id": r[0],
            "name": r[1],
            "organization_name": r[2],
            "email": r[3],
            "verified": bool(r[4]) if len(r) > 4 else False,
            "gmail_connected": is_gmail_connected(r[3]),
        }
        for r in rows
    ]


# =========================
# GET SINGLE SENDER
# =========================
def get_sender_by_id(sender_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM senders WHERE id = ?", (sender_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "id": row[0],
            "user_id": row[1],
            "name": row[2],
            "organization_name": row[3],
            "email": row[4],
            "password": row[5],
            "smtp_host": row[6] if len(row) > 6 else "smtp.gmail.com",
            "smtp_port": row[7] if len(row) > 7 else 465,
            "smtp_use_tls": bool(row[8]) if len(row) > 8 else True,
            "smtp2go_api_key": row[9] if len(row) > 9 else None,
            "verified": bool(row[10]) if len(row) > 10 else False,
        }

    return None


# =========================
# GMAIL OAUTH TOKENS TABLE
# =========================
def create_gmail_tokens_table():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gmail_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT UNIQUE,
            refresh_token TEXT,
            access_token TEXT,
            token_expiry TEXT,
            connected_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def save_gmail_token(user_email: str, refresh_token: str, access_token: str = None, token_expiry=None):
    """Insert or update the stored Gmail OAuth token for a user."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    expiry_str = token_expiry.isoformat() if hasattr(token_expiry, "isoformat") else token_expiry

    cursor.execute("SELECT refresh_token FROM gmail_tokens WHERE user_email = ?", (user_email,))
    existing = cursor.fetchone()

    if existing:
        # Google only returns refresh_token on first consent; keep old one if new is empty
        new_refresh = refresh_token or existing[0]
        cursor.execute("""
            UPDATE gmail_tokens
            SET refresh_token = ?, access_token = ?, token_expiry = ?
            WHERE user_email = ?
        """, (new_refresh, access_token, expiry_str, user_email))
    else:
        cursor.execute("""
            INSERT INTO gmail_tokens (user_email, refresh_token, access_token, token_expiry)
            VALUES (?, ?, ?, ?)
        """, (user_email, refresh_token, access_token, expiry_str))

    conn.commit()
    conn.close()


def get_gmail_token(user_email: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_email, refresh_token, access_token, token_expiry, connected_at
        FROM gmail_tokens WHERE user_email = ?
    """, (user_email,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "user_email": row[0],
            "refresh_token": row[1],
            "access_token": row[2],
            "token_expiry": row[3],
            "connected_at": row[4],
        }
    return None


def update_gmail_access_token(user_email: str, access_token: str, token_expiry=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    expiry_str = token_expiry.isoformat() if hasattr(token_expiry, "isoformat") else token_expiry

    cursor.execute("""
        UPDATE gmail_tokens SET access_token = ?, token_expiry = ?
        WHERE user_email = ?
    """, (access_token, expiry_str, user_email))

    conn.commit()
    conn.close()


def delete_gmail_token(user_email: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM gmail_tokens WHERE user_email = ?", (user_email,))
    conn.commit()
    conn.close()


def is_gmail_connected(user_email: str) -> bool:
    return get_gmail_token(user_email) is not None


# =========================
# INIT ALL TABLES
# =========================
def setup_database():
    init_db()
    create_senders_table()
    create_gmail_tokens_table()


setup_database()