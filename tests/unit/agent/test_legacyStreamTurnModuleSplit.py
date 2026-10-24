# -*- coding: utf-8 -*-
"""legacy 流式读取循环必须留在独立模块里（性能门禁 hot-path 尺寸上限的常驻判据）。

背景：`ChatPipeline` 所在的 `neurova/agent/chat_pipeline.py` 是每轮对话的必经面，
`scripts/ci/perf_gate.py` 对它设了 160000B 上限。§6-405 那一批把退化守卫接进 legacy
流式路时，这段读取循环原地长了 77 行，尺寸从 159820B 顶到 164604B，perf-gate 因此红。

处置不是抬上限（那是教义第 2 条禁止的降级换绿），而是把读取循环抽到
`neurova/agent/legacy_stream_turn.py`。抽完仍然贴着上限（159771B / 160000B）——
只靠"这次抽了"守不住，下一次谁在原位加几行就又红。本判据把这件事钉成红/绿：

1. 读取循环的形状（显式迭代器 + 退化守卫 + 非空交代）只允许出现在独立模块里；
2. `ChatPipeline` 侧只做装配，不得再把循环抄回来；
3. 独立模块不得反向依赖 Agent（否则抽出即造环）。
"""
from __future__ import annotations

import io
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PIPELINE = PROJECT_ROOT / "neurova" / "agent" / "chat_pipeline.py"
LEGACY_TURN = PROJECT_ROOT / "neurova" / "agent" / "legacy_stream_turn.py"


class TestReadLoopLivesInItsOwnModule:
    def testLoopShapeIsInTheStandaloneModule(self):
        src = io.open(LEGACY_TURN, encoding="utf-8").read()
        for marker in (
            "__anext__",
            "ReasoningStreamGuard",
            "DEGENERATE_STREAM_STOPPED_NOTICE",
        ):
            assert marker in src, f"读取循环的形状不在独立模块里：缺 {marker}"

    def testPipelineOnlyAssembles(self):
        src = io.open(PIPELINE, encoding="utf-8").read()
        start = src.index("    async def _call_legacy_stream")
        end = src.index("    @staticmethod\n    def _raise_for_llm_error_dict")
        body = src[start:end]
        assert "consumeLegacyStream" in body, "装配点没有接上独立模块"
        for marker in ("__anext__", "ReasoningStreamGuard", "DEGENERATE_STREAM_STOPPED_NOTICE"):
            assert marker not in body, (
                f"读取循环被抄回 chat_pipeline（命中 {marker}）＝谁都能在原位继续加行，"
                "hot-path 尺寸上限会再次被顶穿"
            )

    def testStandaloneModuleDoesNotDependOnTheAgent(self):
        src = io.open(LEGACY_TURN, encoding="utf-8").read()
        for banned in ("from neurova.agent.chat_pipeline", "import chat_pipeline"):
            assert banned not in src, f"独立模块反向依赖了 chat_pipeline（{banned}）＝造环"
