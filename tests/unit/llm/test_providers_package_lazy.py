# -*- coding: utf-8 -*-
"""llm.providers 包惰性化（2026-11-24 启动性能根修）。

红灯依据：包 __init__ 顶层 import 全部 7 个 provider 实现，连带
langchain-anthropic / anthropic / langchain-ollama 等重依赖链（首载实测
~3.8s）。只取轻量子模块（types/secret_store_clean/rate_limiter）的
provider_manager、multi_model_client 也被被迫加载全部适配器——这段成本
落在每次后端启动的关键路径上。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

_HEAVY_PREFIXES = ("langchain", "anthropic", "google.genai", "ollama")
_HEAVY_TUPLE = "(" + ", ".join(repr(p) for p in _HEAVY_PREFIXES) + ")"

_PROBE_CODE = (
    "import sys;"
    "import neurova.llm.provider_manager;"
    "import neurova.llm.multi_model_client;"
    f"heavy = sorted(m for m in sys.modules if m.startswith({_HEAVY_TUPLE}));"
    "assert not heavy, 'light modules dragged heavy deps: %s' % heavy;"
    "print('OK')"
)


def _run_probe() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _PROBE_CODE],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(_REPO_ROOT),
        env=os.environ.copy(),
    )


def test_light_modules_do_not_drag_provider_implementations():
    """import provider_manager / multi_model_client 不得连带加载 langchain 适配器。"""
    proc = _run_probe()
    assert proc.returncode == 0, (
        "轻量模块 import 被重依赖拖累或探测脚本失败：\n"
        f"stdout={proc.stdout[-1000:]}\nstderr={proc.stderr[-2000:]}"
    )
    assert "OK" in proc.stdout


def test_lazy_attribute_access_loads_and_caches():
    """`from neurova.llm.providers import X` 契约保持：首访加载并固化。"""
    import neurova.llm.providers as providers_pkg

    cls = providers_pkg.AnthropicProvider
    assert cls is not None
    # 首访后固化为真模块属性，后续访问走常规查找（不再进 __getattr__）
    assert providers_pkg.AnthropicProvider is cls


def test_dir_includes_lazy_public_names():
    import neurova.llm.providers as providers_pkg

    names = dir(providers_pkg)
    for expected in ("AnthropicProvider", "OpenAIProvider", "BaseProvider", "ConnectionResult"):
        assert expected in names, f"dir() 缺少公开名 {expected}"


def test_unknown_attribute_still_raises_attribute_error():
    import neurova.llm.providers as providers_pkg

    try:
        providers_pkg.DefinitelyNotAProvider
    except AttributeError:
        pass
    else:
        raise AssertionError("未知属性必须抛 AttributeError")
