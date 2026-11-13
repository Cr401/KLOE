-- 법령 개정판이 들어와도 본문이 같은 조문의 결과(fact)를 새 조문으로 이어받는다 (개선안 A1).
-- carried_from: 복사해 온 원래 fact. null이면 그 조문에서 직접 뽑은 것.
alter table fact add column carried_from bigint references fact(id);
