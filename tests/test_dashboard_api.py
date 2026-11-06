from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import admin_routes
from app.security import hash_api_key


@pytest.fixture
def web(settings, monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    admin_routes.limiter.attempts.clear()
    with TestClient(main.app) as web:
        yield web


@pytest.fixture
def auth():
    return {"X-Admin-API-Key": "admin-secret"}


def create(web, auth, name="A", slug="client-a"):
    response = web.post("/admin/clients", headers=auth, json={"name": name, "slug": slug, "domains": ["https://example.com"], "prompt": "Original prompt", "config": {"assistantName": "Orbit"}})
    assert response.status_code == 200, response.text
    return response.json()


def test_protected_shell_and_all_administrative_families(web):
    assert web.get("/admin", follow_redirects=False).headers["location"] == "/admin/login"
    for path in ("/admin/overview", "/admin/clients", "/admin/analytics", "/admin/activity", "/admin/status", "/admin/settings/provider", "/admin/settings/system", "/admin/auth/session", "/metrics"):
        assert web.get(path).status_code == 401, path
    for path in ("/admin/login", "/static/admin.js", "/static/admin.css", "/static/api.js", "/widget.js", "/widget.css"):
        assert web.get(path).status_code == 200
    assert web.get("/widget.js").headers["content-type"].startswith("application/javascript")


def test_cookie_session_csrf_logout_and_no_credential_echo(web):
    assert web.post("/admin/auth/login", json={"api_key": "incorrect"}).status_code == 401
    response = web.post("/admin/auth/login", json={"api_key": "admin-secret"})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "admin-secret" not in response.text and "admin-secret" not in cookie
    csrf = response.json()["csrf_token"]
    assert web.get("/admin").status_code == 200
    assert web.get("/admin/overview").headers["cache-control"] == "no-store"
    assert web.post("/admin/auth/validate").status_code == 403
    assert web.post("/admin/auth/validate", headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert web.post("/admin/auth/validate", headers={"X-CSRF-Token": csrf, "Origin": "https://attacker.example"}).status_code == 403
    assert web.post("/admin/auth/validate", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert web.post("/admin/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert web.get("/admin/overview").status_code == 401


def test_expiry_and_admin_key_change_revoke_sessions(web):
    web.post("/admin/auth/login", json={"api_key": "admin-secret"})
    token = web.cookies.get("orbit_admin_session")
    repo = main.app.state.state.repository
    with repo._db() as db:
        db.execute("UPDATE admin_sessions SET expires_at=?", ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(),))
    assert web.get("/admin/auth/session").status_code == 401
    assert repo.admin_session(hash_api_key(token)) is None
    web.post("/admin/auth/login", json={"api_key": "admin-secret"})
    from pydantic import SecretStr
    main.app.state.state.settings.admin_api_key = SecretStr("different-secret")
    assert web.get("/admin/auth/session").status_code == 401


def test_login_origin_and_throttle(web):
    assert web.post("/admin/auth/login", headers={"Origin": "https://other.example"}, json={"api_key": "admin-secret"}).status_code == 403
    for _ in range(10):
        assert web.post("/admin/auth/login", json={"api_key": "wrong"}).status_code == 401
    assert web.post("/admin/auth/login", json={"api_key": "wrong"}).status_code == 429


def test_client_lifecycle_prompts_domain_validation_and_keys(web, auth):
    item = create(web, auth)
    path = "/admin/clients/" + item["id"]
    original_key = item["api_key"]
    public_headers = {"X-API-Key": original_key, "Origin": "https://example.com"}
    assert web.get("/v1/config", headers=public_headers).status_code == 200
    assert web.get("/v1/config", headers={"X-API-Key": original_key}).status_code == 403
    assert "key_hash" not in web.get(path, headers=auth).text
    assert web.patch(path, headers=auth, json={"domains": ["https://example.com/path"]}).status_code == 422
    assert web.patch(path, headers=auth, json={"name": "Edited", "prompt": "Second prompt", "domains": ["HTTPS://EXAMPLE.COM:443/"]}).status_code == 200
    history = web.get(path + "/prompts/history", headers=auth).json()
    assert history[0]["prompt"] == "Original prompt"
    assert web.post(path + f"/prompts/{history[0]['id']}/restore", headers=auth).json()["prompt"] == "Original prompt"
    assert web.post(path + "/prompts/reset", headers=auth).status_code == 200
    clone = web.post(path + "/duplicate", headers=auth, json={"name": "Clone", "slug": "clone-a"}).json()
    assert clone["id"] != item["id"] and clone["api_key"] != original_key
    assert web.post(path + "/duplicate", headers=auth, json={"name": "Clone", "slug": "clone-a"}).status_code == 409
    assert web.get("/admin/clients?q=Edited&page_size=1", headers=auth).json()["total"] == 1
    assert web.get("/admin/clients?page_size=10000", headers=auth).status_code == 422
    assert web.post(path + "/key/disable", headers=auth).status_code == 200
    assert web.get("/v1/config", headers=public_headers).status_code == 401
    web.post(path + "/key/enable", headers=auth)
    rotated = web.post(path + "/rotate-key", headers=auth).json()["apiKey"]
    assert web.get("/v1/config", headers=public_headers).status_code == 401
    assert web.get("/v1/config", headers={**public_headers, "X-API-Key": rotated}).status_code == 200
    web.patch(path, headers=auth, json={"enabled": False})
    assert web.get("/admin/clients?status=suspended", headers=auth).json()["total"] == 1
    web.delete(path, headers=auth)
    assert web.get(path, headers=auth).status_code == 404


class Embeddings:
    async def embed_documents(self, texts):
        return [[1.0] + [0.0] * 767 for _ in texts]


def test_upload_rebuild_errors_delete_and_tenant_sources(web, auth):
    a, b = create(web, auth), create(web, auth, "B", "client-b")
    state = main.app.state.state
    state.knowledge.embeddings = Embeddings()
    path = f"/admin/clients/{a['id']}/knowledge"
    uploaded = web.post(path, headers=auth, files=[("files", ("pricing.md", b"The price is 10 dollars.", "text/markdown"))])
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["items"][0]["status"] == "ready"
    assert web.get(path, headers=auth).json()[0]["chunks"] == 1
    assert web.get(f"/admin/clients/{b['id']}/knowledge", headers=auth).json() == []
    assert web.post(path + "/rebuild", headers=auth).json()["status"] == "completed"
    assert web.get(path, headers=auth).json()[0]["chunks"] == 1
    error = web.post(path, headers=auth, files=[("files", ("bad.exe", b"bad"))]).json()["items"][0]
    assert error["status"] == "error"
    file = web.get(path, headers=auth).json()[0]
    source_path = state.storage._path(a["id"], file["id"], "pricing.md")
    assert source_path.exists()
    assert web.delete(f"/admin/clients/{b['id']}/knowledge/pricing.md", headers=auth).status_code == 404
    assert source_path.exists()
    assert web.delete(path + "/pricing.md", headers=auth).status_code == 200
    assert not source_path.exists()


def test_rebuild_does_not_report_completion_when_provider_fails(web, auth):
    a = create(web, auth)
    state = main.app.state.state
    state.knowledge.embeddings = Embeddings()
    path = f"/admin/clients/{a['id']}/knowledge"
    web.post(path, headers=auth, files=[("files", ("a.txt", b"A business fact"))])
    class Failing:
        async def embed_documents(self, texts):
            raise RuntimeError("private provider content")
    state.knowledge.embeddings = Failing()
    response = web.post(path + "/rebuild", headers=auth)
    assert response.json()["status"] == "completed_with_errors"
    assert "private provider content" not in response.text
    assert web.get(path, headers=auth).json()[0]["chunks"] == 1


def test_sessions_leads_csv_analytics_and_tenant_boundaries(web, auth):
    a, b = create(web, auth), create(web, auth, "B", "client-b")
    repo = main.app.state.state.repository
    session = repo.create_conversation(a["id"])
    repo.save_message(a["id"], session, "user", "A private question")
    repo.save_message(a["id"], session, "assistant", "Grounded answer", [{"source_id": "S1", "filename": "a.txt", "excerpt": "fact"}], "BUSINESS_KNOWLEDGE", "SUFFICIENT")
    repo.usage(a["id"], "BUSINESS_KNOWLEDGE", 21)
    path = f"/admin/clients/{a['id']}"
    other = f"/admin/clients/{b['id']}"
    assert web.get(path + "/sessions?q=private", headers=auth).json()["total"] == 1
    assert web.get(other + f"/sessions/{session}", headers=auth).status_code == 404
    detail = web.get(path + f"/sessions/{session}", headers=auth).json()
    assert detail["messages"][1]["citations"][0]["filename"] == "a.txt"
    lead = repo.create_lead(a["id"], {"name": " =SUM(A1:A2)", "message": "Private request"}, session, "lead-1")
    assert web.get(other + f"/leads/{lead['id']}", headers=auth).status_code == 404
    assert web.patch(other + f"/leads/{lead['id']}", headers=auth, json={"status": "won"}).status_code == 404
    assert web.patch(path + f"/leads/{lead['id']}", headers=auth, json={"client_id": b["id"]}).status_code == 422
    assert web.patch(path + f"/leads/{lead['id']}", headers=auth, json={"status": "nonsense"}).status_code == 422
    updated = web.patch(path + f"/leads/{lead['id']}", headers=auth, json={"status": "qualified", "notes": "Call next week", "assignee": "Owner"})
    assert updated.json()["status"] == "qualified"
    assert "'=SUM" not in web.get(path + "/leads.csv", headers=auth).text  # whitespace is preserved after prefix
    assert "' =SUM" in web.get(path + "/leads.csv", headers=auth).text
    assert web.get(other + "/leads.csv", headers=auth).text.count("Private") == 0
    metrics = web.get(path + "/analytics", headers=auth).json()
    assert metrics["messages"] == 2 and metrics["leads"] == 1 and metrics["average_latency_ms"] == 21
    assert sum(row["conversations"] for row in metrics["series"]) == 1
    assert web.get(other + "/analytics", headers=auth).json()["conversations"] == 0
    assert web.get("/admin/overview", headers=auth).json()["active_clients"] == 2
    assert web.get("/admin/analytics?days=90", headers=auth).json()["requests"] == 1
    assert web.delete(other + f"/sessions/{session}", headers=auth).status_code == 404
    assert web.delete(path + f"/sessions/{session}", headers=auth).status_code == 200


def test_provider_staging_test_security_and_safe_system_output(web, auth, monkeypatch):
    before = web.get("/admin/settings/provider", headers=auth)
    assert "router-secret" not in before.text and "answer-secret" not in before.text
    monkeypatch.setattr(admin_routes.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("8.8.8.8", 443))])
    payload = {role: {"provider": "openrouter", "model": "org/model", "api_base": "https://public.example/v1"} for role in ("router", "answer")}
    assert web.put("/admin/settings/provider", headers=auth, json=payload).json()["restartRequired"]
    assert main.app.state.state.settings.answer_provider == "test"
    payload["answer"]["api_key"] = "never-save-this"
    response = web.put("/admin/settings/provider", headers=auth, json=payload)
    assert response.status_code == 422 and "never-save-this" not in response.text
    del payload["answer"]["api_key"]
    monkeypatch.setattr(admin_routes.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))])
    assert web.put("/admin/settings/provider", headers=auth, json=payload).status_code == 422
    async def completion(*args, **kwargs):
        return "CONNECTION_OK"
    main.app.state.state.llm.complete = completion
    assert web.post("/admin/settings/provider/test", headers=auth, json={"role": "router"}).json()["connected"]
    assert web.post("/admin/settings/provider/test", headers=auth, json={"role": "invalid"}).status_code == 422
    result = web.get("/admin/settings/system", headers=auth)
    assert result.json()["chunk_size"] == 1000 and not result.json()["editable"]
    assert "embedding-secret" not in result.text
    assert web.get("/admin/status", headers=auth).status_code == 200
    assert web.get("/admin/activity?q=provider", headers=auth).json()["total"] == 2


