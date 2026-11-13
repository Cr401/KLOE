-- 아이디어 단계 (kloe-ideate)와 점검 (review.md -> kloe review-ingest).
-- 설계 3.4는 idea를 L3 보고서 산출물로만 두었으나, 시스템이 근거 fact를 달아 아이디어를 가져오고 사람은 점검만 한다 (2026-11-12 결정).

alter table batch drop constraint batch_stage_check;
alter table batch add constraint batch_stage_check
  check (stage in ('classify', 'extract', 'program', 'audit', 'ideate', 'synthesize', 'report'));

alter table idea add column lens          text;
alter table idea add column summary       text;
alter table idea add column payload       jsonb;                         -- 결과 원본 (claims, to_check)
alter table idea add column evidence      jsonb not null default '[]';   -- [{"kind": "fact|program|delegation|change", "id": N}]
alter table idea add column evidence_hash text;
alter table idea add column extractor     text;
alter table idea add column batch_id      bigint references batch(id);
alter table idea add column status        text not null default 'proposed'; -- proposed / approved / rejected / needs_recheck
create unique index idea_evidence_hash on idea (evidence_hash);

-- 근거 집합이 이미 있는 아이디어와 같아서 막힌 것 (지표: 중복 차단 수)
create table idea_duplicate (
  id            bigserial primary key,
  evidence_hash text not null,
  batch_id      bigint references batch(id),
  title         text not null,
  created_at    timestamptz not null default now()
);

alter table review drop constraint review_target_kind_check;
alter table review add constraint review_target_kind_check check (target_kind in ('fact', 'opportunity', 'gap', 'idea'));
