# -*- coding: utf-8 -*-
"""工具结果溢出分层 offload（P1 #6 触点2/3 核心判定）。

定稿（对比报告 §5.6 + P0-4 契约变更）：
  - 超阈值（可重现与否）→ 全文落工作区文件，消息体=head+tail+截断标注+指针
  - 落盘失败 → fail-open 全文原样（保真优先）
  - 未超阈值 → 原样
阈值：security/tool_offload_settings（默认 64KB，钳位 8–512KB，env 优先）。
"""
import json

import pytest

from neurova.core.tool_offload import apply_offload_policy, get_threshold_kb
from neurova.security import tool_offload_settings as tos


# ── 阈值设置层 ─────────────────────────────────────────────────────

def test_default_and_clamp(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_SETTINGS", str(tmp_path / "s.json"))
    monkeypatch.delenv("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB", raising=False)
    assert tos.load_settings()["threshold_kb"] == 64
    assert tos.save_settings({"threshold_kb": 2000}) is True
    assert tos.load_settings()["threshold_kb"] == 512  # 钳上限
    assert tos.save_settings({"threshold_kb": 1}) is True
    assert tos.load_settings()["threshold_kb"] == 8    # 钳下限


def test_env_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_SETTINGS", str(tmp_path / "s.json"))
    tos.save_settings({"threshold_kb": 128})
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB", "256")
    assert tos.load_settings()["threshold_kb"] == 256


def test_corrupt_file_falls_back_default(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    p.write_text("{{{", encoding="utf-8")
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_SETTINGS", str(p))
    monkeypatch.delenv("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB", raising=False)
    assert tos.load_settings()["threshold_kb"] == 64


# ── offload 判定 ──────────────────────────────────────────────────

@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "ws").mkdir()
    return tmp_path / "ws"


def test_under_threshold_passthrough(ws, monkeypatch):
    monkeypatch.delenv("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB", raising=False)
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_SETTINGS", str(ws / "none.json"))
    out = apply_offload_policy(
        tool_name="file_read", call_id="c1", content="short result",
        reproducible=True, workspace_root=ws,
    )
    assert out.offloaded is False
    assert out.content == "short result"
    assert out.offload_path is None


def test_reproducible_oversize_offloads_file_with_pointer(ws, monkeypatch):
    monkeypatch.delenv("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB", raising=False)
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_SETTINGS", str(ws / "none.json"))
    big = "数" * 40000  # ~120KB UTF-8 > 64KB
    out = apply_offload_policy(
        tool_name="file_read", call_id="c7", content=big,
        reproducible=True, workspace_root=ws,
    )
    assert out.offloaded is True
    target = ws / out.offload_path
    assert target.exists()
    assert target.read_text(encoding="utf-8") == big  # 全文一条不丢
    # 消息体 = 预览 + 指针
    assert out.content != big
    assert "tool_offload" in out.content or "offload" in out.content.lower()
    assert "c7" in out.content and out.content.startswith("[")


def test_non_reproducible_oversize_offloads_with_head_tail(ws, monkeypatch):
    """不可重现超阈值（P0-4 契约变更）：落盘保全全文 + head+tail+标注。

    原"全文直进窗口"会在窗口折叠中整段丢失；现在落盘文件是全文真相，
 消息体保留首尾+指针；落盘失败仍 fail-open 原样。
    """
    monkeypatch.delenv("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB", raising=False)
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_SETTINGS", str(ws / "none.json"))
    big = "y" * 400000
    out = apply_offload_policy(
        tool_name="run_code", call_id="c8", content=big,
        reproducible=False, workspace_root=ws,
    )
    assert out.offloaded is True
    target = ws / out.offload_path
    assert target.exists()
    assert target.read_text(encoding="utf-8") == big  # 全文一条不丢
    assert out.content != big
    assert out.content.startswith("[")
    assert "截断" in out.content


def test_no_workspace_falls_back_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB", "8")
    big = "z" * 30000
    out = apply_offload_policy(
        tool_name="web_fetch", call_id="c9", content=big,
        reproducible=True, workspace_root=None,
    )
    assert out.offloaded is True
    # 回退根：data/tool_offload/ 下可读回（文件名内容寻址 tool-sha16，不含 call）
    from pathlib import Path

    d = Path("data") / "outputs" / "tool_offload"
    found = list(d.glob("*.txt"))
    assert found and found[0].read_text(encoding="utf-8") == big
    assert out.offload_path.replace("\\", "/").endswith(".txt")
    for f in found:
        f.unlink()


def test_offload_filename_content_addressed(ws, monkeypatch):
    """同内容重复溢出幂等复用同一文件。"""
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB", "8")
    big = "same" * 5000
    a = apply_offload_policy("file_read", "c1", big, True, ws)
    b = apply_offload_policy("file_read", "c2", big, True, ws)
    assert a.offload_path == b.offload_path
