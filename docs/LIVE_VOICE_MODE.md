# Live Voice Mode

The embedded widget now includes a continuous, turn-based voice conversation mode. It uses the tenant-authenticated `/v1/stt`, `/v1/chat/stream`, and `/v1/tts/stream` endpoints; no provider-specific browser code is required. The legacy `/v1/chat` and `/v1/tts` endpoints remain available for compatibility.

## Visitor experience

1. The visitor opens the chat widget and selects the voice button.
2. The widget requests microphone permission and displays a full-height voice surface with an animated orb.
3. Microphone input is recorded while the listening state is active. Browser audio-level analysis detects speech and automatically closes a turn after approximately 1.15 seconds of silence.
4. The recorded audio is sent to `/v1/stt`. The detected language is retained and passed to `/v1/tts/stream` for the assistant response.
5. The answer is displayed progressively in the voice surface and played through `/v1/tts/stream`.
6. When playback ends, the widget automatically resumes listening for the next turn.

The voice surface shows listening, thinking, speaking, muted, and error states. Visitors can mute/unmute, interrupt assistant playback to speak, minimize the widget, or end the voice session. Minimizing the widget leaves an active voice session running; ending it stops the recorder, microphone tracks, pending speech requests, and audio playback.

## Browser behavior

- Microphone access requires HTTPS (or localhost during development) and visitor permission.
- The preferred path uses `MediaRecorder` plus the Web Audio API for silence detection and live orb level response.
- If Web Audio analysis is unavailable, a 12-second recording fallback is used.
- If remote STT is disabled, the existing browser `SpeechRecognition` fallback is retained. Continuous voice turns still use browser recognition and browser speech synthesis when server TTS is disabled.
- Speech segments are capped at 25 seconds before being submitted, to avoid unbounded recordings.
- Microphone tracks request echo cancellation, noise suppression, and automatic gain control where the browser supports them.

## Language handling

The STT response's `language` value is passed to the TTS endpoint. If STT does not return a language, Devanagari text falls back to `hi`; otherwise the configured TTS default remains in effect. Existing `TTS_LANGUAGE_MODELS` mappings therefore continue to choose the appropriate provider voice/model without coupling the widget to Deepgram, AssemblyAI, or another provider.

## Tuning

The silence detector currently uses an RMS level threshold of `0.018`, a silence window of `1150 ms`, and a maximum segment duration of `25000 ms`. These are browser-side usability defaults, not provider settings. If a particular microphone environment cuts off speech too early or waits too long, adjust these values in `app/widget/static/widget.js` after testing on real devices.


## Streaming behavior

The widget now consumes `/v1/chat/stream` as server-sent events. Router, retrieval,
evidence evaluation, answer generation, grounding, correction, and save phases emit
real stage updates. General conversation answers stream directly from LiteLLM as
provider chunks arrive. Business/RAG drafts remain server-side until grounding
verification is complete; only the verified final answer is then chunked to the
widget. This avoids speaking or displaying unverified business claims.

TTS uses `/v1/tts/stream`. During live voice turns, the widget detects completed
sentences in the incoming LLM text stream and starts a separate TTS request for each
sentence while the model continues generating. Sentences are played in order, so the
first audio can begin before the full answer is ready. Deepgram audio is forwarded as
response chunks, and the widget uses Media Source Extensions where supported,
falling back to buffered audio playback when the browser cannot append that codec.
Providers that only return a complete audio file retain the compatible buffered
behavior. The text transcript continues updating while audio sentences are played.

Set `widget.voiceStatusSpeech: true` in an individual client's widget config to
allow one short spoken progress message after a four-second wait during voice chat.
Detailed progress remains visual and is not repeatedly spoken.
