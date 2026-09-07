"""B0 工具目录预算治理（docs/04-plans/2026-09-07-提示词与工具面升级实施方案.md 批次 B0）

防回归点（对比报告 F4）：
- 旧行为：render_directory 超预算时整行丢弃工具 → 工具从隐藏目录消失，
  模型彻底不知道该工具存在；
- 新行为：先 per-desc 截断（默认 120 字符）再装填，同预算装下更多工具；
  目录预算默认 20000，可经 NEUROVA_TOOL_SEARCH_BUDGET 覆写；
- 多行 description 塌缩为单行（目录是扁平清单）。
"""

from neurova.context import tool_search


def _entries(n: int, desc_len: int = 300):
    return [
        {
            "name": f"tool_{i:03d}",
            "description": "功能说明" + "x" * desc_len,
            "schema": {},
            "params_text": "",
        }
        for i in range(n)
    ]


class TestRenderDirectoryBudget:
    def test_overload_zero_line_drop(self):
        """80 工具 × 300 字符 desc 的超载场景：截断后所有工具名仍在目录中。

        80×317≈25K 字符 > 20000 预算——旧代码（无截断）必丢行，新代码截到
        120 字符后 80×134≈10.7K 全部装下。
        """
        entries = _entries(80, desc_len=300)
        rendered = tool_search.render_directory(entries, max_chars=20000)
        for e in entries:
            assert e["name"] in rendered, f"工具 {e['name']} 从目录中丢失（F4 回归）"

    def test_per_desc_truncated_to_limit(self):
        """每条 description 截断到 120 字符上限（含省略号 ≤121）。"""
        entries = _entries(3, desc_len=300)
        rendered = tool_search.render_directory(entries, max_chars=20000)
        assert rendered.splitlines(), "目录不应为空"
        for line in rendered.splitlines():
            assert line.startswith("- "), f"目录行格式被破坏: {line!r}"
            desc_part = line.split(": ", 1)[1]
            assert len(desc_part) <= 121, f"目录 desc 超限: {len(desc_part)}"

    def test_budget_env_override_and_default(self, monkeypatch):
        """NEUROVA_TOOL_SEARCH_BUDGET 覆写预算；缺省回 20000。"""
        monkeypatch.setenv("NEUROVA_TOOL_SEARCH_BUDGET", "600")
        assert tool_search.get_directory_budget() == 600
        monkeypatch.delenv("NEUROVA_TOOL_SEARCH_BUDGET")
        assert tool_search.get_directory_budget() == 20000

    def test_budget_env_malformed_falls_back(self, monkeypatch):
        """env 值非法时回退默认值，不抛异常。"""
        monkeypatch.setenv("NEUROVA_TOOL_SEARCH_BUDGET", "not-a-number")
        assert tool_search.get_directory_budget() == 20000

    def test_tiny_budget_drops_with_suffix(self, monkeypatch):
        """预算极小装不下时：允许丢行但必须带 tool_search 尾注（语义保留）。"""
        monkeypatch.setenv("NEUROVA_TOOL_SEARCH_BUDGET", "600")
        rendered = tool_search.render_directory(_entries(50, desc_len=300))
        assert "tool_search 检索" in rendered
        monkeypatch.delenv("NEUROVA_TOOL_SEARCH_BUDGET")

    def test_multiline_desc_collapsed(self):
        """多行 description 塌缩为单行，目录保持一行一工具。"""
        entries = [
            {"name": "t1", "description": "第一行\n第二行\n第三行", "schema": {}, "params_text": ""}
        ]
        rendered = tool_search.render_directory(entries, max_chars=20000)
        assert len(rendered.splitlines()) == 1
        assert "第一行 第二行 第三行" in rendered

    def test_orchestrator_uses_shared_budget(self, monkeypatch):
        """orchestrator 目录渲染与 tool_search 共用同一 env 预算源。"""
        import inspect

        from neurova.context import orchestrator

        monkeypatch.setenv("NEUROVA_TOOL_SEARCH_BUDGET", "7777")
        src = inspect.getsource(orchestrator)
        assert "get_directory_budget" in src, "orchestrator 未接入共享预算源（仍硬编码 18000）"
        monkeypatch.delenv("NEUROVA_TOOL_SEARCH_BUDGET")
