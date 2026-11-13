-- 조문 잇기: 조회용 stage 컬럼·뷰, 버린 job을 DB에, 시행령→시행규칙 위임, parent_ref를 조문으로 푼 결과.

alter table fact add column stage text generated always as (payload->>'stage') stored;

-- 현행 조문의 verified 추출 결과를 열로 편 것. 사람과 SQL이 바로 읽는 용도 (payload가 원본).
create view extract_fact as
select f.id, f.provision_id, f.text_hash, d.law_id, d.law_name, p.article_key,
       f.payload->>'role' as role,
       f.payload->>'benefit_type' as benefit_type,
       f.payload->>'beneficiary' as beneficiary,
       f.payload->>'trigger' as trigger,
       f.payload->>'parent_ref' as parent_ref,
       (f.payload->'benefit_size'->>'rate')::numeric as rate,
       (f.payload->'benefit_size'->>'cap_krw')::bigint as cap_krw,
       f.payload->'benefit_size'->>'raw' as size_raw,
       (f.payload->'time_window'->>'sunset')::date as sunset,
       jsonb_array_length(coalesce(f.payload->'uncertain', '[]'::jsonb)) as n_uncertain,
       f.carried_from, f.extractor, f.payload
from fact f
join provision p on p.id = f.provision_id and p.text_hash = f.text_hash
join source_document d on d.id = p.document_id
where f.stage = 'extract' and f.status = 'verified' and p.effective_to is null;

-- 재시도까지 실패한 job. 같은 (단계, 대상, 본문 해시)는 다시 내보내지 않는다. 본문이 바뀌면 다시 나간다.
create table dropped_job (
  stage      text not null,
  target_id  bigint not null,             -- provision.id / program_version.id / fact.id (단계에 따라)
  text_hash  text not null,
  reasons    jsonb not null default '[]',
  dropped_at timestamptz not null default now(),
  primary key (stage, target_id, text_hash)
);

-- 위임 문구 하나가 대상 여러 개를 가질 수 있다 (정확히 같은 항을 가리키는 하위 조문이 여럿일 때)
create unique index delegation_source_phrase_target on delegation (source_id, phrase, coalesce(target_id, 0));

-- 추출 fact의 parent_ref("법 제29조의4제1항", "영 제10조", "제2항")를 현행 조문으로 푼 것
create table fact_link (
  id         bigserial primary key,
  fact_id    bigint not null references fact(id),
  target_id  bigint not null references provision(id),
  ref        text not null,
  created_at timestamptz not null default now(),
  unique (fact_id, target_id)
);
