-- Additive dashboard state. Service role only: no direct browser or tenant access.
create table if not exists public.admin_sessions (
  token_hash text primary key,
  csrf_token text not null,
  credential_hash text not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);
create index if not exists admin_sessions_expiry on public.admin_sessions(expires_at);
alter table public.admin_sessions enable row level security;
revoke all on public.admin_sessions from anon, authenticated;

create table if not exists public.admin_settings (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);
alter table public.admin_settings enable row level security;
revoke all on public.admin_settings from anon, authenticated;
