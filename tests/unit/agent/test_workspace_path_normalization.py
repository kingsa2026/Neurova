"""
工作区路径归一化测试（修复 growth 校验器父目录穿越误杀）

背景（启动性能排查 2026-09-09 顺带发现的真实缺陷）：app.py 构造默认工作区
路径用 `neurova/api/../../agent_workspaces/default` 字面拼接，AgentConfig 原样
持有，GrowthAnalyzer._validated_storage_target 按 parts 检查到 `..` 段直接拒绝
→ 启动日志 "认知能力初始化失败"，成长链路静默失效。

根因修复：AgentConfig 构造时 realpath 归一化 workspace_path（`..` 语义在
构造时消解，校验器见到的永远是干净路径）。真实穿越（base 之外解析逃逸）
仍由校验器拒绝。
"""
import os
from pathlib import Path

import pytest

from neurova.agent_core import AgentConfig


class TestWorkspacePathNormalization:
    def test_parent_segments_resolved(self, tmp_path):
        """带 .. 段的路径在构造时归一化为真实绝对路径"""
        messy = str(tmp_path / "nested" / ".." / "ws")
        cfg = AgentConfig(name="t", agent_id="t1", workspace_path=messy)
        assert ".." not in cfg.workspace_path.parts
        assert cfg.workspace_path == (tmp_path / "ws").resolve()

    def test_dot_segments_resolved(self, tmp_path):
        messy = str(tmp_path / "." / "ws")
        cfg = AgentConfig(name="t", agent_id="t2", workspace_path=messy)
        assert cfg.workspace_path == (tmp_path / "ws").resolve()

    def test_relative_path_anchored_to_cwd(self, tmp_path, monkeypatch):
        """相对路径按调用方 CWD 锚定后归一化（file_operation 沙箱同语义）"""
        monkeypatch.chdir(tmp_path)
        cfg = AgentConfig(name="t", agent_id="t3", workspace_path="agent_workspaces/t3")
        assert cfg.workspace_path == (tmp_path / "agent_workspaces" / "t3").resolve()

    def test_clean_path_unchanged(self, tmp_path):
        clean = str(tmp_path / "ws")
        cfg = AgentConfig(name="t", agent_id="t4", workspace_path=clean)
        assert cfg.workspace_path == Path(clean).resolve()

    def test_growth_validator_accepts_normalized_workspace(self, tmp_path):
        """端到端：与 app.py 默认工作区同形态的字面路径（x/api/../../agent_workspaces/default）
        归一化后通过 GrowthAnalyzer 校验——启动日志的报错不再复现"""
        from neurova.cognitive_layers.growth_layer.analyzer import GrowthAnalyzer

        messy = str(tmp_path / "neurova" / "api" / ".." / ".." / "agent_workspaces" / "default")
        cfg = AgentConfig(name="t", agent_id="t5", workspace_path=messy)
        assert ".." not in cfg.workspace_path.parts
        target = GrowthAnalyzer._validated_storage_target(
            str(cfg.workspace_path / "memory" / "growth")
        )
        assert target.name == "growth.json"
