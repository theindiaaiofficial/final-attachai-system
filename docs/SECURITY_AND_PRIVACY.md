# Security and privacy

* Admin endpoints require `X-Admin-API-Key` with constant-time comparison.
* Public endpoints require a hashed tenant API key and exact normalized Origin. Missing Origin is rejected.
* Tenant IDs and session IDs are never accepted as proof of authorization; repository methods always include authenticated tenant scope.
* Raw API keys are returned only on creation/rotation and only SHA-256 digests are stored.
* Secrets remain server-side. Browser config exposes presentation fields only.
* Model/retrieved content is logged only through route/tenant/request metadata; raw prompts and chunks are not logged by the pipeline.
* Uploaded documents are untrusted reference data. Prompts tell model roles not to execute document instructions.
* CSV export prefixes formula-like values with an apostrophe.
* Configured LLM and embedding providers may receive prompts, bounded history, retrieved text, and document text. The service does not claim local-only processing.

Supabase service-role access bypasses RLS, so application tenant filters remain mandatory. RLS policies in the migrations provide defense in depth for direct authenticated access.
