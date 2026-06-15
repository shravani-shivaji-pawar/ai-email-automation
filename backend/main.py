from __future__ import annotations
from datetime import datetime, timezone, timedelta
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import threading
import types as _types
import uuid
from typing import Any
import imaplib
from fastapi import Body, FastAPI, File, HTTPException, UploadFile, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import hashlib
import re
import os
from imap_tools import MailBox

# =========================
# REDIS CACHING SETUP
# =========================
import json
import logging

logger = logging.getLogger(__name__)

# Redis configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
EMAIL_CACHE_TTL = 1800  # 30 minutes cache

_redis_client = None

def _get_redis():
    """Get Redis client with lazy initialization"""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD,
                db=REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            _redis_client.ping()  # Test connection
            logger.info(f"✅ Redis connected: {REDIS_HOST}:{REDIS_PORT}")
        except Exception as e:
            logger.warning(f"⚠️ Redis not available: {e}")
            _redis_client = None
    return _redis_client

def _get_cached_emails(user_email: str) -> list | None:
    """Get emails from Redis cache"""
    try:
        client = _get_redis()
        if client:
            data = client.get(f"email_cache:{user_email}")
            if data:
                logger.info(f"📬 Cache HIT for {user_email}")
                return json.loads(data)
    except Exception as e:
        logger.warning(f"Cache get error: {e}")
    return None

def _set_cached_emails(user_email: str, emails: list):
    """Store emails in Redis cache"""
    try:
        client = _get_redis()
        if client:
            client.setex(
                f"email_cache:{user_email}",
                EMAIL_CACHE_TTL,
                json.dumps(emails, default=str)
            )
            logger.info(f"📬 Cache SET for {user_email}: {len(emails)} emails")
    except Exception as e:
        logger.warning(f"Cache set error: {e}")

def _invalidate_cache(user_email: str):
    """Clear cache for a user"""
    try:
        client = _get_redis()
        if client:
            client.delete(f"email_cache:{user_email}")
            logger.info(f"🗑️ Cache cleared for {user_email}")
    except Exception as e:
        logger.warning(f"Cache invalidate error: {e}")

from app.ai_client import API_KEY, answer_email_question, enhance_email
from app.email_ssl_service import load_smtp_settings, send_email_smtp
from app.excel_utils import (
    detect_email_column,
    detect_first_name_column,
    parse_excel,
    personalize_message,
)
from app.schemas import (
    ChatTurnRequest,
    EmailActionRequest,
    EmailBulkActionRequest,
    EnhanceRequest,
    GenerateRequest,
    PreviewRequest,
    PromptQueryRequest,
    SendRequest,
)
from app.manual import ManualEmailSender
from test import check_bounces

from app.database import (
    init_db,
    create_user,
    get_user_by_email,
    create_senders_table,
    add_sender,
    get_senders,
    get_sender_by_id,
    create_gmail_tokens_table,
    save_gmail_token,
    get_gmail_token,
    delete_gmail_token,
    is_gmail_connected,
)
from app.auth_google import get_auth_url, get_flow, fetch_tokens, get_user_info, verify_state
from app.gmail_service import send_email_gmail, GmailAuthError
from app.vector_search import (
    DEFAULT_EMBED_MODEL,
    VectorHit,
    get_chat_history,
    init_chat_tables,
    init_vector_tables,
    semantic_search,
    upsert_email_embedding,
)

app = FastAPI(title="AI Email Automation Agent")

# CORS middleware
_default_cors_origins = "http://localhost:5173,https://ai-email-automation-1.vercel.app"
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", _default_cors_origins).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FAST_CONTEXT_EMAIL_LIMIT = 10  # Reduced for faster LLM response
FAST_BODY_CHAR_LIMIT = 600  # Shorter preview
INSIGHTS_CACHE_TTL_S = 300
INBOX_CACHE_TTL_S = 45
IMAP_UNLIMITED_HARD_MAX = 2500
IMAP_SCAN_BUDGET_S = 60  # Increased to allow fetching more emails

init_db()
create_senders_table()
create_gmail_tokens_table()
_DB_CONN = None

# Google OAuth redirect URI (must match Google Cloud Console + frontend env)
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "https://ai-email-backend-r2bw.onrender.com/google/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# ════════════════════════════════════════
# THREAD SAFE SEND STATE
# ════════════════════════════════════════

send_lock = threading.Lock()

parallel_send_state = {
    "running": False,
    "processed": 0,
    "delivered": 0,
    "failed": 0,
    "total": 0,
}
def send_emails_worker(
    sender_email: str,
    sender_password: str,
    subject: str,
    message_template: str,
    contacts: list,
    job_id: str,
):
    """
    Background thread worker.
    Each sender gets its own thread/job.
    """

    global parallel_send_state

    total = len(contacts)

    # create job entry
    with send_lock:
        parallel_send_state[job_id] = {
            "job_id": job_id,
            "from_email": sender_email,
            "total": total,
            "processed": 0,
            "delivered": 0,
            "failed": 0,
            "current_email": "",
            "in_progress": True,
            "started_at": time.time(),
        }

    for idx, row in enumerate(contacts):

        try:
            # detect receiver email column
            email_col = detect_email_column(row.keys())

            if not email_col:
                continue

            to_email = str(row[email_col]).strip()

            # update live progress
            with send_lock:
                parallel_send_state[job_id]["current_email"] = to_email

            # personalize email
            personalized_message = personalize_message(
                message_template,
                row,
            )

            # SEND EMAIL
            send_email_smtp(
                smtp_email=sender_email,
                smtp_password=sender_password,
                to_email=to_email,
                subject=subject,
                body=personalized_message,
            )

            # success update
            with send_lock:
                parallel_send_state[job_id]["processed"] += 1
                parallel_send_state[job_id]["delivered"] += 1

        except Exception as e:

            print(f"[THREAD ERROR] {e}")

            with send_lock:
                parallel_send_state[job_id]["processed"] += 1
                parallel_send_state[job_id]["failed"] += 1

    # mark completed
    with send_lock:
        parallel_send_state[job_id]["in_progress"] = False
def _db():
    # Process-wide SQLite connection for low-latency lookups.
    # Note: this is safe for dev and typical single-process uvicorn usage.
    global _DB_CONN
    if _DB_CONN is None:
        import sqlite3

        _DB_CONN = sqlite3.connect("users.db", check_same_thread=False, timeout=30)
        init_vector_tables(_DB_CONN)
        init_chat_tables(_DB_CONN)
    return _DB_CONN


def _clean_human_date(text: str) -> str:
    cleaned = text.lower().strip()
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _parse_human_date(text: str) -> datetime | None:
    value = _clean_human_date(text)
    patterns = [
        "%d %B %Y",
        "%d %b %Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
    ]
    for fmt in patterns:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _extract_date_range_from_question(question: str) -> tuple[datetime | None, datetime | None]:
    match = re.search(r"from\s+(.+?)\s+to\s+(.+?)(?:$|[?.!,])", question, flags=re.IGNORECASE)
    if not match:
        return None, None

    start_raw, end_raw = match.group(1), match.group(2)
    start = _parse_human_date(start_raw)
    end = _parse_human_date(end_raw)
    if not start or not end:
        return None, None
    if end < start:
        start, end = end, start
    end = end.replace(hour=23, minute=59, second=59, microsecond=0)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, end


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _active_mail_credentials() -> tuple[str, str]:
    active = state.get("active_sender")
    if active and active.get("email") and active.get("password"):
        return active["email"], active["password"]
    env_user = os.getenv("SMTP_USER", "").strip()
    env_pass = os.getenv("SMTP_PASSWORD", "").strip()
    if env_user and env_pass:
        return env_user, env_pass
    raise HTTPException(status_code=400, detail="No active sender credentials found for email insights.")


def _extract_sender_email(raw_from: str) -> str:
    match = re.search(r"<([^>]+)>", raw_from or "")
    if match:
        return match.group(1).strip().lower()
    return (raw_from or "").strip().lower()


def _detect_intent(question: str) -> str:
    q = question.lower()
    if "action item" in q or "todo" in q or "next step" in q:
        return "action_items"
    if "unread" in q or "follow up" in q or "follow-up" in q:
        return "unread_followups"
    if "urgent" in q or "asap" in q or "immediately" in q or "priority" in q:
        return "urgent_mails"
    if "summary" in q or "summarize" in q or "overview" in q:
        return "summary"
    # Search intents
    if "find" in q or "search" in q or "look for" in q or "locate" in q:
        return "search_emails"
    # Bulk action intents
    if any(k in q for k in ("mark read", "mark unread", "delete", "trash", "spam", "important", "star")):
        return "email_action"
    return "general_qa"


