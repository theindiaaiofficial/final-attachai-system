from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import Settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Safe provider error without request content or secrets."""


class CompletionProvider(Protocol):
    async def complete(
        self,
        role: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str: ...


@dataclass(frozen=True)
class ModelRole:
    role: str
    provider: str
    model: str
    api_key: str | None
    api_base: str | None
    params: dict[str, Any]


class LiteLLMProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def role(self, role: str) -> ModelRole:
        cfg = self.settings.provider_configuration(role)

        provider = (cfg.get("provider") or "openai").strip().lower()
        model = (cfg.get("model") or "").strip()

        if not model:
            raise LLMError(f"{role.title()} model is not configured")

        if not model.startswith(f"{provider}/"):
            model = f"{provider}/{model}"

        return ModelRole(
            role=role,
            provider=provider,
            model=model,
            api_key=cfg.get("api_key"),
            api_base=cfg.get("api_base"),
            params=dict(cfg.get("litellm_params") or {}),
        )

    @staticmethod
    def _status_code(exc: Exception) -> int | None:
        status = getattr(exc, "status_code", None)

        if status is None:
            status = getattr(
                getattr(exc, "response", None),
                "status_code",
                None,
            )

        return status if isinstance(status, int) else None

    @staticmethod
    def _is_json_validation_error(exc: Exception) -> bool:
        message = str(exc).casefold()

        return "json_validate_failed" in message or "failed to validate json" in message

    @staticmethod
    def _retry_delay_seconds(exc: Exception, attempt: int) -> float:
        response = getattr(exc, "response", None)

        headers = (
            getattr(response, "headers", None) or getattr(exc, "headers", None) or {}
        )

        try:
            value = headers.get("retry-after")

            if value is None:
                value = headers.get("Retry-After")

            if value is not None:
                return min(30.0, max(0.25, float(value)))

        except (TypeError, ValueError):
            pass

        match = re.search(
            r"(?:please\s+)?(?:try again in|retry in)\s*"
            r"(\d+(?:\.\d+)?)\s*(milliseconds?|msecs?|ms|seconds?|secs?|s)\b",
            str(exc),
            re.IGNORECASE,
        )

        if match:
            amount = float(match.group(1))
            unit = match.group(2).casefold()
            seconds = amount / 1000 if unit.startswith(("m", "mill")) else amount
            safety_margin = 0.1 if seconds < 1 else 0.2
            return min(30.0, max(0.25, seconds + safety_margin))

        return min(8.0, 1.0 * (2**attempt))

    async def complete(
        self,
        role: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:

        cfg = self.role(role)

        if not cfg.api_key:
            raise LLMError(f"{role.title()} provider credentials are not configured")

        try:
            from litellm import acompletion
        except ImportError as exc:
            raise LLMError("LiteLLM is not installed") from exc

        operation = kwargs.pop("operation", role)

        payload: dict[str, Any] = {
            **cfg.params,
            "model": cfg.model,
            "messages": messages,
            "timeout": self.settings.llm_timeout_seconds,
            "drop_params": self.settings.llm_drop_unsupported_params,
            "api_key": cfg.api_key,
        }

        if cfg.api_base:
            payload["api_base"] = cfg.api_base

        if cfg.provider == "groq" and "gpt-oss" in cfg.model.casefold():
            payload.setdefault("reasoning_effort", "low")

        payload.update(kwargs)

        json_fallback_used = False
        transient_retries = 0
        last_error: Exception | None = None

        while True:
            try:
                response = await acompletion(**payload)

                if not response.choices:
                    raise LLMError("Provider returned no choices")

                choice = response.choices[0]
                message = choice.message
                content = message.content

                if isinstance(content, list):
                    content = "".join(
                        (
                            part.get("text", "")
                            if isinstance(part, dict)
                            else str(getattr(part, "text", part))
                        )
                        for part in content
                    )

                if not isinstance(content, str) or not content.strip():
                    dump = getattr(message, "model_dump", None)

                    fields = (
                        list(dump(exclude_none=True).keys()) if callable(dump) else []
                    )

                    logger.warning(
                        "llm_empty_response role=%s operation=%s "
                        "provider=%s model=%s finish_reason=%s "
                        "message_fields=%s",
                        role,
                        operation,
                        cfg.provider,
                        cfg.model,
                        choice.finish_reason,
                        fields,
                    )

                    raise LLMError("Provider returned empty user-facing content")

                return content.strip()

            except Exception as exc:
                last_error = exc
                status = self._status_code(exc)

                # JSON mode compatibility fallback.
                if (
                    "response_format" in payload
                    and not json_fallback_used
                    and self._is_json_validation_error(exc)
                    and status in (None, 400)
                ):
                    payload.pop("response_format", None)
                    json_fallback_used = True

                    logger.warning(
                        "llm_json_mode_fallback role=%s operation=%s "
                        "provider=%s model=%s",
                        role,
                        operation,
                        cfg.provider,
                        cfg.model,
                    )

                    continue

                error_name = type(exc).__name__.casefold()

                retryable = (
                    status == 429
                    or (status is not None and status >= 500)
                    or any(
                        item in error_name
                        for item in (
                            "timeout",
                            "connection",
                            "serviceunavailable",
                            "internalserver",
                        )
                    )
                )

                max_retries = 1 if status == 429 else 2
                if retryable and transient_retries < max_retries:

                    if status == 429:
                        delay = self._retry_delay_seconds(
                            exc,
                            transient_retries,
                        )
                    else:
                        delay = min(
                            8.0,
                            0.75 * (2**transient_retries) + random.random() * 0.25,
                        )

                    transient_retries += 1

                    logger.warning(
                        "llm_retry role=%s operation=%s provider=%s "
                        "model=%s status=%s retry=%s delay_seconds=%.2f",
                        role,
                        operation,
                        cfg.provider,
                        cfg.model,
                        status,
                        transient_retries,
                        delay,
                    )

                    await asyncio.sleep(delay)
                    continue

                safe_message = str(exc)

                if cfg.api_key:
                    safe_message = safe_message.replace(
                        cfg.api_key,
                        "[REDACTED]",
                    )

                safe_message = re.sub(
                    r"(?i)(authorization|api[_-]?key|bearer)\s*[:=]\s*\S+",
                    "[REDACTED]",
                    safe_message,
                )[:700]

                logger.warning(
                    "llm_provider_failed role=%s operation=%s "
                    "provider=%s model=%s status=%s "
                    "error_type=%s detail=%s",
                    role,
                    operation,
                    cfg.provider,
                    cfg.model,
                    status,
                    type(exc).__name__,
                    safe_message,
                )

                break

        raise LLMError(f"{role.title()} provider request failed") from last_error


def extract_json_object(raw: str) -> dict[str, Any]:
    candidate = raw.strip()

    if candidate.startswith("```"):
        candidate = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            candidate,
            flags=re.I | re.S,
        )

    try:
        value = json.loads(candidate)

    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, re.S)

        if not match:
            raise ValueError("Provider did not return a JSON object") from None

        value = json.loads(match.group(0))

    if not isinstance(value, dict):
        raise ValueError("Provider JSON must be an object")

    return value
