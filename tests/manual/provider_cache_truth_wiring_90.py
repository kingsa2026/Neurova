# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · 判据 7）：provider 真值从记账器到面板快照的**真链路**。

链路口径（全走生产构造面，不手工拼 payload）：

1. 真 `TokenUsageAccounting.record(...)` 记一次带 `cache_read_tokens` 的调用
   —— `multi_model_client` 入账时走的就是它（真值唯一出处）；
2. 真 `ChatPipeline._backfillProviderCacheUsage(ctx)` —— 生产回填点（不手工调
   `applyProviderCacheUsage`，否则验的是判据自己的实现而不是接线）；
3. 真 `measure_composition` 落的快照 → 真 `get_last_composition`（前端读的那份）。

判据四条：
1. 归一形真值（`last_call()` 的形状）被识别为 `provider`，命中率 = 命中/prompt；
2. 回填只改命中的两个字段，组成其余字段逐字不变；
3. 会话维度快照（环图按会话隔离读的那份）同批更新；
4. 无真值时口径**不**被改写成 provider（不把估算伪装成实测）。

跑法：`PYTHONPATH=. python tests/manual/provider_cache_truth_wiring_90.py`
"""

from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="neurovaCacheTruth_"))

from neurova.context.composition import (  # noqa: E402
    get_last_composition,
    measure_composition,
    reset_composition,
)
from neurova.core.usage_accounting import (  # noqa: E402
    reset_usage_accounting,
)
from neurova.core.usage_accounting import (  # noqa: E402
    get_usage_accounting,
)

MESSAGES = [
    {"role": "system", "content": "固定系统前缀" * 50},
    {"role": "user", "content": "本轮提问"},
]


def _pipeline(agentId: str = "a-cache-truth"):
    """真 `ChatPipeline` 实例（只读 agent 的 property 面），**不 mock 回填点本身**。

    用 `__new__` 直构：本脚本只验回填这一条链路，不装配整条聊天管线
    （那需要全套子系统）。回填方法只读 `self.config` 与 `ctx.session_id`，
    直构路径与生产路径访问的是同一份实现。
    """
    from neurova.agent.chat_pipeline import ChatPipeline

    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline._agent = SimpleNamespace(
        config=SimpleNamespace(agent_id=agentId, llm_config=SimpleNamespace(model="test-model"))
    )
    return pipeline


def main() -> None:
    reset_composition()
    reset_usage_accounting()
    agentId = "a-cache-truth"

    # 1) 真记账（生产入账路径的同一份单例）
    payload = get_usage_accounting().record(
        model="m",
        provider="p",
        prompt_tokens=1000,
        completion_tokens=10,
        estimated=False,
        cache_read_tokens=800,
        cache_write_tokens=0,
    )
    print(f"[1 记账] last_call 形状 = {sorted(payload)} cache_read={payload['cache_read_tokens']}")

    # 2) 组成快照（生产在 LLM 调用前落的同一份）
    before = measure_composition(agentId, MESSAGES, None, session_id="s-1")
    assert before["cache_source"] != "provider", f"调用前就报 provider？{before['cache_source']}"
    print(f"[2 调用前快照] cache_source={before['cache_source']} total_tokens={before['total_tokens']}")

    # 3) 生产回填点（真 ChatPipeline 方法，读真 last_call）
    ctx = SimpleNamespace(session_id="s-1")
    applied = _pipeline(agentId)._backfillProviderCacheUsage(ctx)
    after = get_last_composition(agentId, "s-1")
    sess = get_last_composition(agentId, "s-1")
    assert applied, "回填未生效 —— 生产链路没接通"
    assert after["cache_source"] == "provider", f"口径未改：{after['cache_source']}"
    assert abs(after["cache_hit_rate"] - 0.8) < 1e-9, f"命中率算错：{after['cache_hit_rate']}"
    print(f"[3 回填] applied={applied} cache_source={after['cache_source']} 命中率={after['cache_hit_rate']}")

    # 4) 组成其余字段逐字不变（回填不得重算组成）
    for field in ("total_tokens", "messages", "tools", "measured_at"):
        assert after[field] == before[field], f"回填改动了组成字段 {field}：{after[field]} != {before[field]}"
    print(f"[4 组成不变] total_tokens={after['total_tokens']} measured_at={after['measured_at']} 逐字相同=True")

    # 5) 会话维度快照（前端环图读的那份）同批更新
    assert sess is not None and sess["cache_source"] == "provider", f"会话快照未更新：{sess}"
    print(f"[5 会话快照] session_id=s-1 cache_source={sess['cache_source']} 命中率={sess['cache_hit_rate']}")

    # 6) 无真值不得伪装成实测（清空记账器 → last_call() 返回 None）
    reset_usage_accounting()
    measure_composition(agentId, MESSAGES, None, session_id="s-3")
    changed = _pipeline(agentId)._backfillProviderCacheUsage(SimpleNamespace(session_id="s-3"))
    final = get_last_composition(agentId, "s-3")
    assert not changed and final["cache_source"] != "provider", (
        f"无真值时把估算伪装成了实测：changed={changed} source={final['cache_source']}"
    )
    print(f"[6 无真值] 口径未被改写：changed={changed} cache_source={final['cache_source']}")

    print("LIVE-VERIFY PASSED")


if __name__ == "__main__":
    main()
