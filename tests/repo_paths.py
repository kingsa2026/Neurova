# -*- coding: utf-8 -*-
"""仓库路径解析（跨平台）——测试内禁止硬编码开发机绝对路径。

根因（Issue #62）：`tests/unit/tools/test_tool_layer_breakpoints_zoom_out.py`
等 7 个测试文件把「盘符 + 仓库目录」形态的 Windows 开发机绝对路径写死进
`open()` / `subprocess.run(cwd=...)`。在 Linux/CI 上这些测试不是断言失败，
而是 `FileNotFoundError` 直接炸——守卫测试**根本没跑起来**，
`tool_router` 的静默 except / falsy registry 检查回归时 CI 会静默放行。
（写死路径的形态由 tests/unit/test_dev_path_and_runtime_dep_guards.py 常驻拦截。）

统一走本模块解析，路径来源=`__file__`（与 pyproject 的
`PROJECT_ROOT = Path(__file__).resolve().parents[N]` 同口径）。
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_path(*parts: str) -> Path:
    """仓库内路径（返回 Path，可直接喂 open()/cwd=）。"""
    return REPO_ROOT.joinpath(*parts)


def repo_str(*parts: str) -> str:
    """仓库内路径（字符串形态，供命令行参数/正则拼接用）。"""
    return str(repo_path(*parts))
