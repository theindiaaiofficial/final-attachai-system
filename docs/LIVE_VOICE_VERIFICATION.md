# Live Voice Mode — Verification

## Implemented
- Full-height voice mode overlay inside the existing chat widget.
- Animated orb with listening, thinking, speaking, muted, and error states.
- Microphone-level animation while listening and assistant-audio-level animation while speaking.
- Turn-based hands-free conversation: speech detection, silence-based turn submission, STT, chat, TTS, and automatic return to listening.
- STT-detected language is forwarded to TTS when available; Devanagari fallback detection is used when the STT response omits language.
- Mute/unmute, interrupt assistant, minimize, and end-session controls.
- Microphone track cleanup and request/audio cancellation when the session ends.
- Existing chat UI and provider configuration remain in place.

## Checks run in the build environment
- `python -m compileall -q app scripts tests` — passed.
- `python -m pytest -q --ignore=tests/test_llm_provider.py` — **56 passed**.
- Full pytest collection could not include `tests/test_llm_provider.py` because `litellm` was not installed in this build environment. The project already declares `litellm==1.80.11` in `requirements.txt`.
- Widget CSS parsed with `tinycss2` — 185 top-level rules, 0 parse errors.
- Chromium mocked browser checks — widget mounted without JS errors; a mocked Hindi STT → chat → Hindi TTS turn completed and returned to listening; mute, interrupt, and end-session microphone cleanup checks passed.

## Important test scope
Browser conversation tests used mocked microphone/provider responses. They verify frontend state transitions and request payloads, but are not a substitute for testing a real microphone and live Deepgram credentials on the deployed website.
