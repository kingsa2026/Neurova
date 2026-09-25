"""升级通道可达性（工单 009）：自动调整失效时，人工评审这条臂必须真的能走到。

审计实测它是"逻辑上存在、事实上不可达的死码"，本单把它接上三条真实触发：

1. **发散来源真实化**。`measurement_blind`（工单 007 上抛的"量不出来"）与
   工单 006 的真 ROI 零产出，都是"自动参数调整已失效"的准确定义，
   不必等到数值上出现负增益。旧判据只认 `diverging`/`oscillating+负斜率`，
   而 `diverging` 要求 `mean_gain < -0.05` —— 增益按构造非负，该分支永不触发。
2. **判据走 `GateVerdict`（工单 003 三态）**，且**每个被跳过的系统都要有原因**。
   旧实现返回裸 `[]`：既分不清"没失效"与"没读数"，也看不见是哪个系统被
   `performance>=0.5` 这道过滤挡掉的 ⇒ 不允许静默空列表。
3. **升级结论必须抵达观测面**（工单 012 的 `get_status()`），否则通道通不通没人知道。

用例会创建提案，故一律 `monkeypatch.chdir(tmp_path)`：`SelfImprovementProposer`
的目录仍由编排器硬编码为仓库根 `.agents/`（该注入缺口登记在工单 010，本单不偷改）。
"""

from __future__ import annotations

from neurova.evolution.rsi.gate_verdict import GateVerdict


def _blind_round(probe, measured_eval_harness):
    """把迭代做成"参数改坏但评测集量不出来"的形态（工单 007 的 measurement_blind）。

    必须跑两轮以上：`run_iteration` 第 2 步读的收敛状态是**上一轮**记完的历史，
    首轮的 `evidence_history` 还是空的 ⇒ 只能判 `insufficient_data`。
    这不是测试的妥协，而是被接线次序本身决定的事实（工单 008 的失明判定
    抢在样本量门槛之前，但仍在记史之后）。
    """
    probe.orchestrator._eval_harness = measured_eval_harness([])
    result = probe.orchestrator.run_iteration()
    for _ in range(2):
        if result["convergence"]["status"] == "measurement_blind":
            return result
        result = probe.orchestrator.run_iteration()
    return result


def test_measurement_blind_round_escalates(rsi_probe_factory, measured_eval_harness, monkeypatch, tmp_path):
    """度量失明即自动通道失效 ⇒ 必须产出人工提案（旧实现恒返回空列表）。"""
    monkeypatch.chdir(tmp_path)
    probe = rsi_probe_factory(rsi_phase=2)

    result = _blind_round(probe, measured_eval_harness)

    status = result["convergence"]["status"]
    escalation = result["escalation"]
    assert status == "measurement_blind", f"前置：本轮应判度量失明，实际 {status}"
    assert escalation["proposals"], (
        f"度量失明这一轮没有产出任何人工提案（通道仍不可达）：{escalation}")


def test_zero_roi_round_escalates(rsi_probe_factory, measured_eval_harness, monkeypatch, tmp_path):
    """真 ROI 报"花了成本零产出" ⇒ 判据成立（工单 006 的读数在此首次有了消费方）。

    这一轮默认装配里没有任何系统低于 0.5 ⇒ 提案可以为空，但**不得静默**：
    每个被挡下的系统都要点名（"空列表"本身就是要被拆掉的那个黑箱）。
    提案真产出的路径由 `test_each_skipped_system_carries_a_reason` 与
    `test_measurement_blind_round_escalates` 覆盖。
    """
    monkeypatch.chdir(tmp_path)
    probe = rsi_probe_factory(rsi_phase=2)
    # 两轮：第二轮起 cost 已累计、roi 可算；把增益压成 0 ⇒ roi == 0
    probe.orchestrator._eval_harness = measured_eval_harness([0.5, 0.5, 0.5, 0.5])

    probe.orchestrator.run_iteration()
    second = probe.orchestrator.run_iteration()

    roi = probe.orchestrator.convergence_analyzer.compute_roi()
    assert roi is not None and roi <= 0.0, f"前置：本轮 roi 应为非正，实际 {roi}"
    escalation = second["escalation"]
    assert escalation["verdict"]["state"] == GateVerdict.STATE_PASSED, (
        f"roi<=0 未被当作升级触发：{escalation['verdict']}")
    assert escalation["skipped"] and all(
        item["reason"] for item in escalation["skipped"]
    ), f"判据成立却零提案时，每个系统都必须给出挡下的理由：{escalation}"


def test_healthy_round_escalates_nothing_but_says_so(rsi_probe_factory, measured_eval_harness,
                                                     monkeypatch, tmp_path):
    """没失效也要出声：判据为"未触发"时必须写明凭什么，不得只留一个空列表。"""
    monkeypatch.chdir(tmp_path)
    probe = rsi_probe_factory(rsi_phase=2)
    probe.orchestrator._eval_harness = measured_eval_harness([0.5, 0.9])

    result = probe.orchestrator.run_iteration()
    escalation = result["escalation"]

    assert escalation["proposals"] == [], f"正增益且非失明不该升级：{escalation}"
    assert escalation["verdict"]["state"] == GateVerdict.STATE_FAILED, escalation
    assert escalation["verdict"]["reason"], "未触发也必须给出依据（三态契约）"


