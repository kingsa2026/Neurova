"""反射式自动改写已退役：LLM 文本进化统一到 SkillEvolutionService。

旧契约（`changes["improved_text"]` + 自动应用）已被单一 service 路径取代；
本文件只保留一条回归：异步入口不得再产 `improved_text`，避免第三条路径复活。
"""

import pytest

from neurova.evolution.skill_improver import get_skill_improver, reset_skill_improver


@pytest.fixture
def improver():
    reset_skill_improver()
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


@pytest.mark.asyncio
async def test_async_entry_returns_dictionary_proposals_only(improver, monkeypatch):
    monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
    _feed_failures(improver)

    proposals = await improver.propose_pending_improvements_async()

    assert proposals, "字典路径必须仍工作"
    assert all("improved_text" not in p.changes for p in proposals), (
        "异步入口不得再生成反射正文；LLM 文本进化只走 SkillEvolutionService"
    )
