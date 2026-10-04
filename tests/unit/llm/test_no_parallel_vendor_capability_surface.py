# -*- coding: utf-8 -*-
"""T-20 反向守卫：``cognitive_layers/model_adapter`` 整块退役后不得复活。

裁决与施工单见 ``docs/04-plans/2026-10-02-model-adapter-retirement-plan.md``：
该块预置未接线且一调即炸（转发行 kwarg 撞车、兜底适配器调不存在的方法、
凭据源断链），能力面由现役 ``llm/capability_detector.py`` 族表单源承接。

本守卫钉四条否定式判据，防"退役把能力面删薄了"或"死码悄悄回来"：
- ① 退役目录不存在；
- ② 端点挂载表不含 ``/v1/model-adapter``（逐行读活表，不按文档）；
- ③ 生产源码中退役块的符号（AdapterCapabilities/BaseModelAdapter）命中为 0；
- ④ 现役族表能答出退役块答得出的东西——六族模型推断到具体能力而非兜底
  ``['text']``（本条在改前即预验为绿，落进判据是防它将来被改坏）。
"""

from pathlib import Path

import pytest

from neurova.llm.capability_detector import infer_capabilities

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NEUROVA = PROJECT_ROOT / "neurova"

RETIRED_DIR = NEUROVA / "cognitive_layers" / "model_adapter"
ENDPOINT_INIT = NEUROVA / "api" / "endpoints" / "__init__.py"
RETIRED_ROUTE = "/v1/model-adapter"
RETIRED_SYMBOLS = ("AdapterCapabilities", "BaseModelAdapter")

# T-20 施工单 S0④ 的六族读数（2026-10-02 预验 + 本判据入库时复验一致）
FAMILY_EXPECTATIONS = {
    "kimi-k2": ["text", "tool_use"],
    "moonshot-v1-128k": ["text", "tool_use"],
    "hunyuan-image": ["image_generation"],
    "deepseek-chat": ["text", "tool_use"],
    "glm-5": ["text", "reasoning", "tool_use"],
    "claude-sonnet-4": ["text", "vision", "tool_use"],
}


class TestNoParallelVendorCapabilitySurface:
    def test_retiredModelAdapterDirectoryIsGone(self):
        assert not RETIRED_DIR.exists(), (
            f"退役块 {RETIRED_DIR} 重新出现——model_adapter 已按 T-20 裁决退役，"
            "能力声明与厂商路由由 neurova/llm/capability_detector.py 单源承接，不得回填。"
        )

    def test_mountTableHasNoModelAdapterRoute(self):
        lines = ENDPOINT_INIT.read_text(encoding="utf-8").splitlines()
        hits = [f"第{i + 1}行: {line.strip()}" for i, line in enumerate(lines) if RETIRED_ROUTE in line]
        assert not hits, f"端点挂载表仍含已退役路由 {RETIRED_ROUTE}：{hits}"

    def test_productionSourceHasNoRetiredAdapterSymbols(self):
        offenders = []
        for py in NEUROVA.rglob("*.py"):
            rel = py.relative_to(PROJECT_ROOT).as_posix()
            for lineno, line in enumerate(py.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for symbol in RETIRED_SYMBOLS:
                    if symbol in line:
                        offenders.append(f"{rel}:{lineno}")
        assert not offenders, f"生产源码仍引用退役块符号 {RETIRED_SYMBOLS}：{offenders}"

    @pytest.mark.parametrize("modelId,expectedCaps", sorted(FAMILY_EXPECTATIONS.items()))
    def test_familyTableInfersConcreteCapabilities(self, modelId, expectedCaps):
        caps = infer_capabilities(modelId)
        assert caps == expectedCaps, (
            f"现役族表对 {modelId} 只答出 {caps}（期望 {expectedCaps}）——"
            "能力面被删薄或族表被改坏，退役前提（替代源更宽）不再成立。"
        )
