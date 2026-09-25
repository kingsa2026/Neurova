# -*- coding: utf-8 -*-
"""Issue #55 缓存收敛守卫：模型能力缓存不得出现两个"生产事实源"。

背景：仓库里出现两份"模型能力缓存"——

1. ``neurova/llm/model_capability_cache.py::ModelCapabilityCache``
   ——学习型（试错发现的行为），**生产路径唯一消费者**：
   ``llm/provider_manager.py`` 用 learn()/get() 记住"某模型拒绝图片"这类事实。
2. ``neurova/llm/providers/capability_cache.py::CapabilityCache``
   ——探测结果持久化（JSON），配套 ``providers/capability_detector.py``；
   生产零消费，仅离线探测工具链/回归测试引用。

两份并存本身可接受（语义不同：学习事实 vs 探测结果），但**不能再多**，
且第二份必须显式标注"非生产路径"，否则下一个接入者会挑错一份，
仪表盘/路由读到过期或造出来的能力值。

本守卫钉住三件事：
- 生产代码里只允许 model_capability_cache 被 import；
- providers/capability_cache 必须有"非生产路径/单一事实源"标注；
- 不允许出现第三份能力缓存模块。
"""

import ast
import io
import re
from pathlib import Path

import pytest

from tests import ast_scan

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NEUROVA = PROJECT_ROOT / "neurova"

PRODUCTION_CAPABILITY_CACHE = "neurova.llm.model_capability_cache"
OFFLINE_CAPABILITY_CACHE = "neurova.llm.providers.capability_cache"

# 允许出现的"模型能力缓存"模块清单（新增即需在此留痕 + 说明语义差异）
KNOWN_CAPABILITY_CACHE_MODULES = {
    "neurova/llm/model_capability_cache.py",
    "neurova/llm/providers/capability_cache.py",
}

# providers/capability_cache.py 内的 CapabilityCache（探测栈），与
# providers/capability_detector.py 同文件内的 CapabilityCache 是同一套。
# 生产路径禁止 import 后者。
FORBIDDEN_IN_PRODUCTION = (OFFLINE_CAPABILITY_CACHE, "neurova.llm.providers.capability_detector")


def _iterProductionPy():
    """生产侧源码路径（解析走 `tests/ast_scan.py` 的共享预算）。"""
    return ast_scan.filesUnder(NEUROVA)


class TestSingleProductionSource:
    @pytest.mark.parametrize("module", FORBIDDEN_IN_PRODUCTION)
    def test_offline_cache_not_imported_in_production(self, module):
        offenders = []
        for path, node in ast_scan.nodeScan(NEUROVA, hints=(module,)):
            rel = ast_scan.relativeToRepo(path)
            if rel.startswith("neurova/llm/providers/"):
                # 探测栈内部自引用（providers 包 / 探测模块）不算生产接入
                continue
            if isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith(module):
                    offenders.append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(module):
                        offenders.append(f"{rel}:{node.lineno}")
        assert not offenders, (
            f"生产代码引用了离线探测能力缓存 {module}：{offenders}\n"
            f"生产唯一事实源是 {PRODUCTION_CAPABILITY_CACHE}（学习型，"
            "provider_manager 读写）。需要能力缓存请用后者。"
        )

    def test_learning_cache_is_the_production_consumer(self):
        src = io.open(NEUROVA / "llm" / "provider_manager.py", encoding="utf-8").read()
        assert "model_capability_cache" in src, (
            "生产学习型能力缓存的消费方是 provider_manager，不得被摘掉"
        )


class TestOfflineCacheLabelled:
    def test_module_docstring_marks_non_production(self):
        src = io.open(
            NEUROVA / "llm" / "providers" / "capability_cache.py", encoding="utf-8"
        ).read()
        doc = ast.get_docstring(ast.parse(src)) or ""
        assert "非生产路径" in doc, (
            "providers/capability_cache.py 必须显式标注'非生产路径/单一事实源'，"
            "否则下一个接入者会把两份缓存挑错"
        )
        assert "model_capability_cache" in doc, (
            "标注里必须点名生产事实源，形成可跳转的路标"
        )


class TestNoThirdCapabilityCache:
    def test_no_new_capability_cache_module(self):
        found = set()
        for path in _iterProductionPy():
            rel = ast_scan.relativeToRepo(path)
            if re.search(r"capability_cache\.py$", rel) or re.search(
                r"model_capability_cache\.py$", rel
            ):
                found.add(rel)
        extra = found - KNOWN_CAPABILITY_CACHE_MODULES
        assert not extra, (
            f"出现第三份能力缓存模块: {sorted(extra)}。\n"
            "能力缓存必须收敛——先在 KNOWN_CAPABILITY_CACHE_MODULES 说明语义差异，"
            "或直接复用 model_capability_cache。"
        )

    def test_known_modules_still_exist(self):
        missing = [m for m in KNOWN_CAPABILITY_CACHE_MODULES if not (PROJECT_ROOT / m).exists()]
        assert not missing, f"已登记的能力缓存模块丢失: {missing}"
