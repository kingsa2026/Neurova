# -*- coding: utf-8 -*-
"""全量回归死锁根修 · 诊断路径禁止触发重 import。

实测（2026-11-20，/tmp/unit_rest.log Timeout dump）：`encodeOrNone` 未就绪时的
debug 日志路径 `_unreadyReason()` 真去 `import sentence_transformers`，把
sentence_transformers→sklearn→scipy 整条重链拉起来（首次 60s+），pytest-timeout
当场判死、进程 os._exit，全量跑拿不到汇总。诊断只需要「装没装」，用 find_spec
只定位不执行；本文件钉住：诊断路径不得尝试 import 重型栈。
"""

import builtins

import pytest

from neurova.embedding.onnx_embedding import ONNXEmbeddingEngine

_HEAVY_ROOTS = ("sentence_transformers", "sklearn", "scipy", "transformers", "onnxruntime")
# encodeOrNone 的懒初始化自救（initialize_sync）允许尝试 onnxruntime——那是「尝试真做事」；
# 60s 级卡死来自 sentence_transformers→sklearn→scipy 科学计算链，热路径一律禁止。
_SCIENCE_ROOTS = ("sentence_transformers", "sklearn", "scipy", "transformers")


@pytest.fixture()
def heavy_import_guard(monkeypatch):
    attempted = []
    real_import = builtins.__import__

    def _guard(name, *args, **kwargs):
        root = name.split(".")[0]
        if root in _HEAVY_ROOTS:
            attempted.append(name)
            raise AssertionError(f"诊断路径触发了重 import：{name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guard)
    return attempted


def _unready_engine(monkeypatch):
    engine = ONNXEmbeddingEngine(auto_download=False)
    monkeypatch.setattr(engine, "_initialized", False)
    return engine


class TestUnreadyReasonIsLightweight:
    def test_unready_reason_avoids_heavy_import(self, monkeypatch, heavy_import_guard):
        engine = _unready_engine(monkeypatch)
        reason = engine._unreadyReason()
        assert reason, f"诊断文案不得为空：{reason!r}"
        assert not heavy_import_guard, f"_unreadyReason 触发了重 import：{heavy_import_guard}"

    def test_encode_or_none_unready_keeps_light(self, monkeypatch):
        """热路径（encodeOrNone 未就绪分支）不得拉起科学计算链。"""
        attempted = []
        real_import = builtins.__import__

        def _guard(name, *args, **kwargs):
            root = name.split(".")[0]
            if root in _SCIENCE_ROOTS:
                attempted.append(name)
                raise AssertionError(f"encodeOrNone 触发了科学计算链 import：{name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _guard)
        engine = _unready_engine(monkeypatch)
        # 懒初始化自救（initialize_sync）是另一套机制、另有测试；这里把它桩掉，
        # 只验「未就绪分支本身」不拉科学计算链（其残骸见 2026-11-20 全量 Timeout dump）
        monkeypatch.setattr(engine, "initialize_sync", lambda: False)
        out = engine.encodeOrNone("许昌明天天气怎么样")
        assert out is None, "未就绪引擎不得交出向量"
        assert not attempted, f"encodeOrNone 触发了重 import：{attempted}"
