# Orbit AI Python

Orbit AI is a Python 3.12 / FastAPI application. Its only public chat orchestrator is `app/rag/pipeline.py`, which implements the RAG-2.0 route decision, bounded tenant memory, retrieval, evidence evaluation, answer generation, grounding verification, one correction/re-verification cycle, safe fallback, citation filtering, and persistence.

## Repository contents

* `app/` — FastAPI composition root, secure admin session/auth, dashboard APIs, services, provider adapters, repositories, knowledge ingestion, frontend, widget, and RAG pipeline.
* `migrations/` — ordered Supabase schema, additive legacy-128-to-768 vector migration, and dashboard session/settings tables.
* `tests/` — offline security, tenant isolation, dashboard API, routing, retrieval-boundary, correction, and citation tests.
* `docs/` — discovery, architecture, security/privacy, provider, migration, Render, traceability, RAG reference comparison, debugging guide, widget TTS player guide, verification documentation, screenshots, and browser results.
* `render.yaml` — Python-only Render service definition.

## Requirements

* Python 3.12.x
* A Supabase project and provider credentials for production
* No Node.js, npm, npx, TypeScript, or frontend build step is required.

## Local setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 10000
```

Open `http://localhost:10000/admin`. Liveness is `http://localhost:10000/health`; readiness is `http://localhost:10000/ready`; OpenAPI is `/docs`. The local adapter uses SQLite and `data/`, which is ignored by Git. By default the data providers use `auto`: when both `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are configured, Orbit selects Supabase for database, private object storage, and vector search. Without both credentials, it uses local SQLite/filesystem storage. Set an explicit local provider trio to opt out of Supabase.

## Environment configuration

`.env.example` is the complete non-secret variable contract. Copy it to `.env` for local work and replace blank values only on your machine. Never commit `.env`, `orbit-python-final.env`, provider keys, or the Supabase service-role key. Render secrets belong in Render Environment Variables.

Router and answer LLM roles are configured independently through `ROUTER_*` and `ANSWER_*`. LLM provider/model changes do not require re-embedding. Embedding provider, model, preprocessing, or dimension changes require a complete tenant-scoped reindex and a matching vector migration. See `docs/PROVIDER_CONFIGURATION.md`.

## Widget text-to-speech

The visitor widget has no live microphone or continuous voice-conversation mode. When TTS is configured, each assistant reply has a speaker action beside Copy. Clicking it shows a loading state until provider audio is ready, then a waveform, elapsed/total time, progress, pause/resume, and stop controls. The player calls the provider-neutral `/v1/tts` API, so Deepgram, AssemblyAI, OpenAI-compatible services, and registered custom TTS adapters share the same interface. See `docs/WIDGET_TTS_PLAYER.md` and `docs/SPEECH_CONFIGURATION.md`. The standalone `/v1/stt` endpoint remains for external integrations.

## Supabase migrations

Apply in order:

1. `migrations/0001_orbit_base.sql`
2. `migrations/0002_vector_768.sql`
3. `migrations/0003_admin_dashboard.sql`
4. `migrations/0004_orbit_runtime_security.sql`

The vector migration is additive. It does not cast, mutate, or drop the legacy Orbit `vector(128)` data. The dashboard migration adds server-side admin session/settings tables with no browser or tenant access. The runtime-security migration restricts vector search RPC execution to the server role, completes missing tenant policies, keeps the knowledge bucket private, and records a readiness marker. Re-embed source documents from private storage, validate counts/retrieval/tenant isolation, then cut over to the 768-dimensional fingerprint. See `docs/SUPABASE_MIGRATION_AND_REINDEX.md`.

By default, `DATABASE_PROVIDER`, `STORAGE_PROVIDER`, and `VECTOR_PROVIDER` are `auto`. Set only `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` on the server after applying all four migrations; Orbit will select Supabase for database, storage, and vector search. If older Render variables explicitly set the provider trio to `sqlite` / `local` / `sqlite`, remove those overrides or set all three to `auto`.
See `docs/ORBIT_UPDATE_VERIFICATION_2026-11-06.md` for the exact changes, test results, environment limitations, and deployment checklist.

## Admin dashboard

The dashboard is served by FastAPI and requires no Node build. Visit `/admin/login` and submit `ADMIN_API_KEY`. Successful login creates an expiring HttpOnly, SameSite session with CSRF protection; the key is not stored in localStorage. The dashboard includes Overview, Clients, Conversations, Knowledge base, Leads, Analytics, AI providers, System settings, Activity log, and Documentation. Destructive actions require confirmation, metrics come from persisted records, provider secrets remain server-side, and unavailable metrics are shown as unavailable.

For the optional real-browser check, install `requirements-dev.txt` and Chromium, then run:

```powershell
pip install -r requirements-dev.txt
python -m playwright install chromium
python scripts/dashboard_browser_check.py
```

## RAG-2.0 behavior and diagnostics

The pipeline follows the supplied RAG-2.0-v2 behavior: four route categories, history-aware clarification recovery, tenant-specific assistant identity, tenant-filtered retrieval, evidence evaluation, grounded answer generation, one correction/re-verification cycle, citation filtering, and safe fallback. See `docs/RAG_REFERENCE_COMPARISON.md` for the component-by-component comparison.

For local end-to-end diagnosis, enable `ORBIT_TRACE_DEBUG=1`. Traces are written as rotated JSONL records under `data/logs/orbit-trace.jsonl` by default and are excluded from version control. Content logging remains disabled unless explicitly enabled outside production. See `docs/RAG_DEBUGGING_GUIDE.md` for exact regression questions and expected stage order.

## Verification

```powershell
python -m compileall -q app tests scripts
ruff check app tests scripts
pytest -q
python scripts/verify.py
python scripts/dashboard_browser_check.py  # optional Chromium UI/API verification
```

The final evidence is recorded in `docs/FINAL_VERIFICATION_REPORT.md` with explicit PASS, FAIL, and NOT RUN classifications. `docs/DASHBOARD_BROWSER_RESULTS.json` and `docs/screenshots/` contain the latest local Chromium evidence. Live provider, Supabase staging, and deployed browser checks require external credentials and are not substituted with claims from offline tests.

## GitHub

Create a new private or public GitHub repository, review the tree and secret scan, then run:

```powershell
git init
git add .
git status
git commit -m "feat: rebuild Orbit AI in Python"
git branch -M main
git remote add origin https://github.com/<org-or-user>/<repo>.git
git push -u origin main
```

Do not use the supplied source archives or local environment files as GitHub project inputs. The `.gitignore` excludes secrets, local databases, uploads, virtual environments, caches, bytecode, and logs.

## Render deployment

Create a Render Python web service from the GitHub repository. `render.yaml` uses:

```text
Build: pip install -r requirements.txt
Start: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Health: /health
```

Set all production secrets and provider settings in Render Environment Variables. Apply Supabase migrations before enabling production traffic. Render's injected `PORT` takes precedence; production state must remain in Supabase rather than the ephemeral local filesystem. No deployment is claimed by this repository until an authorized deployment is actually verified.
