from __future__ import annotations

import csv
import io
import json
import math
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.security import hash_api_key, normalize_origin


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteRepository:
    """Offline/dev repository with the same tenant-scoped contract as Supabase."""

    name = "sqlite"

    def __init__(self, path: Path, embedding_fingerprint: str = "unknown"):
        self.path = path
        self.embedding_fingerprint = embedding_fingerprint
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._lock, self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS clients (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1, config_json TEXT NOT NULL, prompt TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY, client_id TEXT UNIQUE NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                key_hash TEXT UNIQUE NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS domains (client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE, domain TEXT NOT NULL, PRIMARY KEY(client_id, domain));
            CREATE TABLE IF NOT EXISTS prompt_versions (id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE, prompt TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, citations_json TEXT NOT NULL DEFAULT '[]', route TEXT, evidence_status TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS leads (id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE, conversation_id TEXT, idempotency_key TEXT, data_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', assignee TEXT, notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS leads_client_idempotency ON leads(client_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
            CREATE TABLE IF NOT EXISTS usage_logs (id TEXT PRIMARY KEY, client_id TEXT NOT NULL, kind TEXT NOT NULL, latency_ms REAL NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit_logs (id TEXT PRIMARY KEY, client_id TEXT, action TEXT NOT NULL, detail_json TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS knowledge_files (id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE, filename TEXT NOT NULL, content_hash TEXT NOT NULL, size INTEGER NOT NULL, status TEXT NOT NULL, error TEXT, updated_at TEXT NOT NULL, UNIQUE(client_id, filename));
            CREATE TABLE IF NOT EXISTS knowledge_chunks (id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE, file_id TEXT NOT NULL REFERENCES knowledge_files(id) ON DELETE CASCADE, chunk_index INTEGER NOT NULL, content TEXT NOT NULL, embedding_json TEXT NOT NULL, source_filename TEXT NOT NULL, page INTEGER, title TEXT, embedding_fingerprint TEXT NOT NULL, UNIQUE(client_id, file_id, chunk_index, embedding_fingerprint));
            CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, client_id TEXT, idempotency_key TEXT UNIQUE, recipient TEXT, subject TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS messages_conversation_created ON messages(conversation_id, id);
            CREATE INDEX IF NOT EXISTS chunks_client ON knowledge_chunks(client_id);
            CREATE TABLE IF NOT EXISTS admin_sessions (token_hash TEXT PRIMARY KEY, csrf_token TEXT NOT NULL, credential_hash TEXT NOT NULL, expires_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS admin_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
            """)

    @staticmethod
    def _client(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["config"] = json.loads(item.pop("config_json"))
        item.pop("prompt", None)
        return item

    def create_client(self, name: str, slug: str, domains: list[str], config: dict[str, Any], prompt: str) -> dict[str, Any]:
        client_id, timestamp = str(uuid.uuid4()), now()
        key = "orb_" + secrets.token_urlsafe(32)
        with self._lock, self._db() as db:
            db.execute("INSERT INTO clients VALUES (?,?,?,?,?,?,?,?)", (client_id, name, slug, 1, json.dumps(config), prompt, timestamp, timestamp))
            for domain in domains:
                db.execute("INSERT INTO domains VALUES (?,?)", (client_id, normalize_origin(domain)))
            db.execute("INSERT INTO api_keys VALUES (?,?,?,?,?)", (str(uuid.uuid4()), client_id, hash_api_key(key), 1, timestamp))
        return {**self.get_client(client_id), "api_key": key, "domains": self.domains(client_id)}

    def list_clients(self, q: str = "", status: str = "all") -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT id,name,slug,enabled,config_json,created_at,updated_at FROM clients ORDER BY created_at DESC").fetchall()
        result = [self._client(row) for row in rows]
        return [x for x in result if (not q or q.casefold() in f"{x['name']} {x['slug']}".casefold()) and (status == "all" or x["enabled"] == (status == "active"))]

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT id,name,slug,enabled,config_json,prompt,created_at,updated_at FROM clients WHERE id=?", (client_id,)).fetchone()
        item = self._client(row)
        if item:
            item["prompt"] = row["prompt"]
        return item

    def get_client_by_key_hash(self, key_hash: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT c.id,c.name,c.slug,c.enabled,c.config_json,c.prompt,c.created_at,c.updated_at FROM clients c JOIN api_keys k ON k.client_id=c.id WHERE k.key_hash=? AND k.enabled=1", (key_hash,)).fetchone()
        item = self._client(row)
        if item:
            item["prompt"] = row["prompt"]
        return item

    def update_client(self, client_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_client(client_id)
        if not current:
            return None
        updates, values = [], []
        for key in ("name", "enabled", "prompt"):
            if key in fields and fields[key] is not None:
                updates.append(f"{key}=?"); values.append(int(fields[key]) if key == "enabled" else fields[key])
        if "config" in fields and fields["config"] is not None:
            updates.append("config_json=?"); values.append(json.dumps(fields["config"]))
        if updates:
            updates.append("updated_at=?"); values.extend([now(), client_id])
            with self._lock, self._db() as db:
                db.execute(f"UPDATE clients SET {', '.join(updates)} WHERE id=?", values)
        if "domains" in fields and fields["domains"] is not None:
            self.set_domains(client_id, fields["domains"])
        return self.get_client(client_id)

    def delete_client(self, client_id: str) -> bool:
        with self._lock, self._db() as db:
            result = db.execute("DELETE FROM clients WHERE id=?", (client_id,))
        return result.rowcount > 0

    def domains(self, client_id: str) -> list[str]:
        with self._db() as db:
            return [row[0] for row in db.execute("SELECT domain FROM domains WHERE client_id=? ORDER BY domain", (client_id,))]

    def set_domains(self, client_id: str, domains: list[str]) -> None:
        normalized = [normalize_origin(value) for value in domains]
        with self._lock, self._db() as db:
            db.execute("DELETE FROM domains WHERE client_id=?", (client_id,))
            db.executemany("INSERT INTO domains VALUES (?,?)", [(client_id, value) for value in normalized])

    def key_status(self, client_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT enabled,created_at FROM api_keys WHERE client_id=?", (client_id,)).fetchone()
        return {"enabled": bool(row[0]), "created_at": row[1]} if row else None

    def rotate_key(self, client_id: str) -> str | None:
        raw = "orb_" + secrets.token_urlsafe(32)
        with self._lock, self._db() as db:
            result = db.execute("UPDATE api_keys SET key_hash=?,enabled=1,created_at=? WHERE client_id=?", (hash_api_key(raw), now(), client_id))
        return raw if result.rowcount else None

    def set_key_enabled(self, client_id: str, enabled: bool) -> bool:
        with self._lock, self._db() as db:
            result = db.execute("UPDATE api_keys SET enabled=? WHERE client_id=?", (int(enabled), client_id))
        return result.rowcount > 0

    def save_prompt_version(self, client_id: str, prompt: str) -> None:
        with self._lock, self._db() as db:
            db.execute("INSERT INTO prompt_versions VALUES (?,?,?,?)", (str(uuid.uuid4()), client_id, prompt, now()))

    def prompt_versions(self, client_id: str) -> list[dict[str, Any]]:
        with self._db() as db:
            return [dict(row) for row in db.execute("SELECT id,client_id,prompt,created_at FROM prompt_versions WHERE client_id=? ORDER BY created_at DESC", (client_id,))]

    def create_conversation(self, client_id: str) -> str:
        conversation_id, timestamp = str(uuid.uuid4()), now()
        with self._lock, self._db() as db:
            db.execute("INSERT INTO conversations VALUES (?,?,?,?,?)", (conversation_id, client_id, "New conversation", timestamp, timestamp))
        return conversation_id

    def conversation_exists(self, client_id: str, conversation_id: str) -> bool:
        with self._db() as db:
            return db.execute("SELECT 1 FROM conversations WHERE id=? AND client_id=?", (conversation_id, client_id)).fetchone() is not None

    def history(self, client_id: str, conversation_id: str, limit: int) -> list[dict[str, str]]:
        with self._db() as db:
            rows = db.execute("SELECT m.role,m.content FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.conversation_id=? AND c.client_id=? ORDER BY m.id DESC LIMIT ?", (conversation_id, client_id, limit)).fetchall()
        return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

    def save_message(self, client_id: str, conversation_id: str, role: str, content: str, citations: list[dict[str, Any]] | None = None, route: str | None = None, evidence_status: str | None = None) -> None:
        if not self.conversation_exists(client_id, conversation_id):
            raise KeyError("Conversation not found")
        timestamp = now()
        with self._lock, self._db() as db:
            db.execute("INSERT INTO messages(conversation_id,role,content,citations_json,route,evidence_status,created_at) VALUES (?,?,?,?,?,?,?)", (conversation_id, role, content, json.dumps(citations or [], ensure_ascii=False), route, evidence_status, timestamp))
            title = content[:72] if role == "user" else None
            if title:
                db.execute("UPDATE conversations SET title=?,updated_at=? WHERE id=?", (title, timestamp, conversation_id))
            else:
                db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (timestamp, conversation_id))

    def list_conversations(self, client_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT c.id AS session_id,c.title,c.created_at,c.updated_at,COUNT(m.id) message_count FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.id WHERE c.client_id=? GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ? OFFSET ?", (client_id, limit, offset)).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, client_id: str, conversation_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            conversation = db.execute("SELECT id AS session_id,title,created_at,updated_at FROM conversations WHERE id=? AND client_id=?", (conversation_id, client_id)).fetchone()
            if not conversation:
                return None
            rows = db.execute("SELECT role,content,citations_json,route,evidence_status,created_at FROM messages WHERE conversation_id=? ORDER BY id", (conversation_id,)).fetchall()
        return {**dict(conversation), "messages": [{**dict(row), "citations": json.loads(row["citations_json"])} for row in rows]}

    def delete_conversation(self, client_id: str, conversation_id: str) -> bool:
        with self._lock, self._db() as db:
            result = db.execute("DELETE FROM conversations WHERE id=? AND client_id=?", (conversation_id, client_id))
        return result.rowcount > 0

    def delete_expired_conversations(self, cutoff: str) -> int:
        with self._lock, self._db() as db:
            result = db.execute("DELETE FROM conversations WHERE created_at<=?", (cutoff,))
        return result.rowcount

    def save_file(self, client_id: str, filename: str, content_hash: str, size: int, status: str = "processing") -> str:
        file_id, timestamp = str(uuid.uuid4()), now()
        with self._lock, self._db() as db:
            old = db.execute("SELECT id FROM knowledge_files WHERE client_id=? AND filename=?", (client_id, filename)).fetchone()
            if old:
                file_id = old[0]
                db.execute("UPDATE knowledge_files SET content_hash=?,size=?,status=?,error=NULL,updated_at=? WHERE id=?", (content_hash, size, status, timestamp, file_id))
            else:
                db.execute("INSERT INTO knowledge_files VALUES (?,?,?,?,?,?,?,?)", (file_id, client_id, filename, content_hash, size, status, None, timestamp))
        return file_id

    def finish_file(self, client_id: str, file_id: str, status: str, error: str | None = None) -> None:
        with self._lock, self._db() as db:
            db.execute("UPDATE knowledge_files SET status=?,error=?,updated_at=? WHERE id=? AND client_id=?", (status, error[:500] if error else None, now(), file_id, client_id))

    def list_files(self, client_id: str) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT id,filename,content_hash,size,status,error,updated_at FROM knowledge_files WHERE client_id=? ORDER BY filename", (client_id,)).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["chunks"] = db.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE file_id=?", (row["id"],)).fetchone()[0]
                result.append(item)
        return result

    def delete_file(self, client_id: str, filename: str) -> bool:
        with self._lock, self._db() as db:
            result = db.execute("DELETE FROM knowledge_files WHERE client_id=? AND filename=?", (client_id, filename))
        return result.rowcount > 0

    def save_chunks(self, client_id: str, file_id: str, filename: str, chunks: list[dict[str, Any]]) -> None:
        with self._lock, self._db() as db:
            # The transaction preserves the previous serving chunks if insertion fails.
            db.execute("DELETE FROM knowledge_chunks WHERE file_id=? AND client_id=?", (file_id, client_id))
            db.executemany("INSERT INTO knowledge_chunks VALUES (?,?,?,?,?,?,?,?,?,?)", [(str(uuid.uuid4()), client_id, file_id, item["index"], item["text"], json.dumps(item["embedding"]), filename, item.get("page"), item.get("title"), self.embedding_fingerprint) for item in chunks])

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right))
        nl = math.sqrt(sum(a * a for a in left)); nr = math.sqrt(sum(b * b for b in right))
        return dot / (nl * nr) if nl and nr else 0.0

    def search_chunks(self, client_id: str, vector: list[float], top_k: int, threshold: float) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT id,content,source_filename,page,title,embedding_json FROM knowledge_chunks WHERE client_id=? AND embedding_fingerprint=?", (client_id, self.embedding_fingerprint)).fetchall()
        scored = []
        for row in rows:
            score = self._cosine(vector, json.loads(row["embedding_json"]))
            if score >= threshold:
                scored.append({"id": row["id"], "text": row["content"], "similarity": score, "metadata": {"source_filename": row["source_filename"], "page_number": row["page"], "document_title": row["title"]}})
        return sorted(scored, key=lambda x: x["similarity"], reverse=True)[:top_k]

    def create_lead(self, client_id: str, data: dict[str, Any], conversation_id: str | None, idempotency_key: str | None) -> dict[str, Any]:
        if idempotency_key:
            with self._db() as db:
                old = db.execute("SELECT * FROM leads WHERE client_id=? AND idempotency_key=?", (client_id, idempotency_key)).fetchone()
            if old:
                return self._lead(old)
        lead_id, timestamp = str(uuid.uuid4()), now()
        with self._lock, self._db() as db:
            db.execute("INSERT INTO leads VALUES (?,?,?,?,?,?,?,?,?,?)", (lead_id, client_id, conversation_id, idempotency_key, json.dumps(data), "new", None, "", timestamp, timestamp))
            row = db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        return self._lead(row)

    def enqueue_notification(self, client_id: str, idempotency_key: str, recipient: str, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._db() as db:
            existing = db.execute("SELECT * FROM notifications WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                return dict(existing)
            notification_id = str(uuid.uuid4())
            db.execute("INSERT INTO notifications VALUES (?,?,?,?,?,?,?,?,?,?)", (notification_id, client_id, idempotency_key, recipient, subject, json.dumps(payload), "pending", 0, None, now()))
            return {"id": notification_id, "status": "pending"}

    @staticmethod
    def _lead(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row); item["data"] = json.loads(item.pop("data_json")); return item

    def list_leads(self, client_id: str) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM leads WHERE client_id=? ORDER BY created_at DESC", (client_id,)).fetchall()
        return [self._lead(row) for row in rows]

    def update_lead(self, client_id: str, lead_id: str, fields: dict[str, Any]) -> bool:
        allowed = {key: fields[key] for key in ("status", "assignee", "notes") if key in fields}
        if "data" in fields:
            allowed["data_json"] = json.dumps(fields["data"])
        if not allowed:
            return False
        sets = ", ".join(f"{key}=?" for key in allowed); values = list(allowed.values()) + [now(), lead_id, client_id]
        with self._lock, self._db() as db:
            result = db.execute(f"UPDATE leads SET {sets},updated_at=? WHERE id=? AND client_id=?", values)
        return result.rowcount > 0

    def audit(self, client_id: str | None, action: str, detail: dict[str, Any]) -> None:
        with self._lock, self._db() as db:
            db.execute("INSERT INTO audit_logs VALUES (?,?,?,?,?)", (str(uuid.uuid4()), client_id, action, json.dumps(detail), now()))

    def audits(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._db() as db:
            return [dict(row) for row in db.execute("SELECT id,client_id,action,detail_json,created_at FROM audit_logs ORDER BY created_at DESC LIMIT ?", (limit,))]

    def audit_page(self, client_id: str | None, q: str, page: int, page_size: int) -> dict:
        conditions, values = [], []
        if client_id:
            conditions.append("client_id=?")
            values.append(client_id)
        if q:
            conditions.append("action LIKE ?")
            values.append(f"%{q}%")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self._db() as db:
            total = db.execute(f"SELECT COUNT(*) FROM audit_logs{where}", values).fetchone()[0]
            rows = db.execute(f"SELECT id,client_id,action,created_at FROM audit_logs{where} ORDER BY created_at DESC LIMIT ? OFFSET ?", [*values, page_size, (page - 1) * page_size]).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "pageSize": page_size}

    def usage(self, client_id: str, kind: str, latency_ms: float) -> None:
        with self._lock, self._db() as db:
            db.execute("INSERT INTO usage_logs VALUES (?,?,?,?,?)", (str(uuid.uuid4()), client_id, kind, latency_ms, now()))

    def analytics(self, client_id: str) -> dict[str, Any]:
        from app.services.admin_reporting import aggregate
        return aggregate(self.reporting_records(client_id))

    def overview(self) -> dict[str, Any]:
        from app.services.admin_reporting import aggregate
        clients = self.list_clients()
        return {"clients": len(clients), "active_clients": sum(item["enabled"] for item in clients), **aggregate(self.reporting_records())}

    def reporting_records(self, client_id: str | None = None) -> dict[str, list[dict]]:
        result = {}
        with self._db() as db:
            for table in ("conversations", "leads", "usage_logs", "knowledge_files"):
                where = " WHERE client_id=?" if client_id else ""
                rows = db.execute(f"SELECT * FROM {table}{where}", (client_id,) if client_id else ()).fetchall()
                result[table] = [dict(row) for row in rows]
            for item in result["conversations"]:
                item["message_count"] = db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?", (item["id"],)).fetchone()[0]
        return result

    def create_admin_session(self, token_hash: str, csrf_token: str, credential_hash: str, expires_at: str) -> None:
        with self._lock, self._db() as db:
            db.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (now(),))
            db.execute("INSERT INTO admin_sessions VALUES (?,?,?,?)", (token_hash, csrf_token, credential_hash, expires_at))

    def admin_session(self, token_hash: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM admin_sessions WHERE token_hash=?", (token_hash,)).fetchone()
        return dict(row) if row else None

    def delete_admin_session(self, token_hash: str) -> None:
        with self._lock, self._db() as db:
            db.execute("DELETE FROM admin_sessions WHERE token_hash=?", (token_hash,))

    def setting(self, key: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT value_json FROM admin_settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_setting(self, key: str, value: dict) -> None:
        with self._lock, self._db() as db:
            db.execute("INSERT INTO admin_settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (key, json.dumps(value)))

    def delete_setting(self, key: str) -> None:
        with self._lock, self._db() as db:
            db.execute("DELETE FROM admin_settings WHERE key=?", (key,))

    def health(self) -> dict[str, Any]:
        with self._db() as db:
            db.execute("SELECT 1")
        return {"provider": self.name, "status": "ok"}

    def export_leads_csv(self, client_id: str) -> str:
        fields = ["id", "name", "email", "phone", "requirement", "message", "status", "assignee", "notes", "created_at"]
        output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
        for lead in self.list_leads(client_id):
            row = {key: lead.get(key, lead.get("data", {}).get(key, "")) for key in fields}
            for key, value in row.items():
                if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
                    row[key] = "'" + value
            writer.writerow(row)
        return output.getvalue()
