# -*- coding: utf-8 -*-
"""T-20 反向守卫：``cognitive_layers/model_adapter`` 整块退役后不得复活。

裁决与施工单见 ``docs/04-plans/2026-10-02-model-adapter-retirement-plan.md``：
该块预置未接线且一调即炸（转发行 kwarg 撞车、兜底适配器调不存在的方法、
凭据源断链），能力面由现役 ``llm/capability_detector.py`` 族表单源承接。

七条判据分三个轴向，防"退役把能力面删薄了"或"死码悄悄回来"：

**仓库态（该不该存在）**
- ① 退役目录不存在；
- ② 退役包下无任何**跟踪态**文件（`git ls-tree`，不看磁盘）；
- ③ 挂载表 `ENDPOINT_MODULES` 不含 ``/v1/model-adapter``（按 AST 取表项，理由见下）；
- ④ 生产源码中退役块符号（AdapterCapabilities / BaseModelAdapter /
  get_model_adapter_registry）命中为 0。

**运行态（能不能被 import）**
- ⑤ 退役包与其三个子模块一律不可解析。这条不是凑数：``git rm`` 只删跟踪的 ``.py``，
  本地会留下**只含 ``__pycache__`` 的目录**，而 Python 3 把它当**命名空间包**——
  T-20 重复交付批次在本机实测 ``import neurova.cognitive_layers.model_adapter`` 仍返回
  spec（``STILL IMPORTABLE``）。① 之外的"仓库里有没有"类判据全绿也看不见这个影子，
  只有落到能不能被解析才咬得住。

**反向控制（判据不许空转）**
- ⑥ 挂载表邻居仍在（>20 条）——防 ③ 靠"整表被清空"或解析退化蒙对；
- ⑦ 现役族表能答出退役块答得出的东西——六族模型推断到具体能力而非兜底 ``['text']``
  （本条在改前即预验为绿，落进判据是防它将来被改坏）。

③ 为什么按 AST 而不是按子串扫整份文件：这条判据要问的是**挂载表里有没有这一条**。
子串扫会把注释与文档串里"某路由已按 T-20 退役"这类留痕行也当命中，于是**在代码里记一笔
退役说明反而把自己判红**——那是判据的错，不是留痕的错，而且会教后来人别留痕。
"""

import ast
import importlib.util
import subprocess
from pathlib import Path

import pytest

from neurova.llm.capability_detector import infer_capabilities
from tests.ast_scan import parseSource

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: `git ls-tree` 的预算唯一出处（毫秒级；此前无 `timeout=`＝无界等待）。取低于全局 30s 的
#: 20s——先到点的应当是子进程那条诚实的 TimeoutExpired，而不是 thread 法的全局墙
#: （§6-402 批 K 口径）。
GIT_WALL_S = 20
NEUROVA = PROJECT_ROOT / "neurova"

RETIRED_PACKAGE = "neurova/cognitive_layers/model_adapter"
RETIRED_PACKAGE_DOTTED = "neurova.cognitive_layers.model_adapter"
RETIRED_DIR = NEUROVA / "cognitive_layers" / "model_adapter"
ENDPOINT_INIT = NEUROVA / "api" / "endpoints" / "__init__.py"
RETIRED_ROUTE = "/v1/model-adapter"
RETIRED_SYMBOLS = ("AdapterCapabilities", "BaseModelAdapter", "get_model_adapter_registry")

# T-20 施工单 S0④ 的六族读数（2026-10-02 预验 + 本判据入库时复验一致）
FAMILY_EXPECTATIONS = {
    "kimi-k2": ["text", "tool_use"],
    "moonshot-v1-128k": ["text", "tool_use"],
    "hunyuan-image": ["image_generation"],
    "deepseek-chat": ["text", "tool_use"],
    "glm-5": ["text", "reasoning", "tool_use"],
    "claude-sonnet-4": ["text", "vision", "tool_use"],
}


