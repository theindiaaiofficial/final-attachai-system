# RAG-2.0-v2 reference comparison

The original `RAG-2.0-v2.zip` was extracted and compared with the current Orbit implementation on 2026-11-03. The reference project remains the behavioral source for routing, history, retrieval, evidence, grounding, correction, and citation policy.

| RAG-2.0 reference component | Current Orbit component | Difference found | Required fix / result |
|---|---|---|---|
| `app/router/intelligence_router.py` and `router/prompts.py` | `app/rag/router.py` | The current system had a shortened router prompt, no identity intent path, and no deterministic recovery for a pending business/general clarification. | Ported the reference classification rules, history guidance, named-business identity routing, Hindi/English identity fast paths, and `business`/`general` clarification recovery. |
| `RouteDecision` schema | `app/rag/router.py::RouteDecision` | Route flags were present, but the current pipeline had no way to carry the original question when a user answered a clarification with a one-word choice. | Added `resolved_query`, while preserving the four reference routes and enforced RAG/grounding invariants. |
| `app/memory/conversation_store.py` | `SQLiteRepository.history` and tenant-scoped conversation tables | Tenant scoping existed, but clarification state was inferred only by the model. | The router now inspects the preceding assistant clarification and prior user turn before invoking the provider. |
| `app/rag/retriever.py` | `app/rag/retrieval.py` | Retrieval and `[S1]` context construction were structurally aligned, but lacked trace events and reference-level timing metadata. | Preserved tenant-filtered retrieval and source labeling; added end-to-end retrieval trace events. |
| `app/generation/prompts.py` | `app/rag/generation.py` | The current general prompt inherited only the client free-form prompt, allowing generic provider identity leakage. | Added explicit tenant identity context and ported the reference general/business/correction rules. |
| `app/verification/evidence.py` | `app/rag/evidence.py` | The current evaluator prompt was much shorter and did not explicitly distinguish absence from contradiction. | Added the reference evidence-coverage task and safe parsing trace. |
| `app/verification/grounding.py` | `app/rag/grounding.py` | The current verifier prompt omitted several reference distinctions around unsupported claims and source IDs. | Added the reference grounding task, source filtering, and safe parsing trace. |
| `app/services/chat_service.py` | `app/rag/pipeline.py` | The one-correction structure existed, but identity was not resolved before generation and stages were opaque during failures. | Added tenant identity resolution, direct identity answers, resolved clarification queries, stage tracing, and preserved exactly one correction/re-verification. |
| Reference frontend `app.js` | `app/widget/static/widget.js` | The current widget was a minimal white panel with weak contrast, no session persistence, no markdown, no typing state, and no retry state. | Rebuilt the widget UI without Node/npm: Shadow DOM isolation, readable bubbles, markdown-safe rendering, citations, sessionStorage session/history, typing indicator, responsive layout, Enter/Shift+Enter, and retry. |
| Reference knowledge corpus | Existing tenant knowledge ingestion | The reference corpus is present in the supplied project/reference archive, but the application must use the tenant’s indexed records rather than a global corpus. | Business identity questions route to tenant retrieval; source citations remain tenant-scoped. The provided knowledge file is the recommended local regression fixture. |

## Behavioral conclusions

* `aap koun ho` and `what is your name` now take the general/identity path and use the tenant’s configured assistant identity without calling retrieval.
* `who is this AttachAI` takes the business path when `AttachAI` is the current tenant business name, so the answer can be grounded in tenant knowledge and cite `[S1]`, `[S2]`, and so on.
* A prior clarification followed by `business` resolves to the prior user question and proceeds through retrieval. It does not repeat the clarification.
* General turns still bypass embeddings, retrieval, evidence evaluation, and grounding.
* Business and mixed turns still require retrieval, evidence evaluation, grounding verification, citation filtering, one correction attempt, and a safe fallback if verification fails.
