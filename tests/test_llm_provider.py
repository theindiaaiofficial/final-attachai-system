from types import SimpleNamespace

import litellm
import pytest

from app.providers.llm import LiteLLMProvider


def test_detects_groq_json_validation_error():
    error = Exception("GroqException: json_validate_failed")

    assert LiteLLMProvider._is_json_validation_error(error)


def test_reads_groq_retry_message():
    error = Exception("Please try again in 4.3275s")

    delay = LiteLLMProvider._retry_delay_seconds(error, 0)

    assert 4.4 <= delay <= 5.0


def test_reads_retry_after_header():
    error = Exception("Rate limited")
    error.response = SimpleNamespace(headers={"retry-after": "2.5"})

    delay = LiteLLMProvider._retry_delay_seconds(error, 0)

    assert delay == 2.5


@pytest.mark.asyncio
async def test_json_validation_retries_without_response_format(
    settings,
    monkeypatch,
):
    provider = LiteLLMProvider(settings)

    calls = []

    class BadRequest(Exception):
        status_code = 400

    async def fake_acompletion(**kwargs):
        calls.append(kwargs.copy())

        if len(calls) == 1:
            raise BadRequest("json_validate_failed: Failed to validate JSON")

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"status":"SUFFICIENT"}'),
                    finish_reason="stop",
                )
            ]
        )

    monkeypatch.setattr(
        litellm,
        "acompletion",
        fake_acompletion,
    )

    result = await provider.complete(
        "answer",
        [{"role": "user", "content": "Test"}],
        response_format={"type": "json_object"},
    )

    assert result == '{"status":"SUFFICIENT"}'
    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


@pytest.mark.asyncio
async def test_groq_429_uses_retry_after(
    settings,
    monkeypatch,
):
    provider = LiteLLMProvider(settings)

    calls = []
    delays = []

    class RateLimited(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "1.5"})

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)

        if len(calls) == 1:
            raise RateLimited("Rate limit")

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Success"),
                    finish_reason="stop",
                )
            ]
        )

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(
        litellm,
        "acompletion",
        fake_acompletion,
    )

    monkeypatch.setattr(
        "app.providers.llm.asyncio.sleep",
        fake_sleep,
    )

    result = await provider.complete(
        "answer",
        [{"role": "user", "content": "Test"}],
    )

    assert result == "Success"
    assert len(calls) == 2
    assert delays == [1.5]