def test_public_chat_and_stream_still_use_pipeline_and_widget(web, auth):
    item = create(web, auth)
    state = main.app.state.state
    async def answer(*args):
        return "Hello from the answer role."
    state.pipeline.generator.general = answer
    headers = {"X-API-Key": item["api_key"], "Origin": "https://example.com"}
    response = web.post("/v1/chat", headers=headers, json={"message": "hello"})
    assert response.json()["route"] == "GENERAL_CONVERSATION"
    session = response.json()["session_id"]
    assert len(state.repository.history(item["id"], session, 12)) == 2
    stream = web.post("/v1/chat/stream", headers=headers, json={"message": "hello", "session_id": session})
    assert "event: done" in stream.text and "event: token" in stream.text
    assert "event: progress" in stream.text
    widget_source = web.get("/widget.js").text
    assert "event: token" in stream.text
    assert '<span>Chat</span>' in widget_source
    assert '<span>Ai</span>' not in widget_source
    assert 'voiceSpeechChain' not in widget_source
    assert 'getUserMedia' not in widget_source
    assert 'MediaRecorder' not in widget_source
    assert 'SpeechRecognition' not in widget_source
    assert '/v1/stt' not in widget_source
    assert 'orbit-voice-panel' not in widget_source
    assert 'Preparing audio…' in widget_source
    assert 'Finished speaking' in widget_source
    assert 'currentTime' in widget_source
    assert 'fetch(`${base}/v1/tts`' in widget_source
    assert 'Chat with us' not in widget_source


