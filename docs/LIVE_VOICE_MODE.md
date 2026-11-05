# Live Voice Mode

The embedded widget now includes a continuous, turn-based voice conversation mode. It uses the existing tenant-authenticated `/v1/stt`, `/v1/chat`, and `/v1/tts` endpoints; no provider-specific browser code or new environment variables are required.

## Visitor experience

1. The visitor opens the chat widget and selects the voice button.
2. The widget requests microphone permission and displays a full-height voice surface with an animated orb.
3. Microphone input is recorded while the listening state is active. Browser audio-level analysis detects speech and automatically closes a turn after approximately 1.15 seconds of silence.
4. The recorded audio is sent to `/v1/stt`. The detected language is retained and passed to `/v1/tts` for the assistant response.
5. The answer is displayed in the voice surface and played through `/v1/tts`.
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
