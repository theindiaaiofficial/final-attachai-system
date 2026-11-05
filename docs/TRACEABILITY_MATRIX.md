# Route and feature traceability

| Orbit feature/route family | Python implementation | Status |
|---|---|---|
| `/health`, `/ready`, `/metrics` | `app/main.py` | Implemented |
| `/v1/config` | `public_config` | Implemented |
| `/v1/chat`, `/v1/chat/stream` | `public_chat`, `ChatPipeline` | Implemented |
| `/v1/leads` | `public_lead`, idempotent repository | Implemented |
| Admin auth/overview | `admin_context`, routes | Implemented |
| Client CRUD/domain/key lifecycle | admin routes/repository | Implemented |
| Prompt history/reset | admin routes/repository | Implemented |
| Knowledge upload/list/delete/rebuild | `KnowledgeService`, admin routes | Implemented; rebuild is queued contract |
| Sessions list/detail/delete | repository and session routes | Implemented |
| Leads workflow/export | admin routes/repository | Implemented |
| Analytics | repository/admin route | Implemented |
| Provider/system display | admin routes | Implemented |
| Supabase durable staging | SQL and adapter boundary | Blocked pending isolated project |
| Live provider/Render/browser E2E | external systems | Blocked; no credentials/deployment supplied |