def _mountedPrefixes() -> list:
    """按 AST 取 ``ENDPOINT_MODULES`` 各元组的第二项（挂载前缀）。"""
    tree = parseSource(ENDPOINT_INIT.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ENDPOINT_MODULES" for t in node.targets
        ):
            return [
                elt.elts[1].value
                for elt in node.value.elts
                if isinstance(elt, ast.Tuple) and len(elt.elts) >= 2
                and isinstance(elt.elts[1], ast.Constant) and isinstance(elt.elts[1].value, str)
            ]
    raise AssertionError("ENDPOINT_MODULES 挂载表在 __init__.py 里找不到了——轴向变了，先修判据再谈红绿")


def _resolves(moduleName: str) -> bool:
    """该模块名在运行态能否被解析。

    ``importlib.util.find_spec`` 对**父包都不存在**的子模块名是抛 ``ModuleNotFoundError``，
    不是回 ``None``（T-20 批次第一版就把这两态混为一谈，于是干净态反被判红）；
    父包存在而子模块缺失才回 ``None``。两种"取不到"都算不可解析。
    """
    try:
        return importlib.util.find_spec(moduleName) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _trackedFilesUnder(prefix: str) -> list:
    """取 HEAD 提交里的跟踪态路径——磁盘残留不算"仓库里有"（问 git 不问磁盘）。"""
    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", prefix],
        cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=GIT_WALL_S,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return [line for line in proc.stdout.splitlines() if line.strip()]


class TestNoParallelVendorCapabilitySurface:
    def test_retiredModelAdapterDirectoryIsGone(self):
        assert not RETIRED_DIR.exists(), (
            f"退役块 {RETIRED_DIR} 重新出现——model_adapter 已按 T-20 裁决退役，"
            "能力声明与厂商路由由 neurova/llm/capability_detector.py 单源承接，不得回填。"
        )

    def test_noTrackedFileUnderRetiredPackage(self):
        tracked = _trackedFilesUnder(RETIRED_PACKAGE)
        assert not tracked, f"退役包下仍有跟踪态文件：{tracked[:4]}（共 {len(tracked)}）"

    def test_mountTableHasNoModelAdapterRoute(self):
        assert RETIRED_ROUTE not in _mountedPrefixes(), (
            f"{RETIRED_ROUTE} 仍挂在 ENDPOINT_MODULES——包都退役了路由还活着就是空壳端点")

    def test_mountTableStillHasNeighbours(self):
        """反向控制：邻居必须还在，否则上一条是"整表为空"蒙对的。"""
        mounted = _mountedPrefixes()
        assert len(mounted) > 20, f"挂载表只剩 {len(mounted)} 条，路由判据已失去意义"

    def test_productionSourceHasNoRetiredAdapterSymbols(self):
        offenders = []
        for py in NEUROVA.rglob("*.py"):
            rel = py.relative_to(PROJECT_ROOT).as_posix()
            for lineno, line in enumerate(py.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                for symbol in RETIRED_SYMBOLS:
                    if symbol in line:
                        offenders.append(f"{rel}:{lineno} {symbol}")
        assert not offenders, f"生产源码仍引用退役块符号：{offenders[:6]}（共 {len(offenders)}）"

    def test_retiredPackageUnresolvableAtRuntime(self):
        stillResolvable = [
            name for name in (
                RETIRED_PACKAGE_DOTTED,
                f"{RETIRED_PACKAGE_DOTTED}.base",
                f"{RETIRED_PACKAGE_DOTTED}.registry",
                f"{RETIRED_PACKAGE_DOTTED}.builtin",
            )
            if _resolves(name)
        ]
        assert not stillResolvable, (
            f"退役包在运行态仍可解析：{stillResolvable}——若只是本机残留只含 __pycache__ 的"
            "目录（Python 视其为命名空间包），删掉该目录即可；若有人回填了源码，"
            "按 T-20 裁决不予恢复。"
        )

    @pytest.mark.parametrize("modelId,expectedCaps", sorted(FAMILY_EXPECTATIONS.items()))
    def test_familyTableInfersConcreteCapabilities(self, modelId, expectedCaps):
        caps = infer_capabilities(modelId)
        assert caps == expectedCaps, (
            f"现役族表对 {modelId} 只答出 {caps}（期望 {expectedCaps}）——"
            "能力面被删薄或族表被改坏，退役前提（替代源更宽）不再成立。"
        )
