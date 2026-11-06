# Supabase migration and reindex

1. Back up the Supabase project and verify the backup before changing production traffic.
   If this project already has migrations 0001-0003 applied, apply only the new
   `migrations/0004_orbit_runtime_security.sql`; do not replay old migration files.
2. Apply `migrations/0001_orbit_base.sql` when setting up a fresh project.
3. Apply `migrations/0002_vector_768.sql`. It creates a new 768-dimensional table/RPC and does not mutate the legacy 128-dimensional table.
4. Apply `migrations/0003_admin_dashboard.sql` for admin sessions/settings.
5. Apply `migrations/0004_orbit_runtime_security.sql` to lock the vector RPC to the server service role and complete grants/policies.
6. Re-embed each source from its private storage object using the active provider/model/dimension fingerprint. Never cast legacy vectors.
7. Build a staged tenant index, compare source/chunk counts, sample retrieval, citation metadata, and tenant isolation, then switch the serving fingerprint.
8. Reconcile orphaned objects, vectors, and manifests before marking a rebuild complete.

Rollback means switching the serving fingerprint back to the previously validated 768-dimensional version (or the legacy application only if it still supports the old schema); do not write 768 vectors into the 128 table. Keep the old data until backup, re-embedding, validation, and cutover are complete.


## Runtime connection

## Runtime connection (Render or another server)

After all four SQL files finish successfully, set these server-side environment
variables:

```text
SUPABASE_URL=https://<your-project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<the project's service-role secret>
SUPABASE_STORAGE_BUCKET=knowledge
```

`SUPABASE_STORAGE_BUCKET` is optional when using the default private `knowledge`
bucket created by the migrations. `DATABASE_PROVIDER`, `STORAGE_PROVIDER`, and
`VECTOR_PROVIDER` default to `auto`, so no provider flags are required: when both
Supabase credentials are present, Orbit selects Supabase for database, private
object storage, and vector search. When both are absent, local SQLite/filesystem
mode is selected. A partial credential pair is a configuration error, not a
reason to fall back silently.

**Important for an existing Render service:** older deployments may already have
explicit `DATABASE_PROVIDER=sqlite`, `STORAGE_PROVIDER=local`, and
`VECTOR_PROVIDER=sqlite` variables. Remove those three overrides or change all
three to `auto`; explicit local settings intentionally keep Orbit local even if
Supabase credentials are also present.

Keep the service-role key only in the server environment. Never place it in
widget JavaScript, HTML, browser settings, or public client configuration.

The `/ready` endpoint re-probes the required database tables, migration-0004
marker, and private storage bucket each time it is called. It reports
`data_providers` and `backend_health`. Missing migrations, a missing bucket,
invalid credentials, or connectivity failures return `503`; it does not silently
fall back to SQLite. A successful response should contain:

```json
{
  "status": "ready",
  "data_providers": {
    "database": "supabase",
    "storage": "supabase",
    "vector": "supabase"
  }
}
```

The example omits the `backend_health` details for readability; the live response
includes those checks. Embedding and LLM provider credentials are separate from
Supabase and must also be configured for full application readiness.