def test_widget_config_speech_flags_and_public_chat_delete(web, auth):
    item = create(web, auth, "Speech Test", "speech-test")
    headers = {"X-API-Key": item["api_key"], "Origin": "https://example.com"}

    config = web.get("/v1/config", headers=headers).json()
    assert config["speech"] == {"ttsEnabled": False}

    repository = main.app.state.state.repository
    session_id = repository.create_conversation(item["id"])
    repository.save_message(item["id"], session_id, "user", "Delete me")

    assert web.delete(
        f"/v1/conversations/{session_id}",
        headers=headers,
    ).json() == {"deleted": True}
    assert repository.get_conversation(item["id"], session_id) is None


def test_public_speech_routes_fail_safely_when_not_configured(web, auth):
    item = create(web, auth, "Speech Disabled", "speech-disabled")
    headers = {"X-API-Key": item["api_key"], "Origin": "https://example.com"}

    tts = web.post("/v1/tts", headers=headers, json={"text": "Hello"})
    assert tts.status_code == 503
    streamed_tts = web.post("/v1/tts/stream", headers=headers, json={"text": "Hello"})
    assert streamed_tts.status_code == 503
    assert "api_key" not in tts.text.casefold() + streamed_tts.text.casefold()

    stt = web.post(
        "/v1/stt",
        headers=headers,
        files={"file": ("recording.webm", b"audio", "audio/webm")},
    )
    assert stt.status_code == 503
    assert "api_key" not in stt.text.casefold()


def test_readiness_rechecks_remote_data_services_each_request(web, monkeypatch):
    current = main.app.state.state
    monkeypatch.setattr(type(current.settings), "readiness_issues", lambda self: [])
    monkeypatch.setattr(current.repository, "health", lambda: {"provider": "supabase", "status": "ok", "migrations": "0001-0004"})
    monkeypatch.setattr(current.storage, "health", lambda: {"provider": "supabase", "status": "ok", "bucket": "knowledge"})

    ready = web.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["backend_health"]["database"]["migrations"] == "0001-0004"

    def unavailable():
        raise RuntimeError("do not expose connection details")

    monkeypatch.setattr(current.repository, "health", unavailable)
    not_ready = web.get("/ready")
    assert not_ready.status_code == 503
    assert not_ready.json()["backend_health"]["database"] == {
        "provider": "sqlite", "status": "unavailable", "error": "RuntimeError"
    }
