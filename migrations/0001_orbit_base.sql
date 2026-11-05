-- Orbit AI base schema. Apply before 0002_vector_768.sql.
create extension if not exists pgcrypto;
create extension if not exists vector;

insert into storage.buckets (id, name, public)
values ('knowledge', 'knowledge', false)
on conflict (id) do update set public = false;

create table if not exists public.clients (
  id uuid primary key default gen_random_uuid(), name text not null, slug text not null unique,
  enabled boolean not null default true, config jsonb not null default '{}'::jsonb,
  prompt text not null, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.api_keys (
  id uuid primary key default gen_random_uuid(), client_id uuid not null unique references public.clients(id) on delete cascade,
  key_hash text not null unique, enabled boolean not null default true, created_at timestamptz not null default now()
);
create table if not exists public.domains (client_id uuid not null references public.clients(id) on delete cascade, domain text not null, primary key(client_id, domain));
create table if not exists public.prompt_versions (id uuid primary key default gen_random_uuid(), client_id uuid not null references public.clients(id) on delete cascade, prompt text not null, created_at timestamptz not null default now());
create table if not exists public.conversations (id uuid primary key default gen_random_uuid(), client_id uuid not null references public.clients(id) on delete cascade, title text not null default 'New conversation', created_at timestamptz not null default now(), updated_at timestamptz not null default now());
create table if not exists public.messages (id bigint generated always as identity primary key, conversation_id uuid not null references public.conversations(id) on delete cascade, role text not null check(role in ('user','assistant')), content text not null, citations jsonb not null default '[]'::jsonb, route text, evidence_status text, created_at timestamptz not null default now());
create table if not exists public.leads (id uuid primary key default gen_random_uuid(), client_id uuid not null references public.clients(id) on delete cascade, conversation_id uuid references public.conversations(id) on delete set null, idempotency_key text, data jsonb not null default '{}'::jsonb, status text not null default 'new', assignee text, notes text not null default '', created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique(client_id, idempotency_key));
create table if not exists public.usage_logs (id uuid primary key default gen_random_uuid(), client_id uuid not null references public.clients(id) on delete cascade, kind text not null, latency_ms double precision not null, created_at timestamptz not null default now());
create table if not exists public.audit_logs (id uuid primary key default gen_random_uuid(), client_id uuid references public.clients(id) on delete set null, action text not null, detail jsonb not null default '{}'::jsonb, created_at timestamptz not null default now());
create table if not exists public.knowledge_files (id uuid primary key default gen_random_uuid(), client_id uuid not null references public.clients(id) on delete cascade, filename text not null, content_hash text not null, size bigint not null, status text not null, error text, updated_at timestamptz not null default now(), unique(client_id, filename));
create table if not exists public.knowledge_chunks (
  id uuid primary key default gen_random_uuid(), client_id uuid not null references public.clients(id) on delete cascade,
  file_id uuid not null references public.knowledge_files(id) on delete cascade, chunk_index integer not null,
  content text not null, source_filename text not null, page integer, title text,
  embedding_fingerprint text not null, created_at timestamptz not null default now()
);
create table if not exists public.notifications (
  id uuid primary key default gen_random_uuid(), client_id uuid references public.clients(id) on delete cascade,
  idempotency_key text unique, recipient text, subject text not null, payload jsonb not null default '{}'::jsonb,
  status text not null default 'pending' check(status in ('pending','processing','sent','failed','dead_letter')),
  attempts integer not null default 0, lease_until timestamptz, last_error text, created_at timestamptz not null default now()
);
create index if not exists conversations_client_updated on public.conversations(client_id, updated_at desc);
create index if not exists messages_conversation_created on public.messages(conversation_id, created_at);
create index if not exists chunks_client_file on public.knowledge_chunks(client_id, file_id);

create or replace function public.app_tenant_id() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claims', true)::jsonb ->> 'tenant_id', '')::uuid
$$;

alter table public.clients enable row level security;
alter table public.api_keys enable row level security;
alter table public.domains enable row level security;
alter table public.prompt_versions enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.leads enable row level security;
alter table public.usage_logs enable row level security;
alter table public.audit_logs enable row level security;
alter table public.knowledge_files enable row level security;
alter table public.knowledge_chunks enable row level security;
alter table public.notifications enable row level security;

do $$ begin
  create policy clients_tenant on public.clients for all using (id = public.app_tenant_id()) with check (id = public.app_tenant_id());
exception when duplicate_object then null; end $$;
do $$ begin
  create policy keys_tenant on public.api_keys for all using (client_id = public.app_tenant_id()) with check (client_id = public.app_tenant_id());
exception when duplicate_object then null; end $$;
do $$ begin
  create policy domains_tenant on public.domains for all using (client_id = public.app_tenant_id()) with check (client_id = public.app_tenant_id());
exception when duplicate_object then null; end $$;
do $$ begin
  create policy prompts_tenant on public.prompt_versions for all using (client_id = public.app_tenant_id()) with check (client_id = public.app_tenant_id());
exception when duplicate_object then null; end $$;
do $$ begin
  create policy conversations_tenant on public.conversations for all using (client_id = public.app_tenant_id()) with check (client_id = public.app_tenant_id());
exception when duplicate_object then null; end $$;
do $$ begin
  create policy messages_tenant on public.messages for all using (exists(select 1 from public.conversations c where c.id = conversation_id and c.client_id = public.app_tenant_id())) with check (exists(select 1 from public.conversations c where c.id = conversation_id and c.client_id = public.app_tenant_id()));
exception when duplicate_object then null; end $$;
do $$ begin
  create policy leads_tenant on public.leads for all using (client_id = public.app_tenant_id()) with check (client_id = public.app_tenant_id());
exception when duplicate_object then null; end $$;
do $$ begin
  create policy files_tenant on public.knowledge_files for all using (client_id = public.app_tenant_id()) with check (client_id = public.app_tenant_id());
exception when duplicate_object then null; end $$;
do $$ begin
  create policy chunks_tenant on public.knowledge_chunks for all using (client_id = public.app_tenant_id()) with check (client_id = public.app_tenant_id());
exception when duplicate_object then null; end $$;
