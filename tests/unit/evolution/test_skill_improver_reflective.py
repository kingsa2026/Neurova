"""Wave 1 — skill_improver 反射式接线测试。

根因: _suggest_fix 字典查表把 "timeout" 永远映射到 "增加超时时间"。
propose_pending_improvements_async 在 NEUROVA_TEXT_EVOLUTION 开启时把真实
失败记录喂给 ReflectiveMutator,产出 changes["improved_text"]。
开关关闭/无 loader/变异失败 → 原样返回字典提案(保守回退,零破坏)。
"""

import pytest

from neurova.evolution.skill_improver import get_skill_improver, reset_skill_improver


@pytest.fixture
def improver():
    reset_skill_improver()  # 套件内其他测试可能已按默认参数创建单例
    inst = get_skill_improver(min_records_for_analysis=2, failure_threshold=0.3)
    yield inst
    reset_skill_improver()


def _feed_failures(improver, skill_id="sk-timeout"):
    for i in range(4):
        improver.record_usage(
            skill_id=skill_id,
            success=False,
            error_message=f"Connection timeout after 30s while calling upstream-{i}",
            input_summary=f"调用上游接口 任务{i}",
            output_summary="",
        )
    for i in range(2):
        improver.record_usage(skill_id=skill_id, success=True, input_summary=f"ok{i}")


class TestAsyncProposals:
    @pytest.mark.asyncio
    async def test_disabled_switch_returns_plain_proposals(self, improver, monkeypatch):
        monkeypatch.delenv("NEUROVA_TEXT_EVOLUTION", raising=False)
        _feed_failures(improver)
        proposals = await improver.propose_pending_improvements_async(
            skill_text_loader=lambda sid: "技能正文"
        )
        assert proposals, "字典路径必须仍工作(回退语义)"
        assert all("improved_text" not in p.changes for p in proposals)

    @pytest.mark.asyncio
    async def test_enabled_with_loader_enriches_improved_text(self, improver, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        _feed_failures(improver)

        async def fake_call(self, messages, model):
            return {"success": True, "response": "改进后的技能正文 v2"}

        from neurova.evolution.eval import mutator as mutator_mod

        original = mutator_mod.ReflectiveMutator._call_llm
        monkeypatch.setattr(mutator_mod.ReflectiveMutator, "_call_llm", fake_call)
        try:
            proposals = await improver.propose_pending_improvements_async(
                skill_text_loader=lambda sid: "原始技能正文"
            )
        finally:
            monkeypatch.setattr(mutator_mod.ReflectiveMutator, "_call_llm", original)

        enriched = [p for p in proposals if "improved_text" in p.changes]
        assert enriched, "开启开关 + 有正文时必须产出反射式改进文本"
        assert enriched[0].changes["improved_text"] == "改进后的技能正文 v2"

    @pytest.mark.asyncio
    async def test_real_failure_content_reaches_mutator(self, improver, monkeypatch):
        """判据升级的本质断言:失败的真实内容(非关键词映射)进入变异 prompt。"""
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        _feed_failures(improver)
        captured = {}

        async def fake_call(self, messages, model):
            captured["blob"] = str(messages)
            return {"success": True, "response": "改进后的技能正文 v2"}

        from neurova.evolution.eval import mutator as mutator_mod

        original = mutator_mod.ReflectiveMutator._call_llm
        monkeypatch.setattr(mutator_mod.ReflectiveMutator, "_call_llm", fake_call)
        try:
            await improver.propose_pending_improvements_async(
                skill_text_loader=lambda sid: "原始技能正文"
            )
        finally:
            monkeypatch.setattr(mutator_mod.ReflectiveMutator, "_call_llm", original)

        assert "upstream-0" in captured["blob"], "真实错误内容必须进入变异 prompt"

    @pytest.mark.asyncio
    async def test_no_loader_returns_plain_proposals(self, improver, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        _feed_failures(improver)
        proposals = await improver.propose_pending_improvements_async()
        assert proposals
        assert all("improved_text" not in p.changes for p in proposals)

    @pytest.mark.asyncio
    async def test_mutator_failure_falls_back(self, improver, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        _feed_failures(improver)

        async def fake_call(self, messages, model):
            return {"success": False, "error": "boom"}

        from neurova.evolution.eval import mutator as mutator_mod

        original = mutator_mod.ReflectiveMutator._call_llm
        monkeypatch.setattr(mutator_mod.ReflectiveMutator, "_call_llm", fake_call)
        try:
            proposals = await improver.propose_pending_improvements_async(
                skill_text_loader=lambda sid: "原始技能正文"
            )
        finally:
            monkeypatch.setattr(mutator_mod.ReflectiveMutator, "_call_llm", original)

        # LLM 失败 → mutate 返回原文 → 与正文相同 → 不富化,字典提案保留
        assert proposals
        assert all("improved_text" not in p.changes for p in proposals)
