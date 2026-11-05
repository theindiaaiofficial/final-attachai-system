# Rebuild discovery

## Supplied inputs inspected

* `orbit-ai-main.zip`: TypeScript/Fastify API, React/Vite dashboard, widget, SQLite/Supabase repositories, legacy `vector(128)` migration, public/admin route handlers and tests.
* `RAG-2.0-v2.zip`: Python/FastAPI reference pipeline, router fast paths, bounded memory, parsers/chunker, retrieval, evidence evaluation, answer generation, grounding verification and correction fallback.
* `orbit-python-final.env`: Render/Supabase/Groq/Gemini target configuration.

The archives were extracted for source inspection only; no archive scripts were executed.

## Key findings

1. Orbit's public tenant identity is API-key plus exact allowed Origin. Client IDs are not credentials.
2. Orbit has client CRUD, domains, key lifecycle, prompts, knowledge, leads, analytics, settings and streaming contracts.
3. Orbit's original migration uses `knowledge_vectors.embedding vector(128)` while the target env requires 768-dimensional Gemini embeddings. The rebuilt SQL uses additive `knowledge_vectors_v2` and a dimension-specific RPC.
4. RAG-2.0's general branch must bypass embeddings/retrieval. Business and mixed branches require evidence and grounding. Unverified business claims fall back to evidence-limited text.
5. The old Node build is not used by the rebuilt runtime.

## Decisions

* `ChatPipeline` is the only public chat orchestrator.
* SQLite is a durable local/test adapter; production Supabase migration and adapter boundaries are supplied separately.
* Secrets are represented as `SecretStr` and never returned by safe config routes.
* Browser content uses `textContent`; the widget does not inject model text as HTML.
