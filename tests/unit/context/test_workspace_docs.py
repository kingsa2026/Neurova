# -*- coding: utf-8 -*-
"""P0-1 工作区文档（AGENTS.md）自动注入。

- AGENTS.md 根→子目录层级收集，每目录 AGENTS.override.md 优先
- 总字节预算（默认 16KB），超预算截断并显式标注
- 噪音目录跳过（.git/node_modules/__pycache__/.venv…）
- 无工作区/无文档 → 空字符串，system prompt 零变化
"""
import pytest


@pytest.fixture()
def ws(tmp_path):
    w = tmp_path / "ws"
    w.mkdir()
    return w


class TestCollectWorkspaceDocs:
    def test_missing_workspace_returns_empty(self, tmp_path):
        from neurova.context.workspace_docs import collect_workspace_docs

        assert collect_workspace_docs(str(tmp_path / "nope")) == ""
        assert collect_workspace_docs("") == ""

    def test_root_agents_md_collected(self, ws):
        from neurova.context.workspace_docs import collect_workspace_docs

        (ws / "AGENTS.md").write_text("# 规则\n只在周一部署", encoding="utf-8")
        doc = collect_workspace_docs(str(ws))
        assert "只在周一部署" in doc
        assert "project-doc" in doc

    def test_override_wins_in_same_dir(self, ws):
        from neurova.context.workspace_docs import collect_workspace_docs

        (ws / "AGENTS.md").write_text("baseline", encoding="utf-8")
        (ws / "AGENTS.override.md").write_text("override wins", encoding="utf-8")
        doc = collect_workspace_docs(str(ws))
        assert "override wins" in doc
        assert "baseline" not in doc

    def test_nested_docs_root_first_with_relpath_header(self, ws):
        from neurova.context.workspace_docs import collect_workspace_docs

        (ws / "AGENTS.md").write_text("root doc", encoding="utf-8")
        sub = ws / "sub"
        sub.mkdir()
        (sub / "AGENTS.md").write_text("sub doc", encoding="utf-8")
        doc = collect_workspace_docs(str(ws))
        assert doc.index("root doc") < doc.index("sub doc")
        assert "sub" in doc  # 相对路径标注

    def test_noise_dirs_skipped(self, ws):
        from neurova.context.workspace_docs import collect_workspace_docs

        for d in (".git", "node_modules", "__pycache__", ".venv"):
            (ws / d).mkdir()
            (ws / d / "AGENTS.md").write_text(f"noise {d}", encoding="utf-8")
        assert collect_workspace_docs(str(ws)) == ""

    def test_byte_budget_truncates_with_marker(self, ws):
        from neurova.context.workspace_docs import collect_workspace_docs

        (ws / "AGENTS.md").write_text("x" * 30000, encoding="utf-8")
        doc = collect_workspace_docs(str(ws), max_bytes=1024)
        assert len(doc.encode("utf-8")) <= 1024 + 200  # 预算+截断标注余量
        assert "截断" in doc

    def test_second_doc_dropped_when_budget_exhausted(self, ws):
        from neurova.context.workspace_docs import collect_workspace_docs

        (ws / "AGENTS.md").write_text("a" * 900, encoding="utf-8")
        sub = ws / "s2"
        sub.mkdir()
        (sub / "AGENTS.md").write_text("b" * 900, encoding="utf-8")
        doc = collect_workspace_docs(str(ws), max_bytes=1024)
        assert "a" * 100 in doc
        assert "b" * 100 not in doc
        assert "截断" in doc

    def test_empty_workspace_returns_empty(self, ws):
        from neurova.context.workspace_docs import collect_workspace_docs

        assert collect_workspace_docs(str(ws)) == ""


class TestSystemPromptInjection:
    def _build_orchestrator(self, workspace_path):
        from unittest.mock import MagicMock

        from neurova.context.orchestrator import ContextOrchestrator

        agent = MagicMock()
        agent.config.workspace_path = workspace_path
        agent.config.constitution = ""
        agent.config.behavior_rules = []
        agent.soul = "你是助手"
        agent.personality = ""
        orch = ContextOrchestrator.__new__(ContextOrchestrator)
        orch._agent = agent
        # config/soul/personality/session_id 均为只读 property（委托 _agent/_session_id）
        orch._session_id = "s1"
        return orch

    def test_system_prompt_contains_agents_doc(self, ws):
        (ws / "AGENTS.md").write_text("只在周一部署", encoding="utf-8")
        orch = self._build_orchestrator(str(ws))
        prompt = orch.build_system_prompt()
        assert "## 工作区文档" in prompt
        assert "只在周一部署" in prompt

    def test_system_prompt_unchanged_without_docs(self, ws):
        orch = self._build_orchestrator(str(ws))
        prompt = orch.build_system_prompt()
        assert "## 工作区文档" not in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestDualPathConsistency:
    """P0-1 防漂移钉：主链 build_context 与工具方法 build_system_prompt
    必须共用 _workspace_docs_section 单源——历史上时间段/规则段曾因双路径
    各自拼装漂移（本测试防 AGENTS.md 注入重蹈覆辙）。"""

    def test_both_prompt_paths_use_single_source_helper(self):
        import inspect

        from neurova.context.orchestrator import ContextOrchestrator

        src_main = inspect.getsource(ContextOrchestrator.build_context)
        src_util = inspect.getsource(ContextOrchestrator.build_system_prompt)
        assert "_workspace_docs_section()" in src_main, "主链 build_context 未接工作区文档"
        assert "_workspace_docs_section()" in src_util, "工具方法 build_system_prompt 未接工作区文档"

    def test_helper_returns_section_with_docs(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("只在周一部署", encoding="utf-8")
        orch = TestSystemPromptInjection()._build_orchestrator(str(tmp_path))
        section = orch._workspace_docs_section()
        assert section.startswith("## 工作区文档")
        assert "只在周一部署" in section

    def test_helper_empty_without_docs(self, tmp_path):
        orch = TestSystemPromptInjection()._build_orchestrator(str(tmp_path))
        assert orch._workspace_docs_section() == ""
