from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
from pydantic import SecretStr


logger = logging.getLogger("orbit.speech")

# Native provider plugins register async or synchronous callables with these
# signatures. OpenAI-compatible services do not need a custom adapter.
_TTS_ADAPTERS: dict[str, Callable[..., Any]] = {}
_STT_ADAPTERS: dict[str, Callable[..., Any]] = {}


def register_tts_adapter(provider: str, adapter: Callable[..., Any]) -> None:
    name = _provider_name(provider)
    if not name or name in {"assemblyai", "deepgram", "openai_compatible"}:
        raise ValueError("Choose a non-built-in TTS provider name")
    _TTS_ADAPTERS[name] = adapter


def register_stt_adapter(provider: str, adapter: Callable[..., Any]) -> None:
    name = _provider_name(provider)
    if not name or name in {"assemblyai", "deepgram", "openai_compatible"}:
        raise ValueError("Choose a non-built-in STT provider name")
    _STT_ADAPTERS[name] = adapter


def load_speech_adapter_modules(module_names: str | list[str] | None) -> None:
    if not module_names:
        return
    names = module_names if isinstance(module_names, list) else module_names.split(",")
    for module_name in (str(item).strip() for item in names):
        if module_name:
            importlib.import_module(module_name)
            logger.info("speech_adapter_module_loaded module=%s", module_name)


async def _run_adapter(adapter: Callable[..., Any], *args: Any) -> Any:
    result = adapter(*args)
    return await result if inspect.isawaitable(result) else result


class SpeechProviderError(RuntimeError):
    """Safe speech-provider error without exposing upstream response details."""


def _secret(value: SecretStr | None) -> str:
    return value.get_secret_value() if value else ""


def _url(base: str, endpoint: str) -> str:
    return f"{base.rstrip('/')}/{endpoint.lstrip('/')}"


def _provider_name(value: str) -> str:
    name = (value or "").strip().casefold()
    if name in {"custom", "openai", "generic", "openai-compatible"}:
        return "openai_compatible"
    return name


def _provider_key(settings: Any, role: str, provider: str) -> str:
    role_key = _secret(getattr(settings, f"{role}_api_key", None))
    if provider == "assemblyai":
        return _secret(getattr(settings, "assemblyai_api_key", None)) or role_key
    if provider == "deepgram":
        return _secret(getattr(settings, "deepgram_api_key", None)) or role_key
    return role_key


def _auth_headers(key: str, header: str = "Authorization", scheme: str = "Bearer") -> dict[str, str]:
    value = f"{scheme.strip()} {key}".strip() if scheme.strip() else key
    return {header.strip() or "Authorization": value}


def _language_base(language: str | None) -> str:
    value = (language or "").strip().replace("_", "-").casefold()
    return value.split("-", 1)[0]


_ASSEMBLYAI_TTS_LANGUAGES = {
    "en": "english",
    "es": "spanish",
    "fr": "french",
    "de": "german",
    "it": "italian",
    "pt": "portuguese",
}


def _assemblyai_synthesize(
    key: str, text: str, voice_id: str, configured_language: str, container_name: str,
    detected_language: str | None = None,
) -> tuple[bytes, str]:
    language_code = _language_base(detected_language)
    if language_code:
        language = _ASSEMBLYAI_TTS_LANGUAGES.get(language_code)
        if not language:
            raise SpeechProviderError(
                f"AssemblyAI TTS does not support detected language '{language_code}'. "
                "Select a multilingual TTS provider for this language."
            )
    else:
        language = configured_language

    try:
        import assemblyai as aai

        tts = aai.TextToSpeech(api_key=key)
        container = getattr(aai.TTSContainer, container_name.casefold())
        result = tts.synthesize(
            text,
            aai.TTSConfig(
                voice_id=voice_id,
                container=container,
                language=language,
            ),
        )
        audio = bytes(result.audio)
        if not audio:
            raise SpeechProviderError("AssemblyAI returned empty speech audio")
        return audio, "audio/wav"
    except SpeechProviderError:
        raise
    except Exception as exc:
        logger.exception(
            "assemblyai_tts_failed type=%s status=%s",
            type(exc).__name__, getattr(exc, "status_code", None),
        )
        raise SpeechProviderError(f"AssemblyAI TTS failed ({type(exc).__name__})") from None


