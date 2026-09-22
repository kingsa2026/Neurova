"""「清空生效正文」必须在**所有**形态下被拦——工具序列在场不是豁免牌。

立项锚点（Issue #46 收口复核，2026-09-22，实测复现）：

`_quality_gate` 的 `content_non_empty` 判据把"有效正文"定义为
**指令体 / 描述 / 工具序列任一非空**。于是对一条**带工具序列**的技能：

```
update_auto_skill("sk", config={"tool_sequence": STEPS, "context_template": ""})
→ True   落盘成功，context_template 被清成 ''
```

`tool_sequence` 在场 ⇒ `has_body` 恒真 ⇒ "把正文写成空串"这条**未被拦下**。
而 PR #47 的公开结论是"正文写空串照样落盘"已堵——实际只堵了"无工具序列"
那一种形态（现有用例正是用空 `tool_sequence` 构造的）。

危害不是理论上的：`context_template` 是技能**行为正文**的事实源
（`text_evolution_api` 以它为进化对象、`post_chat_pipeline` 以它做运行时
文本装载）。被清空后条目仍"有内容"（只剩工具序列），评审闸也看不出来。

修法在判据本身（不是给报错处加兜底）：原判据回答的是"生效内容是否为空"，
而这里要拦的动作是"**本次把指令体清空**"——与既有 `content_cleared`
（针对 description 的同一类动作）对称，故新增同名同构的 `body_cleared`。
"""

from tests.unit.skills.creation_helpers import register_proven_skill

STEPS = [{"tool": "file_read", "params": {"path": "a.txt"}},
         {"tool": "file_write", "params": {"path": "b.txt"}}]


def _svc(tmp_path):
    import os

    from neurova.skills.skill_service import SkillService

    os.environ["NEUROVA_SKILL_REVIEW_GATE"] = "1"
    return SkillService(agent_id="body-t", skills_dir=str(tmp_path / "skills"))


class TestBodyClearIsGated:
    def test_clearing_instruction_body_with_sequence_present_is_rejected(self, tmp_path):
        """带工具序列时清空 `context_template` 必须被拒（实测旧实现返回 True）。"""
        svc = _svc(tmp_path)
        register_proven_skill(
            svc, "sk", name="sk", description="报告处理",
            config={"tool_sequence": STEPS, "context_template": "原始正文"},
        )
        assert svc.update_auto_skill(
            "sk", config={"tool_sequence": STEPS, "context_template": ""},
            enforce_quality=True,
        ) is False, "带序列不是豁免牌：清空指令体必须被拦"
        assert svc.get_skill_info("sk")["manifest"]["config"]["context_template"] == "原始正文"

    def test_clearing_via_editor_chain_is_rejected(self, tmp_path):
        """编辑链（version=None）同样不得清空指令体——否则旧洞从侧门复活。"""
        svc = _svc(tmp_path)
        register_proven_skill(
            svc, "sk2", name="sk2", description="报告处理",
            config={"tool_sequence": STEPS, "context_template": "原始正文"},
        )
        assert svc.update_auto_skill(
            "sk2", config={"tool_sequence": STEPS, "context_template": "   "},
            enforce_quality=True,
        ) is False, "仅空白也算清空"
        assert svc.get_skill_info("sk2")["manifest"]["config"]["context_template"] == "原始正文"

    def test_existing_empty_body_entry_still_editable(self, tmp_path):
        """存量空指令体是真实一等公民：字段编辑不得被新判据误杀。

        反向锁：新判据只咬"**本次把非空正文清空**"这个动作，不咬存量空。
        """
        svc = _svc(tmp_path)
        register_proven_skill(
            svc, "sk3", name="sk3", description="报告处理",
            config={"tool_sequence": STEPS},
        )
        assert svc.update_auto_skill(
            "sk3", config={"tool_sequence": STEPS, "category": "工具"},
            enforce_quality=True,
        ) is True, "存量空指令体的正常字段编辑不得被拦"

    def test_body_replacement_with_real_text_still_passes(self, tmp_path):
        """正常改写（提交新的非空正文）不得被误杀。"""
        svc = _svc(tmp_path)
        register_proven_skill(
            svc, "sk4", name="sk4", description="报告处理",
            config={"tool_sequence": STEPS, "context_template": "原始正文"},
        )
        assert svc.update_auto_skill(
            "sk4", version="2.0.0",
            config={"tool_sequence": STEPS, "context_template": "改进后的正文"},
            enforce_quality=True,
        ) is True
        assert svc.get_skill_info("sk4")["manifest"]["config"]["context_template"] == "改进后的正文"
