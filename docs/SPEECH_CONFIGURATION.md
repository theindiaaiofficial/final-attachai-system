# Widget speech configuration

The widget calls Orbit's `/v1/stt` and `/v1/tts` endpoints. Speech-provider credentials stay on the server and are not returned by `/v1/config` or sent to the visitor's browser.

## AssemblyAI (tested SDK integration)

Install the Python dependency from `requirements.txt`, then add these values to the server's existing `.env` file:

```dotenv
TTS_PROVIDER=assemblyai
STT_PROVIDER=assemblyai
ASSEMBLYAI_API_KEY=your-assemblyai-api-key
ASSEMBLYAI_TTS_VOICE_ID=49c443a4-8a1d-5f7e-b70b-98bdbd9823c3
ASSEMBLYAI_TTS_LANGUAGE=english
ASSEMBLYAI_TTS_CONTAINER=wav
```

The same AssemblyAI API key is used server-side for both speech-to-text and text-to-speech. The default TTS voice ID is Audrey, matching the supplied working test. The current adapter returns WAV audio for browser playback. STT uses the AssemblyAI Python SDK to transcribe the recorded audio bytes; the SDK call runs in a worker thread so it does not block FastAPI's event loop.

After changing `.env` or installing requirements, restart Orbit. In the browser, allow microphone access and use HTTPS (or localhost for development). The widget currently limits uploaded recordings to 12 MB.

## OpenAI-compatible speech providers

To use a different OpenAI-compatible speech service, set `TTS_PROVIDER=openai_compatible` and/or `STT_PROVIDER=openai_compatible`, then configure the corresponding `TTS_API_*` and `STT_API_*` settings. That adapter expects `/audio/speech` and `/audio/transcriptions`-compatible endpoints with Bearer authentication.

TTS and STT can be configured independently. Setting one provider to `assemblyai` does not force the other to use it.
