# Widget TTS Player

The visitor widget provides single-message text-to-speech from the speaker icon beside Copy. It does not expose a microphone, continuous listening, or live voice conversation mode.

## Request flow

1. The widget reads `speech.ttsEnabled` from `/v1/config`. It shows the speaker action only when TTS is configured.
2. Clicking the speaker opens an inline loading state and sends the selected assistant response to `POST /v1/tts`.
3. The server uses the configured TTS provider and returns audio bytes with the provider's media type.
4. When playback starts, the player shows an animated waveform, elapsed and total time, and playback progress. Pause, resume, and stop are available.

## Provider support

The player is provider-neutral. It consumes the `POST /v1/tts` contract rather than using a provider-specific browser SDK or codec. Built-in providers include Deepgram, AssemblyAI, and OpenAI-compatible TTS. Additional providers can register a TTS adapter using `register_tts_adapter`, returning `(audio_bytes, media_type)`.

The `/v1/stt` API and STT provider adapters remain available for external integrations, but the visitor widget no longer starts microphone or live voice sessions.
