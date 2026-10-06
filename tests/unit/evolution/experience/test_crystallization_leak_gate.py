"""P1-1 结晶入库泄漏闸 — 红灯先行的契约测试(2026-10-07)。

背景(对比研究 B.2):结晶经验会经上下文注入回流进后续会话——若结晶文本
携带评测任务的题干/判据原文,评测分将被记忆化而非能力推高(背题的另一条
入口,与候选泄漏闸同型但方向相反:这次守的是**入库面**)。

咽喉事实:两条入库路径(LLM 裁决后 confirm_pending、治理关闸直写
_try_crystallize)唯一共同落点是 _store_candidate——闸必须在咽喉处,
且缺席时行为逐字节不变(与既有 test_crystallization_gate 的门槛语义正交)。
"""

import pytest

from neurova.evolution.eval import eval_corpus as ec
from neurova.evolution.eval.dataset import EvalDataset, EvalExample

CONTAMINATED = "用户要求:帮我把这个季度销售数据整理成表格"
CLEAN = "整理周会纪要并同步到协作面板"
RUBRIC = "必须输出完整报告表格并给出结论"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_EVOLUTION_EVAL_CORPUS",
                       str(tmp_path / "eval_corpus.json"))
    yield


def _observe(cryst, context):
    for _ in range(3):
        cryst.observe(tool_name="pdf_export", context=context, success=True)


def _seed_corpus_and_attach(cryst):
    ec.update_eval_corpus(
        "gate-agent",
        EvalDataset(train=[EvalExample(task_input=CONTAMINATED.replace("用户要求:", ""),
                                       expected_behavior=RUBRIC)]))
    assert ec.attach_crystallization_leak_gate(cryst, "gate-agent") is True


def test_contaminated_sample_context_rejected_at_choke_point(
        crystallizer_with_registry_bridge):
    """题干原文进了结晶文本 → 咽喉处被拦:不入库、计数可读、LLM 裁决账目诚实。"""
    _feedback, cryst, engine = crystallizer_with_registry_bridge
    _seed_corpus_and_attach(cryst)

    _observe(cryst, CONTAMINATED)
    key = cryst.list_pending()[0]["key"]
    result = cryst.confirm_pending([{"key": key, "approved": True, "reason": ""}])

    assert not engine.stored, "污染候选不得入库"
    assert result["gate_rejected"] == 1, "LLM 批准但被泄漏闸拦下,账目必须单列"
    assert cryst.gate_rejected == 1


def test_clean_sample_context_stored(crystallizer_with_registry_bridge):
    _feedback, cryst, engine = crystallizer_with_registry_bridge
    _seed_corpus_and_attach(cryst)

    _observe(cryst, CLEAN)
    key = cryst.list_pending()[0]["key"]
    result = cryst.confirm_pending([{"key": key, "approved": True, "reason": ""}])

    assert len(engine.stored) == 1
    assert result["gate_rejected"] == 0 and cryst.gate_rejected == 0


def test_direct_store_path_also_gated(make_crystallizer):
    """治理关闸(直写)路径同样过闸——闸是入库面围栏,不是裁决的附属品。"""
    cryst, engine = make_crystallizer()
    _seed_corpus_and_attach(cryst)

    stored = cryst._store_candidate({
        "key": "k1", "primary_tool": "pdf_export", "rate": 0.9,
        "sample_count": 3, "sample_context": CONTAMINATED,
    })
    assert stored is False and not engine.stored

    stored_clean = cryst._store_candidate({
        "key": "k2", "primary_tool": "pdf_export", "rate": 0.9,
        "sample_count": 3, "sample_context": CLEAN,
    })
    assert stored_clean is True and len(engine.stored) == 1


def test_missing_corpus_is_honest_no_fence(make_crystallizer):
    """无语料 = 无围栏:放行但闸在(宁漏勿误杀),不伪造拦截。"""
    cryst, engine = make_crystallizer()
    assert ec.attach_crystallization_leak_gate(cryst, "no-such-agent") is True

    stored = cryst._store_candidate({
        "key": "k1", "primary_tool": "pdf_export", "rate": 0.9,
        "sample_count": 3, "sample_context": CONTAMINATED,
    })
    assert stored is True and len(engine.stored) == 1
