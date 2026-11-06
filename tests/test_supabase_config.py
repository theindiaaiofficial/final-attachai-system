from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.config import Settings


def test_auto_data_backend_selects_supabase_when_credentials_are_present(settings):
    settings.database_provider = "auto"
    settings.storage_provider = "auto"
    settings.vector_provider = "auto"
    settings.supabase_url = "https://orbit-project.supabase.co"
    settings.supabase_service_role_key = SecretStr("server-only-service-role-secret")

    assert settings.resolve_data_providers() == ("supabase", "supabase", "supabase")


def test_auto_data_backend_stays_local_without_supabase_credentials(settings):
    settings.database_provider = "auto"
    settings.storage_provider = "auto"
    settings.vector_provider = "auto"
    settings.supabase_url = None
    settings.supabase_service_role_key = None

    assert settings.resolve_data_providers() == ("sqlite", "local", "sqlite")


def test_partial_supabase_credentials_fail_instead_of_falling_back(settings):
    settings.database_provider = "auto"
    settings.storage_provider = "auto"
    settings.vector_provider = "auto"
    settings.supabase_url = "https://orbit-project.supabase.co"
    settings.supabase_service_role_key = None

    with pytest.raises(ValueError, match="must both be configured"):
        settings.resolve_data_providers()


def test_inconsistent_mixed_data_backends_are_rejected(settings):
    settings.database_provider = "supabase"
    settings.storage_provider = "local"
    settings.vector_provider = "supabase"
    settings.supabase_url = "https://orbit-project.supabase.co"
    settings.supabase_service_role_key = SecretStr("server-only-service-role-secret")

    with pytest.raises(ValueError, match="unified data backend"):
        settings.resolve_data_providers()


def test_supabase_storage_health_checks_storage_bucket_endpoint(monkeypatch):
    from app.storage.supabase import SupabaseStorage

    requested = []

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers):
            requested.append((url, headers))
            return FakeResponse()

    monkeypatch.setattr("app.storage.supabase.httpx.Client", FakeClient)
    storage = SupabaseStorage("https://orbit-project.supabase.co/", "server-secret", "knowledge")

    assert storage.health() == {"provider": "supabase", "status": "ok", "bucket": "knowledge"}
    assert requested[0][0] == "https://orbit-project.supabase.co/storage/v1/bucket/knowledge"
    assert requested[0][1]["Authorization"] == "Bearer server-secret"


def test_supabase_migration_four_marker_is_required_for_readiness(monkeypatch):
    from app.repositories.supabase import SupabaseRepository

    repository = SupabaseRepository("https://orbit-project.supabase.co", "server-secret", "fingerprint")
    calls = []

    def fake_request(method, table, **kwargs):
        calls.append((method, table, kwargs))
        if table == "orbit_schema_migrations":
            return [{"version": 4}]
        return []

    monkeypatch.setattr(repository, "_request", fake_request)
    assert repository.health() == {"provider": "supabase", "status": "ok", "migrations": "0001-0004"}
    marker_call = calls[-1]
    assert marker_call[1] == "orbit_schema_migrations"
    assert marker_call[2]["params"]["version"] == "eq.4"

    monkeypatch.setattr(repository, "_request", lambda method, table, **kwargs: [] if table == "orbit_schema_migrations" else [])
    with pytest.raises(RuntimeError, match="migration 0004"):
        repository.health()


def test_supabase_security_migration_revokes_vector_rpc_from_browser_roles():
    from pathlib import Path

    sql = (Path(__file__).parents[1] / "migrations" / "0004_orbit_runtime_security.sql").read_text()
    normalized = " ".join(sql.casefold().split())
    assert "revoke all on function public.match_knowledge_vectors_v2" in normalized
    assert "from anon, authenticated" in normalized
    assert "to service_role" in normalized
    assert "orbit_schema_migrations" in normalized


def test_supabase_url_and_service_role_key_alone_enable_supabase_defaults():
    configured = Settings(
        _env_file=None,
        SUPABASE_URL="https://orbit-project.supabase.co",
        SUPABASE_SERVICE_ROLE_KEY="server-only-service-role-secret",
    )

    assert configured.database_provider == "auto"
    assert configured.storage_provider == "auto"
    assert configured.vector_provider == "auto"
    assert configured.resolve_data_providers() == ("supabase", "supabase", "supabase")
