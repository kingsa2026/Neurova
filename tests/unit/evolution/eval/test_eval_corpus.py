"""P1-1 结晶闸语料工件 — 红灯先行的契约测试(2026-10-07)。

评测集此前只在运行期存在(golden→挖掘→合成),结晶入库闸没有可消费的
稳定语料工件——对比研究 B.2 登记的"层序受阻"缺的就是这一环。本文件钉住:

- 语料落 data_root/agents/<id>/evolution/eval_corpus.json
  (env NEUROVA_EVOLUTION_EVAL_CORPUS 重定位,测试指临时目录);
- update 合并去重、有界(防无界增长);
- build_dataset 物化评测集时自动喂语料(写入方接线,不产生只写不读);
- 标记纪律与 leak_critic 同源(单一事实源,教义第 7 条);
- 门工厂:命中返回证据片段,无语料诚实放行(宁漏勿误杀);
- 挂载幂等。
"""

import json

import pytest

from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval import eval_corpus as ec


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_EVOLUTION_EVAL_CORPUS",
                       str(tmp_path / "eval_corpus.json"))
    yield


def _ds(*pairs):
    return EvalDataset(train=[EvalExample(task_input=t, expected_behavior=e)
                              for t, e in pairs])


class TestCorpusArtifact:
    def test_update_merges_and_dedupes(self):
        ec.update_eval_corpus("a", _ds(("任务一", "行为一"), ("任务二", "行为二")))
        ec.update_eval_corpus("a", _ds(("任务二", "行为二"), ("任务三", "行为三")))
        examples = ec.load_corpus_examples("a")
        keys = {(e["task_input"], e["expected_behavior"]) for e in examples}
        assert len(keys) == 3, f"去重失败: {keys}"

    def test_corpus_bounded(self):
        ec.update_eval_corpus("a", _ds(*[(f"任务{i}", "行为") for i in range(ec.CORPUS_CAP + 50)]))
        assert len(ec.load_corpus_examples("a")) <= ec.CORPUS_CAP

    def test_service_build_dataset_feeds_corpus(self, monkeypatch):
        """golden 分支物化评测集 → 语料工件自动更新(写入方接线)。"""
        from neurova.evolution.eval.service import SkillEvolutionService

        svc = SkillEvolutionService(agent_id="svc-agent")
        monkeypatch.setattr(svc, "_golden_dataset",
                            lambda skill_id: _ds(("金标任务", "金标行为")))
        import asyncio

        ds = asyncio.run(svc.build_dataset("sk1", "技能文本", source="golden"))
        assert ds is not None and ds.all_examples
        examples = ec.load_corpus_examples("svc-agent")
        assert any(e["task_input"] == "金标任务" for e in examples)


class TestGateFactory:
    CORPUS = _ds(("帮我把这个季度销售数据整理成表格", "必须输出完整报告表格并给出结论"))

    def test_markers_and_gate_hit(self):
        ec.update_eval_corpus("a", self.CORPUS)
        gate = ec.make_crystallization_leak_gate("a")
        hit = gate("用户要求:帮我把这个季度销售数据整理成表格")
        assert hit is not None, "题干回填必须被拦"
        assert gate("整理周会纪要并同步到协作面板") is None, "清洁文本不得误杀"

    def test_missing_corpus_passes_honestly(self):
        """无语料 = 无围栏:诚实放行(宁漏勿误杀),不伪造检查。"""
        gate = ec.make_crystallization_leak_gate("no-such-agent")
        assert ec.corpus_markers("no-such-agent") == frozenset()
        assert gate("任何文本") is None

    def test_attach_idempotent(self):
        from neurova.cognitive_layers.memory_layer.pattern_crystallizer import (
            PatternCrystallizer,
        )

        cryst = PatternCrystallizer(engine=object())
        first = ec.attach_crystallization_leak_gate(cryst, "a")
        second = ec.attach_crystallization_leak_gate(cryst, "a")
        assert first is True
        assert second is False, "重复挂载必须被幂等拒绝"
        assert cryst._ingestion_gate is not None
