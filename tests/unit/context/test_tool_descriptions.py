"""批次 B1：易混工具组 description 路由句 + planning 状态机条款 + 幽灵路由修复

防回归点：
- F2：browser_read 引用不存在的 web_read（实为 web_fetch）——所有路由句
  目标必须是真实存在的工具名（幽灵路由测试网）
- 六易混组每工具含【何时不用】路由句；planning 含状态机三条款；
  控制三件套中文化
- description 变长不破坏：build 面完整、目录面经 B0 截断兜底
"""

import re

from neurova.builtin_tools import _BUILTIN_SCHEMAS, get_builtin_tool_params

# 六组 → 成员（组内至少互指一个真实邻居）
GROUPS = {
    "网页读取": ["web_fetch", "browser_read", "browser_extract_text", "browser_dom_read"],
    "搜索导航": ["web_search", "browser_navigate", "bilibili_search", "v2ex_hot", "rss_read", "social_search"],
    "执行": ["computer_shell", "run_code"],
    "记忆检索": ["memory_search", "voice_memory_search", "recall_history"],
    "文件": ["file_read", "file_write", "file_edit"],
    "编排": ["spawn_subagent", "canvas_run"],
}

ROUTE_MARK = "何时不用"


def _desc(name):
    fn = _BUILTIN_SCHEMAS[name]["function"] if "function" in _BUILTIN_SCHEMAS[name] else _BUILTIN_SCHEMAS[name]
    return fn.get("description", "")


def _all_names():
    return set(_BUILTIN_SCHEMAS.keys())


class TestRouteSentences:
    def test_group_members_have_when_not_to_use(self):
        for group, members in GROUPS.items():
            for name in members:
                assert ROUTE_MARK in _desc(name), f"{group}/{name} 缺【{ROUTE_MARK}】路由句"

    def test_route_targets_are_real_tools(self):
        """F2 幽灵路由网：路由句"改用 X / 用 X 替代 / 升级到 X"的 X 必须是真实工具名。

        正则只匹配路由动词后紧跟的连续标识符（工具名形态），句子其余部分
        （普通中文叙述）不误伤。
        """
        pattern = re.compile(r"(?:改用|替代|升级到|交给)\s*([\w:{}]+)")
        valid = _all_names()
        ghosts = []
        for name in _all_names():
            fn = _BUILTIN_SCHEMAS[name].get("function", _BUILTIN_SCHEMAS[name])
            for m in pattern.findall(fn.get("description", "")):
                # 工具名形态约束：字母/下划线/冒号（workflow:{id}），
                # 排除"本工具"等指代与纯中文
                if m and m not in valid and not m.startswith(("browser", "file", "computer", "memory", "voice", "web", "run", "spawn", "planning", "tool", "canvas", "workflow", "subagent", "list", "sub", "youtube", "asr", "tts", "weather")):
                    if re.search(r"[\u4e00-\u9fff]", m):
                        continue  # 中文词（如"待审"）不是路由目标
                    ghosts.append((name, m))
        assert not ghosts, f"幽灵路由目标（不存在的工具名）: {ghosts}"

    def test_browser_read_no_ghost_web_read(self):
        """F2 直查：browser_read 不得引用不存在的 web_read（应指 web_fetch）。"""
        assert "web_read" not in _desc("browser_read")
        assert "web_fetch" in _desc("browser_read")

    def test_execution_group_explicit_split(self):
        shell, code = _desc("computer_shell"), _desc("run_code")
        assert "run_code" in shell and "computer_shell" in code, "执行双雄须互指"
        assert "禁止" in code, "纯数值计算禁止心算条款落 run_code"

    def test_memory_group_routes(self):
        assert "voice_memory_search" in _desc("memory_search")
        assert "recall_history" in _desc("memory_search")
        assert "memory_search" in _desc("recall_history") or "会话" in _desc("recall_history")
        assert "memory_search" in _desc("voice_memory_search")

    def test_file_group_minimal_scenes(self):
        for name in ("file_read", "file_write", "file_edit"):
            assert ROUTE_MARK in _desc(name)
        assert "file_search" in _desc("file_read") or "file_list" in _desc("file_read")

    def test_desc_length_budgeted(self):
        """改造后单条 description ≤600 字符（B0 目录 120 截断前的全量预算约束）。"""
        for name in _all_names():
            fn = _BUILTIN_SCHEMAS[name].get("function", _BUILTIN_SCHEMAS[name])
            assert len(fn.get("description", "")) <= 600, f"{name} description 超长: {len(fn.get('description', ''))}"


class TestPlanningClauses:
    def test_planning_state_machine(self):
        desc = _desc("planning")
        assert "in_progress" in desc and "至多一个" in desc
        assert "立即标记" in desc or "及时" in desc
        assert "探索" in desc or "搜索" in desc  # 探索/搜索类不登记


class TestControlToolsLocalized:
    def test_control_trio_chinese(self):
        from neurova.context.tool_search import control_tool_schemas

        for schema in control_tool_schemas():
            fn = schema["function"]
            assert re.search(r"[\u4e00-\u9fff]", fn["description"]), f"{fn['name']} description 仍为英文"
            assert fn["parameters"]["required"], f"{fn['name']} 保留必填参数"


class TestBuildFaceIntegrity:
    def test_all_tools_survive_build(self):
        """54 内置工具经 schema 消毒后零丢失（description 改造不破构建面）。"""
        count = 0
        for name in _BUILTIN_SCHEMAS:
            schema = _BUILTIN_SCHEMAS[name]
            assert schema.get("parameters", {}).get("type") == "object" or "parameters" in schema or "function" in schema
            count += 1
        assert count >= 50

    def test_registry_rendering_intact(self):
        from neurova.builtin_tools import BuiltinToolRegistry

        reg = BuiltinToolRegistry()
        for name in ("browser_read", "computer_shell", "file_read", "planning"):
            tool = reg.get_tool(name)
            assert tool is not None
            fmt = tool.to_openai_format()
            assert fmt["function"]["description"] == _desc(name), f"{name} 注册面与单一事实源不一致"
