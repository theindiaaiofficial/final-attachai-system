from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
RESERVED_LLM_PARAMS = {
    "model", "messages", "api_key", "api_base", "base_url", "timeout", "temperature",
    "max_tokens", "response_format", "drop_params", "stream",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8", extra="ignore", case_sensitive=False,
    )

    app_env: str = Field("development", alias="APP_ENV")
    app_host: str = Field("0.0.0.0", alias="APP_HOST")
    port: int = Field(10000, ge=1, le=65535, alias="PORT")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    allowed_origins: str = Field("", alias="ALLOWED_ORIGINS")
    admin_api_key: SecretStr = Field(SecretStr("change-me"), alias="ADMIN_API_KEY", repr=False)
    admin_session_hours: int = Field(8, ge=1, le=24, alias="ADMIN_SESSION_HOURS")
    orbit_trace_debug: bool = Field(False, alias="ORBIT_TRACE_DEBUG")
    orbit_trace_include_content: bool = Field(False, alias="ORBIT_TRACE_INCLUDE_CONTENT")
    orbit_trace_log_path: Path = Field(Path("data/logs/orbit-trace.jsonl"), alias="ORBIT_TRACE_LOG_PATH")
    orbit_trace_max_bytes: int = Field(5_000_000, ge=100_000, le=50_000_000, alias="ORBIT_TRACE_MAX_BYTES")

    database_provider: str = Field("auto", alias="DATABASE_PROVIDER")
    sqlite_path: Path = Field(ROOT / "data" / "orbit.db", alias="SQLITE_PATH")
    storage_provider: str = Field("auto", alias="STORAGE_PROVIDER")
    local_storage_path: Path = Field(ROOT / "data" / "storage", alias="LOCAL_STORAGE_PATH")
    vector_provider: str = Field("auto", alias="VECTOR_PROVIDER")
    supabase_url: str | None = Field(None, alias="SUPABASE_URL")
    supabase_service_role_key: SecretStr | None = Field(None, alias="SUPABASE_SERVICE_ROLE_KEY", repr=False)
    supabase_storage_bucket: str = Field("knowledge", alias="SUPABASE_STORAGE_BUCKET")
    supabase_vector_dimensions: int = Field(768, ge=1, le=3072, alias="SUPABASE_VECTOR_DIMENSIONS")

    embedding_provider: str = Field("gemini", alias="EMBEDDING_PROVIDER")
    gemini_api_key: SecretStr | None = Field(None, alias="GEMINI_API_KEY", repr=False)
    embedding_api_key: SecretStr | None = Field(None, alias="EMBEDDING_API_KEY", repr=False)
    embedding_api_base: str | None = Field(None, alias="EMBEDDING_API_BASE")
    embedding_model: str = Field("gemini-embedding-001", alias="EMBEDDING_MODEL")
    embedding_output_dimensionality: int = Field(768, ge=1, le=3072, alias="EMBEDDING_OUTPUT_DIMENSIONALITY")
    embedding_batch_size: int = Field(16, ge=1, le=100, alias="EMBEDDING_BATCH_SIZE")

    router_provider: str | None = Field(None, alias="ROUTER_PROVIDER")
    router_model: str = Field("", alias="ROUTER_MODEL")
    router_api_key: SecretStr | None = Field(None, alias="ROUTER_API_KEY", repr=False)
    router_api_base: str | None = Field(None, alias="ROUTER_API_BASE")
    router_litellm_params: dict[str, Any] = Field(default_factory=dict, alias="ROUTER_LITELLM_PARAMS")
    router_confidence_threshold: float = Field(0.70, ge=0, le=1, alias="ROUTER_CONFIDENCE_THRESHOLD")
    answer_provider: str | None = Field(None, alias="ANSWER_PROVIDER")
    answer_model: str = Field("", alias="ANSWER_MODEL")
    answer_api_key: SecretStr | None = Field(None, alias="ANSWER_API_KEY", repr=False)
    answer_api_base: str | None = Field(None, alias="ANSWER_API_BASE")
    answer_litellm_params: dict[str, Any] = Field(default_factory=dict, alias="ANSWER_LITELLM_PARAMS")
    llm_timeout_seconds: int = Field(45, ge=5, le=300, alias="LLM_TIMEOUT_SECONDS")
    llm_drop_unsupported_params: bool = Field(True, alias="LLM_DROP_UNSUPPORTED_PARAMS")

    rag_chunk_size: int = Field(1000, ge=200, le=5000, alias="RAG_CHUNK_SIZE")
    rag_chunk_overlap: int = Field(150, ge=0, le=2000, alias="RAG_CHUNK_OVERLAP")
    rag_top_k: int = Field(5, ge=1, le=20, alias="RAG_TOP_K")
    rag_min_similarity: float = Field(0.22, ge=0, le=1, alias="RAG_MIN_SIMILARITY")
    rag_max_context_chars: int = Field(10000, ge=1000, le=50000, alias="RAG_MAX_CONTEXT_CHARS")
    max_history_messages: int = Field(40, ge=2, le=100, alias="MAX_HISTORY_MESSAGES")
    notification_provider: str = Field("supabase", alias="NOTIFICATION_PROVIDER")
    # Speech providers are selected independently for STT and TTS.
    # Built-ins: assemblyai, deepgram, openai_compatible (custom aliases supported).
    tts_provider: str = Field("openai_compatible", alias="TTS_PROVIDER")
    tts_api_key: SecretStr | None = Field(None, alias="TTS_API_KEY", repr=False)
    tts_api_base: str = Field("https://api.openai.com/v1", alias="TTS_API_BASE")
    tts_model: str = Field("", alias="TTS_MODEL")
    tts_voice: str = Field("alloy", alias="TTS_VOICE")
    tts_response_format: str = Field("mp3", alias="TTS_RESPONSE_FORMAT")
    tts_endpoint: str = Field("audio/speech", alias="TTS_ENDPOINT")
    tts_auth_header: str = Field("Authorization", alias="TTS_AUTH_HEADER")
    tts_auth_scheme: str = Field("Bearer", alias="TTS_AUTH_SCHEME")
    tts_language_field: str = Field("", alias="TTS_LANGUAGE_FIELD")
    tts_language_models: dict[str, str] = Field(default_factory=dict, alias="TTS_LANGUAGE_MODELS")
    stt_provider: str = Field("openai_compatible", alias="STT_PROVIDER")
    stt_api_key: SecretStr | None = Field(None, alias="STT_API_KEY", repr=False)
    stt_api_base: str = Field("https://api.openai.com/v1", alias="STT_API_BASE")
    stt_model: str = Field("", alias="STT_MODEL")
    stt_language: str = Field("", alias="STT_LANGUAGE")
    stt_endpoint: str = Field("audio/transcriptions", alias="STT_ENDPOINT")
    stt_auth_header: str = Field("Authorization", alias="STT_AUTH_HEADER")
    stt_auth_scheme: str = Field("Bearer", alias="STT_AUTH_SCHEME")
    assemblyai_api_key: SecretStr | None = Field(None, alias="ASSEMBLYAI_API_KEY", repr=False)
    assemblyai_tts_voice_id: str = Field("aai-jane", alias="ASSEMBLYAI_TTS_VOICE_ID")
    assemblyai_tts_language: str = Field("english", alias="ASSEMBLYAI_TTS_LANGUAGE")
    assemblyai_tts_container: str = Field("wav", alias="ASSEMBLYAI_TTS_CONTAINER")
    deepgram_api_key: SecretStr | None = Field(None, alias="DEEPGRAM_API_KEY", repr=False)
    deepgram_api_base: str = Field("https://api.deepgram.com", alias="DEEPGRAM_API_BASE")
    deepgram_tts_endpoint: str = Field("v2/speak", alias="DEEPGRAM_TTS_ENDPOINT")
    deepgram_stt_endpoint: str = Field("v1/listen", alias="DEEPGRAM_STT_ENDPOINT")
    speech_adapter_modules: str = Field("", alias="SPEECH_ADAPTER_MODULES")
    orbit_rag_diagnostics: bool = Field(False, alias="ORBIT_RAG_DIAGNOSTICS")
    orbit_temp_debug_gousto: bool = Field(False, alias="ORBIT_TEMP_DEBUG_GOUSTO")
    orbit_temp_debug_llm_input: bool = Field(False, alias="ORBIT_TEMP_DEBUG_LLM_INPUT")
    orbit_temp_debug_puregym: bool = Field(False, alias="ORBIT_TEMP_DEBUG_PUREGYM")
    orbit_temp_debug_client_id: str = Field("", alias="ORBIT_TEMP_DEBUG_CLIENT_ID")

    @field_validator("router_litellm_params", "answer_litellm_params", mode="before")
    @classmethod
    def parse_json_params(cls, value: Any) -> dict[str, Any]:
        if value in (None, "", {}):
            return {}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("LLM_LITELLM_PARAMS must be valid JSON") from exc
            if not isinstance(parsed, dict):
                raise ValueError("LLM_LITELLM_PARAMS must be a JSON object")
            return parsed
        if not isinstance(value, dict):
            raise ValueError("LLM_LITELLM_PARAMS must be an object")
        return value

    @field_validator("tts_language_models", mode="before")
    @classmethod
    def parse_tts_language_models(cls, value: Any) -> dict[str, str]:
        if value in (None, "", {}):
            return {}
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("TTS_LANGUAGE_MODELS must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("TTS_LANGUAGE_MODELS must be a JSON object")
        parsed = {str(key).strip().casefold(): str(model).strip() for key, model in value.items()}
        if any(not key or not model for key, model in parsed.items()):
            raise ValueError("TTS_LANGUAGE_MODELS cannot contain empty keys or models")
        return parsed

    @model_validator(mode="after")
    def validate_contract(self) -> Settings:
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("RAG_CHUNK_OVERLAP must be smaller than RAG_CHUNK_SIZE")
        # Unknown providers are permitted for future/custom adapters; the runtime
        # returns a clear error until an adapter is registered for that provider.
        if not self.tts_provider.strip() or not self.stt_provider.strip():
            raise ValueError("TTS_PROVIDER and STT_PROVIDER cannot be empty")
        if self.assemblyai_tts_container.strip().casefold() != "wav":
            raise ValueError("ASSEMBLYAI_TTS_CONTAINER currently supports only 'wav'")
        if self.supabase_vector_dimensions != self.embedding_output_dimensionality:
            raise ValueError("SUPABASE_VECTOR_DIMENSIONS must equal EMBEDDING_OUTPUT_DIMENSIONALITY")
        for role, params in (("router", self.router_litellm_params), ("answer", self.answer_litellm_params)):
            invalid = RESERVED_LLM_PARAMS.intersection(params)
            if invalid:
                raise ValueError(f"{role.upper()}_LITELLM_PARAMS contains reserved parameters: {sorted(invalid)}")
        return self

    def resolve_data_providers(self) -> tuple[str, str, str]:
        """Resolve storage backends without silently ignoring Supabase credentials.

        With all provider settings left at ``auto``, complete Supabase credentials
        select Supabase for database, object storage, and vectors. Without
        credentials, Orbit keeps its local SQLite/filesystem defaults. Explicit
        legacy local settings remain supported.
        """
        requested = tuple(
            str(value or "auto").strip().casefold()
            for value in (self.database_provider, self.storage_provider, self.vector_provider)
        )
        allowed = {"auto", "supabase", "sqlite", "local"}
        if any(value not in allowed for value in requested):
            raise ValueError("Database/storage/vector provider must be auto, supabase, or the supported local provider")

        has_url = bool((self.supabase_url or "").strip())
        service_key = self.supabase_service_role_key.get_secret_value().strip() if self.supabase_service_role_key else ""
        has_key = bool(service_key and not service_key.startswith("YOUR_"))
        if has_url != has_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must both be configured")

        if has_url:
            from urllib.parse import urlparse
            parsed = urlparse(self.supabase_url or "")
            if parsed.scheme not in {"https", "http"} or not parsed.netloc:
                raise ValueError("SUPABASE_URL must be a valid http(s) project URL")

        if requested == ("sqlite", "local", "sqlite"):
            return ("sqlite", "local", "sqlite")

        explicit = {value for value in requested if value != "auto"}
        if len(explicit) > 1:
            # Orbit currently supports a unified data backend, not mixed local/cloud stores.
            raise ValueError("Use one unified data backend: Supabase or local SQLite/filesystem")

        selected = next(iter(explicit), "supabase" if has_url else "local")
        if selected == "supabase":
            if not has_url or not has_key:
                raise ValueError("Supabase is selected but SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing")
            return ("supabase", "supabase", "supabase")
        if selected in {"sqlite", "local"}:
            # Normalize the historical trio and its automatic no-credentials default.
            return ("sqlite", "local", "sqlite")
        raise ValueError("Unsupported data backend configuration")

    @property
    def tts_enabled(self) -> bool:
        provider = self.tts_provider.strip().casefold()
        if provider == "assemblyai":
            return any(key and key.get_secret_value().strip() for key in (self.assemblyai_api_key, self.tts_api_key))
        if provider == "deepgram":
            has_key = any(key and key.get_secret_value().strip() for key in (self.deepgram_api_key, self.tts_api_key))
            return bool(has_key and (self.tts_model.strip() or self.tts_language_models))
        if provider in {"openai_compatible", "openai-compatible", "custom", "openai", "generic"}:
            return bool(self.tts_api_key and self.tts_api_key.get_secret_value().strip() and self.tts_model.strip())
        return bool(self.tts_api_key and self.tts_api_key.get_secret_value().strip())

    @property
    def stt_enabled(self) -> bool:
        provider = self.stt_provider.strip().casefold()
        if provider == "assemblyai":
            return any(key and key.get_secret_value().strip() for key in (self.assemblyai_api_key, self.stt_api_key))
        if provider == "deepgram":
            return any(key and key.get_secret_value().strip() for key in (self.deepgram_api_key, self.stt_api_key))
        if provider in {"openai_compatible", "openai-compatible", "custom", "openai", "generic"}:
            return bool(self.stt_api_key and self.stt_api_key.get_secret_value().strip() and self.stt_model.strip())
        return bool(self.stt_api_key and self.stt_api_key.get_secret_value().strip())

    @property
    def origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    def provider_configuration(self, role: str) -> dict[str, Any]:
        if role not in {"router", "answer"}:
            raise ValueError(f"Unknown LLM role: {role}")
        prefix = "router" if role == "router" else "answer"
        key = getattr(self, f"{prefix}_api_key")
        return {
            "provider": (getattr(self, f"{prefix}_provider") or "").strip().lower() or None,
            "model": getattr(self, f"{prefix}_model").strip(),
            "api_key": key.get_secret_value() if key else None,
            "api_base": (getattr(self, f"{prefix}_api_base") or "").strip() or None,
            "litellm_params": dict(getattr(self, f"{prefix}_litellm_params")),
        }

    def readiness_issues(self) -> list[str]:
        issues: list[str] = []
        if self.app_env == "production" and (self.admin_api_key.get_secret_value().startswith("YOUR_") or self.admin_api_key.get_secret_value() == "change-me"):
            issues.append("ADMIN_API_KEY is still a placeholder")
        for role in ("router", "answer"):
            cfg = self.provider_configuration(role)
            if not cfg["model"]:
                issues.append(f"{role.upper()}_MODEL is not configured")
            if not cfg["api_key"] or cfg["api_key"].startswith("YOUR_"):
                issues.append(f"{role.upper()}_API_KEY is not configured")
        embedding_key = self.embedding_api_key or self.gemini_api_key
        if not embedding_key or embedding_key.get_secret_value().startswith("YOUR_"):
            issues.append("Embedding API key is not configured")
        if self.embedding_provider != "gemini" and not self.embedding_api_base:
            issues.append("EMBEDDING_API_BASE is required for non-Gemini embeddings")
        if self.app_env == "production" and any((self.orbit_temp_debug_gousto, self.orbit_temp_debug_llm_input, self.orbit_temp_debug_puregym, bool(self.orbit_temp_debug_client_id.strip()))):
            issues.append("Temporary debug switches must be disabled in production")
        try:
            self.resolve_data_providers()
        except ValueError as exc:
            issues.append(str(exc))
        return issues


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
