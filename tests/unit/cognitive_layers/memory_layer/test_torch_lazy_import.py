"""memory_field 惰性导出防回归（内存优化 H1：torch 白拉 +176MB）。

契约（2026-09-08 内存分析报告 H1）：
1. 导入 memory_layer 任一子模块不得拉入 torch（MemoryField 运行时零消费方，
   torch 导入即 +176MB）；
2. `from ... import MemoryFieldXxx` 等历史 API 仍可用（惰性加载后返回真值）；
3. torch 缺失时属性访问保持历史 fail-soft 语义（AttributeError，不崩）。
"""

import subprocess
import sys


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=300
    )


def test_import_submodule_does_not_load_torch():
    r = _run(
        "import neurova.cognitive_layers.memory_layer.unified_vector_store, sys; "
        "assert 'torch' not in sys.modules, 'torch 被包 __init__ 急切拉入'"
    )
    assert r.returncode == 0, r.stderr


def test_lazy_attribute_access_still_works():
    r = _run(
        "from neurova.cognitive_layers.memory_layer import MemoryFieldConfig; "
        "import sys; assert 'torch' in sys.modules; print('ok')"
    )
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr


def test_missing_torch_fail_soft():
    # sys.modules["torch"]=None → `import torch` 抛 ImportError；
    # 历史行为：急切导入 fail-soft，名字不可见（AttributeError）。惰性化后须保持。
    code = (
        "import sys; sys.modules['torch'] = None; "
        "import neurova.cognitive_layers.memory_layer as ml; "
        "soft = False\n"
        "try:\n"
        "    ml.MemoryFieldConfig\n"
        "except AttributeError:\n"
        "    soft = True\n"
        "assert soft, 'expected AttributeError'\n"
        "print('soft-ok')"
    )
    r = _run(code)
    assert r.returncode == 0 and "soft-ok" in r.stdout, r.stderr
