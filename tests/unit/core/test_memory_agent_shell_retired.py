"""兼容壳 `neurova/memory_agent.py` 的退役守卫（纯静态，零导入）。

背景：记忆中枢在 `dc9b9a0f`「记忆系统架构统一」里由 `memory_agent` 迁为
`mem_core.MemCore`，壳文件只为兜住"旧导入路径还有人用"这一种可能。实测生产零引用，
它唯一的消费者是把壳自身钉住的三条断言（原 `test_mem_core_bugfix.py` 的 BUG 2 段）
——兼容层由自己的回归测试供养，没有任何访客走这条路。

本次把方向反过来钉：旧导入路径必须无人引用。壳已删，若日后有人再按旧路径 import，
会在 CI 红而不是到运行时才 ImportError。

全静态、不导入被测模块：`neurova.mem_core` 的导入有副作用，会扰动同目录用例的共享状态。
"""

import ast
import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_SHELL_PATH = _REPO_ROOT / "neurova" / "memory_agent.py"
_MEM_CORE = _REPO_ROOT / "neurova" / "mem_core.py"
_AGENT_CORE = _REPO_ROOT / "neurova" / "agent_core.py"

# 扫描面：仓库内的 Python 代码树。构建期副本（NeurUI/src-tauri/**）与虚拟环境不算使用方。
_SOURCE_ROOTS = ("neurova", "tests", "scripts")
_OLD_IMPORT_PATH = re.compile(r"neurova[./]memory_agent\b|from\s+\.+memory_agent\b")


def _sourceFiles():
    for rel in _SOURCE_ROOTS:
        root = _REPO_ROOT / rel
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if path == pathlib.Path(__file__):
                continue  # 本守卫在正文与正则里点名旧路径，不构成使用方
            yield path


def test_compatShellModuleRetired():
    assert not _SHELL_PATH.exists(), (
        "兼容壳 neurova/memory_agent.py 仍在原位——退役未完成；"
        "若确需复活，请先给出按旧路径导入的真实使用方"
    )


def test_noSourceStillImportsRetiredPath():
    offenders = []
    for path in _sourceFiles():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if _OLD_IMPORT_PATH.search(text):
            offenders.append(path.relative_to(_REPO_ROOT).as_posix())
    assert not offenders, (
        "有源码仍引用已退役的导入路径，运行时必 ImportError：" + "、".join(sorted(offenders))
    )


def test_realMemCorePathIntact():
    """退役不能把真路径一起带走：MemCore 定义仍在，Agent 的接线仍指向它。"""
    tree = ast.parse(_MEM_CORE.read_text(encoding="utf-8"))
    assert any(
        isinstance(n, ast.ClassDef) and n.name == "MemCore" for n in tree.body
    ), "MemCore 类定义不再位于 mem_core.py，真路径需重新认定"

    wiring = _AGENT_CORE.read_text(encoding="utf-8")
    assert re.search(r"\bmemory_agent\s*=\s*MemCore\(", wiring), (
        "agent_core.py 不再把 MemCore 实例挂到 agent.memory_agent 属性，"
        "本守卫的'真路径'前提已变，需同步更新"
    )
