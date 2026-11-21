"""P1-5 世代谱系与门禁结果治理读面测试（governance RSI 面扩展）。

设计出处：docs/04-plans/2026-11-21-recursive-self-evolution-plan.md
§6 P1 批 P1-5、§10.5（租户可见性：世代谱系进 admin 审计面）。

先红后绿：本文件先于端点实现存在——GET /v1/governance/rsi/generations*
四条读面在实现前一律 404（路由不存在），跑批即红灯；实现转绿后逐条钉住：

1. 权限：无凭据 401、非 admin 403（沿 governance 既有 require_admin 门）；
2. 读面诚实：账本空 → 空列表 / 404（不造数据）；世代管线未装配 → 503；
3. 存在世代时：列表（limit / status 过滤）、单代详情（signals/changes/
   verdicts 全量/decision/deployment）、谱系回溯链、当前生产基线正确。

数据源是**真实** GenerationLedger（tmp 落盘，不进仓库 data/）；
RSI 四闭环系统按 API 测试既有惯例用 MagicMock 占位（被测链路不经过它们）。
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.auth_headers import overrideIdentity

PREFIX = "/api/v1/governance/rsi/generations"

# ── 装配 helper ────────────────────────────────────────────────


def _tmpLedger():
    """tmp 落盘账本：显式 statePath，不依赖 env，零仓库 data/ 污染。"""
    from neurova.evolution.rsi.generation_ledger import GenerationLedger

    root = Path(tempfile.mkdtemp(prefix="p15generations-"))
    return GenerationLedger(statePath=root / "generations.json")


def _rsiWithGenerationPipeline(ledger):
    """真 RSI 编排器 + 真世代编排器 + 真 tmp 账本（P1-3 生产装配形态）。"""
    from neurova.evolution.rsi.generation_orchestrator import GenerationOrchestrator
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    rsi = RSIOrchestrator(
        sleep_system=MagicMock(),
        emotion_system=MagicMock(),
        experience_system=MagicMock(),
        tool_memory_system=MagicMock(),
    )
    rsi.generationOrchestrator = GenerationOrchestrator(
        rsiOrchestrator=rsi, ledger=ledger
    )
    return rsi


@contextmanager
def _clientFor(rsi=None, identity=None):
    """governance 路由测试客户端：identity=None 时不打身份替身（测 401）。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.endpoints.governance import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/governance")
    if identity is not None:
        overrideIdentity(app, identity)
    with patch(
        "neurova.api.endpoints.governance._get_rsi_orchestrator",
        return_value=rsi,
    ):
        yield TestClient(app)


def _seedDeployed(ledger, *, parentNo=None, basis="abc1234", auto=False):
    """开一代并驱动到 deployed（账本状态机全路径，同 P0-3 判据）。"""
    from neurova.evolution.rsi.gate_verdict import GateVerdict
    from neurova.evolution.rsi.generation_ledger import (
        ChangeRef,
        DecisionRef,
        DeploymentRef,
        SignalRef,
    )

    gen = ledger.openGeneration(
        parentNo,
        [SignalRef(kind="feedback", ref="sleep", summary="performance_score=0.812")],
        [
            ChangeRef(
                targetId="rsi.parameterFamily",
                kind="parameter",
                ref="sleep.temperature: 0.5 -> 0.7",
                rationale="决策档回退信号",
            )
        ],
        basis,
    )
    ledger.recordVerdicts(gen.generationNo, {"g0": GateVerdict.passed("存活探针全绿")})
    ledger.recordVerdicts(gen.generationNo, {"g2": GateVerdict.passed("业务判据不回退")})
    if auto:
        ledger.recordDecision(gen.generationNo, DecisionRef(kind="auto"))
    else:
        ledger.recordDecision(
            gen.generationNo, DecisionRef(kind="approval", approver="admin1")
        )
    ledger.markDeployed(gen.generationNo, DeploymentRef(canaryConclusion="观测窗平稳"))
    return gen


