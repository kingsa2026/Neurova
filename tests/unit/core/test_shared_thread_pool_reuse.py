# -*- coding: utf-8 -*-
"""P1 共享线程池回归（Issue #55）：热路径不得每次创建/销毁线程池。

原状：
- neurova/agent/tool_pipeline.py:430 `with ThreadPoolExecutor(...)` 每次
  pipeline 执行创建并销毁池；
- neurova/mem_core.py:200 每次 run_async_safely 新建池；
- neurova/asr/manager.py:154 同理；
而 core/thread_pool.py 的共享单例只有 neurova_recall.py 在用。

本套件钉住：三处都改走共享具名池，同一 name 复用同一实例。
"""

import ast
import io
from pathlib import Path

import pytest

from neurova.core.thread_pool import (
    DEFAULT_POOL_NAME,
    ThreadPoolManager,
    get_thread_pool,
    shutdown_thread_pool,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _reset_pool_manager():
    shutdown_thread_pool(wait=False)
    yield
    shutdown_thread_pool(wait=False)


def _tree(rel_path: str) -> ast.AST:
    return ast.parse(io.open(PROJECT_ROOT / rel_path, encoding="utf-8").read())


def _constructed_pool_names(tree: ast.AST) -> list:
    """源码里所有 `ThreadPoolExecutor(...)` 调用（含 with 语句形态）。"""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "ThreadPoolExecutor":
                found.append(ast.unparse(node))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "ThreadPoolExecutor":
                found.append(ast.unparse(node))
    return found


class TestNoPerCallPoolCreation:
    """生产热路径不得再直接 new ThreadPoolExecutor。"""

    @pytest.mark.parametrize(
        "rel_path",
        [
            "neurova/agent/tool_pipeline.py",
            "neurova/mem_core.py",
            "neurova/asr/manager.py",
        ],
    )
    def test_no_direct_thread_pool_construction(self, rel_path):
        names = _constructed_pool_names(_tree(rel_path))
        # tool_pipeline 仍 import 名字（as_completed 用），但不得实例化
        assert not names, (
            f"{rel_path} 仍在直接构造线程池: {names}——每次调用创建/销毁是纯开销，"
            f"应改用 neurova.core.thread_pool.get_thread_pool(name=...)"
        )

    @pytest.mark.parametrize(
        "rel_path,pool_name",
        [
            ("neurova/agent/tool_pipeline.py", "tool-pipeline"),
            ("neurova/mem_core.py", "mem-async-bridge"),
            ("neurova/asr/manager.py", "asr-consent"),
        ],
    )
    def test_site_uses_named_shared_pool(self, rel_path, pool_name):
        src = io.open(PROJECT_ROOT / rel_path, encoding="utf-8").read()
        assert "get_thread_pool(" in src, f"{rel_path} 未接入共享线程池"
        assert pool_name in src, (
            f"{rel_path} 未用具名池 {pool_name!r}——具名才能隔离 busy 面"
        )


class TestSharedPoolSemantics:
    """共享池本身：同一 name 同实例、跨 name 隔离、线程数只注册一次。"""

    def test_same_name_returns_same_instance(self):
        assert get_thread_pool() is get_thread_pool()
        assert get_thread_pool(DEFAULT_POOL_NAME) is get_thread_pool()

    def test_named_pools_are_isolated(self):
        a = get_thread_pool(name="pool-a", max_workers=2)
        b = get_thread_pool(name="pool-b", max_workers=2)
        assert a is not b

    def test_max_workers_registered_once(self):
        """两个调用方对同一 name 传不同 max_workers：以首次注册为准，不互相改。"""
        first = get_thread_pool(name="stable-size", max_workers=3)
        second = get_thread_pool(name="stable-size", max_workers=9)
        assert first is second
        assert first._max_workers == 3

    def test_thread_name_prefix_carries_pool_name(self):
        pool = get_thread_pool(name="named-prefix", max_workers=1)
        pool.submit(lambda: None).result()
        names = {t.name for t in __import__("threading").enumerate()}
        assert any("named-prefix" in n for n in names), (
            "线程名前缀应含池名，线程栈排查才分得清来源"
        )

    def test_manager_singleton(self):
        assert ThreadPoolManager() is ThreadPoolManager()

    def test_shutdown_clears_pools(self):
        pool = get_thread_pool(name="to-close", max_workers=1)
        shutdown_thread_pool(wait=False)
        assert get_thread_pool(name="to-close", max_workers=1) is not pool
