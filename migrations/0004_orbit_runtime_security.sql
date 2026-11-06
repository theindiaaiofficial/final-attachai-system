-- Orbit runtime hardening and service-role access contract.
-- Apply after 0001_orbit_base.sql, 0002_vector_768.sql, and 0003_admin_dashboard.sql.

-- Record that the runtime hardening migration was applied. The readiness probe
-- checks this marker so a deployment cannot report healthy with only part of the
-- required Supabase schema installed.
create table if not exists public.orbit_schema_migrations (
  version integer primary key,
  applied_at timestamptz not null default now()
);
alter table public.orbit_schema_migrations enable row level security;
revoke all on public.orbit_schema_migrations from PUBLIC, anon, authenticated;
insert into public.orbit_schema_migrations (version) values (4)
on conflict (version) do nothing;

-- The vector RPC is SECURITY DEFINER. It must never be callable by browser roles,
-- because callers could otherwise supply another tenant's UUID. Orbit calls it
-- only from the server with the Supabase service-role credential.
revoke all on function public.match_knowledge_vectors_v2(
  vector(768), uuid, text, double precision, integer
) from PUBLIC;
revoke all on function public.match_knowledge_vectors_v2(
  vector(768), uuid, text, double precision, integer
) from anon, authenticated;
grant execute on function public.match_knowledge_vectors_v2(
  vector(768), uuid, text, double precision, integer
) to service_role;

-- Ensure the service role can use the application schema, tables, and identity
-- sequences used by PostgREST inserts. Browser roles are intentionally not granted
-- broad table access; RLS remains enabled on tenant and admin tables.
grant usage on schema public to service_role;
grant all privileges on all tables in schema public to service_role;
grant all privileges on all sequences in schema public to service_role;

-- Complete tenant policies for tables which were RLS-enabled in the base schema
-- but did not yet have a tenant policy. The service role bypasses RLS; these
-- policies are for any future tenant-scoped JWT access.
do $$ begin
  create policy usage_tenant on public.usage_logs for all
    using (client_id = public.app_tenant_id())
    with check (client_id = public.app_tenant_id());
exception when duplicate_object then null; end $$;

do $$ begin
  create policy audit_tenant on public.audit_logs for all
    using (client_id = public.app_tenant_id())
    with check (client_id = public.app_tenant_id());
exception when duplicate_object then null; end $$;

do $$ begin
  create policy notifications_tenant on public.notifications for all
    using (client_id = public.app_tenant_id())
    with check (client_id = public.app_tenant_id());
exception when duplicate_object then null; end $$;

-- Keep the knowledge bucket private; reads/writes happen through the server
-- storage adapter using the service-role credential.
insert into storage.buckets (id, name, public)
values ('knowledge', 'knowledge', false)
on conflict (id) do update set public = false;
