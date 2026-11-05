-- Additive migration from Orbit's legacy knowledge_vectors vector(128).
-- Do not alter, cast, or drop the legacy table. Re-embed source objects before cutover.
create table if not exists public.knowledge_vectors_v2 (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references public.clients(id) on delete cascade,
  file_id uuid references public.knowledge_files(id) on delete cascade,
  chunk_index integer not null,
  content text not null,
  embedding vector(768) not null,
  source_filename text not null,
  page integer,
  title text,
  embedding_provider text not null,
  embedding_model text not null,
  embedding_dimension integer not null check (embedding_dimension = 768),
  embedding_fingerprint text not null,
  created_at timestamptz not null default now(),
  unique(client_id, file_id, chunk_index, embedding_fingerprint)
);
create index if not exists knowledge_vectors_v2_client_idx on public.knowledge_vectors_v2(client_id, file_id);
create index if not exists knowledge_vectors_v2_embedding_idx on public.knowledge_vectors_v2 using hnsw (embedding vector_cosine_ops);
alter table public.knowledge_vectors_v2 enable row level security;
do $$ begin
  create policy vectors_v2_tenant on public.knowledge_vectors_v2 for all using (client_id = public.app_tenant_id()) with check (client_id = public.app_tenant_id());
exception when duplicate_object then null; end $$;

create or replace function public.match_knowledge_vectors_v2(
  query_embedding vector(768), match_client_id uuid, match_fingerprint text, match_threshold float, match_count int
) returns table(id uuid, content text, source_filename text, page integer, title text, similarity float)
language sql stable security definer set search_path = public as $$
  select v.id, v.content, v.source_filename, v.page, v.title,
         1 - (v.embedding <=> query_embedding) as similarity
  from public.knowledge_vectors_v2 v
  where v.client_id = match_client_id and v.embedding_fingerprint = match_fingerprint
    and 1 - (v.embedding <=> query_embedding) >= match_threshold
  order by v.embedding <=> query_embedding limit match_count;
$$;
