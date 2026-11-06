from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.api.admin_routes import router as admin_router
from app.config import Settings, get_settings
from app.domain.schemas import ChatRequest, LeadRequest
from app.knowledge.service import KnowledgeService
from app.providers.embeddings import GeminiEmbeddings, OpenAICompatibleEmbeddings
from app.providers.llm import LiteLLMProvider
from app.providers.speech import (
    SpeechProviderError, load_speech_adapter_modules, synthesize_speech,
    speech_media_type, stream_synthesize_speech, transcribe_speech_with_language,
)
from app.rag.evidence import EvidenceEvaluator
from app.rag.generation import AnswerGenerator
from app.rag.grounding import GroundingVerifier
from app.rag.identity import resolve_identity
from app.rag.pipeline import ChatPipeline
from app.rag.retrieval import Retriever
from app.rag.router import IntelligenceRouter
from app.repositories.sqlite import SQLiteRepository
from app.repositories.supabase import SupabaseRepository
from app.security import hash_api_key, origin_matches
from app.security.admin_session import require_admin, session_record
from app.storage.local import LocalTenantStorage
from app.storage.supabase import SupabaseStorage

logger = logging.getLogger("orbit")
ASSETS = Path(__file__).parent


class SpeechRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=8000)
    language: str | None = Field(None, max_length=24)


class State:
    def __init__(self, settings: Settings):
        load_speech_adapter_modules(settings.speech_adapter_modules)
        self.settings = settings
        self.provider_tests: dict[str, dict] = {}
        self.embeddings = GeminiEmbeddings(settings) if settings.embedding_provider.casefold() == "gemini" else OpenAICompatibleEmbeddings(settings)
        database_provider, storage_provider, vector_provider = settings.resolve_data_providers()
        self.data_providers = {
            "database": database_provider,
            "storage": storage_provider,
            "vector": vector_provider,
        }
        if database_provider == "supabase":
            key = settings.supabase_service_role_key.get_secret_value()
            self.repository = SupabaseRepository(settings.supabase_url or "", key, self.embeddings.fingerprint)
            self.storage = SupabaseStorage(settings.supabase_url or "", key, settings.supabase_storage_bucket)
        else:
            self.repository = SQLiteRepository(settings.sqlite_path, self.embeddings.fingerprint)
            self.storage = LocalTenantStorage(settings.local_storage_path)

        # Probe real services rather than marking a configured URL as connected.
        self.backend_health: dict[str, dict[str, str]] = {}
        for label, component in (("database", self.repository), ("storage", self.storage)):
            try:
                self.backend_health[label] = component.health()
            except Exception as exc:
                self.backend_health[label] = {"provider": getattr(component, "name", "unknown"), "status": "unavailable", "error": type(exc).__name__}
                logger.warning("backend_health_failed component=%s provider=%s error_type=%s", label, getattr(component, "name", "unknown"), type(exc).__name__)
        staged = self.repository.setting("providers")
        if staged:
            for role in ("router", "answer"):
                for field in ("provider", "model", "api_base"):
                    setattr(settings, f"{role}_{field}", staged[role][field])
            self.repository.delete_setting("providers")
        self.llm = LiteLLMProvider(settings)
        self.pipeline = ChatPipeline(settings, self.repository, IntelligenceRouter(self.llm, settings), Retriever(settings, self.embeddings, self.repository), EvidenceEvaluator(), AnswerGenerator(self.llm, settings), GroundingVerifier(self.llm))
        self.knowledge = KnowledgeService(settings, self.repository, self.embeddings, self.storage)


async def conversation_retention_worker(repository: Any) -> None:
    while True:
        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        try:
            await asyncio.to_thread(repository.delete_expired_conversations, cutoff)
        except Exception as exc:
            logger.warning("conversation_retention_failed category=%s", type(exc).__name__)
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.state = State(get_settings())
    retention_task = asyncio.create_task(
        conversation_retention_worker(app.state.state.repository)
    )
    try:
        yield
    finally:
        retention_task.cancel()
        try:
            await retention_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Orbit AI", version="1.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ASSETS / "frontend" / "static"), name="frontend-static")
app.include_router(admin_router)


def state(request: Request) -> State:
    return request.app.state.state