def _assemblyai_transcribe(key: str, audio: bytes) -> tuple[str, str | None]:
    try:
        import assemblyai as aai

        aai.settings.api_key = key
        config_type = getattr(aai, "TranscriptionConfig", None)
        transcriber = (
            aai.Transcriber(config=config_type(language_detection=True))
            if config_type is not None
            else aai.Transcriber()
        )
        transcript = transcriber.transcribe(audio)
        if transcript.status == aai.TranscriptStatus.error:
            raise SpeechProviderError("AssemblyAI could not transcribe this audio")
        text = (transcript.text or "").strip()
        if not text:
            raise SpeechProviderError("AssemblyAI returned no transcript")
        response = getattr(transcript, "json_response", {}) or {}
        language = response.get("language_code") if isinstance(response, dict) else None
        return text, str(language) if language else None
    except SpeechProviderError:
        raise
    except Exception as exc:
        logger.exception("assemblyai_stt_failed type=%s", type(exc).__name__)
        raise SpeechProviderError(f"AssemblyAI STT failed ({type(exc).__name__})") from None


def _deepgram_language_models(settings: Any) -> dict[str, str]:
    value = getattr(settings, "tts_language_models", {}) or {}
    return {str(key).casefold(): str(model) for key, model in value.items()}


def _deepgram_tts_model(settings: Any, language: str | None) -> str:
    models = _deepgram_language_models(settings)
    normalized = _language_base(language)
    mapped = models.get((language or "").casefold()) or models.get(normalized)
    if mapped:
        return mapped
    if models and normalized:
        raise SpeechProviderError(
            f"No Deepgram TTS model is configured for detected language '{normalized}'. "
            "Add it to TTS_LANGUAGE_MODELS."
        )
    return str(getattr(settings, "tts_model", "")).strip()


async def _deepgram_synthesize(
    settings: Any, key: str, text: str, language: str | None
) -> tuple[bytes, str]:
    model = _deepgram_tts_model(settings, language)
    if not model:
        raise SpeechProviderError(
            "Deepgram TTS model is not configured. Set TTS_MODEL or TTS_LANGUAGE_MODELS."
        )

    base = str(getattr(settings, "deepgram_api_base", "https://api.deepgram.com"))
    endpoint = str(getattr(settings, "deepgram_tts_endpoint", "v2/speak"))
    encoding = str(getattr(settings, "tts_response_format", "mp3")).casefold()
    params: dict[str, str] = {"model": model}
    if encoding == "wav":
        params.update({"encoding": "linear16", "container": "wav"})
    elif encoding:
        params["encoding"] = encoding

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                _url(base, endpoint),
                headers={**_auth_headers(key, scheme="Token"), "Content-Type": "application/json"},
                params=params,
                json={"text": text},
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning("deepgram_tts_http_error status=%s", exc.response.status_code)
        raise SpeechProviderError(
            f"Deepgram TTS request failed (HTTP {exc.response.status_code})"
        ) from None
    except httpx.HTTPError as exc:
        logger.warning("deepgram_tts_network_error type=%s", type(exc).__name__)
        raise SpeechProviderError("Deepgram TTS connection failed") from None

    if not response.content:
        raise SpeechProviderError("Deepgram TTS returned empty audio")
    media_type = response.headers.get("content-type", "audio/mpeg").split(";", 1)[0]
    if not media_type.startswith("audio/"):
        media_type = "audio/mpeg"
    return response.content, media_type


def _parse_deepgram_transcript(body: dict[str, Any]) -> tuple[str, str | None]:
    try:
        alternative = body["results"]["channels"][0]["alternatives"][0]
        text = str(alternative.get("transcript") or "").strip()
        languages = alternative.get("languages") or []
        detected = languages[0] if languages else None
        if not detected:
            for word in alternative.get("words") or []:
                detected = word.get("language")
                if detected:
                    break
        if not text:
            raise SpeechProviderError("Deepgram returned no transcript")
        return text, str(detected) if detected else None
    except SpeechProviderError:
        raise
    except (KeyError, IndexError, TypeError, AttributeError):
        raise SpeechProviderError("Deepgram returned an unexpected transcription response") from None


