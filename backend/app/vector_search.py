from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"


@dataclass(frozen=True)
class VectorHit:
    uid: str
    score: float
    meta: dict[str, Any]


_MODEL: "SentenceTransformer | None" = None


def _get_model(model_name: str = DEFAULT_EMBED_MODEL) -> "SentenceTransformer":
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "sentence-transformers is not installed. Run: pip install -r requirements.txt"
        ) from exc

    _MODEL = SentenceTransformer(model_name)
    return _MODEL


def _to_unit(x: np.ndarray) -> np.ndarray:
    denom = np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
    return x / denom


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def init_vector_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS email_embeddings (
            sender_email TEXT NOT NULL,
            uid TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            vec_json TEXT NOT NULL,
            meta_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (sender_email, uid)
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_email_embeddings_sender ON email_embeddings(sender_email)"
    )
    conn.commit()


def init_chat_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sender_email TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_turns_lookup ON chat_turns(user_id, sender_email, created_at)"
    )
    conn.commit()


def upsert_email_embedding(
    conn: sqlite3.Connection,
    *,
    sender_email: str,
    uid: str,
    content: str,
    meta: dict[str, Any],
    model_name: str = DEFAULT_EMBED_MODEL,
) -> bool:
    """
    Returns True if updated, False if skipped (content unchanged).
    """
    sender_email = (sender_email or "").strip().lower()
    uid = (uid or "").strip()
    if not sender_email or not uid:
        return False

    content_hash = _hash_text(content)
    cur = conn.cursor()
    row = cur.execute(
        "SELECT content_hash FROM email_embeddings WHERE sender_email=? AND uid=?",
        (sender_email, uid),
    ).fetchone()
    if row and row[0] == content_hash:
        return False

    model = _get_model(model_name)
    vec = model.encode([content], show_progress_bar=False, convert_to_numpy=True)
    vec = _to_unit(vec.astype(np.float32))
    vec_json = json.dumps(vec[0].tolist())
    meta_json = json.dumps(meta or {})
    now = time.time()

    cur.execute(
        """
        INSERT INTO email_embeddings(sender_email, uid, content_hash, vec_json, meta_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(sender_email, uid)
        DO UPDATE SET
            content_hash=excluded.content_hash,
            vec_json=excluded.vec_json,
            meta_json=excluded.meta_json,
            updated_at=excluded.updated_at
        """,
        (sender_email, uid, content_hash, vec_json, meta_json, now),
    )
    conn.commit()
    return True


def semantic_search(
    conn: sqlite3.Connection,
    *,
    sender_email: str,
    query: str,
    top_k: int = 12,
    model_name: str = DEFAULT_EMBED_MODEL,
) -> list[VectorHit]:
    sender_email = (sender_email or "").strip().lower()
    query = (query or "").strip()
    if not sender_email or not query:
        return []

    cur = conn.cursor()
    rows = cur.execute(
        "SELECT uid, vec_json, meta_json FROM email_embeddings WHERE sender_email=?",
        (sender_email,),
    ).fetchall()
    if not rows:
        return []

    model = _get_model(model_name)
    q = model.encode([query], show_progress_bar=False, convert_to_numpy=True).astype(np.float32)
    q = _to_unit(q)[0]

    uids: list[str] = []
    vecs: list[np.ndarray] = []
    metas: list[dict[str, Any]] = []
    for uid, vec_json, meta_json in rows:
        try:
            v = np.array(json.loads(vec_json), dtype=np.float32)
            meta = json.loads(meta_json) if meta_json else {}
        except Exception:
            continue
        uids.append(str(uid))
        vecs.append(v)
        metas.append(meta if isinstance(meta, dict) else {})

    if not vecs:
        return []
    M = _to_unit(np.stack(vecs, axis=0))
    scores = (M @ q).tolist()

    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[: max(1, int(top_k))]
    hits: list[VectorHit] = []
    for i in ranked:
        hits.append(VectorHit(uid=uids[i], score=float(scores[i]), meta=metas[i]))
    return hits


def add_chat_turn(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    sender_email: str,
    role: str,
    content: str,
) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_turns(user_id, sender_email, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (int(user_id), (sender_email or "").strip().lower(), role, content, time.time()),
    )
    conn.commit()


def get_chat_history(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    sender_email: str,
    limit: int = 40,
) -> list[dict[str, str]]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT role, content
        FROM chat_turns
        WHERE user_id=? AND sender_email=?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (int(user_id), (sender_email or "").strip().lower(), int(limit)),
    ).fetchall()
    # Return oldest → newest
    rows = list(reversed(rows))
    return [{"role": r, "content": c} for (r, c) in rows if r and c]