def test_each_skipped_system_carries_a_reason(rsi_probe_factory, monkeypatch, tmp_path):
    """被 `performance>=0.5` 挡掉的系统必须点名，否则"空列表"仍是黑箱。"""
    monkeypatch.chdir(tmp_path)
    probe = rsi_probe_factory(rsi_phase=2)
    signals = {
        "sleep": {"performance_score": 0.2, "verdict": {"state": "measured"}},
        "emotion": {"performance_score": 0.9, "verdict": {"state": "measured"}},
        "experience": {"not_a_signal_dict": True},
    }

    outcome = probe.orchestrator._escalate_to_proposer_if_needed(
        {"status": "diverging", "metrics": {"trend_slope": -0.1}}, signals
    )

    assert [p["system"] for p in outcome["skipped"]] and \
        {p["system"] for p in outcome["skipped"]} >= {"emotion", "experience"}, (
        f"性能达标/信号形态不符的系统应被点名跳过：{outcome['skipped']}")
    for item in outcome["skipped"]:
        assert item["reason"], f"跳过必须带原因：{item}"
    assert len(outcome["proposals"]) == 1, (
        f"三分母里只有 sleep 该产提案：{outcome}")


def test_round_without_convergence_reading_is_unevidenced_not_passed(
        rsi_probe_factory, monkeypatch, tmp_path):
    """收敛读数缺席 ⇒ 判 unevidenced，不得被读成"没失效所以不用升级"。"""
    monkeypatch.chdir(tmp_path)
    probe = rsi_probe_factory(rsi_phase=2)

    outcome = probe.orchestrator._escalate_to_proposer_if_needed(
        {"status": "", "metrics": {}}, {"sleep": {"performance_score": 0.2}}
    )

    assert outcome["verdict"]["state"] == GateVerdict.STATE_UNEVIDENCED, outcome
    assert outcome["proposals"] == []


def test_escalation_reaches_the_status_surface(rsi_probe_factory, measured_eval_harness,
                                               monkeypatch, tmp_path):
    """通道走没走过、为什么没走，必须能在工单 012 的状态面上读到。"""
    monkeypatch.chdir(tmp_path)
    probe = rsi_probe_factory(rsi_phase=2)
    _blind_round(probe, measured_eval_harness)

    status = probe.orchestrator.get_status()

    assert "escalation" in status, "升级通道对观测面不可见 = 通不通没人知道"
    assert status["escalation"]["proposals"], status["escalation"]
    assert status["escalation"]["verdict"]["state"] == GateVerdict.STATE_PASSED


def test_escalated_proposal_shows_up_in_pending_endpoint(
        rsi_probe_factory, measured_eval_harness, monkeypatch, tmp_path):
    """集成（票面验收 3）：升级产出的提案 ID 出现在待审列表端点里。"""
    from unittest.mock import patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.chdir(tmp_path)
    probe = rsi_probe_factory(rsi_phase=2)
    result = _blind_round(probe, measured_eval_harness)
    proposal_id = result["escalation"]["proposals"][0]

    app = FastAPI()
    from neurova.api.deps import get_current_user
    from neurova.api.endpoints.governance import router

    app.include_router(router, prefix="/api/v1/governance")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "admin1", "role": "admin"}
    with patch(
        "neurova.api.endpoints.governance._get_rsi_orchestrator",
        return_value=probe.orchestrator,
    ):
        resp = TestClient(app).get("/api/v1/governance/rsi/proposals/pending")

    assert resp.status_code == 200, resp.text
    ids = [p["proposal_id"] for p in resp.json()["data"]["proposals"]]
    assert proposal_id in ids, f"升级提案没进待审队列：{proposal_id} 不在 {ids}"


def test_consecutive_failing_rounds_do_not_flood_the_pending_queue(
        rsi_probe_factory, measured_eval_harness, monkeypatch, tmp_path):
    """同一系统已有待审提案时不得再问一遍（工单 009 落地后实测踩到的回归）。

    通道接通后每轮失效都产提案 ⇒ 一个持续失明的 agent 会以"每轮×每系统"的
    速率刷人工队列（实测一次全套跑出 800+ 条同形 pending）。人工队列被刷屏
    与通道不可达是同样致命的失效，所以去重必须做在这里，而不是留给下游兜底。
    """
    monkeypatch.chdir(tmp_path)
    probe = rsi_probe_factory(rsi_phase=2)
    probe.orchestrator._eval_harness = measured_eval_harness([])

    produced = []
    for _ in range(5):
        result = probe.orchestrator.run_iteration()
        produced.append(len(result["escalation"]["proposals"]))

    escalated = [i for i, count in enumerate(produced) if count]
    assert escalated, f"五轮失明一次都没升级过：{produced}"
    first = escalated[0]
    assert produced[first + 1:] == [0] * (4 - first), (
        f"系统已有待审提案后仍在逐轮重复产：{produced}")

    pending = probe.orchestrator.self_improvement_proposer.list_pending_proposals()
    targets = [p.target for p in pending]
    assert len(targets) == len(set(targets)), f"同一系统出现了多条待审提案：{targets}"

    final = probe.orchestrator.get_status()["escalation"]
    assert final["skipped"] and all(
        "已有待审" in item["reason"] for item in final["skipped"]
    ), f"被去重挡下也要点名，不得静默：{final['skipped']}"


def test_escalation_never_auto_applies(rsi_probe_factory, measured_eval_harness,
                                       monkeypatch, tmp_path):
    """回归护栏：人工通道的提案一律保持 PENDING，本单不得开出自动 apply 路径。"""
    monkeypatch.chdir(tmp_path)
    probe = rsi_probe_factory(rsi_phase=2)
    result = _blind_round(probe, measured_eval_harness)

    proposals = probe.orchestrator.self_improvement_proposer.list_pending_proposals()
    pending_ids = {pr.proposal_id for pr in proposals}
    assert result["escalation"]["proposals"], "前置：本单用例应确有升级提案"
    missing = [pid for pid in result["escalation"]["proposals"] if pid not in pending_ids]
    assert not missing, f"提案离开 PENDING 即意味着存在自动 apply 路径：{missing}"
