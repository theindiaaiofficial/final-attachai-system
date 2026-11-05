from __future__ import annotations

import csv
import io
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from app.security import hash_api_key, normalize_origin


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SupabaseRepository:
    """Synchronous PostgREST repository with explicit tenant filters."""

    name = "supabase"

    def __init__(self, url: str, service_role_key: str, embedding_fingerprint: str):
        self.base_url = url.rstrip("/") + "/rest/v1"
        self.headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}
        self.embedding_fingerprint = embedding_fingerprint

    def _request(self, method: str, table: str, *, tenant_id: str | None = None, params: dict[str, str] | None = None, payload: Any = None) -> Any:
        params = dict(params or {})
        if tenant_id and table not in {"clients", "api_keys"}:
            params.setdefault("client_id", f"eq.{tenant_id}")
        headers = {**self.headers, "Prefer": "return=representation"}
        with httpx.Client(timeout=20) as client:
            response = client.request(method, f"{self.base_url}/{table}", headers=headers, params=params, json=payload)
        response.raise_for_status()
        return response.json() if response.content else []

    @staticmethod
    def _client(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if not row:
            return None
        return {**row, "config": row.get("config") or {}, "enabled": bool(row.get("enabled", True))}

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        rows = self._request("GET", "clients", params={"id": f"eq.{client_id}", "limit": "1"})
        return self._client(rows[0] if rows else None)

    def get_client_by_key_hash(self, key_hash: str) -> dict[str, Any] | None:
        keys = self._request("GET", "api_keys", params={"key_hash": f"eq.{key_hash}", "enabled": "eq.true", "limit": "1"})
        return self.get_client(keys[0]["client_id"]) if keys else None

    def create_client(self, name: str, slug: str, domains: list[str], config: dict[str, Any], prompt: str) -> dict[str, Any]:
        client_id = str(uuid.uuid4()); raw_key = "orb_" + secrets.token_urlsafe(32); timestamp = _now()
        rows = self._request("POST", "clients", payload={"id": client_id, "name": name, "slug": slug, "config": config, "prompt": prompt, "created_at": timestamp, "updated_at": timestamp})
        self._request("POST", "api_keys", payload={"client_id": client_id, "key_hash": hash_api_key(raw_key), "enabled": True})
        self._request("POST", "domains", payload=[{"client_id": client_id, "domain": normalize_origin(domain)} for domain in domains])
        return {**self._client(rows[0]), "api_key": raw_key, "domains": self.domains(client_id)}

    def list_clients(self, q: str = "", status: str = "all") -> list[dict[str, Any]]:
        rows = self._all("clients", params={"select": "id,name,slug,enabled,config,created_at,updated_at", "order": "created_at.desc,id"})
        return [item for item in (self._client(row) for row in rows) if item and (not q or q.casefold() in f"{item['name']} {item['slug']}".casefold()) and (status == "all" or item["enabled"] == (status == "active"))]

    def update_client(self, client_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        payload = {key: fields[key] for key in ("name", "enabled", "prompt", "config") if key in fields}
        if payload:
            payload["updated_at"] = _now(); self._request("PATCH", "clients", params={"id": f"eq.{client_id}"}, payload=payload)
        if fields.get("domains") is not None:
            self.set_domains(client_id, fields["domains"])
        return self.get_client(client_id)

    def delete_client(self, client_id: str) -> bool:
        self._request("DELETE", "clients", params={"id": f"eq.{client_id}"})
        return True

    def domains(self, client_id: str) -> list[str]:
        rows = self._request("GET", "domains", tenant_id=client_id, params={"select": "domain", "order": "domain"})
        return [row["domain"] for row in rows]

    def set_domains(self, client_id: str, domains: list[str]) -> None:
        self._request("DELETE", "domains", tenant_id=client_id)
        self._request("POST", "domains", payload=[{"client_id": client_id, "domain": normalize_origin(value)} for value in domains])

    def key_status(self, client_id: str) -> dict[str, Any] | None:
        rows = self._request("GET", "api_keys", params={"client_id": f"eq.{client_id}", "select": "enabled,created_at", "limit": "1"})
        return {"enabled": bool(rows[0]["enabled"]), "created_at": rows[0]["created_at"]} if rows else None

    def rotate_key(self, client_id: str) -> str | None:
        raw = "orb_" + secrets.token_urlsafe(32)
        rows = self._request("PATCH", "api_keys", params={"client_id": f"eq.{client_id}"}, payload={"key_hash": hash_api_key(raw), "enabled": True, "created_at": _now()})
        return raw if rows else None

    def set_key_enabled(self, client_id: str, enabled: bool) -> bool:
        return bool(self._request("PATCH", "api_keys", params={"client_id": f"eq.{client_id}"}, payload={"enabled": enabled}))

    def save_prompt_version(self, client_id: str, prompt: str) -> None:
        self._request("POST", "prompt_versions", payload={"client_id": client_id, "prompt": prompt})

    def prompt_versions(self, client_id: str) -> list[dict[str, Any]]:
        return self._request("GET", "prompt_versions", tenant_id=client_id, params={"order": "created_at.desc"})

    def create_conversation(self, client_id: str) -> str:
        rows = self._request("POST", "conversations", payload={"client_id": client_id})
        return rows[0]["id"]

    def conversation_exists(self, client_id: str, conversation_id: str) -> bool:
        return bool(self._request("GET", "conversations", params={"id": f"eq.{conversation_id}", "client_id": f"eq.{client_id}", "select": "id", "limit": "1"}))

    def history(self, client_id: str, conversation_id: str, limit: int) -> list[dict[str, str]]:
        if not self.conversation_exists(client_id, conversation_id):
            return []
        rows = self._request("GET", "messages", params={"conversation_id": f"eq.{conversation_id}", "select": "role,content", "order": "created_at.desc", "limit": str(limit)})
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    def save_message(self, client_id: str, conversation_id: str, role: str, content: str, citations: list[dict[str, Any]] | None = None, route: str | None = None, evidence_status: str | None = None) -> None:
        if not self.conversation_exists(client_id, conversation_id):
            raise KeyError("Conversation not found")
        self._request("POST", "messages", payload={"conversation_id": conversation_id, "role": role, "content": content, "citations": citations or [], "route": route, "evidence_status": evidence_status})
        self._request("PATCH", "conversations", params={"id": f"eq.{conversation_id}", "client_id": f"eq.{client_id}"}, payload={"updated_at": _now(), **({"title": content[:72]} if role == "user" else {})})

    def list_conversations(self, client_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        rows = self._all("conversations", tenant_id=client_id, params={"order": "updated_at.desc,id"})
        return [{**row, "session_id": row["id"]} for row in rows[offset:offset + limit]]

    def get_conversation(self, client_id: str, conversation_id: str) -> dict[str, Any] | None:
        rows = self._request("GET", "conversations", params={"id": f"eq.{conversation_id}", "client_id": f"eq.{client_id}", "limit": "1"})
        if not rows:
            return None
        messages = self._request("GET", "messages", params={"conversation_id": f"eq.{conversation_id}", "order": "created_at"})
        return {**rows[0], "session_id": rows[0]["id"], "messages": messages}

    def delete_conversation(self, client_id: str, conversation_id: str) -> bool:
        before = self.get_conversation(client_id, conversation_id)
        self._request("DELETE", "conversations", params={"id": f"eq.{conversation_id}", "client_id": f"eq.{client_id}"})
        return before is not None

    def delete_expired_conversations(self, cutoff: str) -> int:
        rows = self._request(
            "DELETE",
            "conversations",
            params={"created_at": f"lte.{cutoff}", "select": "id"},
        )
        return len(rows)

    def save_file(self, client_id: str, filename: str, content_hash: str, size: int, status: str = "processing") -> str:
        rows = self._request("GET", "knowledge_files", tenant_id=client_id, params={"filename": f"eq.{filename}", "limit": "1"})
        payload = {"client_id": client_id, "filename": filename, "content_hash": content_hash, "size": size, "status": status, "updated_at": _now()}
        if rows:
            file_id = rows[0]["id"]
            self._request("PATCH", "knowledge_files", params={"id": f"eq.{file_id}", "client_id": f"eq.{client_id}"}, payload=payload)
            return file_id
        return self._request("POST", "knowledge_files", payload=payload)[0]["id"]

    def finish_file(self, client_id: str, file_id: str, status: str, error: str | None = None) -> None:
        self._request("PATCH", "knowledge_files", params={"id": f"eq.{file_id}", "client_id": f"eq.{client_id}"}, payload={"status": status, "error": error[:500] if error else None, "updated_at": _now()})

    def list_files(self, client_id: str) -> list[dict[str, Any]]:
        files = self._all("knowledge_files", tenant_id=client_id, params={"order": "filename"})
        for item in files:
            item["chunks"] = len(self._request("GET", "knowledge_chunks", tenant_id=client_id, params={"file_id": f"eq.{item['id']}", "select": "id"}))
        return files

    def delete_file(self, client_id: str, filename: str) -> bool:
        files = self._request("GET", "knowledge_files", tenant_id=client_id, params={"filename": f"eq.{filename}", "select": "id"})
        if not files:
            return False
        self._request("DELETE", "knowledge_files", params={"id": f"eq.{files[0]['id']}", "client_id": f"eq.{client_id}"})
        return True

    def save_chunks(self, client_id: str, file_id: str, filename: str, chunks: list[dict[str, Any]]) -> None:
        self._request("DELETE", "knowledge_chunks", tenant_id=client_id, params={"file_id": f"eq.{file_id}"})
        self._request("DELETE", "knowledge_vectors_v2", tenant_id=client_id, params={"file_id": f"eq.{file_id}"})
        self._request("POST", "knowledge_chunks", payload=[{"client_id": client_id, "file_id": file_id, "chunk_index": item["index"], "content": item["text"], "source_filename": filename, "page": item.get("page"), "title": item.get("title"), "embedding_fingerprint": self.embedding_fingerprint} for item in chunks])
        self._request("POST", "knowledge_vectors_v2", payload=[{"client_id": client_id, "file_id": file_id, "chunk_index": item["index"], "content": item["text"], "embedding": item["embedding"], "source_filename": filename, "page": item.get("page"), "title": item.get("title"), "embedding_provider": self.embedding_fingerprint.split(":", 1)[0], "embedding_model": self.embedding_fingerprint.split(":")[1], "embedding_dimension": len(item["embedding"]), "embedding_fingerprint": self.embedding_fingerprint} for item in chunks])

    def search_chunks(self, client_id: str, vector: list[float], top_k: int, threshold: float) -> list[dict[str, Any]]:
        rows = self._request("POST", "rpc/match_knowledge_vectors_v2", payload={"query_embedding": vector, "match_client_id": client_id, "match_fingerprint": self.embedding_fingerprint, "match_threshold": threshold, "match_count": top_k})
        return [{"id": row["id"], "text": row["content"], "similarity": row["similarity"], "metadata": {"source_filename": row["source_filename"], "page_number": row.get("page"), "document_title": row.get("title")}} for row in rows]

    def create_lead(self, client_id: str, data: dict[str, Any], conversation_id: str | None, idempotency_key: str | None) -> dict[str, Any]:
        if idempotency_key:
            old = self._request("GET", "leads", tenant_id=client_id, params={"idempotency_key": f"eq.{idempotency_key}", "limit": "1"})
            if old:
                return old[0]
        return self._request("POST", "leads", payload={"client_id": client_id, "conversation_id": conversation_id, "idempotency_key": idempotency_key, "data": data})[0]

    def enqueue_notification(self, client_id: str, idempotency_key: str, recipient: str, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self._request("GET", "notifications", tenant_id=client_id, params={"idempotency_key": f"eq.{idempotency_key}", "limit": "1"})
        if existing:
            return existing[0]
        return self._request("POST", "notifications", payload={"client_id": client_id, "idempotency_key": idempotency_key, "recipient": recipient, "subject": subject, "payload": payload, "status": "pending"})[0]

    def list_leads(self, client_id: str) -> list[dict[str, Any]]:
        return self._all("leads", tenant_id=client_id, params={"order": "created_at.desc,id"})

    def update_lead(self, client_id: str, lead_id: str, fields: dict[str, Any]) -> bool:
        return bool(self._request("PATCH", "leads", params={"id": f"eq.{lead_id}", "client_id": f"eq.{client_id}"}, payload=fields))

    def audit(self, client_id: str | None, action: str, detail: dict[str, Any]) -> None:
        self._request("POST", "audit_logs", payload={"client_id": client_id, "action": action, "detail": detail})

    def audits(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._request("GET", "audit_logs", params={"order": "created_at.desc", "limit": str(limit)})

    def audit_page(self, client_id: str | None, q: str, page: int, page_size: int) -> dict:
        rows = self._all("audit_logs", tenant_id=client_id, params={"select": "id,client_id,action,created_at", "order": "created_at.desc,id"})
        rows = [row for row in rows if q.casefold() in row["action"].casefold()]
        return {"items": rows[(page - 1) * page_size:page * page_size], "total": len(rows), "page": page, "pageSize": page_size}

    def usage(self, client_id: str, kind: str, latency_ms: float) -> None:
        self._request("POST", "usage_logs", payload={"client_id": client_id, "kind": kind, "latency_ms": latency_ms})

    def analytics(self, client_id: str) -> dict[str, Any]:
        from app.services.admin_reporting import aggregate
        return aggregate(self.reporting_records(client_id))

    def overview(self) -> dict[str, Any]:
        from app.services.admin_reporting import aggregate
        clients = self.list_clients()
        return {"clients": len(clients), "active_clients": sum(item["enabled"] for item in clients), **aggregate(self.reporting_records())}

    def _all(self, table: str, tenant_id: str | None = None, params: dict | None = None) -> list[dict]:
        rows = []
        while True:
            page = self._request("GET", table, tenant_id=tenant_id, params={**(params or {}), "limit": "500", "offset": str(len(rows))})
            rows.extend(page)
            if len(page) < 500:
                return rows

    def reporting_records(self, client_id: str | None = None) -> dict[str, list[dict]]:
        result = {table: self._all(table, tenant_id=client_id, params={"order": "id"}) for table in ("conversations", "leads", "usage_logs", "knowledge_files")}
        for item in result["conversations"]:
            messages = self._all("messages", params={"conversation_id": f"eq.{item['id']}", "select": "id", "order": "id"})
            item["message_count"] = len(messages)
        return result

    def create_admin_session(self, token_hash: str, csrf_token: str, credential_hash: str, expires_at: str) -> None:
        self._request("DELETE", "admin_sessions", params={"expires_at": f"lt.{_now()}"})
        self._request("POST", "admin_sessions", payload={"token_hash": token_hash, "csrf_token": csrf_token, "credential_hash": credential_hash, "expires_at": expires_at})

    def admin_session(self, token_hash: str) -> dict | None:
        rows = self._request("GET", "admin_sessions", params={"token_hash": f"eq.{token_hash}", "limit": "1"})
        return rows[0] if rows else None

    def delete_admin_session(self, token_hash: str) -> None:
        self._request("DELETE", "admin_sessions", params={"token_hash": f"eq.{token_hash}"})

    def setting(self, key: str) -> dict | None:
        rows = self._request("GET", "admin_settings", params={"key": f"eq.{key}", "limit": "1"})
        return rows[0]["value"] if rows else None

    def set_setting(self, key: str, value: dict) -> None:
        if self.setting(key) is not None:
            self._request("PATCH", "admin_settings", params={"key": f"eq.{key}"}, payload={"value": value, "updated_at": _now()})
        else:
            self._request("POST", "admin_settings", payload={"key": key, "value": value})

    def delete_setting(self, key: str) -> None:
        self._request("DELETE", "admin_settings", params={"key": f"eq.{key}"})

    def health(self) -> dict[str, str]:
        self._request("GET", "clients", params={"select": "id", "limit": "1"})
        return {"provider": self.name, "status": "ok"}

    def export_leads_csv(self, client_id: str) -> str:
        fields = ["id", "name", "email", "phone", "requirement", "message", "status", "assignee", "notes", "created_at"]
        output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
        for lead in self.list_leads(client_id):
            row = {key: lead.get(key, lead.get("data", {}).get(key, "")) for key in fields}
            for key, value in row.items():
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    row[key] = "'" + value
            writer.writerow(row)
        return output.getvalue()
