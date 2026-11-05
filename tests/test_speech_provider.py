from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.providers import speech


class FakeResponse:
    def __init__(self, *, content=b"audio", body=None, content_type="audio/mpeg"):
        self.content = content
        self.headers = {"content-type": content_type}
        self._body = body or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, response, calls):
        self.response = response
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


@pytest.mark.asyncio
async def test_tts_uses_server_side_credentials_and_configured_endpoint(settings, monkeypatch):
    settings.tts_api_key = SecretStr("speech-secret")
    settings.tts_api_base = "https://speech.example/v1/"
    settings.tts_model = "voice-model"
    settings.tts_voice = "voice-one"
    calls = []
    client = FakeClient(FakeResponse(), calls)
    monkeypatch.setattr(speech.httpx, "AsyncClient", lambda **kwargs: client)

    audio, media_type = await speech.synthesize_speech(settings, "Hello")

    assert audio == b"audio"
    assert media_type == "audio/mpeg"
    url, request = calls[0]
    assert url == "https://speech.example/v1/audio/speech"
    assert request["headers"]["Authorization"] == "Bearer speech-secret"
    assert request["json"]["model"] == "voice-model"
    assert request["json"]["input"] == "Hello"


@pytest.mark.asyncio
async def test_stt_uses_server_side_credentials_and_returns_transcript(settings, monkeypatch):
    settings.stt_api_key = SecretStr("transcription-secret")
    settings.stt_api_base = "https://speech.example/v1"
    settings.stt_model = "transcription-model"
    settings.stt_language = "en"
    calls = []
    client = FakeClient(FakeResponse(body={"text": "Hello there"}), calls)
    monkeypatch.setattr(speech.httpx, "AsyncClient", lambda **kwargs: client)

    transcript = await speech.transcribe_speech(
        settings,
        b"audio-bytes",
        "recording.webm",
        "audio/webm",
    )

    assert transcript == "Hello there"
    url, request = calls[0]
    assert url == "https://speech.example/v1/audio/transcriptions"
    assert request["headers"]["Authorization"] == "Bearer transcription-secret"
    assert request["data"] == {"model": "transcription-model", "language": "en"}
    assert request["files"]["file"][0] == "recording.webm"


@pytest.mark.asyncio
async def test_assemblyai_tts_uses_configured_voice_and_returns_wav(settings, monkeypatch):
    import sys
    from types import ModuleType

    calls = []

    class FakeTTS:
        def __init__(self, *, api_key):
            calls.append(("client", api_key))

        def synthesize(self, text, config):
            calls.append(("synthesize", text, config.voice_id, config.language, config.container))
            return SimpleNamespace(audio=b"wav-audio")

    fake = ModuleType("assemblyai")
    fake.TextToSpeech = FakeTTS
    fake.TTSContainer = SimpleNamespace(wav="wav")
    fake.TTSConfig = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "assemblyai", fake)

    settings.tts_provider = "assemblyai"
    settings.assemblyai_api_key = SecretStr("assemblyai-secret")
    settings.assemblyai_tts_voice_id = "audrey-voice-id"
    settings.assemblyai_tts_language = "english"
    settings.assemblyai_tts_container = "wav"

    audio, media_type = await speech.synthesize_speech(settings, "Hello from Orbit")

    assert audio == b"wav-audio"
    assert media_type == "audio/wav"
    assert calls[0] == ("client", "assemblyai-secret")
    assert calls[1] == ("synthesize", "Hello from Orbit", "audrey-voice-id", "english", "wav")


@pytest.mark.asyncio
async def test_assemblyai_stt_transcribes_recorded_bytes(settings, monkeypatch):
    import sys
    from types import ModuleType

    fake = ModuleType("assemblyai")
    fake.settings = SimpleNamespace(api_key=None)
    fake.TranscriptStatus = SimpleNamespace(error="error")
    calls = []

    class FakeTranscriber:
        def transcribe(self, audio):
            calls.append(audio)
            return SimpleNamespace(status="completed", text="Hello from the microphone")

    fake.Transcriber = FakeTranscriber
    monkeypatch.setitem(sys.modules, "assemblyai", fake)

    settings.stt_provider = "assemblyai"
    settings.assemblyai_api_key = SecretStr("assemblyai-secret")

    transcript = await speech.transcribe_speech(
        settings, b"recorded-webm-bytes", "recording.webm", "audio/webm"
    )

    assert transcript == "Hello from the microphone"
    assert calls == [b"recorded-webm-bytes"]
    assert fake.settings.api_key == "assemblyai-secret"


def test_assemblyai_speech_flags_require_provider_key(settings):
    settings.tts_provider = "assemblyai"
    settings.stt_provider = "assemblyai"
    assert settings.tts_enabled is False
    assert settings.stt_enabled is False

    settings.assemblyai_api_key = SecretStr("assemblyai-secret")
    assert settings.tts_enabled is True
    assert settings.stt_enabled is True
