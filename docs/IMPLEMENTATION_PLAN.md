# Implementation plan and status

| Area | Status | Evidence |
|---|---|---|
| Python/FastAPI composition root | Implemented | `app/main.py`, `render.yaml` |
| Settings/env contract | Implemented | `app/config.py`, `.env.example` |
| Tenant/API-key/origin security | Implemented | `app/security/auth.py`, public dependency |
| RAG-2.0 router and branches | Implemented | `app/rag/router.py`, `app/rag/pipeline.py` |
| Evidence/grounding/correction/citations | Implemented | `app/rag/evidence.py`, `grounding.py`, `pipeline.py` |
| Tenant-scoped conversations | Implemented | `app/repositories/sqlite.py`, public/admin routes |
| Knowledge parse/chunk/embed/index | Implemented | `app/knowledge/`, `app/rag/retrieval.py` |
| Admin/client/lead/analytics contracts | Implemented | `app/main.py` |
| Widget/admin served by Python | Implemented | `app/main.py` |
| Additive 128 to 768 migration | Implemented/documented | `migrations/0001_*.sql`, `0002_*.sql` |
| Supabase staging/live validation | Blocked | No Supabase project credentials supplied |
| Live provider validation | Blocked | No valid provider credentials supplied |
| Browser E2E against deployed Render/Supabase | Blocked | No deployment authorized or supplied |
