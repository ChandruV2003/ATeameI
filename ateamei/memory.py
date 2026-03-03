from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import numpy as np
import requests

from .ollama_client import OllamaClient


def _default_db_path() -> Path:
    # Keep it out of git by default.
    base = Path.home() / ".codex" / "ateamei"
    base.mkdir(parents=True, exist_ok=True)
    new_db = base / "memory.sqlite"

    # One-time migration from the old MeetScribe name (if present).
    old_base = Path.home() / ".codex" / "meetscribe"
    old_db = old_base / "memory.sqlite"
    if not new_db.exists() and old_db.exists():
        base.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(old_db) + suffix)
            dst = Path(str(new_db) + suffix)
            if src.exists() and not dst.exists():
                try:
                    src.rename(dst)
                except OSError:
                    # Best-effort migration; if rename fails we just leave the old DB.
                    pass

    return new_db


def _db_path() -> Path:
    override = os.environ.get("ATEAMEI_MEMORY_PATH", "").strip()
    if not override:
        override = os.environ.get("MEETSCRIBE_MEMORY_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return _default_db_path()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    _init(conn)
    return conn


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at INTEGER NOT NULL,
            source TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS entry_embeddings (
            entry_id INTEGER PRIMARY KEY,
            model TEXT NOT NULL,
            dims INTEGER NOT NULL,
            vector BLOB NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
            text,
            tags,
            source,
            content='entries',
            content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
            INSERT INTO entries_fts(rowid, text, tags, source)
            VALUES (new.id, new.text, new.tags, new.source);
        END;

        CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
            INSERT INTO entries_fts(entries_fts, rowid, text, tags, source)
            VALUES('delete', old.id, old.text, old.tags, old.source);
        END;

        CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
            INSERT INTO entries_fts(entries_fts, rowid, text, tags, source)
            VALUES('delete', old.id, old.text, old.tags, old.source);
            INSERT INTO entries_fts(rowid, text, tags, source)
            VALUES (new.id, new.text, new.tags, new.source);
        END;
        """
    )


_RE_PW_LINE = re.compile(r"(?im)^(.*\b(pass(word)?|pwd)\b\s*[:=]\s*)(.+)$")
_RE_CONN_STR = re.compile(r"(?i)(password\s*=\s*)([^;]+)")


def _redact(text: str) -> str:
    text = _RE_PW_LINE.sub(r"\1[REDACTED]", text)
    text = _RE_CONN_STR.sub(r"\1[REDACTED]", text)
    return text


def add_entry(*, text: str, source: str, tags: str, allow_secrets: bool) -> int:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("entry text is empty")
    if not allow_secrets:
        cleaned = _redact(cleaned)

    tag_str = ",".join(t.strip() for t in (tags or "").split(",") if t.strip())
    created_at = int(time.time())
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO entries(created_at, source, tags, text) VALUES (?, ?, ?, ?)",
            (created_at, source.strip() or "manual", tag_str, cleaned),
        )
        entry_id = int(cur.lastrowid)

        embed_model = os.environ.get("ATEAMEI_EMBED_MODEL", "").strip()
        if not embed_model:
            embed_model = os.environ.get("MEETSCRIBE_EMBED_MODEL", "").strip()
        if embed_model:
            _embed_entry(conn, entry_id, embed_model, cleaned)

        return entry_id


def search_entries(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        raise ValueError("query is empty")
    with _connect() as conn:
        try:
            rows = conn.execute(
                """
                SELECT
                    e.id,
                    e.created_at,
                    e.source,
                    e.tags,
                    snippet(entries_fts, 0, '[', ']', '…', 12) AS snippet
                FROM entries_fts
                JOIN entries e ON e.id = entries_fts.rowid
                WHERE entries_fts MATCH ?
                ORDER BY bm25(entries_fts)
                LIMIT ?
                """,
                (q, int(limit)),
            ).fetchall()
        except sqlite3.OperationalError:
            # If the user provided a natural-language query that isn't valid FTS syntax,
            # fall back to a simple OR query over extracted tokens.
            rows = conn.execute(
                """
                SELECT
                    e.id,
                    e.created_at,
                    e.source,
                    e.tags,
                    snippet(entries_fts, 0, '[', ']', '…', 12) AS snippet
                FROM entries_fts
                JOIN entries e ON e.id = entries_fts.rowid
                WHERE entries_fts MATCH ?
                ORDER BY bm25(entries_fts)
                LIMIT ?
                """,
                (_to_fts_query(q), int(limit)),
            ).fetchall()

        return [dict(r) for r in rows]


def export_entries(*, limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, source, tags, text
            FROM entries
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]


async def ask_memory(question: str, *, ollama_model: str, limit: int = 12) -> str:
    q = (question or "").strip()
    if not q:
        raise ValueError("question is empty")

    hits = search_entries(q, limit=limit)
    if not hits:
        # Fall back to semantic retrieval if embeddings exist.
        hits = await semantic_search(q, limit=limit)
    context = "\n\n".join(
        f"[{h['id']}] source={h['source']} tags={h['tags']} created_at={h['created_at']}\n{h['snippet']}"
        for h in hits
    )

    prompt = (
        "You are a local memory assistant.\n"
        "Answer the question using the memory snippets below. If memory is insufficient, say so.\n"
        "Cite relevant memory ids like [123].\n\n"
        f"Question:\n{q}\n\n"
        f"Memory snippets:\n{context}\n"
    )

    client = OllamaClient()
    return await client.chat(ollama_model, prompt)


def _to_fts_query(text: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
    tokens = [t for t in tokens if len(t) >= 3]
    if not tokens:
        return '"*"'
    # OR tends to be more forgiving for fuzzy recall.
    return " OR ".join(tokens[:20])


def _embed_entry(conn: sqlite3.Connection, entry_id: int, model: str, text: str) -> None:
    resp = requests.post(
        "http://127.0.0.1:11434/api/embeddings",
        json={"model": model, "prompt": text},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    emb = data.get("embedding")
    if not isinstance(emb, list):
        raise ValueError("ollama embeddings response missing 'embedding' list")
    vec = np.array([float(x) for x in emb], dtype=np.float32)
    conn.execute(
        """
        INSERT OR REPLACE INTO entry_embeddings(entry_id, model, dims, vector)
        VALUES (?, ?, ?, ?)
        """,
        (int(entry_id), model, int(vec.size), vec.tobytes()),
    )


async def semantic_search(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        raise ValueError("query is empty")

    with _connect() as conn:
        existing = conn.execute(
            "SELECT entry_id, model, dims, vector FROM entry_embeddings LIMIT 1"
        ).fetchone()
        if existing is None:
            return []

        embed_model = str(existing["model"])
        client = OllamaClient()
        q_vec = np.array(await client.embeddings(embed_model, q), dtype=np.float32)
        q_norm = float(np.linalg.norm(q_vec) + 1e-8)

        rows = conn.execute(
            """
            SELECT
                e.id,
                e.created_at,
                e.source,
                e.tags,
                e.text,
                emb.dims,
                emb.vector
            FROM entry_embeddings emb
            JOIN entries e ON e.id = emb.entry_id
            WHERE emb.model = ?
            """,
            (embed_model,),
        ).fetchall()

    scored: list[tuple[float, dict[str, Any]]] = []
    for r in rows:
        vec = np.frombuffer(r["vector"], dtype=np.float32, count=int(r["dims"]))
        score = float(np.dot(q_vec, vec) / (q_norm * (np.linalg.norm(vec) + 1e-8)))
        scored.append((score, dict(r)))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [item for _score, item in scored[: int(limit)]]
    # Create a snippet-ish view for display compatibility with search_entries.
    for item in top:
        item["snippet"] = (item["text"] or "").strip().replace("\n", " ")[:160]
        item.pop("text", None)
        item.pop("vector", None)
        item.pop("dims", None)
    return top
