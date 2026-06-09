from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_TOP_K = 5
MAX_CHARS_PER_CHUNK = 1800
MIN_CHARS_PER_CHUNK = 30
VECTOR_DIMS = 384
SNIPPET_CHARS = 700


@dataclass(frozen=True)
class KnowledgeHit:
    kind: str
    source_path: str
    title: str
    content: str
    bm25_score: float
    vector_score: float
    score: float

    def to_prompt_block(self, index: int) -> str:
        snippet = compact_text(self.content)[:SNIPPET_CHARS]
        title = self.title or Path(self.source_path).stem
        kind_label = {
            "fraud_case": "内部欺诈案例",
            "risk_rule": "内部风控口径",
            "general": "业务知识",
        }.get(self.kind, self.kind)
        return (
            f"[{index}] 类型: {kind_label}\n"
            f"来源: {self.source_path}\n"
            f"标题: {title}\n"
            f"内容: {snippet}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_path": self.source_path,
            "title": self.title,
            "content": self.content,
            "bm25_score": self.bm25_score,
            "vector_score": self.vector_score,
            "score": self.score,
        }


class KnowledgeBase:
    def __init__(self, root: Path, raw_dir: Path, db_path: Path) -> None:
        self.root = root
        self.raw_dir = raw_dir
        self.db_path = db_path

    def ensure_index(self) -> None:
        if not self.db_path.exists():
            self.rebuild()
            return
        if self._index_is_stale():
            self.rebuild()

    def rebuild(self) -> dict[str, Any]:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()

        docs = list(load_markdown_chunks(self.raw_dir, self.root))
        with sqlite3.connect(self.db_path) as conn:
            init_db(conn)
            for doc in docs:
                conn.execute(
                    """
                    INSERT INTO chunks(
                        kind, source_path, source_mtime, chunk_index, title, content, search_text, vector_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc["kind"],
                        doc["source_path"],
                        doc["source_mtime"],
                        doc["chunk_index"],
                        doc["title"],
                        doc["content"],
                        search_tokens(doc["title"] + "\n" + doc["content"]),
                        json.dumps(embed_text(doc["title"] + "\n" + doc["content"]), separators=(",", ":")),
                    ),
                )
            conn.execute(
                """
                INSERT INTO chunks_fts(rowid, title, content, search_text)
                SELECT id, title, content, search_text FROM chunks
                """
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('raw_dir', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(self.raw_dir),),
            )
            conn.commit()
        return {"ok": True, "chunks": len(docs), "raw_dir": str(self.raw_dir), "db_path": str(self.db_path)}

    def status(self) -> dict[str, Any]:
        markdown_files = list(self.raw_dir.rglob("*.md")) if self.raw_dir.exists() else []
        chunk_count = 0
        stale = True
        if self.db_path.exists():
            with sqlite3.connect(self.db_path) as conn:
                try:
                    chunk_count = int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
                    stale = self._index_is_stale(conn)
                except sqlite3.DatabaseError:
                    stale = True
        return {
            "raw_dir": str(self.raw_dir),
            "db_path": str(self.db_path),
            "markdown_files": len(markdown_files),
            "chunks": chunk_count,
            "stale": stale,
        }

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[KnowledgeHit]:
        query = query.strip()
        if not query:
            return []
        self.ensure_index()
        if not self.db_path.exists():
            return []

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            bm25_rows = self._search_bm25(conn, query, limit=max(top_k * 4, 12))
            vector_rows = self._search_vector(conn, query, limit=max(top_k * 4, 12))

        combined: dict[int, dict[str, Any]] = {}
        for rank, row in enumerate(bm25_rows):
            item = combined.setdefault(row["id"], dict(row))
            item["bm25_rank_score"] = 1.0 / (rank + 1)
            item["raw_bm25_score"] = float(row["bm25_score"])
        for rank, row in enumerate(vector_rows):
            item = combined.setdefault(row["id"], dict(row))
            item["vector_rank_score"] = max(float(row["vector_score"]), 1.0 / (rank + 1) * 0.5)

        hits: list[KnowledgeHit] = []
        for item in combined.values():
            bm25_score = float(item.get("bm25_rank_score", 0.0))
            vector_score = float(item.get("vector_rank_score", 0.0))
            score = 0.65 * bm25_score + 0.35 * vector_score
            hits.append(
                KnowledgeHit(
                    kind=str(item["kind"] or "general"),
                    source_path=str(item["source_path"]),
                    title=str(item["title"] or ""),
                    content=str(item["content"] or ""),
                    bm25_score=bm25_score,
                    vector_score=vector_score,
                    score=score,
                )
            )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

    def _search_bm25(self, conn: sqlite3.Connection, query: str, limit: int) -> list[sqlite3.Row]:
        fts_query = build_fts_query(query)
        if not fts_query:
            return []
        try:
            return list(
                conn.execute(
                    """
                    SELECT c.id, c.kind, c.source_path, c.title, c.content, bm25(chunks_fts) AS bm25_score
                    FROM chunks_fts
                    JOIN chunks c ON c.id = chunks_fts.rowid
                    WHERE chunks_fts MATCH ?
                    ORDER BY bm25_score
                    LIMIT ?
                    """,
                    (fts_query, limit),
                )
            )
        except sqlite3.OperationalError:
            return []

    def _search_vector(self, conn: sqlite3.Connection, query: str, limit: int) -> list[dict[str, Any]]:
        query_vector = embed_text(query)
        rows = conn.execute(
            "SELECT id, kind, source_path, title, content, vector_json FROM chunks"
        ).fetchall()
        scored: list[dict[str, Any]] = []
        for row in rows:
            try:
                vector = json.loads(row["vector_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            score = cosine_similarity(query_vector, vector)
            if score <= 0:
                continue
            scored.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "source_path": row["source_path"],
                    "title": row["title"],
                    "content": row["content"],
                    "vector_score": score,
                }
            )
        scored.sort(key=lambda item: item["vector_score"], reverse=True)
        return scored[:limit]

    def _index_is_stale(self, conn: sqlite3.Connection | None = None) -> bool:
        owns_conn = conn is None
        if conn is None:
            conn = sqlite3.connect(self.db_path)
        try:
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(chunks)")
            }
            if not {"kind", "search_text", "vector_json"}.issubset(columns):
                return True
            indexed = {
                str(row[0]): float(row[1])
                for row in conn.execute("SELECT DISTINCT source_path, source_mtime FROM chunks")
            }
        except sqlite3.DatabaseError:
            return True
        finally:
            if owns_conn:
                conn.close()

        current_files = [path for path in self.raw_dir.rglob("*.md")] if self.raw_dir.exists() else []
        current = {relative_source_path(path, self.root): path.stat().st_mtime for path in current_files}
        if set(indexed) != set(current):
            return True
        return any(abs(indexed[path] - mtime) > 0.001 for path, mtime in current.items())


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_mtime REAL NOT NULL,
            chunk_index INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            search_text TEXT NOT NULL,
            vector_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
        USING fts5(title, content, search_text, tokenize='unicode61')
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def load_markdown_chunks(raw_dir: Path, root: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for path in sorted(raw_dir.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for index, chunk in enumerate(split_markdown(text)):
            content = chunk["content"].strip()
            if len(content) < MIN_CHARS_PER_CHUNK:
                continue
            docs.append(
                {
                    "kind": classify_source(path, raw_dir),
                    "source_path": relative_source_path(path, root),
                    "source_mtime": path.stat().st_mtime,
                    "chunk_index": index,
                    "title": chunk["title"],
                    "content": content,
                }
            )
    return docs


def classify_source(path: Path, raw_dir: Path) -> str:
    try:
        parts = path.resolve().relative_to(raw_dir.resolve()).parts
    except ValueError:
        parts = path.parts
    normalized = {part.lower().replace("_", "-") for part in parts}
    if {"fraud-cases", "fraud", "anti-fraud", "欺诈案例"} & normalized:
        return "fraud_case"
    if {"risk-rules", "risk", "风控口径", "风控规则"} & normalized:
        return "risk_rule"
    return "general"


def split_markdown(text: str) -> list[dict[str, str]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    chunks: list[dict[str, str]] = []
    current_title = "未命名片段"
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        body = "\n".join(current).strip()
        if body:
            chunks.extend(split_large_chunk(current_title, body))
        current = []

    for line in lines:
        heading = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if heading:
            flush()
            current_title = heading.group(2).strip()
            current.append(line)
            continue
        current.append(line)
    flush()
    return chunks


def split_large_chunk(title: str, content: str) -> list[dict[str, str]]:
    if len(content) <= MAX_CHARS_PER_CHUNK:
        return [{"title": title, "content": content}]

    paragraphs = re.split(r"\n\s*\n", content)
    chunks: list[dict[str, str]] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and current_len + len(paragraph) > MAX_CHARS_PER_CHUNK:
            chunks.append({"title": title, "content": "\n\n".join(current)})
            current = []
            current_len = 0
        current.append(paragraph)
        current_len += len(paragraph)
    if current:
        chunks.append({"title": title, "content": "\n\n".join(current)})
    return chunks


def build_fts_query(query: str) -> str:
    tokens = search_tokens(query).split()
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in tokens[:24])


def search_tokens(text: str) -> str:
    lowered = text.lower()
    ascii_words = re.findall(r"[a-z0-9_]{2,}", lowered)
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", lowered)
    cjk_grams: list[str] = []
    for index in range(len(cjk_chars)):
        if index + 1 < len(cjk_chars):
            cjk_grams.append(cjk_chars[index] + cjk_chars[index + 1])
        if index + 2 < len(cjk_chars):
            cjk_grams.append(cjk_chars[index] + cjk_chars[index + 1] + cjk_chars[index + 2])
    tokens = ascii_words + cjk_grams
    seen: set[str] = set()
    unique = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            unique.append(token)
    return " ".join(unique)


def embed_text(text: str) -> list[float]:
    vector = [0.0] * VECTOR_DIMS
    tokens = vector_tokens(text)
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % VECTOR_DIMS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [round(value / norm, 6) for value in vector]


def vector_tokens(text: str) -> list[str]:
    lowered = text.lower()
    words = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]", lowered)
    grams: list[str] = []
    for index in range(len(words)):
        grams.append(words[index])
        if index + 1 < len(words):
            grams.append(words[index] + words[index + 1])
        if index + 2 < len(words):
            grams.append(words[index] + words[index + 1] + words[index + 2])
    return grams


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def relative_source_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def format_hits_for_prompt(hits: list[KnowledgeHit]) -> str:
    if not hits:
        return "无相关知识库片段。"
    general_hits = [hit for hit in hits if hit.kind == "general"]
    internal_hits = [hit for hit in hits if hit.kind != "general"]
    sections: list[str] = []
    if general_hits:
        sections.append(
            "业务知识参考：\n"
            + "\n\n".join(hit.to_prompt_block(index) for index, hit in enumerate(general_hits, 1))
        )
    if internal_hits:
        sections.append(
            "内部风控/欺诈案例参考（仅用于识别风险和组织温和追问，不得向客户外显）：\n"
            + "\n\n".join(hit.to_prompt_block(index) for index, hit in enumerate(internal_hits, 1))
        )
    return "\n\n".join(sections)