def _extract_sender_from_question(question: str) -> str | None:
    """Extract email address or sender name from question."""
    q = (question or "").strip()

    # Pattern: "from email@example.com" or "from john"
    patterns = [
        r"from\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
        r"from\s+<([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>",
        r"from\s+([a-zA-Z][a-zA-Z\s]{2,20})\s",
        r"(?:sender|from)\s+(?:is|was)?\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
    ]

    for pat in patterns:
        match = re.search(pat, q, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip().lower()

    return None


def _extract_date_range(question: str) -> tuple[datetime | None, datetime | None]:
    """Extract date range from question like 'last week', 'last 10 emails', etc."""
    q = (question or "").lower()
    now = datetime.now(timezone.utc)

    # "last N emails" - return None for limit, caller should extract number
    if re.search(r"last\s+(\d+)\s+email", q):
        return None, None
    if re.search(r"latest\s+(\d+)\s+email", q):
        return None, None
    if re.search(r"top\s+(\d+)\s+email", q):
        return None, None

    # "last week"
    if "last week" in q:
        start = now - timedelta(days=7)
        return start, now

    # "last month"
    if "last month" in q:
        start = now - timedelta(days=30)
        return start, now

    # "today"
    if "today" in q:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now

    # "yesterday"
    if "yesterday" in q:
        start = now - timedelta(days=1)
        end = start.replace(hour=23, minute=59, second=59)
        return start, end

    # NEW: Single date queries like "on 15 May 2026", "May 15", "15th May"
    # Pattern: "on [date]" or just "[date]" at end of question
    date_patterns = [
        r"on\s+(\d{1,2}\s+\w+\s+\d{4})",           # "on 15 May 2026"
        r"on\s+(\d{1,2}-\w+-\d{4})",               # "on 15-May-2026"
        r"on\s+(\w+\s+\d{1,2},?\s+\d{4})",         # "on May 15, 2026"
        r"(\d{1,2}\s+\w+\s+\d{4})(?:\s|$)",        # "15 May 2026" (at end)
        r"(\d{1,2}\s+\w+)(?:\s|$)",               # "15 May" (current year assumed)
        r"(\w+\s+\d{1,2},?\s+\d{4})(?:\s|$)",     # "May 15 2026"
        r"(\d{1,2}/\d{1,2}/\d{4})",               # "05/15/2026"
        r"(\d{1,2}-\d{1,2}-\d{4})",               # "05-15-2026"
    ]

    for pat in date_patterns:
        match = re.search(pat, q, re.IGNORECASE)
        if match:
            date_str = match.group(1).strip()
            parsed = _parse_human_date(date_str)
            if parsed:
                # Single day range - start and end of that day
                start = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
                end = parsed.replace(hour=23, minute=59, second=59, microsecond=0)
                return start, end

    # Date range patterns: "from Jan 1 to Jan 15" or "between Jan 1 and Jan 15"
    range_match = re.search(r"from\s+(.+?)\s+(?:to|until|and)\s+(.+?)(?:$|[?.!,])", q, flags=re.IGNORECASE)
    if range_match:
        start_raw, end_raw = range_match.group(1), range_match.group(2)
        start = _parse_human_date(start_raw)
        end = _parse_human_date(end_raw)
        if start and end:
            return start, end

    return None, None


def _summarize_emails(snippets: list[dict], sender_filter: str | None = None, limit: int = 10) -> str:
    """Generate an AI-powered summary of emails."""
    if not snippets:
        return "No emails found to summarize."

    # Apply sender filter if specified
    filtered = snippets
    if sender_filter:
        filtered = [s for s in snippets if sender_filter.lower() in (s.get("sender_email") or "").lower()
                    or sender_filter.lower() in (s.get("from") or "").lower()]

    if not filtered:
        return f"No emails found from sender matching '{sender_filter}'."

    # Limit
    filtered = filtered[:limit]

    # Build context for AI
    context_lines = []
    for idx, e in enumerate(filtered, start=1):
        sender = (e.get("sender_email") or e.get("from") or "unknown").strip()
        subject = (e.get("subject") or "(No subject)").strip()
        date = (e.get("date") or "").split("T")[0]
        seen_status = "Read" if e.get("seen", False) else "Unread"
        context_lines.append(
            f"Email {idx}: Date={date}, From={sender}, Subject={subject}, Status={seen_status}"
        )

    email_context = "\n".join(context_lines)

    # Create a prompt for AI summarization - pass as the question
    summary_question = f"Provide a quick summary of these {len(filtered)} emails. What types are there? Any urgent items? Who sent the most?"

    try:
        # Use AI to generate summary - proper way to call the function
        ai_summary = answer_email_question(
            summary_question,
            email_context,
            f"Based on {len(filtered)} emails",
            []
        )
        return ai_summary
    except Exception as e:
        # Fallback to basic summary if AI fails
        unread = sum(1 for s in filtered if not s.get("seen", False))
        by_sender: dict[str, int] = {}
        for e in filtered:
            sender = (e.get("sender_email") or e.get("from") or "unknown").strip().split('<')[0].strip() or "unknown"
            by_sender[sender] = by_sender.get(sender, 0) + 1

        lines = [f"Summary of {len(filtered)} emails ({unread} unread):"]
        if by_sender:
            lines.append("\nTop senders:")
            for sender, count in sorted(by_sender.items(), key=lambda x: x[1], reverse=True)[:4]:
                lines.append(f"  - {sender}: {count}")
        return "\n".join(lines)


def _extract_uid_from_text(text: str) -> str | None:
    q = (text or "").strip()
    if not q:
        return None
    patterns = [
        r"\buid\s*[:#]?\s*(\d{1,12})\b",
        r"\bemail\s*id\s*[:#]?\s*(\d{1,12})\b",
        r"\bmessage\s*id\s*[:#]?\s*(\d{1,12})\b",
        r"\bmail\s*[:#]?\s*(\d{1,12})\b",
    ]
    for pat in patterns:
        match = re.search(pat, q, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_chat_action(text: str) -> str | None:
    q = (text or "").lower().strip()
    if not q:
        return None
    if "unsubscribe" in q:
        return "unsubscribe"
    if "spam" in q or "junk" in q:
        return "move_to_spam"
    if "unread" in q:
        return "mark_unread"
    if ("important" in q) or ("star" in q):
        return "mark_important"
    if ("mark read" in q) or ("as read" in q):
        return "mark_read"
    if "trash" in q or "delete" in q or "remove" in q:
        return "move_to_trash"
    return None


def _resolve_uid_for_chat_action(question: str, explicit_uid: str | None) -> str | None:
    if explicit_uid:
        return explicit_uid
    q = (question or "").lower()
    if any(token in q for token in ("latest", "last", "most recent", "newest")):
        snippets = _fetch_inbox_snippets(None, None, 1, include_body=False, unread_only=False)
        if snippets:
            uid = (snippets[0].get("uid") or "").strip()
            return uid or None
    return None


def _extract_uid_list_from_text(text: str) -> list[str]:
    q = (text or "").strip()
    if not q:
        return []
    hits = re.findall(r"\buid\s*[:#]?\s*(\d{1,12})\b", q, flags=re.IGNORECASE)
    if hits:
        return hits
    # fallback: "uids 12,13,14" or plain numeric sequence in action command
    if re.search(r"\buids?\b", q, flags=re.IGNORECASE):
        nums = re.findall(r"\b\d{1,12}\b", q)
        return nums
    return []


def _extract_limit_from_text(text: str, default_limit: int = 10, max_limit: int = 50) -> int:
    q = (text or "").lower()
    m = re.search(r"\b(?:top|last|latest|recent|first)\s+(\d{1,3})\b", q)
    if not m:
        m = re.search(r"\b(\d{1,3})\s+(?:emails|mails|messages)\b", q)
    if not m:
        return default_limit
    try:
        n = int(m.group(1))
    except Exception:
        n = default_limit
    return max(1, min(n, max_limit))


def _format_email_list(snippets: list[dict[str, Any]]) -> str:
    if not snippets:
        return "No emails found."

    lines = [f"📧 Found {len(snippets)} email(s):\n"]
    for idx, e in enumerate(snippets, start=1):
        subject = (e.get("subject") or "(No subject)").strip()[:60]
        sender = (e.get("from") or "").strip() or "Unknown"
        # Shorten date
        date = (e.get("date", "")[:10]) if e.get("date") else ""
        seen = "✅" if not e.get("seen", False) else "📖"

        # Truncate subject if too long
        if len(subject) > 55:
            subject = subject[:55] + "..."

        lines.append(f"{idx}. {seen} **{sender}**\n   📅 {date} | {subject}")

    return "\n".join(lines)


def _handle_prompt_command(question: str, max_emails: int = 10) -> dict[str, Any] | None:
    q = (question or "").strip()
    ql = q.lower()
    if not q:
        return None

    # Use max_emails from frontend as base limit
    base_limit = max_emails if max_emails > 0 else 10
    use_unlimited = max_emails == 0  # 0 means unlimited scan

    # NEW: Summarize command - check BEFORE list triggers
    if "summarize" in ql or "summary" in ql:
        limit_from_q = _extract_limit_from_text(q, default_limit=base_limit, max_limit=1500)
        limit = limit_from_q if not use_unlimited else 1500
        sender_filter = _extract_sender_from_question(q)
        start, end = _extract_date_range(q)
        snippets = _fetch_inbox_snippets(start, end, limit, include_body=False, unread_only=False)
        summary = _summarize_emails(snippets, sender_filter, limit)
        return {
            "success": True,
            "intent": "chat_summary",
            "answer": summary,
            "emails_used": len(snippets),
            "senders_used": len({s.get("sender_email", "") for s in snippets if s.get("sender_email")}),
        }

    # 1) Full email by UID / latest
    if any(k in ql for k in ("full email", "open email", "read email", "read latest", "read last", "show email", "email body", "details of")):
        uid = _extract_uid_from_text(q)
        if not uid and any(t in ql for t in ("latest", "last", "most recent", "newest")):
            latest = _fetch_inbox_snippets(None, None, 1, include_body=False, unread_only=False)
            uid = (latest[0].get("uid") or "").strip() if latest else None
        if uid:
            full = _imap_fetch_full_email(uid)
            body = (full.get("body") or "").strip()
            return {
                "success": True,
                "intent": "chat_open_email",
                "answer": f"Full email for UID {uid}:\n\n{body if body else '(empty body)'}",
                "emails_used": 1,
                "senders_used": 0,
                "uid": uid,
            }
        return {
            "success": True,
            "intent": "chat_open_email_missing_uid",
            "answer": "Please provide UID, e.g. 'open email uid 12345', or ask 'open latest email'.",
            "emails_used": 0,
            "senders_used": 0,
        }

    # 2) Inbox listing / unread listing / latest listing
    list_triggers = ("list", "show", "recent", "latest", "inbox", "emails", "mails", "messages")
    if any(t in ql for t in list_triggers):
        unread_only = ("unread" in ql and "mark unread" not in ql)
        # Use base_limit from frontend but allow question to override
        limit_from_q = _extract_limit_from_text(q, default_limit=base_limit, max_limit=1500)
        limit = limit_from_q if not use_unlimited else (1500 if limit_from_q <= base_limit else limit_from_q)

        # NEW: Extract date range from question
        start, end = _extract_date_range(q)

        # Also check for sender filter in "from email" pattern
        sender_filter = None
        sender_from_q = _extract_sender_from_question(q)
        if sender_from_q:
            sender_filter = sender_from_q

        # Fallback: try simple "from" pattern
        if not sender_filter:
            m_from = re.search(r"\bfrom\s+([^\n,;]+)", q, flags=re.IGNORECASE)
            if m_from:
                sender_filter = m_from.group(1).strip().lower()

        # Subject filter
        subj_filter = None
        m_subj = re.search(r"\bsubject\s+(?:contains|has|like)?\s*[:=]?\s*([^\n,;]+)", q, flags=re.IGNORECASE)
        if m_subj:
            subj_filter = m_subj.group(1).strip().lower()

        # Fetch with date range and filters
        snippets = _fetch_inbox_snippets(start, end, limit, include_body=False, unread_only=unread_only)

        # Apply sender filter
        if sender_filter:
            snippets = [
                s for s in snippets
                if sender_filter in (s.get("from", "").lower()) or sender_filter in (s.get("sender_email", "").lower())
            ]
        # Apply subject filter
        if subj_filter:
            snippets = [s for s in snippets if subj_filter in (s.get("subject", "").lower())]

        # Add date info to response if filtered
        date_info = ""
        if start and end:
            date_info = f" (from {start.strftime('%d %b')} to {end.strftime('%d %b %Y')})"

        answer = _format_email_list(snippets)
        if date_info and snippets:
            answer = f"📅 Showing emails{date_info}:\n\n" + answer.replace("📧 Found", "")

        return {
            "success": True,
            "intent": "chat_list_emails",
            "answer": answer,
            "emails_used": len(snippets),
            "senders_used": len({s.get("sender_email", "") for s in snippets if s.get("sender_email")}),
            "emails": snippets[:50],
        }

    # 3) Stats command
    if any(t in ql for t in ("stats", "statistics", "count", "summary of inbox", "inbox summary")):
        limit_from_q = _extract_limit_from_text(q, default_limit=base_limit, max_limit=1500)
        limit = limit_from_q if not use_unlimited else 1500
        snippets = _fetch_inbox_snippets(None, None, limit, include_body=False, unread_only=False)
        unread = sum(1 for s in snippets if not s.get("seen", False))
        read = len(snippets) - unread
        top_senders: dict[str, int] = {}
        for s in snippets:
            sender = (s.get("sender_email") or s.get("from") or "(unknown)").strip().lower()
            top_senders[sender] = top_senders.get(sender, 0) + 1
        top = sorted(top_senders.items(), key=lambda kv: kv[1], reverse=True)[:8]
        lines = [
            f"Inbox quick stats (sample size: {len(snippets)}):",
            f"- Read: {read}",
            f"- Unread: {unread}",
            "- Top senders:",
        ]
        for sender, cnt in top:
            lines.append(f"  - {sender}: {cnt}")
        return {
            "success": True,
            "intent": "chat_inbox_stats",
            "answer": "\n".join(lines),
            "emails_used": len(snippets),
            "senders_used": len(top_senders),
        }

    # NEW: Search/Find emails command
    if any(t in ql for t in ("find", "search", "look for", "locate", "where is")):
        limit_from_q = _extract_limit_from_text(q, default_limit=base_limit, max_limit=1500)
        limit = limit_from_q if not use_unlimited else 1500
        sender_filter = _extract_sender_from_question(q)

        # Extract any keywords for subject search
        subj_keywords = []
        # Pattern: "search for X in subject" or "find email about Y"
        m_subj = re.search(r"(?:subject|about)\s+(?:for|with)?\s*(.+?)(?:$|\?)", q, flags=re.IGNORECASE)
        if m_subj:
            subj_keywords = [m_subj.group(1).strip().lower()]

        snippets = _fetch_inbox_snippets(None, None, limit, include_body=False, unread_only=False)

        # Filter by sender
        if sender_filter:
            snippets = [
                s for s in snippets
                if sender_filter in (s.get("from", "").lower()) or sender_filter in (s.get("sender_email", "").lower())
            ]

        # Filter by subject keywords
        for kw in subj_keywords:
            snippets = [s for s in snippets if kw in (s.get("subject", "").lower())]

        if not snippets:
            return {
                "success": True,
                "intent": "chat_search",
                "answer": f"No emails found matching your search. Try different keywords or check the spelling.",
                "emails_used": 0,
                "senders_used": 0,
            }

        return {
            "success": True,
            "intent": "chat_search",
            "answer": f"Found {len(snippets)} email(s):\n\n" + _format_email_list(snippets[:limit]),
            "emails_used": len(snippets),
            "senders_used": len({s.get("sender_email", "") for s in snippets if s.get("sender_email")}),
            "emails": snippets[:50],
        }

    # NEW: Count emails command
    if "how many" in ql or "count" in ql or "number of" in ql:
        limit_from_q = _extract_limit_from_text(q, default_limit=base_limit, max_limit=1500)
        limit = limit_from_q if not use_unlimited else 1500
        sender_filter = _extract_sender_from_question(q)
        start, end = _extract_date_range(q)

        # Try alternative pattern: "from john@example.com" at end of question
        if not sender_filter:
            m_from = re.search(r"from\s+([^\n?]+)(?:\?|$)", q, flags=re.IGNORECASE)
            if m_from:
                sender_filter = m_from.group(1).strip().lower()

        snippets = _fetch_inbox_snippets(start, end, limit, include_body=False, unread_only=False)

        # Filter by sender if specified
        filtered = snippets
        if sender_filter:
            filtered = [s for s in snippets if sender_filter.lower() in (s.get("sender_email") or "").lower()
                        or sender_filter.lower() in (s.get("from") or "").lower()]

        count = len(filtered)
        date_info = ""
        if start and end:
            date_info = f" from {start.strftime('%d %b %Y')} to {end.strftime('%d %b %Y')}"
        sender_info = f" from {sender_filter}" if sender_filter else ""

        answer = f"You have {count} email(s){date_info}{sender_info}."
        if count > 0:
            unread_count = sum(1 for s in filtered if not s.get("seen", False))
            answer += f" ({unread_count} unread, {count - unread_count} read)"

        return {
            "success": True,
            "intent": "chat_count",
            "answer": answer,
            "emails_used": count,
            "senders_used": len({s.get("sender_email", "") for s in filtered if s.get("sender_email")}),
        }

    # NOTE: Summarize command is handled at the top of this function

        return {
            "success": True,
            "intent": "chat_summary",
            "answer": summary,
            "emails_used": len(snippets),
            "senders_used": len({s.get("sender_email", "") for s in snippets if s.get("sender_email")}),
        }

    # 4) Bulk actions from command
    chat_action = _extract_chat_action(q)
    if chat_action:
        uid_list = _extract_uid_list_from_text(q)
        if len(uid_list) > 1:
            done = 0
            failed: list[str] = []
            for uid in uid_list:
                try:
                    _apply_email_action(chat_action, uid)
                    done += 1
                except Exception:
                    failed.append(uid)
            return {
                "success": True,
                "intent": "chat_bulk_action_executed",
                "answer": (
                    f"Bulk action '{chat_action}' completed. Success: {done}, Failed: {len(failed)}. "
                    f"{('Failed UIDs: ' + ', '.join(failed)) if failed else ''}"
                ).strip(),
                "emails_used": len(uid_list),
                "senders_used": 0,
                "action_requested": chat_action,
            }
    return None


def _fetch_inbox_snippets(
    start: datetime | None,
    end: datetime | None,
    max_emails: int,
    include_body: bool = True,
    unread_only: bool = False,
    bypass_cache: bool = False,
) -> list[dict[str, Any]]:
    """
    Fetch inbox emails using raw imaplib for better reliability.
    Uses Redis cache for faster subsequent fetches.
    """
    import imaplib
    from email.utils import parsedate_to_datetime
    from email.parser import BytesParser

    imap_host = os.getenv("IMAP_HOST", "imap.gmail.com").strip() or "imap.gmail.com"
    imap_user, imap_pass = _active_mail_credentials()
    sender_email = (imap_user or "").strip().lower()

    # Try Redis cache first (if not bypassed)
    if not bypass_cache and not start and not end:
        cached = _get_cached_emails(sender_email)
        if cached:
            # Return limited results from cache
            return cached[:max_emails] if max_emails > 0 else cached

    # Cache key for in-memory cache (fallback)
    cache_key = (
        sender_email,
        imap_host,
        start.isoformat() if start else "",
        end.isoformat() if end else "",
        int(max_emails),
        bool(include_body),
        bool(unread_only),
    )
    now = time.time()
    inbox_cache = state.setdefault("inbox_cache", {})
    if not bypass_cache and isinstance(inbox_cache, dict):
        cached = inbox_cache.get(cache_key)
        if isinstance(cached, dict) and (now - float(cached.get("at", 0))) <= INBOX_CACHE_TTL_S:
            snippets = cached.get("snippets")
            if isinstance(snippets, list):
                print(f"📬 Cache hit: returning {len(snippets)} cached emails")
                return snippets

    snippets: list[dict[str, Any]] = []
    started = time.time()
    hard_max = max_emails if max_emails > 0 else IMAP_UNLIMITED_HARD_MAX

    try:
        client = imaplib.IMAP4_SSL(imap_host)
        client.login(imap_user, imap_pass)
        client.select("INBOX")

        # Get all UIDs
        typ, data = client.uid("SEARCH", None, "ALL")
        if typ != "OK" or not data[0]:
            client.logout()
            return []

        all_uids = data[0].split()
        print(f"📬 Found {len(all_uids)} total UIDs in inbox")

        # Reverse to get newest first, then take max_emails
        # Important: reverse first, then slice to get the newest emails
        reversed_uids = list(reversed(all_uids))
        uids_to_fetch = reversed_uids[:max_emails] if max_emails > 0 else reversed_uids

        parser = BytesParser()
        fetch_count = 0
        skip_count = 0

        for uid_bytes in uids_to_fetch:
            # Check timeout
            if (time.time() - started) > IMAP_SCAN_BUDGET_S:
                print(f"⏱️ Timeout reached after {fetch_count} emails")
                break
            if hard_max > 0 and fetch_count >= hard_max:
                break

            uid = uid_bytes.decode()

            try:
                typ, msg_data = client.uid("FETCH", uid, "(RFC822)")
                if typ != "OK" or not msg_data:
                    continue

                msg = parser.parsebytes(msg_data[0][1])

                # Extract fields
                from_header = msg.get("From") or ""
                subject = msg.get("Subject") or ""
                date_header = msg.get("Date") or ""
                flags = msg.get("Flags") or ""
                seen = "\\Seen" in flags

                # Parse date
                msg_date = None
                try:
                    if date_header:
                        msg_date = parsedate_to_datetime(date_header)
                        msg_date = msg_date.replace(tzinfo=timezone.utc)
                except Exception as e:
                    # Try to extract year from date header manually
                    import re
                    year_match = re.search(r'\b(19|20)\d{2}\b', date_header)
                    if year_match:
                        year = int(year_match.group())
                        try:
                            month_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', date_header, re.IGNORECASE)
                            month = 1
                            if month_match:
                                month_map = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                                            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
                                month = month_map.get(month_match.group(1).lower(), 1)
                            msg_date = datetime(year, month, 1, tzinfo=timezone.utc)
                        except:
                            msg_date = datetime.now(timezone.utc)
                    else:
                        msg_date = datetime.now(timezone.utc)

                # Filter by date range
                if start and msg_date and msg_date < start:
                    skip_count += 1
                    continue
                if end and msg_date and msg_date > end:
                    skip_count += 1
                    continue

                # Filter by unread
                if unread_only and seen:
                    skip_count += 1
                    continue

                # Get body
                body = ""
                if include_body:
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            if content_type == "text/plain":
                                payload = part.get_payload(decode=True)
                                if payload:
                                    body = payload.decode("utf-8", errors="ignore") if isinstance(payload, bytes) else str(payload)
                                    break
                        if not body:
                            for part in msg.walk():
                                if part.get_content_type() == "text/html":
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        body = payload.decode("utf-8", errors="ignore") if isinstance(payload, bytes) else str(payload)
                                        break
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="ignore") if isinstance(payload, bytes) else str(payload)

                    if len(body) > FAST_BODY_CHAR_LIMIT:
                        body = body[:FAST_BODY_CHAR_LIMIT] + "...(truncated)"

                snippets.append({
                    "uid": uid,
                    "date": msg_date.isoformat() if msg_date else "",
                    "from": from_header,
                    "sender_email": _extract_sender_email(from_header),
                    "subject": subject,
                    "body": body,
                    "seen": seen,
                    "flags": flags.split(),
                })
                fetch_count += 1

            except Exception as e:
                print(f"Error fetching UID {uid}: {e}")
                continue

        client.logout()
        print(f"📬 Fetched {fetch_count} emails, skipped {skip_count}")

    except Exception as e:
        print(f"IMAP fetch error: {e}")

    # Cache the results
    if isinstance(inbox_cache, dict):
        inbox_cache[cache_key] = {"at": now, "snippets": snippets}

    # Store in Redis for future requests (if not date filtered)
    if not start and not end and snippets:
        _set_cached_emails(sender_email, snippets)

    return snippets


def _email_to_embedding_text(item: dict[str, Any]) -> str:
    subj = (item.get("subject") or "").strip()
    frm = (item.get("from") or "").strip()
    body = (item.get("body") or "").strip()
    return f"From: {frm}\nSubject: {subj}\nBody: {body}"


def _build_grounded_note(snippets: list[dict[str, Any]]) -> str:
    sender_count = len({s.get("sender_email", "") for s in snippets if s.get("sender_email")})
    return f"Based on {len(snippets)} emails from {sender_count} unique senders."


def _rule_intent_answer(intent: str, snippets: list[dict[str, Any]]) -> str:
    grounded = _build_grounded_note(snippets)
    if intent == "unread_followups":
        unread = [s for s in snippets if not s.get("seen", False)]
        if not unread:
            return f"{grounded}\n\nNo unread follow-up emails found in the scanned set."
        lines = [f"{grounded}", "", "Unread follow-up candidates:"]
        for e in unread[:12]:
            lines.append(f"- {e.get('date','')} | {e.get('from','')} | {e.get('subject','(no subject)')}")
        return "\n".join(lines)
    if intent == "urgent_mails":
        urgent_words = ("urgent", "asap", "immediately", "priority", "critical", "high priority")
        urgent = [s for s in snippets if any(w in (s.get("subject", "") + " " + s.get("body", "")).lower() for w in urgent_words)]
        if not urgent:
            return f"{grounded}\n\nNo strongly urgent emails found in the scanned set."
        lines = [f"{grounded}", "", "Urgent email candidates:"]
        for e in urgent[:12]:
            lines.append(f"- {e.get('date','')} | {e.get('from','')} | {e.get('subject','(no subject)')}")
        return "\n".join(lines)
    if intent == "summary":
        # Fast non-LLM summary: top senders + recent subjects.
        by_sender: dict[str, int] = {}
        for e in snippets:
            sender = (e.get("sender_email") or e.get("from") or "").strip() or "(unknown)"
            by_sender[sender] = by_sender.get(sender, 0) + 1
        top = sorted(by_sender.items(), key=lambda kv: kv[1], reverse=True)[:8]
        lines = [f"{grounded}", "", "Top senders in the scanned set:"]
        for sender, count in top:
            lines.append(f"- {sender}: {count}")
        lines.append("")
        lines.append("Most recent subjects:")
        for e in snippets[:12]:
            subj = e.get("subject") or "(no subject)"
            lines.append(f"- {e.get('date','')} | {subj}")
        return "\n".join(lines)
    if intent == "action_items":
        # Heuristic extraction. Keeps it fast and avoids LLM latency for common "todo/next steps" asks.
        cue_words = ("please", "kindly", "action", "asap", "by ", "deadline", "required", "need you to", "could you", "follow up")
        items: list[str] = []
        for e in snippets[: min(len(snippets), FAST_CONTEXT_EMAIL_LIMIT)]:
            body = (e.get("body") or "").replace("\r", "\n")
            lines = [ln.strip(" -•\t") for ln in body.split("\n") if ln.strip()]
            for ln in lines:
                low = ln.lower()
                if any(w in low for w in cue_words) and len(ln) >= 10:
                    items.append(f"{e.get('subject','(no subject)')}: {ln}")
                if len(items) >= 18:
                    break
            if len(items) >= 18:
                break
        if not items:
            return f"{grounded}\n\nNo clear action items detected in the scanned set."
        out = [f"{grounded}", "", "Possible action items:"]
        for it in items[:18]:
            out.append(f"- {it}")
        return "\n".join(out)
    return ""


def _imap_login_raw() -> tuple[imaplib.IMAP4_SSL, str]:
    imap_host = os.getenv("IMAP_HOST", "imap.gmail.com").strip() or "imap.gmail.com"
    user, password = _active_mail_credentials()
    client = imaplib.IMAP4_SSL(imap_host)
    client.login(user, password)
    return client, user


def _extract_text_from_rfc822(raw_bytes: bytes) -> str:
    import email
    from email.policy import default

    msg = email.message_from_bytes(raw_bytes, policy=default)
    if msg.is_multipart():
        # Prefer text/plain, fallback to text/html.
        plain_parts: list[str] = []
        html_parts: list[str] = []
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            ctype = (part.get_content_type() or "").lower()
            try:
                payload = part.get_content()
            except Exception:
                try:
                    payload = part.get_payload(decode=True) or b""
                    payload = payload.decode("utf-8", errors="ignore")
                except Exception:
                    payload = ""
            if not isinstance(payload, str):
                continue
            if ctype == "text/plain":
                plain_parts.append(payload)
            elif ctype == "text/html":
                html_parts.append(payload)
        text = "\n\n".join([p.strip() for p in plain_parts if p.strip()])
        if text:
            return text
        return "\n\n".join([h.strip() for h in html_parts if h.strip()])
    try:
        payload = msg.get_content()
        return payload if isinstance(payload, str) else ""
    except Exception:
        try:
            payload = msg.get_payload(decode=True) or b""
            return payload.decode("utf-8", errors="ignore")
        except Exception:
            return ""


def _imap_fetch_full_email(uid: str) -> dict[str, Any]:
    uid = (uid or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="UID required")
    client, _ = _imap_login_raw()
    try:
        client.select("INBOX")
        typ, data = client.uid("FETCH", uid, "(RFC822)")
        if typ != "OK" or not data:
            raise HTTPException(status_code=404, detail="Email not found")
        raw = data[0][1] if isinstance(data[0], tuple) and len(data[0]) > 1 else b""
        if not raw:
            raise HTTPException(status_code=404, detail="Email not found")
        body = _extract_text_from_rfc822(raw)
        # Safety limit for UI + LLM context
        max_chars = int(os.getenv("FULL_EMAIL_MAX_CHARS", "20000"))
        if len(body) > max_chars:
            body = body[:max_chars] + "\n...(truncated)"
        return {"uid": uid, "body": body}
    finally:
        try:
            client.logout()
        except Exception:
            pass

def send_single_email_worker(
    row,
    subject,
    message_template,
    smtp_settings,
):
    """
    Sends ONE email safely inside a thread.
    """

    global parallel_send_state

    try:
        # Extract recipient email
        to_email = row.get("email", "").strip()

        if not to_email:
            with send_lock:
                parallel_send_state["failed"] += 1
                parallel_send_state["processed"] += 1
            return {
                "success": False,
                "email": "",
                "error": "Missing email"
            }

        # Personalize message
        personalized_message = personalize_message(
            message_template,
            row
        )

        # Send email
        send_email_smtp(
            smtp_settings=smtp_settings,
            to_email=to_email,
            subject=subject,
            body=personalized_message,
        )

        # Thread-safe success update
        with send_lock:
            parallel_send_state["delivered"] += 1
            parallel_send_state["processed"] += 1

        return {
            "success": True,
            "email": to_email,
        }

    except Exception as e:

        # Thread-safe fail update
        with send_lock:
            parallel_send_state["failed"] += 1
            parallel_send_state["processed"] += 1

        return {
            "success": False,
            "email": row.get("email", ""),
            "error": str(e),
        }
@app.post("/api/email-insights/query")
def email_insights_query(payload: PromptQueryRequest):
    # Get max_emails from frontend (default 10, 0 means unlimited)
    max_emails = int(payload.max_emails) if payload.max_emails else 10
    command_response = _handle_prompt_command(payload.question, max_emails)
    if command_response is not None:
        return command_response

    chat_action = _extract_chat_action(payload.question)
    if chat_action:
        explicit_uid = _extract_uid_from_text(payload.question)
        resolved_uid = _resolve_uid_for_chat_action(payload.question, explicit_uid)
        if not resolved_uid:
            return {
                "success": True,
                "intent": "chat_action_missing_uid",
                "answer": (
                    "I detected an email action command, but no UID was provided. "
                    "Please ask like: 'mark read uid 12345' or 'move latest email to spam'."
                ),
                "emails_used": 0,
                "senders_used": 0,
                "action_requested": chat_action,
            }
        result = _apply_email_action(chat_action, resolved_uid)
        return {
            "success": True,
            "intent": "chat_action_executed",
            "answer": (
                f"Action completed: {result.get('message', 'Done')} "
                f"(uid: {result.get('uid', resolved_uid)})."
            ),
            "emails_used": 0,
            "senders_used": 0,
            "action_requested": chat_action,
            "action_result": result,
        }

    intent = _detect_intent(payload.question)
    start, end = _extract_date_range_from_question(payload.question)
    sender_email, _ = _active_mail_credentials()
    cache_key = "|".join(
        [
            sender_email.lower().strip(),
            (payload.question or "").strip().lower(),
            str(int(payload.max_emails)),
            "mem1" if payload.use_memory else "mem0",
        ]
    )
    now = time.time()
    cache = state.setdefault("insights_cache", {})
    cached = cache.get(cache_key) if isinstance(cache, dict) else None
    if isinstance(cached, dict) and (now - float(cached.get("at", 0))) <= INSIGHTS_CACHE_TTL_S:
        return cached.get("response")

    # If vector index exists, avoid scanning many emails.
    # We fetch only a small window for metadata + use semantic search to pick UIDs.
    max_emails = int(payload.max_emails)

    hits: list[VectorHit] = []
    try:
        hits = semantic_search(_db(), sender_email=sender_email, query=payload.question, top_k=12)
    except Exception:
        hits = []

    # When we have semantic hits, we don't need bodies for the whole window.
    # Pull lightweight snippets for the window, then fetch full bodies only for the hit UIDs.
    snippets = _fetch_inbox_snippets(
        start,
        end,
        max_emails,
        include_body=not bool(hits),
        unread_only=(intent == "unread_followups"),
    )
    if not snippets:
        return {
            "success": True,
            "answer": (
                "No matching emails were found for your query. "
                "Try scanning more emails, changing the question, or verifying IMAP credentials."
            ),
            "intent": intent,
            "emails_used": 0,
            "senders_used": 0,
            "start_date": start.date().isoformat() if start else None,
            "end_date": end.date().isoformat() if end else None,
        }

    if hits:
        by_uid = {s.get("uid"): s for s in snippets}
        picked = []
        for h in hits:
            base = by_uid.get(h.uid)
            if not base:
                continue
            # Lazy drill-down: fetch full body only for selected hit UIDs.
            try:
                full = _imap_fetch_full_email(h.uid)
                base = dict(base)
                base["body"] = full.get("body", "") or base.get("body", "")
            except Exception:
                pass
            picked.append(base)
        context_subset = picked[:FAST_CONTEXT_EMAIL_LIMIT]
    else:
        context_subset = snippets[:FAST_CONTEXT_EMAIL_LIMIT]

    context_lines = []
    for idx, item in enumerate(context_subset, start=1):
        context_lines.append(
            f"--- Email {idx} ---\n"
            f"From: {item['from']}\n"
            f"Date: {item['date'][:10] if item.get('date') else 'N/A'}\n"
            f"Subject: {item['subject'] or '(No subject)'}\n"
            f"Status: {'✅ Unread' if not item.get('seen') else '📖 Read'}\n"
            f"Preview: {item['body'][:500] if item.get('body') else '(No preview)'}\n"
        )
    context = "\n".join(context_lines)
    rule_answer = _rule_intent_answer(intent, snippets)
    grounded_note = _build_grounded_note(snippets)
    history = payload.history if payload.use_memory else []
    answer = rule_answer or answer_email_question(payload.question, context, grounded_note, history)
    senders_used = len({s.get("sender_email", "") for s in snippets if s.get("sender_email")})
    response = {
        "success": True,
        "answer": answer,
        "intent": intent,
        "emails_used": len(snippets),
        "senders_used": senders_used,
        "start_date": start.date().isoformat() if start else None,
        "end_date": end.date().isoformat() if end else None,
    }
    # Cache only successful responses to reduce perceived latency on repeated asks.
    if isinstance(cache, dict):
        cache[cache_key] = {"at": now, "response": response}
    return response


@app.post("/api/email-insights/index")
def email_insights_index(limit: int = 200, mode: str = "headers"):
    """
    Build/refresh the vector index for the active sender.
    """
    sender_email, _ = _active_mail_credentials()
    capped = max(20, min(int(limit), 1500))
    include_body = (mode or "").strip().lower() in {"full", "body", "all"}
    snippets = _fetch_inbox_snippets(None, None, capped, include_body=include_body, unread_only=False)
    updated = 0
    for s in snippets:
        uid = (s.get("uid") or "").strip()
        if not uid:
            continue
        meta = {
            "uid": uid,
            "date": s.get("date"),
            "from": s.get("from"),
            "sender_email": s.get("sender_email"),
            "subject": s.get("subject"),
            "seen": s.get("seen"),
        }
        # For low latency: default index uses headers only; bodies can be added later via "full" mode or lazy indexing.
        if include_body:
            text = _email_to_embedding_text(s)
        else:
            text = f"From: {meta.get('from','')}\nSubject: {meta.get('subject','')}\nDate: {meta.get('date','')}"
        try:
            if upsert_email_embedding(_db(), sender_email=sender_email, uid=uid, content=text, meta=meta):
                updated += 1
        except Exception:
            continue
    return {
        "success": True,
        "sender_email": sender_email,
        "indexed": len(snippets),
        "updated": updated,
        "model": DEFAULT_EMBED_MODEL,
        "mode": "full" if include_body else "headers",
    }


@app.get("/api/email-insights/search")
def email_insights_search(q: str, top_k: int = 12):
    sender_email, _ = _active_mail_credentials()
    hits = semantic_search(_db(), sender_email=sender_email, query=q, top_k=max(1, min(int(top_k), 40)))
    return {
        "success": True,
        "query": q,
        "sender_email": sender_email,
        "hits": [{"uid": h.uid, "score": h.score, "meta": h.meta} for h in hits],
    }


@app.get("/api/chat/history")
def chat_history(user_id: int, limit: int = 40):
    sender_email, _ = _active_mail_credentials()
    history = get_chat_history(
        _db(),
        user_id=int(user_id),
        sender_email=sender_email,
        limit=max(1, min(int(limit), 200)),
    )
    return {"success": True, "sender_email": sender_email, "history": history}


@app.post("/api/chat/turn")
def chat_add_turn(payload: ChatTurnRequest):
    sender_email, _ = _active_mail_credentials()
    role = (payload.role or "").strip().lower()
    if role not in {"user", "assistant"}:
        raise HTTPException(status_code=400, detail="role must be user or assistant")
    from app.vector_search import add_chat_turn

    add_chat_turn(
        _db(),
        user_id=int(payload.user_id),
        sender_email=sender_email,
        role=role,
        content=(payload.content or "").strip(),
    )
    return {"success": True}


@app.get("/api/email-insights/recent")
def email_insights_recent(limit: int = 500, refresh: bool = False):
    """Fetch recent emails - default 500 to get more emails."""
    if limit <= 0:
        # Unlimited - use hard max
        capped = IMAP_UNLIMITED_HARD_MAX
    else:
        capped = max(5, min(limit, 2000))
    snippets = _fetch_inbox_snippets(None, None, capped, include_body=False, unread_only=False, bypass_cache=refresh)
    return {"success": True, "emails": snippets}


@app.get("/api/email-insights/deep-scan")
def email_deep_scan(limit: int = 500):
    """Deep scan - fetch many more emails for full history view."""
    try:
        capped = max(50, min(limit, 1000))  # Allow up to 1000
        snippets = _fetch_inbox_snippets(None, None, capped, include_body=False, unread_only=False)

        # Group by date for summary
        by_date: dict[str, int] = {}
        for s in snippets:
            date_key = (s.get("date") or "")[:10] if s.get("date") else "unknown"
            by_date[date_key] = by_date.get(date_key, 0) + 1

        # Sort dates
        sorted_dates = sorted(by_date.items(), key=lambda x: x[0], reverse=True)

        return {
            "success": True,
            "total_emails": len(snippets),
            "emails": snippets,
            "date_summary": dict(sorted_dates[:30]),
            "date_range": {
                "oldest": snippets[-1].get("date", "N/A") if snippets else None,
                "newest": snippets[0].get("date", "N/A") if snippets else None,
            }
        }
    except Exception as e:
        print(f"Deep scan error: {e}")
        return {"success": False, "error": str(e), "total_emails": 0, "emails": []}


def _fetch_emails_by_date_range(
    start: datetime | None,
    end: datetime | None,
    max_emails: int = 500,
) -> list[dict[str, Any]]:
    """Efficient date-range scan using IMAP SEARCH command."""
    import imaplib
    from email.utils import parsedate_to_datetime

    imap_host = os.getenv("IMAP_HOST", "imap.gmail.com").strip() or "imap.gmail.com"
    imap_user, imap_pass = _active_mail_credentials()

    snippets: list[dict[str, Any]] = []

    # Convert dates to IMAP format (DD-Mon-YYYY)
    start_str = ""
    end_str = ""

    if start:
        start_str = start.strftime("%d-%b-%Y")
    if end:
        end_str = end.strftime("%d-%b-%Y")

    try:
        client = imaplib.IMAP4_SSL(imap_host)
        client.login(imap_user, imap_pass)
        client.select("INBOX")

        # Build search criteria
        search_criteria = []
        if start_str:
            search_criteria.append(f"SINCE {start_str}")
        if end_str:
            search_criteria.append(f"BEFORE {end_str}")

        if not search_criteria:
            # No date filter - get all
            typ, data = client.search(None, "ALL")
        else:
            # Use IMAP SEARCH for efficient date filtering
            search_query = " ".join(search_criteria)
            print(f"🔍 IMAP SEARCH: {search_query}")
            typ, data = client.search(None, search_query)

        if typ != "OK" or not data[0]:
            client.logout()
            return []

        # Get all matching message numbers
        msg_nums = data[0].split()
        print(f"📧 Found {len(msg_nums)} emails matching criteria")

        # Fetch in reverse order (newest first), up to max
        to_fetch = list(reversed(msg_nums[-max_emails:]))

        for num in to_fetch:
            try:
                typ, msg_data = client.fetch(num, "(RFC822)")
                if typ != "OK" or not msg_data:
                    continue

                # Parse email properly
                from email.parser import BytesParser
                raw_email = msg_data[0][1]
                parser = BytesParser()
                msg = parser.parsebytes(raw_email)

                # Extract fields
                from_header = msg.get("From", "") or ""
                subject = msg.get("Subject") or ""
                date_header = msg.get("Date", "")

                # Get body - try plain text first, then html
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        if content_type == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                if isinstance(payload, bytes):
                                    body = payload.decode("utf-8", errors="ignore")
                                else:
                                    body = str(payload)
                                break
                    # If no plain text, try HTML
                    if not body:
                        for part in msg.walk():
                            if part.get_content_type() == "text/html":
                                payload = part.get_payload(decode=True)
                                if payload:
                                    if isinstance(payload, bytes):
                                        body = payload.decode("utf-8", errors="ignore")
                                    else:
                                        body = str(payload)
                                    break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        if isinstance(payload, bytes):
                            body = payload.decode("utf-8", errors="ignore")
                        else:
                            body = str(payload)

                # Strip HTML tags if it's HTML content
                if body and "<html" in body.lower():
                    import re
                    # Basic HTML tag removal
                    body = re.sub(r'<[^>]+>', '', body)
                    body = re.sub(r'\s+', ' ', body).strip()

                # Parse date
                msg_date = None
                try:
                    if date_header:
                        msg_date = parsedate_to_datetime(date_header)
                        msg_date = msg_date.replace(tzinfo=timezone.utc)
                except:
                    msg_date = datetime.now(timezone.utc)

                # Check if within date range (IMAP SINCE/BEFORE are inclusive but may vary)
                if start and msg_date and msg_date < start:
                    continue
                if end and msg_date and msg_date > end:
                    continue

                snippets.append({
                    "uid": str(num.decode() if isinstance(num, bytes) else num),
                    "date": msg_date.isoformat() if msg_date else "",
                    "from": from_header,
                    "sender_email": _extract_sender_email(from_header),
                    "subject": subject,
                    "body": body[:500] if body else "",
                    "seen": False,
                    "flags": [],
                })

            except Exception as e:
                print(f"Error fetching email {num}: {e}")
                continue

        client.logout()

    except Exception as e:
        print(f"IMAP date search error: {e}")

    return snippets


@app.get("/api/email-insights/scan-by-date")
def email_scan_by_date(
    start_date: str = "",
    end_date: str = "",
    limit: int = 500,
):
    """Scan emails by date range - efficient IMAP search."""
    try:
        # Parse dates
        start_dt = None
        end_dt = None

        if start_date:
            start_dt = _parse_human_date(start_date)
        if end_date:
            end_dt = _parse_human_date(end_date)

        # If only start date provided, set end to now
        if start_dt and not end_dt:
            end_dt = datetime.now(timezone.utc)
        # If only end date, go back 30 days
        if end_dt and not start_dt:
            start_dt = end_dt - timedelta(days=30)

        # Default: last 30 days if no dates provided
        if not start_dt and not end_dt:
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(days=30)

        print(f"📅 Scanning from {start_dt} to {end_dt}")

        snippets = _fetch_emails_by_date_range(start_dt, end_dt, limit)

        # Group by date
        by_date: dict[str, int] = {}
        for s in snippets:
            date_key = (s.get("date") or "")[:10] if s.get("date") else "unknown"
            by_date[date_key] = by_date.get(date_key, 0) + 1

        return {
            "success": True,
            "total_emails": len(snippets),
            "emails": snippets,
            "date_summary": by_date,
            "date_range": {
                "start": start_dt.isoformat() if start_dt else None,
                "end": end_dt.isoformat() if end_dt else None,
            }
        }
    except Exception as e:
        print(f"Scan by date error: {e}")
        return {"success": False, "error": str(e), "total_emails": 0, "emails": []}


def _apply_email_action(action: str, uid: str) -> dict[str, Any]:
    action = (action or "").strip().lower()
    uid = (uid or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="UID is required for this action.")

    if action == "unsubscribe":
        snippets = _fetch_inbox_snippets(None, None, 60, include_body=True, unread_only=False)
        target = next((s for s in snippets if s.get("uid") == uid), None)
        if not target:
            raise HTTPException(status_code=404, detail="Email not found for unsubscribe guidance.")
        links = re.findall(r"https?://[^\s\"'<>]+", target.get("body", ""), flags=re.IGNORECASE)
        unsub_links = [u for u in links if "unsubscribe" in u.lower()]
        if not unsub_links:
            return {
                "success": True,
                "message": "No explicit unsubscribe link found in this email body.",
                "uid": uid,
                "action": action,
            }
        return {
            "success": True,
            "message": "Potential unsubscribe links detected.",
            "uid": uid,
            "action": action,
            "unsubscribe_links": unsub_links[:5],
        }

    client, _ = _imap_login_raw()
    try:
        client.select("INBOX")
        if action == "mark_important":
            typ, _ = client.uid("STORE", uid, "+FLAGS", "(\\Flagged)")
            if typ != "OK":
                raise HTTPException(status_code=400, detail="Failed to mark email as important.")
            return {"success": True, "message": "Email marked as important.", "uid": uid, "action": action}
        if action == "mark_unread":
            typ, _ = client.uid("STORE", uid, "-FLAGS", "(\\Seen)")
            if typ != "OK":
                raise HTTPException(status_code=400, detail="Failed to mark as unread.")
            return {"success": True, "message": "Email marked as unread.", "uid": uid, "action": action}
        if action == "mark_read":
            typ, _ = client.uid("STORE", uid, "+FLAGS", "(\\Seen)")
            if typ != "OK":
                raise HTTPException(status_code=400, detail="Failed to mark as read.")
            return {"success": True, "message": "Email marked as read.", "uid": uid, "action": action}
        if action == "move_to_trash":
            trash_folder = os.getenv("IMAP_TRASH_FOLDER", "[Gmail]/Trash")
            typ, _ = client.uid("COPY", uid, trash_folder)
            if typ != "OK":
                raise HTTPException(status_code=400, detail=f"Failed to copy email to trash folder: {trash_folder}")
            typ, _ = client.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            if typ != "OK":
                raise HTTPException(status_code=400, detail="Moved copy but failed to delete original.")
            client.expunge()
            return {"success": True, "message": f"Email moved to trash ({trash_folder}).", "uid": uid, "action": action}
        if action == "move_to_spam":
            spam_folder = os.getenv("IMAP_SPAM_FOLDER", "[Gmail]/Spam")
            typ, _ = client.uid("COPY", uid, spam_folder)
            if typ != "OK":
                raise HTTPException(status_code=400, detail=f"Failed to copy email to spam folder: {spam_folder}")
            typ, _ = client.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            if typ != "OK":
                raise HTTPException(status_code=400, detail="Moved copy but failed to delete original.")
            client.expunge()
            return {"success": True, "message": f"Email moved to spam ({spam_folder}).", "uid": uid, "action": action}
        raise HTTPException(status_code=400, detail="Unsupported action.")
    finally:
        try:
            client.logout()
        except Exception:
            pass


@app.post("/api/email-insights/action")
def email_insights_action(payload: EmailActionRequest):
    return _apply_email_action(payload.action, payload.uid)


@app.post("/api/email-insights/action-bulk")
def email_insights_action_bulk(payload: EmailBulkActionRequest):
    action = payload.action.strip().lower()
    uids = [u.strip() for u in payload.uids if u and u.strip()]
    if not uids:
        raise HTTPException(status_code=400, detail="At least one UID is required")

    # Only allow safe bulk operations
    allowed = {"mark_read", "mark_unread", "mark_important"}
    if action not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported bulk action: {action}")

    client, _ = _imap_login_raw()
    ok = 0
    failed: list[str] = []
    try:
        client.select("INBOX")
        for uid in uids:
            try:
                if action == "mark_important":
                    typ, _ = client.uid("STORE", uid, "+FLAGS", "(\\Flagged)")
                elif action == "mark_unread":
                    typ, _ = client.uid("STORE", uid, "-FLAGS", "(\\Seen)")
                else:
                    typ, _ = client.uid("STORE", uid, "+FLAGS", "(\\Seen)")
                if typ == "OK":
                    ok += 1
                else:
                    failed.append(uid)
            except Exception:
                failed.append(uid)
        return {
            "success": True,
            "action": action,
            "requested": len(uids),
            "updated": ok,
            "failed": failed,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


@app.get("/api/email/uid/{uid}")
def email_get_by_uid(uid: str):
    sender_email, _ = _active_mail_credentials()
    full = _imap_fetch_full_email(uid)
    full["success"] = True
    full["sender_email"] = sender_email
    return full


@app.post("/api/email-insights/refresh-cache")
def refresh_email_cache():
    """Manually refresh the email cache"""
    try:
        sender_email, _ = _active_mail_credentials()
        _invalidate_cache(sender_email)
        return {"success": True, "message": "Cache cleared. Next prompt will fetch fresh emails."}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ════════════════════════════════════════════
# PASSWORD HASH
# ════════════════════════════════════════════
def hash_password(password: str):
    return hashlib.sha256(password.encode()).hexdigest()


# ════════════════════════════════════════════
# AUTH ENDPOINTS (from AI_Email-shravani)
# ════════════════════════════════════════════
@app.post("/api/register")
def register(data: dict):
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    phone = data.get("phone", "").strip()
    password = data.get("password", "")
    role = data.get("role", "individual")
    app_password = data.get("app_password", "").replace(" ", "")

    if len(name) < 3:
        raise HTTPException(400, "Name must be at least 3 characters")

    if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
        raise HTTPException(400, "Invalid email format")

    if not phone.isdigit() or len(phone) != 10:
        raise HTTPException(400, "Phone must be 10 digits")

    if role == "individual":
        if not re.fullmatch(r"[a-z]{16}", app_password):
            raise HTTPException(
                400,
                "App password must be exactly 16 lowercase letters"
            )
        # Keep login flow same: individual can log in using app password.
        password = app_password
    else:
        if len(password) < 6:
            raise HTTPException(400, "Password must be at least 6 characters")

    success = create_user(
        name,
        email,
        phone,
        password,
        role,
        app_password if role == "individual" else None
    )

    if not success:
        raise HTTPException(400, "Email already exists")

    return {
        "message": "User registered successfully",
        "role": role
    }

@app.post("/api/login")
def login(data: dict):
    email = data.get("email", "").strip()
    password = data.get("password", "")

    user = get_user_by_email(email)

    if not user:
        raise HTTPException(400, "User not found")

    if hash_password(password) != user["password"]:
        raise HTTPException(400, "Invalid password")

    state["current_user"] = user
    if user["role"] == "individual":
        state["active_sender"] = {
            "id": user["id"],
            "user_id": user["id"],
            "name": user["name"],
            "organization_name": "Individual",
            "email": user["email"],
            "password": user.get("app_password"),
        }
    else:
        state["active_sender"] = None

    return {
        "user_id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "redirect": "/ai-agent" if user["role"] == "individual"
        else "/organization-dashboard"
    }

# ════════════════════════════════════════════
# SENDER MANAGEMENT ENDPOINTS (from AI_Email-shravani)
# ════════════════════════════════════════════
@app.post("/api/senders/add")
def api_add_sender(data: dict):
    user_id = data.get("user_id")
    name = data.get("name")
    org = data.get("organization_name")
    email = data.get("email")
    password = data.get("password")

    if not all([user_id, name, org, email, password]):
        raise HTTPException(400, "All fields required")
    if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
        raise HTTPException(400, "Invalid email format")

    add_sender(user_id, name, org, email, password)
    return {"message": "Sender added"}


@app.post("/api/senders/select")
def select_sender(data: dict):
    sender_id = data.get("sender_id")
    sender = get_sender_by_id(sender_id)
    if not sender:
        raise HTTPException(404, "Sender not found")
    state["active_sender"] = sender
    return {"message": "Sender selected", "active_email": sender["email"]}

@app.get("/api/senders/active")
def get_active_sender():
    active = state.get("active_sender")
    if not active:
        return {"active": False, "sender": None}
    return {
        "active": True,
        "sender": {
            "id": active.get("id"),
            "name": active.get("name"),
            "email": active.get("email"),
            "organization_name": active.get("organization_name"),
        }
    }

@app.get("/api/senders/{user_id}")
def api_get_senders(user_id: int):
    return {"senders": get_senders(user_id)}

@app.post("/api/send-single")
def send_single_email(data: dict):
    to_email = data.get("to_email", "").strip()
    subject = data.get("subject", "").strip()
    body = data.get("body", "").strip()
    if not to_email or not subject or not body:
        raise HTTPException(status_code=400, detail="to_email, subject, and body are required")
    active = state.get("active_sender")

    # Approach B: if the active sender has connected their Gmail account
    # via OAuth, send through the Gmail API instead of SMTP.
    if active and is_gmail_connected(active["email"]):
        try:
            send_email_gmail(active["email"], to_email, subject, body)
            print(f"✅ USING GMAIL API for {active['email']}")
            return {"success": True, "message": f"Email sent to {to_email} via Gmail API"}
        except GmailAuthError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Gmail send failed: {e}")

    if active:
        from app.email_ssl_service import SMTPSettings
        smtp = SMTPSettings(
            host="smtp.gmail.com",
            port=465,
            user=active["email"],
            password=active["password"],
            from_addr=active["email"],
            use_tls=True,
        )
    else:
        smtp = load_smtp_settings()
    if not smtp:
        raise HTTPException(status_code=400, detail="No sender configured. Add a sender or set SMTP env vars.")
    try:
        send_email_smtp(to_email, subject, body, smtp)
        print(f"⚠️ USING SMTP for {active['email']}")
        return {"success": True, "message": f"Email sent to {to_email}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════
# IN-MEMORY STATE (from main1.py)
# ════════════════════════════════════════════
_send_jobs_lock = threading.Lock()


def _snapshot_send_context() -> dict[str, Any]:
    """Capture current upload + active sender so background jobs stay independent."""
    return {
        "rows": copy.deepcopy(state.get("rows") or []),
        "first_name_column": state.get("first_name_column"),
        "email_column": state.get("email_column"),
        "attachments": copy.deepcopy(list(state.get("attachments") or [])),
        "sender_snapshot": copy.deepcopy(state.get("active_sender")),
    }


state: dict[str, object] = {
    "rows": [],
    "first_name_column": None,
    "email_column": None,
    "stop_requested": False,
    "attachments": [],
    "active_sender": None,
    "insights_cache": {},
    "send_jobs": {},
    "send_stats": {
        "total_attempts": 0,
        "delivered": 0,
        "failed": 0,
        "skipped": 0,
    },
    "last_batch": None,
    "send_in_progress": False,
    "send_progress": {
        "total": 0,
        "processed": 0,
        "delivered": 0,
        "failed": 0,
        "skipped": 0,
        "bounced": 0,
        "current_email": None,
        "results": [],
    },
}


# ════════════════════════════════════════════
# ROOT
# ════════════════════════════════════════════
@app.get("/")
async def root() -> dict[str, object]:
    return {
        "service": "AI Email Automation Agent",
        "docs": "/docs",
        "frontend": "React (Vercel)",
    }


# ════════════════════════════════════════════
# FILE UPLOAD
# ════════════════════════════════════════════
@app.post("/api/upload-excel")
async def upload_excel(file: UploadFile = File(...)) -> dict[str, object]:
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Upload a valid Excel file (.xlsx or .xls).")
    content = await file.read()
    rows = parse_excel(content)
    first_name_column = detect_first_name_column(rows)
    email_column = detect_email_column(rows)
    state["rows"] = rows
    state["first_name_column"] = first_name_column
    state["email_column"] = email_column
    return {
        "success": True,
        "rows_count": len(rows),
        "columns": list(rows[0].keys()) if rows else [],
        "first_name_column": first_name_column,
        "email_column": email_column,
    }


@app.post("/api/upload-attachments")
async def upload_attachments(files: List[UploadFile] = File(...)):
    attachments = []
    for f in files:
        content = await f.read()
        attachments.append({"filename": f.filename, "content": content})
    state["attachments"] = attachments
    return {"attachments": [a["filename"] for a in attachments]}


# ════════════════════════════════════════════
# MESSAGE GENERATION / ENHANCEMENT
# ════════════════════════════════════════════
@app.post("/api/generate-message")
def generate_message(data: dict):
    objective = data.get("objective", "")
    msg = f"Hi {{first_name}},\n\n{objective}\n\nRegards,\nTeam"
    return {"message": msg}


@app.post("/api/enhance-message")
def enhance_message(data: dict):
    text = data.get("message", "")
    print("\n===== ENHANCED EMAIL =====\n")
    return {"message": enhance_email(text)}


@app.post("/api/preview")
async def preview_messages(payload: PreviewRequest) -> dict[str, object]:
    rows = state.get("rows", [])
    if not rows:
        raise HTTPException(status_code=400, detail="Upload Excel before preview.")
    first_name_column = state.get("first_name_column")
    previews = []
    for row in rows[: payload.limit]:
        previews.append(
            {
                "recipient": row,
                "message": personalize_message(payload.message_template, row, first_name_column),
            }
        )
    return {"success": True, "count": len(previews), "previews": previews}


# ════════════════════════════════════════════
# BOUNCE DETECTION
# ════════════════════════════════════════════
@app.get("/api/bounces")
def get_bounces():
    imap_host = os.getenv("IMAP_HOST")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    if not imap_host or not user or not password:
        return {"error": "IMAP config missing"}
    results = check_bounces(imap_host, user, password)
    return {"success": True, "count": len(results), "bounces": results}


def _record_send_result(stats: dict[str, int], status: str) -> None:
    stats["total_attempts"] += 1
    if status == "delivered":
        stats["delivered"] += 1
    elif status == "bounced" or status == "failed":
        stats["failed"] += 1
    else:
        stats["skipped"] += 1


# ════════════════════════════════════════════
# BACKGROUND SEND WORKER — concurrent jobs (multi-sender)
# ════════════════════════════════════════════
def _refresh_legacy_send_aggregate() -> dict[str, Any]:
    """Roll up progress from all concurrent jobs into legacy send_progress UI fields."""
    aggregated = {
        "total": 0,
        "processed": 0,
        "delivered": 0,
        "failed": 0,
        "skipped": 0,
        "bounced": 0,
        "current_email": None,
        "current_emails_summary": "",
        "active_job_count": 0,
    }
    currents: list[str] = []
    jobs_detail: list[dict[str, Any]] = []

    with _send_jobs_lock:
        jobs_map: dict[str, Any] = dict(state.get("send_jobs") or {})  # type: ignore[arg-type]

        for jid, job in jobs_map.items():
            prog = job.get("progress") or {}
            jobs_detail.append(
                {
                    "job_id": jid,
                    "from_email": job.get("from_email"),
                    "subject": job.get("subject"),
                    "in_progress": bool(job.get("in_progress")),
                    "started_at": job.get("started_at"),
                    "completed_at": job.get("completed_at"),
                    "total": prog.get("total"),
                    "processed": prog.get("processed"),
                    "delivered": prog.get("delivered"),
                    "failed": prog.get("failed"),
                    "skipped": prog.get("skipped"),
                    "bounced": prog.get("bounced"),
                    "current_email": prog.get("current_email"),
                }
            )
            if not job.get("in_progress"):
                continue
    
            aggregated["total"] += int(prog.get("total", 0) or 0)
            aggregated["processed"] += int(prog.get("processed", 0) or 0)
            aggregated["delivered"] += int(prog.get("delivered", 0) or 0)
            aggregated["failed"] += int(prog.get("failed", 0) or 0)
            aggregated["skipped"] += int(prog.get("skipped", 0) or 0)
            aggregated["bounced"] += int(prog.get("bounced", 0) or 0)
            cur = prog.get("current_email")
            if job.get("in_progress"):
                aggregated["active_job_count"] += 1

            if cur:
                fe = job.get("from_email") or "?"
                currents.append(f"{fe}: {cur}")

        if currents:
            aggregated["current_emails_summary"] = " | ".join(currents[:8])
            if len(currents) > 8:
                aggregated["current_emails_summary"] += f" … (+{len(currents)-8})"
            aggregated["current_email"] = currents[0]

        state["send_in_progress"] = aggregated["active_job_count"] > 0
        state["send_progress"] = {
            "total": aggregated["total"],
            "processed": aggregated["processed"],
            "delivered": aggregated["delivered"],
            "failed": aggregated["failed"],
            "skipped": aggregated["skipped"],
            "bounced": aggregated["bounced"],
            "current_email": aggregated["current_email"],
            "current_emails_summary": aggregated["current_emails_summary"],
            "active_job_count": aggregated["active_job_count"],
        }
        stats: dict[str, int] = state["send_stats"]
        stats["total_attempts"] = aggregated["processed"]
        stats["delivered"] = aggregated["delivered"]
        stats["failed"] = aggregated["failed"]
        stats["skipped"] = aggregated["skipped"]

    return {**aggregated, "jobs": jobs_detail}


def _send_worker_job(job_id: str, subject: str, message_template: str, snapshot: dict[str, Any]) -> None:
    rows = snapshot.get("rows") or []
    first_name_column = snapshot.get("first_name_column")
    email_column = snapshot.get("email_column")
    attachments = snapshot.get("attachments") or []
    sender_snap = snapshot.get("sender_snapshot")

    use_gmail_api = False
    gmail_sender_email = None

    if sender_snap and is_gmail_connected(sender_snap["email"]):
        use_gmail_api = True
        gmail_sender_email = sender_snap["email"]
        smtp = None
        imap_user = sender_snap["email"]
        imap_pass = sender_snap.get("password")
    elif sender_snap:
        from app.email_ssl_service import SMTPSettings

        smtp = SMTPSettings(
            host="smtp.gmail.com",
            port=465,
            user=sender_snap["email"],
            password=sender_snap["password"],
            from_addr=sender_snap["email"],
            use_tls=True,
        )
        imap_user = sender_snap["email"]
        imap_pass = sender_snap["password"]
    else:
        smtp = load_smtp_settings()
        imap_user = os.getenv("SMTP_USER", "").strip() or None
        imap_pass = os.getenv("SMTP_PASSWORD", "").strip() or None

    with _send_jobs_lock:
        job = dict(state["send_jobs"].get(job_id) or {})
        prog = job.get("progress") or {}
        prog.update(
            {
                "total": len(rows),
                "processed": 0,
                "delivered": 0,
                "failed": 0,
                "skipped": 0,
                "bounced": 0,
                "current_email": None,
                "results": [],
            }
        )
        job["progress"] = prog
        job["in_progress"] = True
        state["send_jobs"][job_id] = job

    for row in rows:
        with _send_jobs_lock:
            job_row = dict(state["send_jobs"].get(job_id) or {})
            if job_row.get("stop_requested"):
                print(f"🛑 STOP TRIGGERED ({job_id})")
                break

        if not email_column:
            entry = {"email": None, "status": "skipped", "detail": "No email column detected."}
            with _send_jobs_lock:
                p = state["send_jobs"][job_id]["progress"]
                p["results"].append(entry)
                p["skipped"] += 1
                p["processed"] += 1
            continue

        to_addr = str(row.get(email_column, "")).strip()
        if not to_addr:
            entry = {"email": None, "status": "skipped", "detail": "Empty email cell"}
            with _send_jobs_lock:
                p = state["send_jobs"][job_id]["progress"]
                p["results"].append(entry)
                p["skipped"] += 1
                p["processed"] += 1
            continue

        body = personalize_message(message_template, row, first_name_column)

        if use_gmail_api:
            try:
                send_email_gmail(gmail_sender_email, to_addr, subject, body)
                entry = {"email": to_addr, "status": "delivered", "detail": "Sent via Gmail API"}
                with _send_jobs_lock:
                    p = state["send_jobs"][job_id]["progress"]
                    p["current_email"] = to_addr
                    p["delivered"] += 1
                    p["processed"] += 1
                    p["results"].append(entry)
            except GmailAuthError as exc:
                entry = {"email": to_addr, "status": "failed", "detail": f"Gmail auth error: {exc}"}
                with _send_jobs_lock:
                    p = state["send_jobs"][job_id]["progress"]
                    p["current_email"] = to_addr
                    p["failed"] += 1
                    p["processed"] += 1
                    p["results"].append(entry)
            except Exception as exc:
                entry = {"email": to_addr, "status": "failed", "detail": str(exc)}
                with _send_jobs_lock:
                    p = state["send_jobs"][job_id]["progress"]
                    p["current_email"] = to_addr
                    p["failed"] += 1
                    p["processed"] += 1
                    p["results"].append(entry)
        elif smtp:
            try:
                send_email_smtp(to_addr, subject, body, smtp, attachments)
                entry = {"email": to_addr, "status": "delivered", "detail": "Accepted by SMTP server"}
                with _send_jobs_lock:
                    p = state["send_jobs"][job_id]["progress"]
                    p["current_email"] = to_addr
                    p["delivered"] += 1
                    p["processed"] += 1
                    p["results"].append(entry)

            except Exception as exc:
                entry = {"email": to_addr, "status": "failed", "detail": str(exc)}
                with _send_jobs_lock:
                    p = state["send_jobs"][job_id]["progress"]
                    p["current_email"] = to_addr
                    p["failed"] += 1
                    p["processed"] += 1
                    p["results"].append(entry)
        else:
            entry = {
                "email": to_addr,
                "status": "delivered",
                "detail": "Simulated (set SMTP_* env vars for real send)",
            }
            with _send_jobs_lock:
                p = state["send_jobs"][job_id]["progress"]
                p["current_email"] = to_addr
                p["delivered"] += 1
                p["processed"] += 1
                p["results"].append(entry)

        time.sleep(0.15)

    with _send_jobs_lock:
        p = state["send_jobs"][job_id]["progress"]
        p["current_email"] = None
    print("⏳ Waiting 20 seconds before bounce check...")
    time.sleep(20)
    from_addr = ""

    if sender_snap:
        from_addr = (sender_snap.get("email") or "").strip()

    if not from_addr:
        from_addr = os.getenv("SMTP_FROM", "") or os.getenv("SMTP_USER", "")

    print("⏳ Waiting for bounce emails...")
    time.sleep(30)

    try:

        # only recent bounce emails
        bounces = check_bounces(
            imap_host=os.getenv("IMAP_HOST", "imap.gmail.com"),
            imap_user=from_addr,
            imap_pass=sender_snap.get("password") if sender_snap else None,
        )

        print("\n📥 Raw bounce results:")
        print(bounces)

        # normalize bounced emails
        bounced_emails = {
            str(b.get("email", "")).lower().strip()
            for b in (bounces or [])
            if b.get("email")
        }

        print("\n📩 Parsed bounced emails:")
        print(bounced_emails)

        # nothing bounced
        if not bounced_emails:
            print("✅ No recent bounces found")
            return

        with _send_jobs_lock:

            p = state["send_jobs"][job_id]["progress"]

            for r in p["results"]:

                em = str(r.get("email") or "").lower().strip()

                if not em:
                    continue

                # skip non matching emails
                if em not in bounced_emails:
                    continue

                current_status = str(r.get("status") or "").lower()

                # already processed
                if current_status == "bounced":
                    continue

                print(f"\n🚨 Bounce matched: {em}")
                print(f"Previous status: {current_status}")

                # update status
                r["status"] = "bounced"
                r["detail"] = "Email bounced (invalid/rejected recipient)"
                r["bounce_detected_at"] = datetime.now(
                    timezone.utc
                ).isoformat()

                # increment bounced count once
                p["bounced"] = int(p.get("bounced") or 0) + 1

                # decrement previous bucket safely
                if current_status == "delivered":

                    p["delivered"] = max(
                        int(p.get("delivered") or 0) - 1,
                        0,
                    )

                elif current_status == "failed":

                    p["failed"] = max(
                        int(p.get("failed") or 0) - 1,
                        0,
                    )

                print(f"✅ Marked as bounced: {em}")

    except Exception as exc:

        print("\n❌ Bounce check failed")
        print(type(exc).__name__)
        print(str(exc))

    with _send_jobs_lock:
        pj = dict(state["send_jobs"][job_id]["progress"])
        final_rows = list(pj.get("results") or [])
        bounced_list = sorted(
            {
                str(r.get("email") or "").strip()
                for r in final_rows
                if str(r.get("status") or "") == "bounced" and r.get("email")
            }
        )

    delivered_count = sum(1 for r in final_rows if r.get("status") == "delivered")
    failed_count = sum(1 for r in final_rows if r.get("status") == "failed")
    skipped_count = sum(1 for r in final_rows if r.get("status") == "skipped")
    bounce_count = sum(1 for r in final_rows if r.get("status") == "bounced")

    from_addr = ""
    if sender_snap:
        from_addr = (sender_snap.get("email") or "").strip()
    if not from_addr:
        from_addr = os.getenv("SMTP_FROM", "") or os.getenv("SMTP_USER", "")

    last_batch = {
        "job_id": job_id,
        "at": datetime.now(timezone.utc).isoformat(),
        "from_email": from_addr,
        "subject": subject,
        "mode": "smtp" if smtp else "demo",
        "total": len(final_rows),
        "processed": int(pj.get("processed", 0)),
        "delivered": delivered_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "bounced": bounce_count,
        "bounced_emails": bounced_list,
        "results": final_rows,
    }

    with _send_jobs_lock:
        j = state["send_jobs"][job_id]
        j["in_progress"] = False
        j["stop_requested"] = False
        j["completed_at"] = datetime.now(timezone.utc).isoformat()
        j["last_batch"] = last_batch
        state["last_batch"] = last_batch
        # reset global flag if no other jobs are running
        if not any(v.get("in_progress") for v in state["send_jobs"].values()):
            state["stop_requested"] = False

    _refresh_legacy_send_aggregate()
    print(f"✅ Send worker finished ({job_id}).")


# ════════════════════════════════════════════
# /api/send — returns immediately; multiple jobs may run in parallel
# ════════════════════════════════════════════
@app.post("/api/send")
async def send_messages(payload: SendRequest) -> dict[str, object]:
    snapshot = _snapshot_send_context()
    rows = snapshot.get("rows") or []
    if not rows:
        raise HTTPException(status_code=400, detail="Upload Excel before send.")

    job_id = uuid.uuid4().hex[:12]
    sender_snap = snapshot.get("sender_snapshot")
    from_email = (sender_snap or {}).get("email") or ""

    with _send_jobs_lock:
        state["stop_requested"] = False
        state["send_jobs"][job_id] = {
            "job_id": job_id,
            "from_email": from_email,
            "subject": payload.subject,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "last_batch": None,
            "in_progress": True,
            "stop_requested": False,
            "progress": {},
            "snapshot_meta": {"row_count": len(rows)},
        }

    threading.Thread(
        target=_send_worker_job,
        args=(job_id, payload.subject, payload.message_template, snapshot),
        daemon=True,
    ).start()

    return {
        "success": True,
        "job_id": job_id,
        "message": (
            f"Send job {job_id} started for {len(rows)} recipients. "
            "Poll /api/send-status — other senders may start jobs in parallel."
        ),
        "total_recipients": len(rows),
        "subject": payload.subject,
        "from_email": from_email,
    }


@app.post("/api/stop")
def emergency_stop(payload: dict = Body(default_factory=dict)):
    jid = str(payload.get("job_id") or "").strip()

    with _send_jobs_lock:
        if jid:
            job = state["send_jobs"].get(jid)
            if job and job.get("in_progress"):
                job["stop_requested"] = True
        else:
            state["stop_requested"] = True
            for job in state["send_jobs"].values():
                if job.get("in_progress"):
                    job["stop_requested"] = True

    if jid:
        return {"message": f"🛑 Stop requested for job {jid} (finishes current email)."}
    return {"message": "🛑 Emergency stop — all active send jobs will halt after their current email."}


@app.post("/api/stop/reset")
def reset_stop():
    with _send_jobs_lock:
        state["stop_requested"] = False
        for job in state["send_jobs"].values():
            job["stop_requested"] = False
    return {"message": "✅ Stop flags cleared"}


@app.get("/api/ai-agent-status")
async def ai_agent_status() -> dict[str, object]:
    """Quick check if AI Agent has email credentials configured."""
    active = state.get("active_sender")
    smtp = load_smtp_settings()

    has_sender = bool(
        (isinstance(active, dict) and active.get("email") and active.get("password"))
        or (smtp is not None)
    )

    # Also check env vars as fallback
    env_user = os.getenv("SMTP_USER", "").strip()
    env_pass = os.getenv("SMTP_PASSWORD", "").strip()
    has_env = bool(env_user and env_pass)

    ready = has_sender or has_env

    return {
        "ready": ready,
        "has_sender": bool(has_sender),
        "has_env": has_env,
        "message": "Ready" if ready else "No sender configured. Add sender in Senders page or set SMTP env vars."
    }


@app.get("/api/send-status")
async def send_status() -> dict[str, object]:
    bundle = _refresh_legacy_send_aggregate()

    smtp = load_smtp_settings()
    active = state.get("active_sender")

    smtp_ready = (
        smtp is not None
        or (
            isinstance(active, dict)
            and bool(active.get("email"))
            and bool(active.get("password"))
        )
    )

    jobs = bundle.get("jobs") or []

    return {
        "success": True,

        "send_in_progress": bundle.get("active_job_count", 0) > 0,

        "stop_requested": state.get("stop_requested", False),

        "progress": {
            "total": sum(j.get("total", 0) or 0 for j in jobs),

            "processed": sum(j.get("processed", 0) or 0 for j in jobs),

            "delivered": sum(j.get("delivered", 0) or 0 for j in jobs),

            "failed": sum(j.get("failed", 0) or 0 for j in jobs),

            "skipped": sum(j.get("skipped", 0) or 0 for j in jobs),

            "bounced": sum(j.get("bounced", 0) or 0 for j in jobs),

            "current_emails_summary": ", ".join(
                [
                    f"{j.get('from_email')} → {j.get('current_email')}"
                    for j in jobs
                    if j.get("current_email")
                ]
            ),

            "active_job_count": bundle.get("active_job_count", 0),
        },

        "jobs": jobs,

        "active_job_count": bundle.get("active_job_count", 0),

        "last_batch": state.get("last_batch"),

        "smtp_configured": bool(smtp_ready),

        "delivery_note": (
            "SMTP via active sender credentials or SMTP_* env. Multiple concurrent sends are supported."
            if smtp_ready
            else "Demo mode: configure sender app password / SMTP_* for real sending."
        ),
    }

# ════════════════════════════════════════════
# MANUAL MODE (from main1.py with browse support)
# ════════════════════════════════════════════
def _extend_sender(sender) -> None:
    if not hasattr(sender, "peek_at"):
        def _peek_at(self, index: int) -> dict:
            if not self.emails:
                return {"message": "No emails loaded"}
            idx = max(0, min(index, len(self.emails) - 1))
            e = self.emails[idx]
            sent_set = getattr(self, "_sent_indices", set())
            skip_set = getattr(self, "_skipped_indices", set())
            return {
                "index": idx,
                "total": len(self.emails),
                "to": e["to"],
                "subject": e["subject"],
                "body": e["body"],
                "status": "sent" if idx in sent_set else "skipped" if idx in skip_set else "pending",
            }
        sender.peek_at = _types.MethodType(_peek_at, sender)

    if not hasattr(sender, "go_prev"):
        def _go_prev(self) -> dict:
            if not hasattr(self, "current_index"):
                self.current_index = 0
            if self.current_index > 0:
                self.current_index -= 1
            return self.peek_at(self.current_index)
        sender.go_prev = _types.MethodType(_go_prev, sender)

    if not hasattr(sender, "go_next"):
        def _go_next(self) -> dict:
            if not hasattr(self, "current_index"):
                self.current_index = 0
            if self.current_index < len(self.emails) - 1:
                self.current_index += 1
            return self.peek_at(self.current_index)
        sender.go_next = _types.MethodType(_go_next, sender)

    if not hasattr(sender, "list_all"):
        def _list_all(self) -> dict:
            sent_set = getattr(self, "_sent_indices", set())
            skip_set = getattr(self, "_skipped_indices", set())
            current = getattr(self, "current_index", 0)
            return {
                "current_index": current,
                "total": len(self.emails),
                "contacts": [
                    {
                        "index": i,
                        "to": e["to"],
                        "subject": e["subject"],
                        "body": e["body"],
                        "status": "sent" if i in sent_set else "skipped" if i in skip_set else "pending",
                        "is_current": i == current,
                    }
                    for i, e in enumerate(self.emails)
                ],
            }
        sender.list_all = _types.MethodType(_list_all, sender)


def init_manual_sender(subject: str, message_template: str):
    rows = state.get("rows", [])
    first_name_column = state.get("first_name_column")
    email_column = state.get("email_column")
    attachments = state.get("attachments", [])

    # Use active_sender if set, else fallback to .env SMTP
    active = state.get("active_sender")
    if active:
        from app.email_ssl_service import SMTPSettings
        smtp = SMTPSettings(
            host="smtp.gmail.com",
            port=465,
            user=active["email"],
            password=active["password"],
            from_addr=active["email"],
            use_tls=True,
        )
    else:
        smtp = load_smtp_settings()

    emails = []
    for row in rows:
        if not email_column:
            continue
        to_addr = str(row.get(email_column, "")).strip()
        if not to_addr:
            continue
        body = personalize_message(message_template, row, first_name_column)
        personalized_subject = personalize_message(subject, row, first_name_column) if subject else subject
        emails.append({"to": to_addr, "subject": personalized_subject, "body": body, "attachments": attachments})
    sender = ManualEmailSender(emails, smtp, state)
    sender.current_index = 0
    _extend_sender(sender)
    state["manual_sender"] = sender


@app.post("/api/manual/init")
def manual_init(payload: SendRequest):
    init_manual_sender(payload.subject, payload.message_template)
    sender = state["manual_sender"]
    return {"success": True, "total": len(sender.emails)}


@app.post("/api/manual/preview")
def manual_preview():
    sender = state.get("manual_sender")
    if not sender:
        raise HTTPException(status_code=400, detail="Manual mode not initialized")
    email = sender.preview_next()
    if not email:
        return {"message": "No emails left"}
    return email


@app.post("/api/manual/send")
def manual_send(payload: SendRequest):
    if not state.get("manual_sender"):
        init_manual_sender(payload.subject, payload.message_template)
    sender = state["manual_sender"]
    result = sender.send_next()

    status_data = sender.status()
    stats = state["send_stats"]
    stats["total_attempts"] = status_data.get("sent", 0) + status_data.get("skipped", 0)
    stats["delivered"] = status_data.get("sent", 0)
    stats["skipped"] = status_data.get("skipped", 0)

    contacts = getattr(sender, "emails", [])
    sent_set = getattr(sender, "_sent_indices", set())
    skip_set = getattr(sender, "_skipped_indices", set())
    results = []
    for i, e in enumerate(contacts):
        s = "delivered" if i in sent_set else "skipped" if i in skip_set else "pending"
        results.append({"email": e["to"], "status": s, "detail": "Manual send"})

    state["last_batch"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "subject": payload.subject,
        "mode": "manual",
        "total": len(contacts),
        "delivered": len(sent_set),
        "failed": 0,
        "skipped": len(skip_set),
        "bounced": 0,
        "bounced_emails": [],
        "results": results,
    }
    return result


@app.post("/api/manual/send-by-index")
def manual_send_by_index(data: dict):
    index = int(data.get("index", -1))
    skip = data.get("skip", False)
    subject = data.get("subject", None)
    body = data.get("body", None)
    sender = state.get("manual_sender")
    if not sender:
        raise HTTPException(status_code=400, detail="Manual mode not initialized")
    if skip:
        return sender.skip_by_index(index)
    result = sender.send_by_index(index, subject=subject, body=body)
    return result

@app.post("/api/manual/skip")
def manual_skip():
    sender = state.get("manual_sender")
    if not sender:
        raise HTTPException(status_code=400, detail="Manual mode not initialized")
    return sender.skip_next()


@app.get("/api/manual/status")
def manual_status():
    sender = state.get("manual_sender")
    if not sender:
        return {"message": "Manual sender not started"}
    return sender.status()


@app.get("/api/manual/peek")
def manual_peek(index: int | None = None):
    sender = state.get("manual_sender")
    if not sender:
        raise HTTPException(status_code=400, detail="Manual mode not initialized")
    if index is None:
        index = getattr(sender, "current_index", 0)
    return sender.peek_at(index)


@app.post("/api/manual/go-prev")
def manual_go_prev():
    sender = state.get("manual_sender")
    if not sender:
        raise HTTPException(status_code=400, detail="Manual mode not initialized")
    return sender.go_prev()


@app.post("/api/manual/go-next")
def manual_go_next():
    sender = state.get("manual_sender")
    if not sender:
        raise HTTPException(status_code=400, detail="Manual mode not initialized")
    return sender.go_next()


@app.get("/api/manual/list")
def manual_list_all():
    sender = state.get("manual_sender")
    if not sender:
        raise HTTPException(status_code=400, detail="Manual mode not initialized")
    return sender.list_all()

# ════════════════════════════════════════════
# GOOGLE OAUTH (Gmail API - Approach B)
# ════════════════════════════════════════════

@app.get("/google/login")
def google_login(user_email: str):
    """
    Step 1: Redirect the logged-in user to Google's consent screen.
    `user_email` is embedded in a signed, stateless `state` param -
    no server-side storage needed (works across reloads/workers).
    """
    auth_url, _ = get_auth_url(user_email, GOOGLE_REDIRECT_URI)
    return {"auth_url": auth_url}


@app.get("/google/callback")
def google_callback(request: Request):
    """
    Step 2: Google redirects here with `code` and `state`.
    Exchange the code for tokens and store the refresh token for the user.
    """
    code = request.query_params.get("code")
    oauth_state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        return RedirectResponse(f"{FRONTEND_URL}/settings?gmail_connected=0&error={error}")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        user_email = verify_state(oauth_state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid or expired OAuth state: {e}")

    credentials = fetch_tokens(code, GOOGLE_REDIRECT_URI)

    if not credentials.refresh_token:
        # Happens if the user already granted consent before and Google
        # didn't re-issue a refresh_token. save_gmail_token() preserves
        # the existing one in that case.
        logger.warning(f"No refresh_token returned for {user_email}; reusing existing if present")

    save_gmail_token(
        user_email=user_email,
        refresh_token=credentials.refresh_token,
        access_token=credentials.token,
        token_expiry=credentials.expiry,
    )

    # Redirect back to frontend settings page
    return RedirectResponse(f"{FRONTEND_URL}/settings?gmail_connected=1")


@app.get("/google/status")
def google_status(user_email: str):
    """Check whether a user has connected their Gmail account."""
    token = get_gmail_token(user_email)
    if not token:
        return {"connected": False}
    return {
        "connected": True,
        "connected_at": token.get("connected_at"),
    }


@app.post("/google/disconnect")
def google_disconnect(payload: dict = Body(...)):
    """Disconnect (remove) a user's stored Gmail tokens."""
    user_email = payload.get("user_email")
    if not user_email:
        raise HTTPException(status_code=400, detail="user_email is required")
    delete_gmail_token(user_email)
    return {"success": True}


# ════════════════════════════════════════════
# SEND VIA GMAIL API (Phase 4)
# ════════════════════════════════════════════

@app.post("/api/gmail/send")
def gmail_send(payload: dict = Body(...)):
    """
    Send a single email via the Gmail API using the sender's connected
    Google account.

    Body: { "user_email": "...", "to": "...", "subject": "...", "body": "...", "html": false }
    """
    user_email = payload.get("user_email")
    to_email = payload.get("to")
    subject = payload.get("subject", "")
    body = payload.get("body", "")
    html = bool(payload.get("html", False))

    if not user_email or not to_email:
        raise HTTPException(status_code=400, detail="user_email and to are required")

    if not is_gmail_connected(user_email):
        raise HTTPException(status_code=400, detail="Gmail account not connected for this user")

    try:
        result = send_email_gmail(user_email, to_email, subject, body, html=html)
        return {"success": True, "message_id": result.get("id")}
    except GmailAuthError as e:
        logger.error(f"Gmail auth error: {e}")
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Gmail send error: {e}")
        raise HTTPException(status_code=500, detail=f"Gmail send failed: {e}")


@app.post("/api/gmail/send-bulk")
def gmail_send_bulk(payload: dict = Body(...)):
    """
    Send to multiple contacts via Gmail API using stored rows/state
    (mirrors the SMTP bulk-send flow but routes through Gmail).

    Body: { "user_email": "...", "subject": "...", "message_template": "..." }
    """
    user_email = payload.get("user_email")
    subject = payload.get("subject", "")
    message_template = payload.get("message_template", "")

    if not user_email:
        raise HTTPException(status_code=400, detail="user_email is required")

    if not is_gmail_connected(user_email):
        raise HTTPException(status_code=400, detail="Gmail account not connected for this user")

    rows = state.get("rows", [])
    email_column = state.get("email_column")
    first_name_column = state.get("first_name_column")

    if not email_column:
        raise HTTPException(status_code=400, detail="No email column detected. Upload contacts first.")

    results = []
    delivered = 0
    failed = 0

    for row in rows:
        to_addr = str(row.get(email_column, "")).strip()
        if not to_addr:
            continue

        personalized_subject = personalize_message(subject, row, first_name_column) if subject else subject
        personalized_body = personalize_message(message_template, row, first_name_column)

        try:
            send_email_gmail(user_email, to_addr, personalized_subject, personalized_body)
            results.append({"email": to_addr, "status": "delivered", "detail": "Sent via Gmail API"})
            delivered += 1
        except GmailAuthError as e:
            results.append({"email": to_addr, "status": "failed", "detail": f"Auth error: {e}"})
            failed += 1
        except Exception as e:
            results.append({"email": to_addr, "status": "failed", "detail": str(e)})
            failed += 1

    state["last_batch"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "subject": subject,
        "mode": "gmail_api",
        "total": len(results),
        "delivered": delivered,
        "failed": failed,
        "skipped": 0,
        "bounced": 0,
        "bounced_emails": [],
        "results": results,
    }

    return {"success": True, "total": len(results), "delivered": delivered, "failed": failed, "results": results}