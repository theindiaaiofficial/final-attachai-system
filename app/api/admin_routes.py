from __future__ import annotations

import asyncio
import ipaddress
import secrets
import socket
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

from app.domain.schemas import (
    AdminLogin,
    ClientCreate,
    ClientPatch,
    DuplicateRequest,
    LeadPatch,
    ProviderTest,
    ProviderUpdate,
)
from app.security import hash_api_key, safe_equal
from app.security.admin_session import (
    COOKIE,
    LoginLimiter,
    require_admin,
    same_origin,
    session_record,
)
from app.services.admin_reporting import aggregate, client_usage

router = APIRouter(prefix="/admin", tags=["Administration"])
protected = APIRouter(dependencies=[Depends(require_admin)])
limiter = LoginLimiter()


def current(request: Request):
    return request.app.state.state


def client(request: Request, client_id: UUID):
    item = current(request).repository.get_client(str(client_id))
    if not item:
        raise HTTPException(404, "Client not found")
    return item


@router.post("/auth/login")
def login(payload: AdminLogin, request: Request, response: Response):
    same_origin(request)
    limiter.check(request.client.host if request.client else "unknown")
    state = current(request)
    if not safe_equal(
        payload.api_key.get_secret_value(),
        state.settings.admin_api_key.get_secret_value(),
    ):
        raise HTTPException(401, "Invalid admin API key")
    previous = request.cookies.get(COOKIE)
    if previous:
        state.repository.delete_admin_session(hash_api_key(previous))
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(hours=state.settings.admin_session_hours)
    state.repository.create_admin_session(
        hash_api_key(token),
        csrf,
        hash_api_key(state.settings.admin_api_key.get_secret_value()),
        expires.isoformat(),
    )
    response.set_cookie(
        COOKIE,
        token,
        max_age=state.settings.admin_session_hours * 3600,
        httponly=True,
        secure=state.settings.app_env == "production",
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    state.repository.audit(None, "admin.login", {})
    return {
        "authenticated": True,
        "csrf_token": csrf,
        "expires_at": expires.isoformat(),
    }


@protected.get("/auth/session")
def session(request: Request):
    item = session_record(request)
    return {
        "authenticated": True,
        "csrf_token": item["csrf_token"] if item else None,
        "expires_at": item["expires_at"] if item else None,
    }


@protected.post("/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        current(request).repository.delete_admin_session(hash_api_key(token))
    response.delete_cookie(COOKIE, path="/")
    return {"authenticated": False}


@protected.post("/auth/validate")
def validate():
    return {"authenticated": True}


def safe_providers(state):
    roles = {}
    for role in ("router", "answer"):
        config = state.settings.provider_configuration(role)
        roles[role] = {key: config[key] for key in ("provider", "model", "api_base")}
        roles[role].update(
            {
                "credentials_present": bool(
                    config["api_key"] and not config["api_key"].startswith("YOUR_")
                ),
                "completion_status": state.provider_tests.get(
                    role, {"status": "not_tested"}
                ),
            }
        )
    roles["embedding"] = {
        "provider": state.settings.embedding_provider,
        "model": state.settings.embedding_model,
        "dimension": state.embeddings.dimension,
        "fingerprint": state.embeddings.fingerprint,
    }
    return roles


@protected.get("/overview")
def overview(request: Request):
    state = current(request)
    return {
        **state.repository.overview(),
        "recentAudits": state.repository.audits(8),
        "providers": safe_providers(state),
    }


@protected.get("/status")
def status(request: Request):
    state = current(request)
    try:
        database = state.repository.health()
    except Exception:
        database = {"provider": state.repository.name, "status": "unavailable"}
    issues = state.settings.readiness_issues()
    return {
        "database": database,
        "storage": state.storage.health(),
        "readiness": "configuration_incomplete" if issues else "configured",
        "issues": issues,
        "rag": {"pipeline": "RAG-2.0", "provider_calls": "not_tested"},
        "delivery": "Outbox persistence only; no delivery transport configured",
    }


@protected.get("/clients")
def clients(
    request: Request,
    q: str = Query("", max_length=120),
    status: Literal["all", "active", "suspended"] = "all",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    repo = current(request).repository
    rows = repo.list_clients(q, status)
    items = [
        {
            **row,
            "domains": repo.domains(row["id"]),
            "apiKey": repo.key_status(row["id"]),
        }
        for row in rows[(page - 1) * page_size : page * page_size]
    ]
    return {"items": items, "total": len(rows), "page": page, "pageSize": page_size}


@protected.post("/clients")
def create(payload: ClientCreate, request: Request):
    repo = current(request).repository
    if any(item["slug"] == payload.slug for item in repo.list_clients()):
        raise HTTPException(409, "A client already uses that slug")
    try:
        item = repo.create_client(**payload.model_dump())
    except sqlite3.IntegrityError:
        raise HTTPException(
            409, "Client could not be created; check the slug and domains"
        ) from None
    repo.audit(item["id"], "client.created", {})
    return item


@protected.get("/clients/{client_id}")
def detail(client_id: UUID, request: Request):
    item = client(request, client_id)
    repo = current(request).repository
    return {
        **item,
        "domains": repo.domains(str(client_id)),
        "apiKey": repo.key_status(str(client_id)),
        "stats": repo.analytics(str(client_id)),
    }


@protected.patch("/clients/{client_id}")
def update(client_id: UUID, payload: ClientPatch, request: Request):
    old = client(request, client_id)
    repo = current(request).repository
    fields = payload.model_dump(exclude_unset=True)
    if fields.get("prompt") is not None and fields["prompt"] != old["prompt"]:
        repo.save_prompt_version(str(client_id), old["prompt"])
    item = repo.update_client(str(client_id), fields)
    repo.audit(str(client_id), "client.updated", {"fields": list(fields)})
    return item


@protected.delete("/clients/{client_id}")
def remove(client_id: UUID, request: Request):
    client(request, client_id)
    state = current(request)
    # Storage deletion must succeed before deleting the manifests that locate objects.
    for item in state.repository.list_files(str(client_id)):
        state.storage.delete(str(client_id), item["id"], item["filename"])
    state.repository.audit(str(client_id), "client.deleted", {})
    state.repository.delete_client(str(client_id))
    return {"deleted": True}


@protected.post("/clients/{client_id}/duplicate")
def duplicate(client_id: UUID, payload: DuplicateRequest, request: Request):
    source = client(request, client_id)
    return create(
        ClientCreate(
            **payload.model_dump(),
            domains=current(request).repository.domains(str(client_id)),
            config=source["config"],
            prompt=source["prompt"],
        ),
        request,
    )


@protected.post("/clients/{client_id}/rotate-key")
def rotate(client_id: UUID, request: Request):
    client(request, client_id)
    repo = current(request).repository
    key = repo.rotate_key(str(client_id))
    repo.audit(str(client_id), "key.rotated", {})
    return {"apiKey": key}


@protected.post("/clients/{client_id}/key/{action}")
def key_action(client_id: UUID, action: Literal["enable", "disable"], request: Request):
    client(request, client_id)
    repo = current(request).repository
    repo.set_key_enabled(str(client_id), action == "enable")
    repo.audit(str(client_id), f"key.{action}d", {})
    return {"enabled": action == "enable"}


@protected.get("/clients/{client_id}/prompts/history")
def prompts(client_id: UUID, request: Request):
    client(request, client_id)
    return current(request).repository.prompt_versions(str(client_id))


@protected.post("/clients/{client_id}/prompts/reset")
def reset_prompt(client_id: UUID, request: Request):
    return update(
        client_id,
        ClientPatch(
            prompt="Answer using only the supplied knowledge. If unavailable, say so clearly."
        ),
        request,
    )


@protected.post("/clients/{client_id}/prompts/{version_id}/restore")
def restore_prompt(client_id: UUID, version_id: UUID, request: Request):
    client(request, client_id)
    version = next(
        (
            row
            for row in current(request).repository.prompt_versions(str(client_id))
            if row["id"] == str(version_id)
        ),
        None,
    )
    if not version:
        raise HTTPException(404, "Prompt version not found for this client")
    return update(client_id, ClientPatch(prompt=version["prompt"]), request)


@protected.get("/clients/{client_id}/knowledge")
def knowledge(client_id: UUID, request: Request):
    client(request, client_id)
    return current(request).knowledge.list(str(client_id))


@protected.post("/clients/{client_id}/knowledge")
async def upload(
    client_id: UUID, request: Request, files: list[UploadFile] = File(...)
):
    await run_in_threadpool(client, request, client_id)
    if not 1 <= len(files) <= 10:
        raise HTTPException(422, "Upload between 1 and 10 files")
    results = []
    for item in files:
        data = await item.read(10 * 1024 * 1024 + 1)
        try:
            result = await current(request).knowledge.ingest(
                str(client_id), item.filename or "upload.txt", data
            )
            results.append(result)
        except Exception as exc:
            results.append(
                {
                    "filename": item.filename,
                    "status": "error",
                    "error": (
                        str(exc)
                        if isinstance(exc, ValueError)
                        else "Processing unavailable; check provider configuration and retry"
                    ),
                }
            )
        finally:
            await item.close()
    await run_in_threadpool(
        current(request).repository.audit,
        str(client_id),
        "knowledge.uploaded",
        {"files": len(files), "failed": sum(x["status"] == "error" for x in results)},
    )
    return {"items": results}


@protected.delete("/clients/{client_id}/knowledge/{filename}")
def delete_knowledge(client_id: UUID, filename: str, request: Request):
    client(request, client_id)
    if not current(request).knowledge.delete(str(client_id), filename):
        raise HTTPException(404, "Knowledge file not found")
    current(request).repository.audit(str(client_id), "knowledge.deleted", {})
    return {"deleted": True}


@protected.post("/clients/{client_id}/knowledge/rebuild")
async def rebuild(client_id: UUID, request: Request):
    await run_in_threadpool(client, request, client_id)
    result = await current(request).knowledge.rebuild(str(client_id))
    await run_in_threadpool(
        current(request).repository.audit,
        str(client_id),
        "knowledge.rebuilt",
        {"status": result["status"]},
    )
    return result


@protected.get("/clients/{client_id}/sessions")
def sessions(
    client_id: UUID,
    request: Request,
    q: str = Query("", max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    client(request, client_id)
    rows = [
        row
        for row in current(request).repository.reporting_records(str(client_id))[
            "conversations"
        ]
        if q.casefold() in row["title"].casefold() or q in row["id"]
    ]
    rows.sort(key=lambda row: row["updated_at"], reverse=True)
    return {
        "items": [
            {**row, "session_id": row["id"]}
            for row in rows[(page - 1) * page_size : page * page_size]
        ],
        "total": len(rows),
        "page": page,
        "pageSize": page_size,
    }


@protected.get("/clients/{client_id}/sessions/{session_id}")
def conversation(client_id: UUID, session_id: UUID, request: Request):
    client(request, client_id)
    item = current(request).repository.get_conversation(str(client_id), str(session_id))
    if not item:
        raise HTTPException(404, "Conversation not found for this client")
    return item


@protected.delete("/clients/{client_id}/sessions/{session_id}")
def delete_session(client_id: UUID, session_id: UUID, request: Request):
    client(request, client_id)
    if not current(request).repository.delete_conversation(
        str(client_id), str(session_id)
    ):
        raise HTTPException(404, "Conversation not found for this client")
    current(request).repository.audit(str(client_id), "conversation.deleted", {})
    return {"deleted": True}


@protected.get("/clients/{client_id}/leads")
def leads(
    client_id: UUID,
    request: Request,
    q: str = Query("", max_length=120),
    status: str = "all",
):
    client(request, client_id)
    return [
        row
        for row in current(request).repository.list_leads(str(client_id))
        if (status == "all" or row["status"] == status)
        and (not q or q.casefold() in str(row).casefold())
    ]


@protected.get("/clients/{client_id}/leads/{lead_id}")
def lead(client_id: UUID, lead_id: UUID, request: Request):
    client(request, client_id)
    row = next(
        (
            row
            for row in current(request).repository.list_leads(str(client_id))
            if row["id"] == str(lead_id)
        ),
        None,
    )
    if not row:
        raise HTTPException(404, "Lead not found for this client")
    return row


@protected.patch("/clients/{client_id}/leads/{lead_id}")
def update_lead(client_id: UUID, lead_id: UUID, payload: LeadPatch, request: Request):
    lead(client_id, lead_id, request)
    fields = payload.model_dump(exclude_unset=True)
    fields = {
        key: value
        for key, value in fields.items()
        if value is not None or key == "assignee"
    }
    if not fields:
        raise HTTPException(422, "Provide at least one lead field")
    current(request).repository.update_lead(str(client_id), str(lead_id), fields)
    current(request).repository.audit(
        str(client_id),
        "lead.updated",
        {"lead_id": str(lead_id), "fields": list(fields)},
    )
    return lead(client_id, lead_id, request)


@protected.get("/clients/{client_id}/leads.csv")
def export_leads(client_id: UUID, request: Request):
    client(request, client_id)
    return PlainTextResponse(
        current(request).repository.export_leads_csv(str(client_id)),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@protected.get("/analytics")
def all_analytics(
    request: Request, client_id: UUID | None = None, days: int = Query(30, ge=1, le=365)
):
    if client_id:
        client(request, client_id)
    repo = current(request).repository
    records = repo.reporting_records(str(client_id) if client_id else None)
    return {
        **aggregate(records, days),
        "client_usage": client_usage(
            records, [client(request, client_id)] if client_id else repo.list_clients()
        ),
    }


@protected.get("/clients/{client_id}/analytics")
def analytics(client_id: UUID, request: Request, days: int = Query(30, ge=1, le=365)):
    return all_analytics(request, client_id, days)


@protected.get("/activity")
def activity(
    request: Request,
    client_id: UUID | None = None,
    q: str = Query("", max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    rows = current(request).repository.audit_page(
        str(client_id) if client_id else None, q, page, page_size
    )
    return rows


def public_endpoint(url: str | None) -> None:
    if not url:
        return
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in {None, 443}
    ):
        raise HTTPException(
            422,
            "Provider base must be a public HTTPS URL without credentials or query parameters",
        )
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parsed.hostname, 443, type=socket.SOCK_STREAM
            )
        }
    except OSError:
        raise HTTPException(422, "Provider hostname could not be resolved") from None
    if not addresses or any(
        not ipaddress.ip_address(item).is_global for item in addresses
    ):
        raise HTTPException(
            422, "Private, loopback, and metadata provider endpoints are forbidden"
        )


@protected.get("/settings/provider")
def providers(request: Request):
    state = current(request)
    staged = state.repository.setting("providers")
    return {
        "running": safe_providers(state),
        "staged": staged,
        "restartRequired": bool(staged),
        "secretPersisted": False,
    }


@protected.put("/settings/provider")
def update_providers(payload: ProviderUpdate, request: Request):
    for item in (payload.router, payload.answer):
        public_endpoint(item.api_base)
    repo = current(request).repository
    repo.set_setting("providers", payload.model_dump())
    repo.audit(None, "provider.settings.staged", {})
    return {"saved": True, "restartRequired": True, "secretPersisted": False}


@protected.post("/settings/provider/test")
async def test_provider(request: Request, payload: ProviderTest = ProviderTest()):
    state = current(request)

    config = state.settings.provider_configuration(payload.role)

    try:
        async with asyncio.timeout(15):
            result = await state.llm.complete(
                payload.role,
                [
                    {
                        "role": "user",
                        "content": "Reply with exactly CONNECTION_OK",
                    }
                ],
                temperature=0,
                max_tokens=32,
                operation="provider_connection_test",
            )

        connected = bool(isinstance(result, str) and result.strip())

    except Exception:
        connected = False

    answer = {
        "connected": connected,
        "status": ("completion_succeeded" if connected else "completion_failed"),
        "checked_at": datetime.now(UTC).isoformat(),
    }

    state.provider_tests[payload.role] = answer

    await run_in_threadpool(
        state.repository.audit,
        None,
        "provider.tested",
        {
            "role": payload.role,
            "connected": connected,
        },
    )

    return answer


@protected.get("/settings/system")
def system(request: Request):
    state = current(request)
    s = state.settings
    return {
        "app_environment": s.app_env,
        "database_provider": state.repository.name,
        "storage_provider": state.storage.name,
        "vector_provider": (
            "supabase" if state.repository.name == "supabase" else "sqlite"
        ),
        "embedding_model": s.embedding_model,
        "embedding_dimensions": s.embedding_output_dimensionality,
        "chunk_size": s.rag_chunk_size,
        "chunk_overlap": s.rag_chunk_overlap,
        "top_k": s.rag_top_k,
        "min_similarity": s.rag_min_similarity,
        "context_limit": s.rag_max_context_chars,
        "history_limit": s.max_history_messages,
        "log_level": s.log_level,
        "session_hours": s.admin_session_hours,
        "readiness_issues": s.readiness_issues(),
        "cors_origins": s.origins,
        "editable": False,
    }


router.include_router(protected)
