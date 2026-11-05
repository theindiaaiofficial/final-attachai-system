from __future__ import annotations

from app.security import hash_api_key, normalize_origin, origin_matches, safe_equal


def test_origin_normalization_is_exact_and_rejects_paths() -> None:
    assert normalize_origin("HTTPS://Exämple.com:443/") == "https://xn--exmple-cua.com"
    assert origin_matches("https://example.com", ["https://example.com/"])
    assert not origin_matches("https://evil-example.com", ["https://example.com"])
    assert not origin_matches("https://example.com/path", ["https://example.com"])


def test_api_keys_are_digest_only_and_constant_time_comparison() -> None:
    assert hash_api_key("secret") != "secret"
    assert safe_equal("secret", "secret")
    assert not safe_equal("secret", "other")


def test_tenant_conversation_and_knowledge_scoping(repository) -> None:
    tenant_a = repository.create_client("A", "tenant-a", ["https://a.example"], {}, "A prompt")
    tenant_b = repository.create_client("B", "tenant-b", ["https://b.example"], {}, "B prompt")
    session_a = repository.create_conversation(tenant_a["id"])
    repository.save_message(tenant_a["id"], session_a, "user", "private A")
    assert repository.conversation_exists(tenant_a["id"], session_a)
    assert not repository.conversation_exists(tenant_b["id"], session_a)
    assert repository.history(tenant_b["id"], session_a, 12) == []


def test_csv_export_neutralizes_formula_values(repository) -> None:
    tenant = repository.create_client("A", "csv-tenant", ["https://csv.example"], {}, "prompt")
    repository.create_lead(tenant["id"], {"name": "=SUM(A1:A2)", "message": "@formula"}, None, "retry-1")
    csv_text = repository.export_leads_csv(tenant["id"])
    assert "'=SUM" in csv_text
    assert "'@formula" in csv_text
