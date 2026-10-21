# -*- coding: utf-8 -*-
"""三项补强的活体验证：judge 回退门、auto 执行面、成功轨迹与大产物证据。

跑的真对象：真 `SkillEvolutionService.evolve` → 真 runner/约束/泄漏门；
真 `recordExecutionEvidence` 落盘；真 `create_app()` + 真 JWT 的 HTTP 证据审计端点。
唯一替身是 LLM 边界（判分器、变异器、执行器），不替代装配与存储链。

一条命令复现：
PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/evolutionFallbackEvidence_live.py
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

isolatedDataRoot()


class _UnavailableJudge:
    async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
        from neurova.evolution.eval.fitness import FitnessScore

        return FitnessScore(
            correctness=0.5,
            procedure_following=0.5,
            conciseness=0.5,
            feedback="judge infra down",
            judge_available=False,
        )


class _UsabilityAgent:
    async def run(self, *, skill_text, task_input):
        return "usable output" if "IMPROVED" in skill_text else ""


async def _mutate(*, artifact_text, artifact_type, failures, **kw):
    return artifact_text + " IMPROVED"


async def main() -> int:
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.auth import create_access_token
    from neurova.evolution.eval.config import EvolutionConfig
    from neurova.evolution.eval.dataset import EvalDataset, EvalExample
    from neurova.evolution.eval.service import SkillEvolutionService
    from neurova.evolution.skill_evidence import (
        executionEvidenceFor,
        loadExecutionEvidence,
        recordExecutionEvidence,
    )

    # 1) judge 不可用 → 确定性回退门 → 人工复核提案，自动审批拒绝
    svc = SkillEvolutionService("live-agent", base_dir=Path(tempfile.mkdtemp()) / "evo")
    dataset = EvalDataset(
        train=[EvalExample(task_input="t1", expected_behavior="r")],
        holdout=[EvalExample(task_input="h1", expected_behavior="r")],
    )
    result, proposal = await svc.evolve(
        skill_id="live-skill",
        skill_text="BASE SKILL TEXT " * 20,
        dataset=dataset,
        iterations=1,
        agent=_UsabilityAgent(),
        judge=_UnavailableJudge(),
        mutate=_mutate,
        config=EvolutionConfig(
            iterations=1,
            judge_fallback="deterministic",
            anchor_floor_enabled=False,
            cost_rule_enabled=False,
        ),
    )
    assert result.judge_fallback == "deterministic", result.to_dict()
    assert proposal is not None, result.to_dict()
    assert proposal.requires_manual_review is True, proposal.to_dict()
    assert svc.decide(
        proposal.proposal_id, True, registry=None, approver="auto:evolution"
    ) is False
    print(
        "JUDGE_FALLBACK_LIVE_OK "
        f"judge_available={result.judge_available} "
        f"fallback={result.judge_fallback} manual={proposal.requires_manual_review}"
    )

    # 2) 成功轨迹 + 小产物复制 + 大产物 hash 引用
    small = Path(tempfile.mkdtemp()) / "small.txt"
    small.write_bytes(b"small-live")
    large = Path(tempfile.mkdtemp()) / "large.bin"
    large.write_bytes(b"x" * 3_000_000)
    trace = [
        {
            "tool": "file_write",
            "artifacts": [
                {"path": str(small), "name": small.name, "kind": "txt",
                 "size": small.stat().st_size},
                {"path": str(large), "name": large.name, "kind": "bin",
                 "size": large.stat().st_size},
            ],
        }
    ]
    written = recordExecutionEvidence(
        "live-agent",
        "live-skill",
        user_input="live input",
        params={"p": 1},
        result=SimpleNamespace(
            success=True, data={"text": "live answer"}, error="", metadata={},
            execution_time=0.1,
        ),
        context={"c": 1},
        trace=trace,
    )
    assert written["evidence_kind"] == "full_success", written
    payload = loadExecutionEvidence(written["evidence_ref"])
    arts = payload["tool_trace"][0]["artifacts"]
    assert arts[0]["storage"] == "copied" and arts[0]["sha256"], arts
    assert arts[1]["storage"] == "reference", arts
    assert arts[1]["sha256"] == hashlib.sha256(b"x" * 3_000_000).hexdigest(), arts
    print(
        "EVIDENCE_LIVE_OK "
        f"kind={written['evidence_kind']} "
        f"small={arts[0]['storage']} large={arts[1]['storage']} "
        f"artifacts={len(payload['artifacts'])}"
    )

    # 3) 真 HTTP：证据审计端点读同一份全量轨迹
    from neurova.evolution.skill_improver import get_skill_improver

    get_skill_improver().record_usage(
        skill_id="live-skill",
        success=True,
        duration=0.1,
        error_message="",
        input_summary="live input",
        output_summary="live answer",
        metadata={"agent_id": "live-agent", "evidence_ref": written["evidence_ref"]},
    )
    token = create_access_token({
        "sub": "u_evo_live", "username": "u_evo_live", "role": "admin",
    })
    headers = {"Authorization": f"Bearer {token}"}
    app = create_app()
    with TestClient(app) as client:
        resp = client.get(
            "/api/v1/evolution/skills/live-agent/evidence/live-skill",
            params={"kind": "success"}, headers=headers,
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]["items"]
        assert items and items[0]["outcome"] == "success", items
        assert "live answer" in str(items[0]["output"]), items
        assert items[0]["artifacts"][1]["storage"] == "reference", items[0]
        print(
            "EVIDENCE_HTTP_LIVE_OK "
            f"items={len(items)} output={str(items[0]['output'])[:40]!r}"
        )

    direct = executionEvidenceFor(
        get_skill_improver().get_usage_history("live-skill"),
        kind="success", agent_id="live-agent",
    )
    assert direct and direct[0]["evidence_kind"] == "full", direct
    print(f"EVIDENCE_READER_LIVE_OK items={len(direct)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
