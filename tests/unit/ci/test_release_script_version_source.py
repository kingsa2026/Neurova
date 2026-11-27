# -*- coding: utf-8 -*-
"""发布脚本版本事实源（fullrepo 审计 2026-11-18 D 组）。

红灯依据：create_github_release.py 硬编码 CURRENT_VERSION="v0.0.1"/
NEXT_VERSION="v0.0.2"，从不读 neurova.__version__（现值
1.0.0-beta14）——照它打 tag 会开出 v0.0.2 这种与代码无关的版本；
且发布说明模板链到仓里不存在的 CONTEXT.md（死链）。
"""
import importlib.util
from pathlib import Path

import neurova

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT_ROOT / "create_github_release.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("create_github_release", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_release_tag_version_comes_from_code_single_source():
    mod = _load_script()
    assert mod.NEXT_VERSION == f"v{neurova.__version__}", (
        "发布脚本打 tag 的版本必须读 neurova.__version__ 单源"
        f"（现 {mod.NEXT_VERSION!r} vs 代码 v{neurova.__version__!r}）"
    )


def test_dead_version_constant_and_context_link_retired():
    text = SCRIPT.read_text(encoding="utf-8")
    mod = _load_script()
    assert not hasattr(mod, "CURRENT_VERSION"), "无人消费的 CURRENT_VERSION 死常量应退役"
    assert "CONTEXT.md" not in text, "发布模板不得再链仓里不存在的 CONTEXT.md"


def test_release_install_command_uses_compiled_lock():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "pip install -r requirements-full.lock" in text, (
        "发布说明必须引导用户安装完整锁，不能退回未锁定的 requirements.txt"
    )
    assert "pip install -r requirements.txt" not in text, (
        "发布说明仍含旧安装命令"
    )
