# -*- coding: utf-8 -*-
"""P0-4 工具结果截断显式化：head+tail + 截断标注（模型必须知道被截了）。

Codex 对齐（docs/Neurova_Codex代码级对比_2026-09-14.md §2.7/P0-4）：
- 可重现超阈值：全文落盘 + 消息体=head+tail+截断标注（原为 head-only 预览）
- 不可重现超阈值：同样全文落盘保全 + 消息体 head+tail+标注 + recall 指针
  （契约变更：原"全文直进窗口"会在窗口内被折叠丢失；落盘文件成为全文真相，
   且文件写失败时 fail-open 原样放行，保真方向不变）
- 未超阈值：零行为变化
"""
import pytest


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "ws").mkdir()
    return tmp_path / "ws"


@pytest.fixture(autouse=True)
def _threshold_default(monkeypatch, ws):
    monkeypatch.delenv("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB", raising=False)
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_SETTINGS", str(ws / "none.json"))


class TestHeadTailPreview:
    def test_reproducible_oversize_head_tail_with_marker(self, ws):
        from neurova.core.tool_offload import apply_offload_policy

        big = "H" * 30 + "M" * 90000 + "T" * 30
        out = apply_offload_policy(
            tool_name="file_read", call_id="c10", content=big,
            reproducible=True, workspace_root=ws,
        )
        assert out.offloaded is True
        assert (ws / out.offload_path).read_text(encoding="utf-8") == big  # 全文一条不丢
        assert "H" * 30 in out.content       # 头部保留
        assert "T" * 30 in out.content       # 尾部保留
        assert "M" * 1000 not in out.content  # 中段不进窗口
        assert "截断" in out.content          # 显式标注
        assert "recall_history" in out.content  # 取回路径指引
        assert str(len(big)) in out.content     # 原始体量可见

    def test_non_reproducible_oversize_now_offloads_with_head_tail(self, ws):
        """契约变更：不可重现超阈值也落盘保全+head+tail（防窗口内折叠丢失）。"""
        from neurova.core.tool_offload import apply_offload_policy

        big = "A" * 20 + "B" * 120000 + "C" * 20
        out = apply_offload_policy(
            tool_name="run_code", call_id="c11", content=big,
            reproducible=False, workspace_root=ws,
        )
        assert out.offloaded is True
        assert (ws / out.offload_path).read_text(encoding="utf-8") == big
        assert out.content != big
        assert "A" * 20 in out.content and "C" * 20 in out.content
        assert "B" * 1000 not in out.content
        assert "截断" in out.content

    def test_non_reproducible_write_failure_fails_open(self, ws, monkeypatch):
        """落盘失败 → fail-open 原样放行（保真优先，既有语义保持）。"""
        from neurova.core import tool_offload as to

        def _boom(self, *a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(to.Path, "write_text", _boom)
        big = "F" * 120000
        out = to.apply_offload_policy(
            tool_name="run_code", call_id="c12", content=big,
            reproducible=False, workspace_root=ws,
        )
        assert out.offloaded is False
        assert out.content == big

    def test_small_output_untouched(self, ws):
        from neurova.core.tool_offload import apply_offload_policy

        out = apply_offload_policy(
            tool_name="file_read", call_id="c13", content="tiny",
            reproducible=False, workspace_root=ws,
        )
        assert out.offloaded is False
        assert out.content == "tiny"

    def test_moderate_oversize_head_only_shape(self, ws):
        """略超阈值（不足 2×preview）时头部+标注即可，无中段省略行。"""
        from neurova.core.tool_offload import apply_offload_policy

        big = "S" * 100000
        out = apply_offload_policy(
            tool_name="file_read", call_id="c14", content=big,
            reproducible=True, workspace_root=ws,
        )
        assert out.offloaded is True
        assert "S" * 100 in out.content
        assert "截断" in out.content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
