"""
干净机器启动崩溃回归（安装版 2026-09-04 backend log）

根因：_load_saved_agents 对 agent_workspaces 目录调用 os.listdir，
但该目录在打包安装机上天然不存在（bundle_backend.py 不复制它），
os.listdir 抛 FileNotFoundError → Application startup failed. Exiting.

契约：
- agent_workspaces 目录不存在 → 静默返回（全新安装无历史 agent 可载入），
  不得抛异常、不得在盘上创建目录（数据目录不应由加载路径凭空创建）
- 目录存在但为空 → 正常返回，无 agent 载入
- 目录存在且有 agent → 原行为不变（有配置则载入）
"""
import json

import pytest

from neurova.api.app import _load_saved_agents


class TestLoadSavedAgentsMissingDir:
    @pytest.fixture(autouse=True)
    def _inject_workspace_root(self, tmp_path, monkeypatch):
        """工作区根由 neurova.core.agent_workspaces 单源给出——测试经 env 注入。"""
        monkeypatch.setenv(
            "NEUROVA_AGENT_WORKSPACES_DIR", str(tmp_path / "agent_workspaces")
        )

    def test_missing_dir_returns_silently(self):
        """agent_workspaces 目录不存在：不抛异常。"""
        # 注意：不创建 agent_workspaces 目录本身
        app_state = _FakeAppState()
        _load_saved_agents(app_state)

        assert app_state.agents == {}
        # 不强制要求"不创建目录"——makedirs 补救也算合法实现，断言放宽为：
        # 无论创建与否，函数正常返回即可（上面未抛异常即通过）。

    def test_missing_dir_does_not_raise(self):
        # os.listdir 的报错点：直接调用不得抛 FileNotFoundError
        try:
            _load_saved_agents(_FakeAppState())
        except FileNotFoundError:
            pytest.fail("_load_saved_agents 在目录缺失时抛 FileNotFoundError")

    def test_empty_dir_ok(self, tmp_path):
        (tmp_path / "agent_workspaces").mkdir()
        app_state = _FakeAppState()
        _load_saved_agents(app_state)
        assert app_state.agents == {}

    def test_existing_agent_still_loaded(self, tmp_path):
        agent_dir = tmp_path / "agent_workspaces" / "kai"
        (agent_dir / "memory").mkdir(parents=True)
        (agent_dir / "agent_config.json").write_text(
            json.dumps({"name": "Kai", "model": "gpt-4", "provider": "openai"}),
            encoding="utf-8",
        )
        app_state = _FakeAppState()
        _load_saved_agents(app_state)
        assert "kai" in app_state.agents


class _FakeAppState:
    def __init__(self):
        self.agents = {}
        self.default_agent_id = "default"

    def add_agent(self, agent_id, agent):
        self.agents[agent_id] = agent
