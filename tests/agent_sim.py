"""테스트용 가짜 L1 에이전트: claimed 배치를 읽고 out 결과를 쓴다."""

import json
import re

from kloe.queue.export import read_jsonl, stage_dir

EXTRACTORS = {"classify": "cowork:test:kloe-classify@0.0", "extract": "cowork:test:kloe-extract@0.0",
              "program": "cc:test:kloe-extract-program@0.0"}


def fake_result(stage: str, job: dict) -> dict:
    text = job["text"]
    benefit = "공제한다" in text
    first_sentence = text.split(". ")[0]
    if stage == "classify":
        return {"job_id": job["job_id"], "extractor": EXTRACTORS[stage], "is_benefit": benefit,
                "benefit_type": "deduction" if benefit else None,
                "quotes": [{"field": "is_benefit", "quote": first_sentence}]}
    if stage == "program":
        first_line = text.splitlines()[0]
        basis = re.findall(r"^근거법령: (.+)$", text, flags=re.M)
        return {"job_id": job["job_id"], "extractor": EXTRACTORS[stage],
                "fact": {"is_benefit": True, "benefit_type": "subsidy", "legal_basis": basis,
                         "quotes": [{"field": "summary", "quote": first_line}]}}
    m = re.search(r"100분의 (\d+)", text)
    fact = {"is_benefit": benefit, "benefit_type": "deduction" if benefit else None,
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