async def _deepgram_transcribe(
    settings: Any, key: str, audio: bytes, content_type: str
) -> tuple[str, str | None]:
    model = str(getattr(settings, "stt_model", "") or "nova-3").strip()
    language = str(getattr(settings, "stt_language", "") or "multi").strip().casefold()
    if language in {"", "auto"}:
        language = "multi"
    base = str(getattr(settings, "deepgram_api_base", "https://api.deepgram.com"))
    endpoint = str(getattr(settings, "deepgram_stt_endpoint", "v1/listen"))
    params = {"model": model, "language": language}

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                _url(base, endpoint),
                headers={
                    **_auth_headers(key, scheme="Token"),
                    "Content-Type": content_type or "application/octet-stream",
                },
                params=params,
                content=audio,
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("deepgram_stt_http_error status=%s", exc.response.status_code)
        raise SpeechProviderError(
            f"Deepgram STT request failed (HTTP {exc.response.status_code})"
        ) from None
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("deepgram_stt_request_error type=%s", type(exc).__name__)
        raise SpeechProviderError("Deepgram STT connection or response failed") from None

    return _parse_deepgram_transcript(body)


async def _openai_compatible_synthesize(
    settings: Any, key: str, text: str, language: str | None
) -> tuple[bytes, str]:
    if not settings.tts_model:
        raise SpeechProviderError("TTS_MODEL is not configured")
    url = _url(settings.tts_api_base, settings.tts_endpoint)
    payload: dict[str, Any] = {
        "model": settings.tts_model,
        "input": text,
        "voice": settings.tts_voice,
        "response_format": settings.tts_response_format,
    }
    language_field = str(getattr(settings, "tts_language_field", "")).strip()
    if language and language_field:
        payload[language_field] = language
    headers = _auth_headers(
        key,
        str(getattr(settings, "tts_auth_header", "Authorization")),
        str(getattr(settings, "tts_auth_scheme", "Bearer")),
    )
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning("tts_http_error provider=openai_compatible status=%s", exc.response.status_code)
        raise SpeechProviderError(
            f"TTS provider request failed (HTTP {exc.response.status_code})"
        ) from None
    except httpx.HTTPError as exc:
        logger.warning("tts_network_error provider=openai_compatible type=%s", type(exc).__name__)
        raise SpeechProviderError("TTS provider connection failed") from None

    if not response.content:
        raise SpeechProviderError("TTS provider returned empty audio")
    media_type = response.headers.get("content-type", "audio/mpeg").split(";", 1)[0]
    if not media_type.startswith("audio/"):
        media_type = "audio/mpeg"
    return response.content, media_type


async def _openai_compatible_transcribe(
    settings: Any, key: str, audio: bytes, filename: str, content_type: str
) -> tuple[str, str | None]:
    if not settings.stt_model:
        raise SpeechProviderError("STT_MODEL is not configured")
    data = {"model": settings.stt_model}
    language = str(getattr(settings, "stt_language", "")).strip()
    if language and language.casefold() not in {"auto", "multi"}:
        data["language"] = language
    url = _url(settings.stt_api_base, settings.stt_endpoint)
    headers = _auth_headers(
        key,
        str(getattr(settings, "stt_auth_header", "Authorization")),
        str(getattr(settings, "stt_auth_scheme", "Bearer")),
    )
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url,
                headers=headers,
                data=data,
                files={"file": (filename, audio, content_type)},
            )
            response.raise_for_status()
            body: dict[str, Any] = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("stt_http_error provider=openai_compatible status=%s", exc.response.status_code)
        raise SpeechProviderError(
            f"STT provider request failed (HTTP {exc.response.status_code})"
        ) from None
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("stt_request_error provider=openai_compatible type=%s", type(exc).__name__)
        raise SpeechProviderError("STT provider connection or response failed") from None

    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise SpeechProviderError("STT provider returned no transcript")
    detected = body.get("language") or body.get("language_code")
    return text.strip(), str(detected) if detected else None


