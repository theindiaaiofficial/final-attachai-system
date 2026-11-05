# Supabase migration and reindex

1. Back up the Supabase project and verify the backup before changing production traffic.
2. Apply `migrations/0001_orbit_base.sql`.
3. Apply `migrations/0002_vector_768.sql`. It creates a new 768-dimensional table/RPC and does not mutate the legacy 128-dimensional table.
4. Re-embed each source from its private storage object using the active provider/model/dimension fingerprint. Never cast legacy vectors.
5. Build a staged tenant index, compare source/chunk counts, sample retrieval, citation metadata, and tenant isolation, then switch the serving fingerprint.
6. Reconcile orphaned objects, vectors, and manifests before marking a rebuild complete.

Rollback means switching the serving fingerprint back to the previously validated 768-dimensional version (or the legacy application only if it still supports the old schema); do not write 768 vectors into the 128 table. Keep the old data until backup, re-embedding, validation, and cutover are complete.
