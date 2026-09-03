"""Web 工具描述中的"轻→重工具阶梯"提示词回归测试

阶梯源自 use-tinyfish 的工具选择原则（search → fetch → agent → browser，
永远用能回答问题的最轻工具），吸收进 builtin_tools 的工具描述后，
防止后续改动把升级提示误删。
"""
from neurova.builtin_tools import _BUILTIN_SCHEMAS


class TestWebToolLadderDescriptions:
    def test_web_search_points_to_web_fetch_as_next_step(self):
        desc = _BUILTIN_SCHEMAS["web_search"]["description"]
        assert "web_fetch" in desc
        assert "最轻" in desc

    def test_web_fetch_defers_browser_to_dynamic_pages(self):
        desc = _BUILTIN_SCHEMAS["web_fetch"]["description"]
        assert "browser" in desc

    def test_browser_navigate_marked_as_heavy_tool(self):
        desc = _BUILTIN_SCHEMAS["browser_navigate"]["description"]
        assert ("web_search" in desc) or ("web_fetch" in desc)