async def tenant_context(request: Request, x_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    if not x_api_key:
        raise HTTPException(401, "Valid public client credential required")
    current = state(request).repository.get_client_by_key_hash(hash_api_key(x_api_key))
    if not current or not current["enabled"]:
        raise HTTPException(401, "Valid public client credential required")
    if not origin_matches(request.headers.get("origin"), state(request).repository.domains(current["id"])):
        raise HTTPException(403, "Origin is not allowed")
    return current


@app.middleware("http")
async def http_headers(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    response = Response(status_code=204) if request.method == "OPTIONS" else await call_next(request)
    response.headers.update({"X-Request-ID": request.state.request_id, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY"})
    if request.url.path.startswith("/admin"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    origin = request.headers.get("origin")
    if origin and (origin in state(request).settings.origins or request.url.path.startswith("/v1/")):
        response.headers.update({"Access-Control-Allow-Origin": origin, "Vary": "Origin", "Access-Control-Allow-Methods": "GET, POST, PATCH, PUT, DELETE, OPTIONS", "Access-Control-Allow-Headers": "Content-Type, X-API-Key, X-Admin-API-Key, Idempotency-Key"})
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Pydantic includes submitted values by default; never echo keys/credentials.
    return JSONResponse({"detail": [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]}, status_code=422)


@app.exception_handler(Exception)
async def safe_error(request: Request, exc: Exception):
    logger.error("request_failed request_id=%s category=%s", getattr(request.state, "request_id", "unknown"), type(exc).__name__)
    return JSONResponse({"detail": "Unable to complete this request. Check configuration and retry.", "request_id": getattr(request.state, "request_id", None)}, status_code=503)


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
def login_page():
    return (ASSETS / "frontend" / "templates" / "login.html").read_text(encoding="utf-8")


@app.get("/admin", include_in_schema=False)
def admin_page(request: Request):
    if not session_record(request):
        return RedirectResponse("/admin/login", status_code=303)
    return HTMLResponse((ASSETS / "frontend" / "templates" / "admin.html").read_text(encoding="utf-8"))


@app.get("/widget.js", include_in_schema=False)
def widget_js():
    return Response((ASSETS / "widget" / "static" / "widget.js").read_text(encoding="utf-8"), media_type="application/javascript")


@app.get("/widget.css", include_in_schema=False)
def widget_css():
    return Response((ASSETS / "widget" / "static" / "widget.css").read_text(encoding="utf-8"), media_type="text/css")


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}


@app.get("/ready")
def ready(request: Request):
    current = state(request)
    issues = current.settings.readiness_issues()
    # Re-probe at request time so readiness can recover after a transient remote
    # outage and does not stay green if Supabase becomes unavailable after startup.
    for label, component in (("database", current.repository), ("storage", current.storage)):
        try:
            current.backend_health[label] = component.health()
        except Exception as exc:
            current.backend_health[label] = {
                "provider": getattr(component, "name", "unknown"),
                "status": "unavailable",
                "error": type(exc).__name__,
            }
            logger.warning(
                "backend_health_failed component=%s provider=%s error_type=%s",
                label, getattr(component, "name", "unknown"), type(exc).__name__,
            )
        if current.backend_health[label].get("status") != "ok":
            issues.append(f"{label.title()} backend is not reachable or is not fully migrated")
    return JSONResponse(
        {
            "status": "not_ready" if issues else "ready",
            "data_providers": current.data_providers,
            "backend_health": current.backend_health,
            "issues": issues,
            "provider_completion": "not_tested",
        },
        status_code=503 if issues else 200,
    )


@app.get("/metrics", dependencies=[Depends(require_admin)])
def metrics(request: Request):
    overview = state(request).repository.overview()
    return PlainTextResponse("\n".join(f"orbit_{key} {value}" for key, value in overview.items() if isinstance(value, (int, float))))


@app.get("/v1/config")
async def public_config(
    request: Request,
    tenant: dict[str, Any] = Depends(tenant_context),
) -> dict[str, Any]:
    config = tenant["config"]
    identity = resolve_identity(tenant)
    settings = state(request).settings
    return {
        "clientName": tenant["name"],
        "assistantName": identity.assistant_name,
        "businessName": identity.business_name,
        "assistantDescription": identity.description,
        "welcomeMessage": config.get("welcomeMessage", f"How can {identity.assistant_name} help?"),
        "widget": config.get("widget", {}),
        "theme": config.get("theme", {}),
        "speech": {
            "ttsEnabled": settings.tts_enabled,
        },
    }


@app.delete("/v1/conversations/{session_id}")
async def public_delete_conversation(
    session_id: str,
    request: Request,
    tenant: dict[str, Any] = Depends(tenant_context),
) -> dict[str, bool]:
    deleted = state(request).repository.delete_conversation(tenant["id"], session_id)
    return {"deleted": deleted}


@app.post("/v1/tts")
async def public_tts(
    payload: SpeechRequestPayload,
    request: Request,
    tenant: dict[str, Any] = Depends(tenant_context),
) -> Response:
    try:
        audio, media_type = await synthesize_speech(
            state(request).settings,
            payload.text.strip(),
            payload.language.strip() if payload.language else None,
        )
    except SpeechProviderError as exc:
        raise HTTPException(503, str(exc)) from None
    return Response(audio, media_type=media_type, headers={"Cache-Control": "no-store"})


@app.post("/v1/tts/stream")
async def public_tts_stream(
    payload: SpeechRequestPayload,
    request: Request,
    tenant: dict[str, Any] = Depends(tenant_context),
) -> StreamingResponse:
    settings = state(request).settings
    if not settings.tts_enabled:
        raise HTTPException(503, "Text-to-speech is not configured")
    return StreamingResponse(
        stream_synthesize_speech(settings, payload.text, payload.language),
        media_type=speech_media_type(settings),
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/v1/stt")
async def public_stt(
    request: Request,
    file: UploadFile = File(...),
    tenant: dict[str, Any] = Depends(tenant_context),
) -> dict[str, Any]:
    audio = await file.read(12 * 1024 * 1024 + 1)
    if not audio or len(audio) > 12 * 1024 * 1024:
        raise HTTPException(413, "Audio upload must be between 1 byte and 12 MB")
    try:
        text, language = await transcribe_speech_with_language(
            state(request).settings,
            audio,
            file.filename or "recording.webm",
            file.content_type or "application/octet-stream",
        )
    except SpeechProviderError as exc:
        raise HTTPException(503, str(exc)) from None
    return {"text": text, "language": language}


@app.post("/v1/chat")
async def public_chat(payload: ChatRequest, request: Request, tenant: dict[str, Any] = Depends(tenant_context)) -> dict[str, Any]:
    try:
        return await state(request).pipeline.handle(tenant["id"], payload.message.strip(), payload.session_id, request.state.request_id)
    except KeyError:
        raise HTTPException(404, "Conversation not found") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except Exception as exc:
        logger.error("chat_failed request_id=%s category=%s", request.state.request_id, type(exc).__name__)
        raise HTTPException(503, "The assistant could not complete this request") from None


@app.post("/v1/chat/stream")
async def public_chat_stream(
    payload: ChatRequest,
    request: Request,
    tenant: dict[str, Any] = Depends(tenant_context),
) -> StreamingResponse:
    """Server-sent events for genuine generation chunks and verified RAG replies."""
    current = state(request)
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    progress_labels = {
        "preparing": "Getting your conversation ready",
        "understanding": "Understanding your question",
        "retrieving": "Finding relevant information",
        "checking_evidence": "Checking the available information",
        "generating": "Writing your response",
        "verifying": "Verifying the response",
        "correcting": "Refining the response for accuracy",
        "saving": "Finishing up",
    }

    async def produce() -> None:
        tokens_sent = False

        def send_progress(stage: str) -> None:
            queue.put_nowait({"event": "progress", "data": {"stage": stage, "label": progress_labels.get(stage, "Working on your response")}})

        def send_token(token: str) -> None:
            nonlocal tokens_sent
            if token:
                tokens_sent = True
                queue.put_nowait({"event": "token", "data": {"text": token}})

        try:
            result = await current.pipeline.handle(
                tenant["id"], payload.message.strip(), payload.session_id,
                request.state.request_id, on_progress=send_progress, on_token=send_token,
            )
            # For RAG responses, do not expose model-draft tokens before grounding
            # verification. Once verified, send the final safe answer progressively.
            if not tokens_sent:
                answer = str(result.get("answer") or "")
                for offset in range(0, len(answer), 48):
                    send_token(answer[offset:offset + 48])
            safe_result = {
                **result,
                "citations": [item.model_dump() if hasattr(item, "model_dump") else item for item in result.get("citations", [])],
            }
            queue.put_nowait({"event": "done", "data": safe_result})
        except KeyError:
            queue.put_nowait({"event": "error", "data": {"status": 404, "detail": "Conversation not found"}})
        except ValueError as exc:
            queue.put_nowait({"event": "error", "data": {"status": 400, "detail": str(exc)}})
        except Exception as exc:
            logger.error("chat_stream_failed request_id=%s category=%s", request.state.request_id, type(exc).__name__)
            queue.put_nowait({"event": "error", "data": {"status": 503, "detail": "The assistant could not complete this request"}})
        finally:
            queue.put_nowait(None)

    async def events():
        task = asyncio.create_task(produce())
        try:
            while True:
                if await request.is_disconnected():
                    task.cancel()
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                data = json.dumps(item["data"], ensure_ascii=False, default=lambda value: value.model_dump() if hasattr(value, "model_dump") else str(value))
                yield f"event: {item['event']}\ndata: {data}\n\n"
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/v1/leads")
async def public_lead(payload: LeadRequest, request: Request, idempotency_key: str | None = Header(default=None), tenant: dict[str, Any] = Depends(tenant_context)) -> dict[str, Any]:
    repo = state(request).repository
    if payload.conversation_id and not repo.conversation_exists(tenant["id"], payload.conversation_id):
        raise HTTPException(404, "Conversation not found")
    data = payload.model_dump(exclude={"conversation_id"}, exclude_none=True)
    if not (data.get("requirement") or data.get("message")):
        raise HTTPException(422, "Message is required")
    lead = repo.create_lead(tenant["id"], data, payload.conversation_id, idempotency_key)
    destination = tenant["config"].get("notificationEmail") or tenant["config"].get("teamEmail")
    if destination:
        repo.enqueue_notification(tenant["id"], f"lead:{lead['id']}", destination, f"New lead for {tenant['name']}", {"lead_id": lead["id"], "data": data})
    repo.audit(tenant["id"], "lead.created", {"lead_id": lead["id"]})
    return {"id": lead["id"], "status": "accepted"}
