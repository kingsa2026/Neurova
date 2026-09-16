# -*- coding: utf-8 -*-
"""preflight torch 探测结果按 解释器+torch 安装件 缓存——启动慢根修回归。

2026-09-16 实测：preflight_torch_runtime 每次启动同步 spawn `python -c "import torch"`
子进程（≈1.2s），且它在启动关键路径最前段。torch DLL/VC++ 属机器级稳定状态，
探测成功后无需每次复探；失败**绝不缓存**（每次启动照旧重试自愈）。

契约（对齐 health_check 依赖探测"按解释器缓存/异常不可用不抛出"先例）：
- 缓存键含 sys.executable + 解释器版本 + torch 包路径与 __init__.py mtime，
  任一变化（升级/重装/换解释器）→ 缓存失效重新探测；
- 探测结果与"启动时模型下载检测"无关：模型就绪是运行期文件存在性检查，
  本缓存只跳过 torch DLL 探测，不得吞掉任何模型下载触发。
"""
from __future__ import annotations

from unittest import mock

from neurova.core import env_check


def _isolate(tmp_path, monkeypatch, windows=True):
    marker = tmp_path / "env_check_torch.json"
    monkeypatch.setenv("NEUROVA_ENV_CHECK_MARKER", str(marker))
    monkeypatch.setattr(env_check, "_IS_WINDOWS", windows)
    return marker


def test_ok_probe_cached_skips_second_probe(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    probe = mock.Mock(return_value=True)
    monkeypatch.setattr(env_check, "torch_imports_ok", probe)

    env_check.preflight_torch_runtime()
    env_check.preflight_torch_runtime()

    assert probe.call_count == 1, "第二次启动未命中缓存，1.2s 子进程探测照跑"


def test_failure_is_not_cached(tmp_path, monkeypatch):
    marker = _isolate(tmp_path, monkeypatch)
    probe = mock.Mock(return_value=False)
    monkeypatch.setattr(env_check, "torch_imports_ok", probe)
    monkeypatch.setattr(env_check, "detect_torch_dll_problem", lambda: None)

    env_check.preflight_torch_runtime()
    env_check.preflight_torch_runtime()

    assert probe.call_count == 2, "探测失败被缓存 = 吞掉自愈重试"
    assert not marker.exists()


def test_cache_invalidated_when_torch_changes(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    probe = mock.Mock(return_value=True)
    monkeypatch.setattr(env_check, "torch_imports_ok", probe)

    env_check.preflight_torch_runtime()
    # 模拟 torch 升级/重装：指纹变化（路径/内容变，缓存必须作废）
    orig = env_check._torch_fingerprint
    monkeypatch.setattr(env_check, "_torch_fingerprint", lambda: orig() + "|v2")
    env_check.preflight_torch_runtime()

    assert probe.call_count == 2


def test_non_windows_noop_untouched(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, windows=False)
    probe = mock.Mock(return_value=True)
    monkeypatch.setattr(env_check, "torch_imports_ok", probe)

    env_check.preflight_torch_runtime()

    probe.assert_not_called()
