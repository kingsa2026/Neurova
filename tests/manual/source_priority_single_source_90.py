# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · T-09 残余）：来源→优先级阶梯的单一事实源。

链路全是**真**生产件，无手工调 `priorityForSource` 冒充：

1. 真 `ContextPool` 写入咽喉 → 真 `ContextInput` → 池内 `priority`；
2. 真 `SemanticMatchDrawer.draw` 按 `priority` 打分排序 → 视图条目顺序；
3. 真端点 `/context/build`（真 FastAPI 路由 + 真 JWT 依赖覆盖）→ 真池；
4. 真 `VoiceContextModule.inject_metadata` → 真池的 EMOTION 条目；
5. 真 `ContextPool.archive_summary` → SUMMARY 条目。

判据（五条都要过）：
1. **同来源同分**：端点写入与编排器写入的用户输入，池内优先级一致（改前 10 vs 90）；
2. **缺省即阶梯**：不传优先级的条目等于阶梯值（改前缺省是常数 50）；
3. **语音 EMOTION 与编排器同分**（改前 60 vs 50）；
4. **draw 真按阶梯排序**：预算紧张时高档来源先入选，且顺序与阶梯一致；
5. **显式取值仍生效**：经验档位（证据驱动）不被阶梯覆盖。

跑法：`PYTHONPATH=. python tests/manual/source_priority_single_source_90.py`
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="neurovaPriority90_"))

from neurova.context.pool_models import ContextInput, ContextSource, priorityForSource  # noqa: E402
from neurova.context_pool import ContextPool  # noqa: E402
from neurova.voice_context_module import VoiceContextModule  # noqa: E402


def _pool(tag: str) -> ContextPool:
    return ContextPool(user_id="u-live", agent_id=f"a-live-{tag}", session_id="s1")


def _residual(item) -> int:
    return item.priority


def main() -> None:
    # [1] 端点写入 vs 编排器写入：同来源必须同分
    pool = _pool("ep")
    from unittest.mock import MagicMock, patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.auth import get_current_user
    from neurova.api.endpoints import context as ctx_mod

    app = FastAPI()
    app.include_router(ctx_mod.router, prefix="/context")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-live"}
    agent = MagicMock()
    agent.context_orchestrator = MagicMock()
    agent.context_orchestrator.context_pool = pool
    client = TestClient(app)
    with patch.object(ctx_mod, "_get_agent", return_value=agent):
        resp = client.post("/context/build", json={"agent_id": "a-live-ep", "user_input": "端点写入"})
    assert resp.status_code == 200, resp.text[:300]
    endpoint_prio = [c for c in pool.get_contexts() if c.content == "端点写入"][0].priority

    orchestrator_prio = ContextInput(source=ContextSource.USER_INPUT, content="编排器写入").priority
    ladder = priorityForSource(ContextSource.USER_INPUT)
    print(
        f"[1 同来源同分] 端点={endpoint_prio} 编排器={orchestrator_prio} 阶梯={ladder}"
    )
    assert endpoint_prio == orchestrator_prio == ladder, "同一来源在两点拿到不同的分"

    # [2] 缺省即阶梯：逐个来源
    mismatched = [
        s.value
        for s in ContextSource
        if ContextInput(source=s, content="x").priority != priorityForSource(s)
    ]
    print(f"[2 缺省即阶梯] 来源数={len(list(ContextSource))} 不一致={mismatched}")
    assert not mismatched, f"这些来源的缺省优先级不是阶梯值：{mismatched}"

    # [3] 语音 EMOTION 与编排器同分
    voicePool = _pool("voice")
    VoiceContextModule().inject_metadata(
        voicePool,
        {
            "text": "测试文本",
            "confidence": 0.9,
            "language": "zh",
            "engine": "funasr",
            "emotion": {"primary_emotion": "angry", "confidence": 0.85, "valence": -0.7, "arousal": 0.8},
        },
    )
    voiceEmotion = [c for c in voicePool.get_contexts() if c.source == ContextSource.EMOTION]
    assert voiceEmotion, "语音情感没进池"
    orchestratorEmotion = ContextInput(source=ContextSource.EMOTION, content="用户情感").priority
    print(
        f"[3 语音同分] 语音EMOTION={voiceEmotion[0].priority} 编排器EMOTION={orchestratorEmotion}"
    )
    assert voiceEmotion[0].priority == orchestratorEmotion, "同一来源（EMOTION）两份口径"

    # [4] draw 真按阶梯排序：预算只够一条时高档来源先入选
    drawPool = _pool("draw")
    drawPool.add_context(ContextInput(source=ContextSource.EMOTION, content="低档情感内容" * 5))
    drawPool.add_context(ContextInput(source=ContextSource.USER_INPUT, content="高档用户输入" * 5))
    drawn = drawPool.draw(budget_tokens=40)
    sources = [c.source.value for c in drawn]
    print(f"[4 draw 按阶梯排序] 预算 40 取到={sources}")
    assert drawn, "预算 40 下一条都没取到——判据不成立"
    assert drawn[0].source == ContextSource.USER_INPUT, (
        f"预算紧张时高优先级来源未先入选：{[ (c.source.value, c.priority) for c in drawn ]}"
    )

    # [5] 显式取值仍生效（经验档位由证据决定）
    explicit = ContextInput(source=ContextSource.EXPERIENCE, content="x", priority=78)
    print(f"[5 显式取值生效] 经验显式=78 实际={explicit.priority}")
    assert explicit.priority == 78, "显式取值被阶梯覆盖——证据驱动档位失效"

    # [6] 摘要归档同样走阶梯
    sumPool = _pool("sum")
    sumPool.archive_summary("部署讨论摘要：数据库迁移待执行")
    summary = [c for c in sumPool.get_contexts() if c.source == ContextSource.SUMMARY]
    print(f"[6 摘要归档] priority={summary[0].priority} 阶梯={priorityForSource(ContextSource.SUMMARY)}")
    assert summary[0].priority == priorityForSource(ContextSource.SUMMARY)

    print("LIVE-VERIFY PASSED")


if __name__ == "__main__":
    main()
