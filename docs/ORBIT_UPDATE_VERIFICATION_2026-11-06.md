# Orbit update verification — 2026-11-06

## Changes included

- Automatic unified Supabase selection from `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` when the three data provider settings are left at `auto`.
- Fail-fast handling for partial credentials, explicit conflicting provider selections, missing Supabase tables, missing migration marker, missing private bucket, and Supabase connectivity errors. The app does not silently switch to local storage.
- A fourth additive SQL migration that hardens the vector-search RPC grants, completes tenant policies for the RLS-enabled usage/audit/notification tables, enforces a private knowledge bucket, and records the migration-0004 readiness marker.
- A live `/ready` probe for both database/vector schema and private storage bucket.
- Genuine chat SSE with actual pipeline stage updates and incremental LLM text chunks for general responses. Business/RAG answers are emitted only after grounding checks succeed.
- Removed the visitor-facing live voice conversation UI, microphone capture, continuous listening, and automatic spoken answer flow.
- Added a single-message TTS player beside Copy. It shows a loading state while the configured provider generates audio, then an animated waveform, elapsed/total time, progress, pause/resume, and stop controls.
- The widget uses the provider-neutral `POST /v1/tts` audio-bytes + media-type contract. Deepgram, AssemblyAI, OpenAI-compatible TTS, and registered custom adapters use the same playback UI.
- The `/v1/stt` API and STT adapters remain available to external integrations, but are no longer used by the visitor widget.
- Widget launcher label is `Chat`.

## Local checks

| Check | Result |
|---|---|
| Automated tests | **71 passed** |
| Python compilation (`python -m compileall -q app tests`) | **Passed** |
| Ruff lint | Not run; Ruff is not installed in the offline build environment |
| Chromium browser E2E | Not run; Playwright Chromium executable is not installed in the build environment |
| Live Supabase connection / SQL execution | Not run; no Supabase project credentials were supplied |
| Render deployment | Not run; no deployment access was supplied |
| Live LLM/TTS provider requests | Not run; tests use isolated adapters and do not make paid provider requests |

The environment used for this build did not have the `litellm` package available and had no network access to install it. The full pytest suite was therefore run with a temporary test-only `litellm` import stub; LLM-provider unit tests monkeypatch `acompletion` with deterministic fakes. The stub is not included in the project archive and is not used by the application at runtime. Render installs the actual runtime dependency from `requirements.txt`.

## Supabase deployment checklist

1. On a fresh project, apply migrations `0001_orbit_base.sql`, `0002_vector_768.sql`, `0003_admin_dashboard.sql`, and `0004_orbit_runtime_security.sql` in this order. If the current Supabase project already has 0001-0003 applied, apply only the new `0004_orbit_runtime_security.sql`.
2. Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the server's environment. `SUPABASE_STORAGE_BUCKET` may remain `knowledge`.
3. Remove old explicit local provider overrides (`DATABASE_PROVIDER=sqlite`, `STORAGE_PROVIDER=local`, `VECTOR_PROVIDER=sqlite`) or set all three to `auto`.
4. Confirm `/ready` reports `status: ready` and all three `data_providers` as `supabase`.
5. Re-embed knowledge sources using the active 768-dimensional embedding configuration before relying on the new vector index. The vector migration intentionally preserves the previous 128-dimensional data.

A successful local test suite verifies application behavior against mocked/local services; it does not claim that an external Supabase project or Render deployment has been connected. Use the deployed `/ready` response as the final external verification.
