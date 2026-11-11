-- 지원사업·장학금·창업 공고 (법령 밖의 혜택). 조문(provision)과 따로 두고, 배치·검증 흐름만 같이 쓴다.

create table program (
  id            bigserial primary key,
  source        text not null,          -- gov24 (보조금24/정부24 공공서비스) / kstartup
  external_id   text not null,          -- 소스의 ID (서비스ID, 공고일련번호)
  title         text not null,
  agency        text,
  category      text,
  url           text,
  apply_start   date,
  apply_end     date,                   -- null = 상시 또는 원문에서 못 읽음
  first_seen    timestamptz not null default now(),
  last_seen     timestamptz not null default now(),
  unique (source, external_id)
);

create table program_version (
  id            bigserial primary key,
  program_id    bigint not null references program(id),
  text          text not null,          -- 필드를 "이름: 값" 줄로 이은 정규화 본문. 인용 검증 기준
  text_hash     text not null,
  file_path     text not null,          -- 이 판을 받은 원본 응답 페이지
  sha256        text not null,
  fetched_at    timestamptz not null default now(),
  superseded_at timestamptz,            -- 본문이 바뀌면 채움 (null = 현행)
  unique (program_id, text_hash)
);

create table program_fact (
  id            bigserial primary key,
  version_id    bigint not null references program_version(id),
  batch_id      bigint not null references batch(id),
  payload       jsonb not null,
  status        text not null default 'verified',  -- verified / rejected / stale
  extractor     text not null,
  created_at    timestamptz not null default now(),
  unique (version_id, extractor)
);

alter table batch drop constraint batch_stage_check;
alter table batch add constraint batch_stage_check
  check (stage in ('classify', 'extract', 'program', 'synthesize', 'report'));

-- 공고가 적은 근거 법령을 이미 모은 법령과 이름으로 잇는다 (가장 긴 법령명 하나). law_id가 null이면 아직 안 모은 법령.
create view program_law_basis as
select pf.id as fact_id, pv.program_id, b.basis, d.law_id, d.law_name
from program_fact pf
join program_version pv on pv.id = pf.version_id
cross join lateral jsonb_array_elements_text(coalesce(pf.payload->'legal_basis', '[]'::jsonb)) as b(basis)
left join lateral (
  select sd.law_id, sd.law_name from source_document sd
  where position(sd.law_name in b.basis) > 0
  order by length(sd.law_name) desc, sd.effective desc limit 1
) d on true
where pf.status = 'verified';
