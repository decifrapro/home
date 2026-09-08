-- ─────────────────────────────────────────────────────────────────────────────
-- Decifra Pro — estrutura no Supabase
--
-- Pode rodar no mesmo projeto Supabase de outro sistema: tudo aqui começa com
-- "decifra_" e os arquivos ficam num balde separado, chamado "decifra".
--
-- Como rodar: painel do Supabase → SQL Editor → cole este arquivo → Run.
-- Rodar duas vezes não faz mal (tudo é "se não existir").
-- ─────────────────────────────────────────────────────────────────────────────

-- Atendimentos
create table if not exists public.decifra_jobs (
  id                  text primary key,
  status              text not null default 'created',
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  original_filename   text,
  zip_size            bigint not null default 0,
  zip_path            text,
  error               text,
  warnings            jsonb not null default '[]'::jsonb,
  inventory           jsonb not null default '{}'::jsonb,
  coverage            jsonb not null default '{}'::jsonb,
  estimate            jsonb,
  cost                jsonb not null default '{}'::jsonb,
  confirmed           boolean not null default false,
  conversation_start  timestamptz,
  conversation_end    timestamptz,
  event_count         integer not null default 0,
  metadata            jsonb not null default '{}'::jsonb,
  schema_version      integer not null default 2
);

create index if not exists decifra_jobs_created_idx on public.decifra_jobs (created_at desc);
create index if not exists decifra_jobs_status_idx on public.decifra_jobs (status);

-- Eventos da conversa, na ordem original
create table if not exists public.decifra_events (
  id                 text primary key,
  job_id             text not null references public.decifra_jobs (id) on delete cascade,
  idx                integer not null,
  raw_timestamp      text not null,
  timestamp          timestamptz,
  sender             text,
  type               text not null,
  raw_text           text not null default '',
  caption            text,
  attachment_name    text,
  attachment_path    text,
  detected_mime      text,
  processed_text     text,
  processing_status  text not null default 'pending',
  processing_error   text,
  leased_until       timestamptz,
  metadata           jsonb not null default '{}'::jsonb
);

create index if not exists decifra_events_job_idx on public.decifra_events (job_id, idx);
create index if not exists decifra_events_pendentes_idx
  on public.decifra_events (job_id, processing_status);

-- Links citados nas mensagens
create table if not exists public.decifra_links (
  id            text primary key,
  job_id        text not null references public.decifra_jobs (id) on delete cascade,
  event_id      text not null,
  url           text not null,
  status        text not null default 'pending',
  title         text,
  description   text,
  content       text,
  error         text,
  leased_until  timestamptz,
  metadata      jsonb not null default '{}'::jsonb
);

create index if not exists decifra_links_job_idx on public.decifra_links (job_id);

-- Arquivos encontrados dentro do ZIP
create table if not exists public.decifra_files (
  job_id            text not null references public.decifra_jobs (id) on delete cascade,
  relative_path     text not null,
  name              text not null,
  original_path     text not null default '',
  original_name     text not null default '',
  size              bigint not null default 0,
  detected_mime     text,
  extension_mime    text,
  mime_mismatch     boolean not null default false,
  matched_event_id  text,
  primary key (job_id, relative_path)
);

-- Segurança: ninguém acessa direto pelo navegador.
-- Sem política liberando, só a chave de serviço (que fica no servidor) enxerga.
alter table public.decifra_jobs   enable row level security;
alter table public.decifra_events enable row level security;
alter table public.decifra_links  enable row level security;
alter table public.decifra_files  enable row level security;

-- Balde privado para os ZIPs e as mídias
insert into storage.buckets (id, name, public)
values ('decifra', 'decifra', false)
on conflict (id) do nothing;