def _seedRejected(ledger, *, parentNo=None, reason="影子验证失败，候选淘汰"):
    from neurova.evolution.rsi.generation_ledger import ChangeRef, SignalRef

    gen = ledger.openGeneration(
        parentNo,
        [SignalRef(kind="evalFailure", ref="case-g2-7", summary="G2 业务判据回退")],
        [ChangeRef(targetId="rsi.parameterFamily", kind="parameter", ref="x: 1 -> 2")],
        "def4567",
    )
    ledger.markRejected(gen.generationNo, reason)
    return gen


# ── 权限（沿 governance admin 门）──────────────────────────────


class TestGenerationEndpointPermissions:
    def test_missing_credentials_401(self):
        """无凭据 401：世代谱系是 admin 审计面，匿名一律身份门拦下。"""
        ledger = _tmpLedger()
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity=None) as client:
            resp = client.get(PREFIX)
            assert resp.status_code == 401, resp.text

    def test_non_admin_403(self):
        """非 admin 403：普通用户不得读世代谱系（§10.5 审计面边界）。"""
        ledger = _tmpLedger()
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "u1", "role": "user"}) as client:
            resp = client.get(PREFIX)
            assert resp.status_code == 403, resp.text


# ── 读面诚实：未装配 / 空账本 ─────────────────────────────────


