"""테스트용 가짜 L1 에이전트: claimed 배치를 읽고 out 결과를 쓴다."""

import json
import re

from kloe.queue.export import read_jsonl, stage_dir

EXTRACTORS = {"classify": "cowork:test:kloe-classify@0.0", "extract": "cowork:test:kloe-extract@0.0",
              "program": "cc:test:kloe-extract-program@0.0", "audit": "cc:test:kloe-audit@0.0",
              "ideate": "cc:test:kloe-ideate@0.0"}


def fake_ideate(job: dict) -> dict:
    """렌즈 형태에 맞는 아이디어 하나 (근거가 모자라면 빈 목록). 인용은 index의 상세 fact quotes에서."""
    idx = job["index"]
    quoted = [(k, v) for k, v in idx.items() if v.get("quotes")]
    by_cluster = {}
    for k, v in quoted:
        by_cluster.setdefault(v["cluster"], (k, v))
    claims = []
    if job["lens"] == "combo":
        picks = list(by_cluster.values())[:2]
    else:
        picks = quoted[:1]
    for k, v in picks:
        kind, i = k.split(":")
        claims.append({"text": "근거", "kind": kind, "id": int(i), "quote": v["quotes"][0]})
    if job["lens"] == "gap":
        g = next((k for k in idx if k.startswith("delegation:")), None)
        if g is None:
            return {"job_id": job["job_id"], "extractor": EXTRACTORS["ideate"], "ideas": []}
        claims.append({"text": "위임 대상 없음", "kind": "delegation", "id": int(g.split(":")[1])})
    if job["lens"] == "time" or (job["lens"] == "combo" and len(picks) < 2) or not picks:
        return {"job_id": job["job_id"], "extractor": EXTRACTORS["ideate"], "ideas": []}
    return {"job_id": job["job_id"], "extractor": EXTRACTORS["ideate"],
            "ideas": [{"title": f"{job['lens']} 아이디어", "summary": "한 줄", "body": "본문", "claims": claims,
                       "to_check": ["원문 확인"]}]}


def fake_result(stage: str, job: dict) -> dict:
    if stage == "ideate":
        return fake_ideate(job)
    text = job["text"]
    benefit = "공제한다" in text
    first_sentence = text.split(". ")[0]
    if stage == "classify":
        return {"job_id": job["job_id"], "extractor": EXTRACTORS[stage], "is_benefit": benefit,
                "benefit_type": "deduction" if benefit else None,
                "quotes": [{"field": "is_benefit", "quote": first_sentence}]}
    if stage == "audit":  # 한도(…만원)가 원문에 있는데 fact에 cap이 없으면 lost로 지적
        m = re.search(r"공제한도는 [^ .]+원", text)
        if m and not (job["fact"].get("benefit_size") or {}).get("cap_krw"):
            return {"job_id": job["job_id"], "extractor": EXTRACTORS[stage], "ok": False,
                    "issues": [{"field": "benefit_size.cap_krw", "direction": "lost", "problem": "한도가 빠짐",
                                "quote": m.group(0)}]}
        return {"job_id": job["job_id"], "extractor": EXTRACTORS[stage], "ok": True, "issues": []}
    if stage == "program":
        first_line = text.splitlines()[0]
        basis = [b for line in re.findall(r"^근거법령: (.+)$", text, flags=re.M) for b in line.split("||")]
        return {"job_id": job["job_id"], "extractor": EXTRACTORS[stage],
                "fact": {"is_benefit": True, "benefit_type": "subsidy", "legal_basis": basis,
                         "quotes": [{"field": "summary", "quote": first_line}]}}
    m = re.search(r"100분의 (\d+)", text)
    fact = {"is_benefit": benefit, "role": "benefit" if benefit else "none", "benefit_type": "deduction" if benefit else None,
            "not_benefit_reason": None if benefit else "혜택 아님",
            "quotes": [{"field": "trigger", "quote": first_sentence}]}
    if m:
        fact["benefit_size"] = {"raw": m.group(0), "rate": int(m.group(1)) / 100}
        fact["quotes"].append({"field": "benefit_size.rate", "quote": m.group(0)})
    return {"job_id": job["job_id"], "extractor": EXTRACTORS[stage], "fact": fact}


def run_agent(work_dir, stage, name, tamper=None):
    jobs = read_jsonl(stage_dir(work_dir, "claimed", stage) / name)
    rows = [fake_result(stage, j) for j in jobs]
    if tamper:
        rows = tamper(rows)
    out = stage_dir(work_dir, "out", stage) / name
    out.write_text("".join(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return out
