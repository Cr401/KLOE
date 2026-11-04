create table source_document (
  id            bigserial primary key,
  law_id        text not null,
  law_name      text not null,
  law_kind      text not null,          -- 법률 / 대통령령 / 총리령·부령 / 고시 / 조례
  version_key   text not null,
  promulgated   date,
  effective     date not null,
  url           text not null,
  file_path     text not null,
  sha256        text not null,
  fetched_at    timestamptz not null default now(),
  unique (law_id, version_key)
);

create table provision (
  id             bigserial primary key,
  document_id    bigint not null references source_document(id),
  article_key    text not null,         -- '16', '16-1-3' (조-항-호)
  heading        text,
  text           text not null,
  text_hash      text not null,
  effective_from date not null,
  effective_to   date,
  unique (document_id, article_key)
);

create table delegation (
  id          bigserial primary key,
  source_id   bigint not null references provision(id),
  target_id   bigint references provision(id),            -- null이면 G3 후보
  phrase      text not null,
  method      text not null check (method in ('regex', 'llm', 'manual'))
);

create table batch (
  id           bigserial primary key,
  stage        text not null check (stage in ('classify', 'extract', 'synthesize', 'report')),
  file_name    text not null unique,
  status       text not null default 'queued',  -- queued / claimed / ingested / failed
  extractor    text,                            -- 결과 파일에서 채움
  exported_at  timestamptz not null default now(),
  ingested_at  timestamptz,
  fail_reason  text
);

create table fact (
  id            bigserial primary key,
  provision_id  bigint not null references provision(id),
  text_hash     text not null,          -- 이 해시 기준으로 추출됨. 조문이 바뀌면 stale
  batch_id      bigint not null references batch(id),
  is_benefit    boolean not null,
  payload       jsonb not null,         -- 3.1 필드 전체
  status        text not null default 'extracted',  -- extracted / verified / rejected / stale
  extractor     text not null,
  created_at    timestamptz not null default now(),
  unique (provision_id, text_hash, extractor)
);

create table opportunity (
  id              bigserial primary key,
  title           text not null,
  fact_ids        bigint[] not null,
  payload         jsonb not null,       -- 3.2 필드 전체
  status          text not null default 'proposed', -- proposed / approved / rejected / needs_recheck
  superseded_by   bigint references opportunity(id),
  extractor       text not null,
  week            text not null,        -- '2026-W45'
  created_at      timestamptz not null default now()
);

create table gap (
  id              bigserial primary key,
  code            text not null,
  opportunity_ids bigint[] not null default '{}',
  provision_ids   bigint[] not null default '{}',
  summary         text not null,
  status          text not null default 'candidate',
  detected_by     text not null,        -- 'sql' 또는 extractor
  created_at      timestamptz not null default now()
);

create table idea (
  id              bigserial primary key,
  week            text not null,
  title           text not null,
  body            text not null,
  opportunity_ids bigint[] not null default '{}',
  tags            text[] not null default '{}',   -- quant / business / report-to-gov …
  created_at      timestamptz not null default now()
);

create table review (
  id          bigserial primary key,
  target_kind text not null check (target_kind in ('fact', 'opportunity', 'gap')),
  target_id   bigint not null,
  verdict     text not null check (verdict in ('approve', 'edit', 'reject')),
  note        text,
  diff        jsonb,
  reviewed_at timestamptz not null default now()
);

create table change_event (
  id              bigserial primary key,
  law_id          text not null,
  article_key     text not null,
  old_provision   bigint references provision(id),
  new_provision   bigint references provision(id),
  kind            text not null,        -- added / amended / repealed
  detected_at     timestamptz not null default now()
);
