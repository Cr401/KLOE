-- 추출 감사(kloe-audit)와 아이디어(kloe-ideate) 단계. 감사 결과는 fact를 고치지 않고 따로 둔다.
alter table batch drop constraint batch_stage_check;
alter table batch add constraint batch_stage_check
  check (stage in ('classify', 'extract', 'program', 'audit', 'ideate', 'synthesize', 'report'));

create table audit (
  id          bigserial primary key,
  fact_id     bigint not null references fact(id),
  batch_id    bigint not null references batch(id),
  ok          boolean not null,
  payload     jsonb not null,           -- {"ok", "issues": [{field, direction, problem, quote, suggested}]}
  extractor   text not null,
  created_at  timestamptz not null default now(),
  unique (fact_id, extractor)
);
