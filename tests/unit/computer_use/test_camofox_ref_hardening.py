"""R2-6 camofox ref 解析加固（CUA 升级方案 Phase 2）

病根（修复前）：单一正则限定引号样式——name 含引号/括号静默失配、
同名多元素静默取第一个、解析失败无候选事实。

验收：
- 裸名/单引号/双引号统一解析；含引号的 name 正确还原
- _find_refs_in_yaml 收集全部匹配（唯一/多个）
- _list_role_names 给出同 role 候选事实（ref_not_found 时的下一步线索）
"""

from neurova.computer_use.camofox_server_backend import (
    _find_ref_in_yaml,
    _find_refs_in_yaml,
    _list_role_names,
    _parse_ref_line,
)

SNAPSHOT = """- generic: active
  - button '登录' [e1]
  - button "Submit" [e2]
  - button 确定 [e3]
  - textbox '搜索' [e4]
  - button '登录' [e5]
"""


class TestParseRefLine:
    def test_single_quoted(self):
        assert _parse_ref_line("- button '登录' [e1]") == ("button", "登录", "1")

    def test_double_quoted(self):
        assert _parse_ref_line('- button "Submit" [e2]') == ("button", "Submit", "2")

    def test_bare_name(self):
        """裸名（无引号）——旧正则会静默漏掉"""
        assert _parse_ref_line("- button 确定 [e3]") == ("button", "确定", "3")

    def test_name_with_quotes_inside(self):
        """name 本身含引号——旧正则失配，现可解析（外层引号被剥）"""
        line = "- button \"说'hello'\" [e9]"
        role, name, ref = _parse_ref_line(line)
        assert role == "button" and ref == "9"
        assert "hello" in name

    def test_no_name(self):
        assert _parse_ref_line("- textbox [e5]:") == ("textbox", None, "5")

    def test_non_ref_line(self):
        assert _parse_ref_line("- generic: active") is None
        assert _parse_ref_line("") is None


class TestFindRefs:
    def test_first_match_compat(self):
        assert _find_ref_in_yaml(SNAPSHOT, "button", "登录") == "e1"

    def test_all_matches_collected(self):
        """同名两个按钮 → 两个 ref 都被收集（旧实现静默取第一个）"""
        assert _find_refs_in_yaml(SNAPSHOT, "button", "登录") == ["e1", "e5"]

    def test_all_role_refs_when_no_name(self):
        assert _find_refs_in_yaml(SNAPSHOT, "button") == ["e1", "e2", "e3", "e5"]

    def test_bare_name_matchable(self):
        assert _find_ref_in_yaml(SNAPSHOT, "button", "确定") == "e3"

    def test_no_match_empty(self):
        assert _find_refs_in_yaml(SNAPSHOT, "button", "不存在") == []
        assert _find_refs_in_yaml("", "button", "x") == []


class TestRoleNameFacts:
    def test_list_role_names(self):
        """ref_not_found 时给 agent 的候选事实"""
        assert _list_role_names(SNAPSHOT, "button") == ["登录", "Submit", "确定", "登录"]
        assert _list_role_names(SNAPSHOT, "textbox") == ["搜索"]
        assert _list_role_names(SNAPSHOT, "link") == []
