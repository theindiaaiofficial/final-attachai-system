# Orbit AI architecture

HTTP dependencies authenticate a tenant, load trusted tenant configuration, verify the conversation belongs to that tenant, and bound history before invoking `ChatPipeline`.

```text
request -> API key + exact Origin -> tenant config/memory
        -> router (LLM 1 / narrow deterministic fast path)
        -> clarification OR general answer OR retrieval
        -> deterministic evidence coverage (no LLM request)
        -> answer generation (LLM)
        -> grounding verification (LLM)
        -> one correction + one re-verification when needed
        -> valid context citations -> tenant-scoped persistence/response
```

Standalone greetings, basic social replies, and identity questions use deterministic local responses and do not call an LLM. The general language-generation path is used only when a free-form response is actually needed. Business turns use tenant-filtered retrieval, deterministic lexical evidence coverage, one answer-generation call, and grounding verification. One correction/re-verification is retained only when the verifier reports unsupported or contradicted claims. If verification is unavailable, a draft is returned only when the deterministic evidence-coverage and answer-overlap gate passes, with valid tenant citations and matching numeric claims; otherwise the safe fallback remains. Retrieval is filtered by tenant ID and embedding fingerprint. Citation source IDs are generated only for chunks included in the assembled context and are intersected with verifier-approved IDs.

Provider adapters are isolated under `app/providers`. LLM provider/model changes do not touch indexing. Embedding changes alter the fingerprint and require reindexing.
