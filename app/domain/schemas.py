from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.security.auth import normalize_origin


class Citation(BaseModel):
    source_id: str
    filename: str
    page: int | None = None
    title: str | None = None
    excerpt: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=12000)
    session_id: str | None = Field(None, max_length=64)


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=8000)


class ChatResponse(BaseModel):
    session_id: str
    request_id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    route: str
    evidence_status: str | None = None


class LeadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=40)
    requirement: str | None = Field(None, max_length=2000)
    message: str | None = Field(None, max_length=2000)

    @field_validator("name", "email", "phone", "requirement", "message")
    @classmethod
    def no_newlines(cls, value: str | None) -> str | None:
        if value is not None and any(c in value for c in "\r\n"):
            raise ValueError("lead fields cannot contain line breaks")
        return value.strip() if value else value


class ClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    domains: list[str] = Field(min_length=1, max_length=30)
    config: dict[str, Any] = Field(default_factory=dict)
    prompt: str = Field(min_length=1, max_length=20000)

    @field_validator("domains")
    @classmethod
    def valid_domains(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(normalize_origin(value) for value in values))


class ClientPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=120)
    enabled: bool | None = None
    prompt: str | None = Field(None, min_length=1, max_length=20000)
    config: dict[str, Any] | None = None
    domains: list[str] | None = Field(None, min_length=1, max_length=30)

    @field_validator("domains")
    @classmethod
    def valid_domains(cls, values: list[str] | None) -> list[str] | None:
        return list(dict.fromkeys(normalize_origin(value) for value in values)) if values else values


class AdminLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr = Field(min_length=1, max_length=1000)


class LeadPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["new", "contacted", "qualified", "won", "lost"] | None = None
    assignee: str | None = Field(None, max_length=120)
    notes: str | None = Field(None, max_length=10000)
    data: dict[str, str] | None = None

    @field_validator("data")
    @classmethod
    def validate_data(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None:
            allowed = {"name", "email", "phone", "message", "requirement"}
            if set(value) - allowed or any(len(v) > 2000 for v in value.values()):
                raise ValueError("Unsupported lead fields or values too long")
        return value


class ProviderRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    model: str = Field(min_length=1, max_length=200)
    api_base: str | None = Field(None, max_length=500)


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    router: ProviderRoleUpdate
    answer: ProviderRoleUpdate


class ProviderTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["router", "answer"] = "answer"


class DuplicateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")


class RouteName(StrEnum):
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"
    BUSINESS_KNOWLEDGE = "BUSINESS_KNOWLEDGE"
    MIXED = "MIXED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