async def stream_synthesize_speech(
    settings: Any, text: str, language: str | None = None
) -> AsyncIterator[bytes]:
    """Yield provider audio chunks where supported; buffer only legacy adapters."""
    provider = _provider_name(settings.tts_provider)
    key = _provider_key(settings, "tts", provider)
    if not key:
        raise SpeechProviderError(f"{provider} TTS API key is not configured")

    if provider == "deepgram":
        model = _deepgram_tts_model(settings, language)
        if not model:
            raise SpeechProviderError("Deepgram TTS model is not configured")
        base = str(getattr(settings, "deepgram_api_base", "https://api.deepgram.com"))
        endpoint = str(getattr(settings, "deepgram_tts_endpoint", "v2/speak"))
        encoding = str(getattr(settings, "tts_response_format", "mp3")).casefold()
        params: dict[str, str] = {"model": model}
        if encoding == "wav":
            params.update({"encoding": "linear16", "container": "wav"})
        elif encoding:
            params["encoding"] = encoding
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                async with client.stream(
                    "POST", _url(base, endpoint),
                    headers={**_auth_headers(key, scheme="Token"), "Content-Type": "application/json"},
                    params=params, json={"text": text},
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        if chunk:
                            yield chunk
        except httpx.HTTPStatusError as exc:
            logger.warning("deepgram_tts_stream_http_error status=%s", exc.response.status_code)
            raise SpeechProviderError(f"Deepgram TTS request failed (HTTP {exc.response.status_code})") from None
        except httpx.HTTPError as exc:
            logger.warning("deepgram_tts_stream_network_error type=%s", type(exc).__name__)
            raise SpeechProviderError("Deepgram TTS streaming connection failed") from None
        return

    # Legacy SDKs and custom adapters return one complete byte string. The API
    # remains compatible and can still stream that single payload to the browser.
    audio, _ = await synthesize_speech(settings, text, language)
    if audio:
        yield audio


def speech_media_type(settings: Any) -> str:
    provider = _provider_name(getattr(settings, "tts_provider", ""))
    if provider == "assemblyai":
        return "audio/wav"
    encoding = str(getattr(settings, "tts_response_format", "mp3")).casefold()
    return {"wav": "audio/wav", "opus": "audio/ogg", "ogg": "audio/ogg", "aac": "audio/aac"}.get(encoding, "audio/mpeg")


async def synthesize_speech(
    settings: Any, text: str, language: str | None = None
) -> tuple[bytes, str]:
    provider = _provider_name(settings.tts_provider)
    key = _provider_key(settings, "tts", provider)
    if not key:
        raise SpeechProviderError(f"{provider} TTS API key is not configured")

    if provider == "assemblyai":
        return await asyncio.to_thread(
            _assemblyai_synthesize,
            key,
            text,
            settings.assemblyai_tts_voice_id,
            settings.assemblyai_tts_language,
            settings.assemblyai_tts_container,
            language,
        )
    if provider == "deepgram":
        return await _deepgram_synthesize(settings, key, text, language)
    if provider == "openai_compatible":
        return await _openai_compatible_synthesize(settings, key, text, language)
    adapter = _TTS_ADAPTERS.get(provider)
    if adapter:
        try:
            result = await _run_adapter(adapter, settings, text, language)
            if not isinstance(result, tuple) or len(result) != 2 or not isinstance(result[0], bytes):
                raise SpeechProviderError("Custom TTS adapter must return (audio_bytes, media_type)")
            return result
        except SpeechProviderError:
            raise
        except Exception as exc:
            logger.exception("custom_tts_adapter_failed provider=%s type=%s", provider, type(exc).__name__)
            raise SpeechProviderError(f"Custom TTS adapter '{provider}' failed") from None
    raise SpeechProviderError(
        f"Unsupported TTS provider '{provider}'. Configure an OpenAI-compatible endpoint or add a native adapter module."
    )


async def transcribe_speech_with_language(
    settings: Any,
    audio: bytes,
    filename: str,
    content_type: str,
) -> tuple[str, str | None]:
    provider = _provider_name(settings.stt_provider)
    key = _provider_key(settings, "stt", provider)
    if not key:
        raise SpeechProviderError(f"{provider} STT API key is not configured")

    if provider == "assemblyai":
        return await asyncio.to_thread(_assemblyai_transcribe, key, audio)
    if provider == "deepgram":
        return await _deepgram_transcribe(settings, key, audio, content_type)
    if provider == "openai_compatible":
        return await _openai_compatible_transcribe(
            settings, key, audio, filename, content_type
        )
    adapter = _STT_ADAPTERS.get(provider)
    if adapter:
        try:
            result = await _run_adapter(adapter, settings, audio, filename, content_type)
            if not isinstance(result, tuple) or len(result) != 2 or not isinstance(result[0], str):
                raise SpeechProviderError("Custom STT adapter must return (transcript_text, language_code_or_none)")
            return result
        except SpeechProviderError:
            raise
        except Exception as exc:
            logger.exception("custom_stt_adapter_failed provider=%s type=%s", provider, type(exc).__name__)
            raise SpeechProviderError(f"Custom STT adapter '{provider}' failed") from None
    raise SpeechProviderError(
        f"Unsupported STT provider '{provider}'. Configure an OpenAI-compatible endpoint or add a native adapter module."
    )


async def transcribe_speech(
    settings: Any, audio: bytes, filename: str, content_type: str
) -> str:
    """Backward-compatible text-only helper for existing internal callers."""
    text, _language = await transcribe_speech_with_language(
        settings, audio, filename, content_type
    )
    return text