class TestGenerationReadFaceHonesty:
    def test_generation_pipeline_not_assembled_503(self):
        """RSI 在池但未挂世代编排器 → 503「世代管线未装配」，不造假数据。"""
        from neurova.evolution.rsi.orchestrator import RSIOrchestrator

        rsi = RSIOrchestrator(
            sleep_system=MagicMock(),
            emotion_system=MagicMock(),
            experience_system=MagicMock(),
            tool_memory_system=MagicMock(),
        )  # generationOrchestrator 保持 None（P1-3 可选件缺席）
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(PREFIX)
            assert resp.status_code == 503, resp.text
            assert "世代管线未装配" in resp.json()["detail"], resp.text

    def test_rsi_not_assembled_503(self):
        """RSI 编排器本身缺席 → 既有 503 语义（不回落、不静默 200）。"""
        with _clientFor(rsi=None, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(PREFIX)
            assert resp.status_code == 503, resp.text
            assert resp.json()["detail"], "503 必须带原因"

    def test_empty_ledger_returns_empty_list(self):
        """账本空 → 空列表（200），不是编造的世代。"""
        ledger = _tmpLedger()
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(PREFIX)
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["generations"] == []
            assert data["count"] == 0

    def test_current_baseline_empty_ledger_404(self):
        """无任何 deployed 代 → /current 404（不把 proposed 编成基线）。"""
        ledger = _tmpLedger()
        _seedRejected(ledger)
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(f"{PREFIX}/current")
            assert resp.status_code == 404, resp.text


# ── 列表读面 ──────────────────────────────────────────────────


class TestGenerationListEndpoint:
    def test_list_returns_summaries(self):
        ledger = _tmpLedger()
        gen1 = _seedDeployed(ledger)
        gen2 = _seedDeployed(ledger, parentNo=gen1.generationNo, basis="def4567")
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(PREFIX)
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["count"] == 2
            items = data["generations"]
            assert [g["generationNo"] for g in items] == [
                gen1.generationNo,
                gen2.generationNo,
            ]
            first = items[0]
            assert first["parentNo"] is None
            assert first["status"] == "deployed"
            assert first["decision"]["kind"] == "approval"
            assert first["decision"]["approver"] == "admin1"
            assert first["promotedAt"], "deployed 代必须带晋升时间"

    def test_list_limit_takes_most_recent(self):
        ledger = _tmpLedger()
        gen1 = _seedDeployed(ledger)
        _seedDeployed(ledger, parentNo=gen1.generationNo)
        gen3 = _seedDeployed(ledger, parentNo=gen1.generationNo, auto=True)
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(PREFIX, params={"limit": 2})
            assert resp.status_code == 200, resp.text
            items = resp.json()["data"]["generations"]
            assert [g["generationNo"] for g in items] == [
                2,
                gen3.generationNo,
            ], "limit 截取最近的 N 代"

    def test_list_status_filter(self):
        ledger = _tmpLedger()
        gen1 = _seedDeployed(ledger)
        rej = _seedRejected(ledger, parentNo=gen1.generationNo)
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(PREFIX, params={"status": "deployed"})
            assert resp.status_code == 200
            items = resp.json()["data"]["generations"]
            assert [g["generationNo"] for g in items] == [gen1.generationNo]

            resp = client.get(PREFIX, params={"status": "rejected"})
            assert resp.status_code == 200
            items = resp.json()["data"]["generations"]
            assert [g["generationNo"] for g in items] == [rej.generationNo]

    def test_list_invalid_status_422(self):
        ledger = _tmpLedger()
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(PREFIX, params={"status": "not-a-status"})
            assert resp.status_code == 422, resp.text

    def test_list_limit_bound_422(self):
        ledger = _tmpLedger()
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(PREFIX, params={"limit": 0})
            assert resp.status_code == 422, resp.text


# ── 详情 / 谱系 / 当前基线 ────────────────────────────────────


class TestGenerationDetailLineageBaseline:
    def test_detail_full_payload(self):
        ledger = _tmpLedger()
        gen = _seedDeployed(ledger)
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(f"{PREFIX}/{gen.generationNo}")
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["generationNo"] == gen.generationNo
            assert data["status"] == "deployed"
            assert data["basisCommit"] == "abc1234"
            # signals / changes / verdicts 全量出街
            assert data["signals"][0]["kind"] == "feedback"
            assert data["signals"][0]["ref"] == "sleep"
            assert data["changes"][0]["targetId"] == "rsi.parameterFamily"
            assert data["verdicts"]["g0"]["state"] == "passed"
            assert data["verdicts"]["g2"]["state"] == "passed"
            assert data["decision"]["kind"] == "approval"
            assert data["deployment"]["promotedAt"]
            assert data["deployment"]["canaryConclusion"] == "观测窗平稳"

    def test_detail_unknown_404(self):
        ledger = _tmpLedger()
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(f"{PREFIX}/999")
            assert resp.status_code == 404, resp.text

    def test_lineage_chain(self):
        ledger = _tmpLedger()
        gen1 = _seedDeployed(ledger)
        gen2 = _seedDeployed(ledger, parentNo=gen1.generationNo)
        gen3 = _seedDeployed(ledger, parentNo=gen2.generationNo, auto=True)
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(f"{PREFIX}/{gen3.generationNo}/lineage")
            assert resp.status_code == 200, resp.text
            chain = resp.json()["data"]["lineage"]
            assert [g["generationNo"] for g in chain] == [
                gen3.generationNo,
                gen2.generationNo,
                gen1.generationNo,
            ], "谱系从指定代向上回溯到根代"
            assert chain[-1]["parentNo"] is None

    def test_lineage_unknown_404(self):
        ledger = _tmpLedger()
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(f"{PREFIX}/999/lineage")
            assert resp.status_code == 404, resp.text

    def test_current_baseline_is_latest_deployed(self):
        ledger = _tmpLedger()
        gen1 = _seedDeployed(ledger)
        gen2 = _seedDeployed(ledger, parentNo=gen1.generationNo, auto=True)
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(f"{PREFIX}/current")
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["generationNo"] == gen2.generationNo
            assert data["status"] == "deployed"
            assert data["deployment"]["promotedAt"]

    def test_current_route_registered_before_path_param(self):
        """/current 不得被 /{generation_no} 吞成 422（路由声明序判据）。"""
        ledger = _tmpLedger()
        gen = _seedDeployed(ledger)
        rsi = _rsiWithGenerationPipeline(ledger)
        with _clientFor(rsi=rsi, identity={"user_id": "a", "role": "admin"}) as client:
            resp = client.get(f"{PREFIX}/current")
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["generationNo"] == gen.generationNo
