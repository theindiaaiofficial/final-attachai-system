import asyncio
from types import SimpleNamespace

from pydantic import SecretStr

from app.config import Settings
from app.providers import speech


def test_language_base_normalizes_region_and_underscore():
    assert speech._language_base("hi-IN") == "hi"
    assert speech._language_base("en_US") == "en"
    assert speech._language_base(None) == ""


def test_deepgram_transcript_uses_language_array():
    body = {
        "results": {
            "channels": [{
                "alternatives": [{
                    "transcript": "Namaste, kaise hain?",
                    "languages": ["hi-IN", "en-IN"],
                    "words": [],
                }]
            }]
        }
    }
    assert speech._parse_deepgram_transcript(body) == ("Namaste, kaise hain?", "hi-IN")


def test_deepgram_transcript_falls_back_to_word_language():
    body = {
        "results": {
            "channels": [{
                "alternatives": [{
                    "transcript": "Hello there",
                    "languages": [],
                    "words": [{"language": "en-US"}],
                }]
            }]
        }
    }
    assert speech._parse_deepgram_transcript(body) == ("Hello there", "en-US")


def test_deepgram_transcript_rejects_empty_text():
    body = {"results": {"channels": [{"alternatives": [{"transcript": ""}]}]}}
    try:
        speech._parse_deepgram_transcript(body)
    except speech.SpeechProviderError as exc:
        assert "no transcript" in str(exc)
    else:
        raise AssertionError("Expected SpeechProviderError")


def test_deepgram_model_map_uses_detected_language():
    settings = SimpleNamespace(
        tts_model="flux-alexis-en",
        tts_language_models={"hi": "flux-ajay-hi", "en": "flux-alexis-en"},
    )
    assert speech._deepgram_tts_model(settings, "hi-IN") == "flux-ajay-hi"
    assert speech._deepgram_tts_model(settings, "en-US") == "flux-alexis-en"
    try:
        speech._deepgram_tts_model(settings, "fr-FR")
    except speech.SpeechProviderError as exc:
        assert "TTS_LANGUAGE_MODELS" in str(exc)
    else:
        raise AssertionError("Expected a missing-language-model error")


def test_deepgram_stt_uses_multilingual_auto_detection(monkeypatch):
    captured = {}

    class FakeResponse:
        content = b'{"audio":true}'
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": {
                    "channels": [{
                        "alternatives": [{
                            "transcript": "नमस्ते",
                            "languages": ["hi"],
                        }]
                    }]
                }
            }

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr(speech.httpx, "AsyncClient", FakeAsyncClient)
    settings = SimpleNamespace(
        stt_model="nova-3",
        stt_language="auto",
        deepgram_api_base="https://api.deepgram.com",
        deepgram_stt_endpoint="v1/listen",
    )
    result = asyncio.run(speech._deepgram_transcribe(settings, "dg-test-key", b"audio", "audio/webm"))

    assert result == ("नमस्ते", "hi")
    assert captured["params"] == {"model": "nova-3", "language": "multi"}
    assert captured["headers"]["Authorization"] == "Token dg-test-key"
    assert captured["content"] == b"audio"


def test_settings_accept_deepgram_and_language_model_map():
    settings = Settings(
        _env_file=None,
        DEEPGRAM_API_KEY="test-key",
        STT_PROVIDER="deepgram",
        STT_MODEL="nova-3",
        STT_LANGUAGE="multi",
        TTS_PROVIDER="deepgram",
        TTS_LANGUAGE_MODELS='{"hi":"flux-ajay-hi","en":"flux-alexis-en"}',
    )
    assert settings.stt_enabled is True
    assert settings.tts_enabled is True
    assert settings.tts_language_models["hi"] == "flux-ajay-hi"


def test_provider_aliases_route_to_openai_compatible():
    assert speech._provider_name("custom") == "openai_compatible"
    assert speech._provider_name("openai-compatible") == "openai_compatible"


def test_deepgram_tts_uses_detected_language_model_and_token_auth(monkeypatch):
    captured = {}

    class FakeResponse:
        content = b"\x00\x01audio"
        headers = {"content-type": "audio/mpeg"}

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr(speech.httpx, "AsyncClient", FakeAsyncClient)
    settings = SimpleNamespace(
        tts_model="flux-alexis-en",
        tts_language_models={"hi": "flux-ajay-hi", "en": "flux-alexis-en"},
        deepgram_api_base="https://api.deepgram.com",
        deepgram_tts_endpoint="v2/speak",
        tts_response_format="mp3",
    )
    audio, media_type = asyncio.run(
        speech._deepgram_synthesize(settings, "dg-test-key", "नमस्ते", "hi-IN")
    )

    assert audio == b"\x00\x01audio"
    assert media_type == "audio/mpeg"
    assert captured["params"] == {"model": "flux-ajay-hi", "encoding": "mp3"}
    assert captured["headers"]["Authorization"] == "Token dg-test-key"
    assert captured["json"] == {"text": "नमस्ते"}


def test_custom_tts_adapter_can_register_and_run():
    provider = "test_custom_voice_provider"

    async def adapter(settings, text, language):
        return b"audio-bytes", "audio/wav"

    speech.register_tts_adapter(provider, adapter)
    settings = SimpleNamespace(
        tts_provider=provider,
        tts_api_key=SecretStr("custom-key"),
        assemblyai_api_key=None,
        deepgram_api_key=None,
    )
    assert asyncio.run(speech.synthesize_speech(settings, "hello", "en")) == (
        b"audio-bytes", "audio/wav"
    )


def test_custom_stt_adapter_can_register_and_return_language():
    provider = "test_custom_transcriber"

    def adapter(settings, audio, filename, content_type):
        return "bonjour", "fr"

    speech.register_stt_adapter(provider, adapter)
    settings = SimpleNamespace(
        stt_provider=provider,
        stt_api_key=SecretStr("custom-key"),
        assemblyai_api_key=None,
        deepgram_api_key=None,
    )
    assert asyncio.run(
        speech.transcribe_speech_with_language(settings, b"audio", "recording.webm", "audio/webm")
    ) == ("bonjour", "fr")
