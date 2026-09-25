"""004 残留 · 三态的**第五个面**：进 prompt 的那一段（红→绿）。

## 上一轮交付了四个面，漏了唯一真正改变下一次调用的那面

票 004 的验收原文是"三种输入在**四个面**（EKB 行、权重表、结晶器、API 展示）
各自独立可分辨"，对照表也确实只交付了四个。但注入进 prompt 的这一段是**第五个消费方**，
且它是唯一会改变模型下一次调用的那一面——库里分得再清，喂给模型时折成两分，
"未测量"仍会被读成"上次做砸了"。

## 本文件钉住的三处（全部实测复现）

1. `context/builder.py` 池提取口：`item.metadata.get("success", True)`
   —— 池条目缺该键时**默认成成功**。实测归档口（`context/orchestrator.py`
   构造 `ContextInput` 时**根本不传 metadata`）正是这个形态，故默认必然生效。
2. `context/injector.py::_format_experience_from_list`：`context` 是 dict
   （工单 009 之后 EKB 的 `context` 就是这个形状）时 `exp.get("context","")[:50]`
   直接抛 `TypeError: unhashable type: 'slice'`，被外层 `except` 吞掉 ⇒ **返回空串**。
   实测：整段经验从 prompt 里静默消失。
3. 同一函数：`success_mark = "✓" if exp.get("success") else "✗"`
   —— `None`（未测量）走 else 被渲染成 `✗`，正是票 004 禁区明写的
   "把未测量报成失败"。

判据都落在生产取数口（`_format_experience_from_list` 是池路径唯一渲染点），
不新造第二套词汇：三态词取 `knowledge_facts.EVIDENCE_STATES` 的既有词汇表。
"""

from __future__ import annotations

import logging

import pytest

from neurova.context.builder import ContextBuilder
from neurova.context.injector import UnifiedContextInjector
from neurova.context_pool import ContextSource


def _injector():
    """只测渲染口本身：绕开重装配，注入 logger（构造口是重依赖的 BaseModule）。"""
    inj = UnifiedContextInjector.__new__(UnifiedContextInjector)
    inj._logger = logging.getLogger("test.experience.prompt.face")
    return inj


def _pool_item(content: str, **metadata):
    """复刻归档口产出的池条目形状（`ContextInput`，metadata 可为空）。"""
    from types import SimpleNamespace

    return SimpleNamespace(source=ContextSource.EXPERIENCE, content=content, metadata=metadata)


class TestPoolExtractionKeepsThreeStates:
    """面⑤-上游：池条目缺 `success` 键时不得默认成"成功"。"""

    def test_missing_key_does_not_default_to_success(self):
        """归档口不传 metadata ⇒ 缺键就是"未测量"，不是"成功"。"""
        builder = ContextBuilder.__new__(ContextBuilder)
        extracted = builder._extract_experience_dicts_from_pool([_pool_item("[经验] 查天气")])
        assert extracted, "池条目没被提取出来"
        assert extracted[0]["success"] is None, (
            "池条目缺 success 键被默认成成功（工单 004 禁区：不得用默认值消除 NULL）："
            f"{extracted[0]['success']!r}"
        )

    def test_present_states_survive_extraction(self):
        """三种输入经提取口后仍各自可分辨（不许半路折叠）。"""
        builder = ContextBuilder.__new__(ContextBuilder)
        extracted = builder._extract_experience_dicts_from_pool([
            _pool_item("[经验] 成功", success=True),
            _pool_item("[经验] 失败", success=False),
            _pool_item("[经验] 未测量", success=None),
        ])
        assert [e["success"] for e in extracted] == [True, False, None], (
            f"三态在池提取口被折叠：{[e['success'] for e in extracted]!r}"
        )


class TestPromptFaceRendersThreeStates:
    """面⑤-渲染：进 prompt 的那一行必须与其余四面同口径。"""

    def test_unmeasured_is_not_rendered_as_failure(self):
        """未测量（None）不得渲染成 `✗`——那是把"没测到"报成"上次做砸了"。"""
        rendered = _injector()._format_experience_from_list(
            [{"context": "查上海天气", "result": "阴", "success": None}]
        )
        assert rendered, "未测量条目整条消失了"
        assert "✗" not in rendered, f"未测量被渲染成失败：{rendered!r}"
        assert rendered.startswith("○") or "未测量" in rendered, (
            f"未测量没有自己的记号，仍与失败/成功混在一起：{rendered!r}"
        )

    def test_true_and_false_keep_their_own_marks(self):
        """真成功与真失败各有自己的记号（反向控制：判据不能把所有值都放行）。"""
        inj = _injector()
        ok = inj._format_experience_from_list(
            [{"context": "查北京天气", "result": "晴", "success": True}]
        )
        bad = inj._format_experience_from_list(
            [{"context": "查上海天气", "result": "阴", "success": False}]
        )
        assert ok.startswith("✓"), f"真成功没被标成成功：{ok!r}"
        assert bad.startswith("✗"), f"真失败没被标成失败：{bad!r}"
        assert ok != bad, "三态在渲染口被折叠成同一个输出"

    def test_dict_shaped_context_does_not_vanish(self):
        """`context` 是 dict（EKB 2.0 契约）时必须渲染出摘要，不得整条消失。

        旧实现直接切片 dict ⇒ TypeError 被外层 except 吞掉 ⇒ 返回空串。
        """
        rendered = _injector()._format_experience_from_list(
            [{"context": {"user_input": "查北京天气"}, "result": {"reply_excerpt": "晴"}, "success": True}]
        )
        assert rendered, "dict 形状的 context 让整段经验从 prompt 里消失（TypeError 被吞）"
        assert "查北京天气" in rendered, f"摘要没取到 user_input：{rendered!r}"
        assert "晴" in rendered, f"结果摘要没取到 reply_excerpt：{rendered!r}"

    def test_dict_shaped_result_does_not_vanish(self):
        """`result` 是 dict 时同理：不得静默吞成空串。"""
        rendered = _injector()._format_experience_from_list(
            [{"context": "查北京天气", "result": {"reply_excerpt": "晴"}, "success": True}]
        )
        assert "晴" in rendered, f"dict 形状的 result 没渲染出摘要：{rendered!r}"


class TestFifthFaceMatchesTheOtherFour:
    """对照表补第五列：同一行输入在面⑤与面①（EKB 行）口径一致。"""

    @pytest.mark.parametrize(
        ("success", "expected_mark", "forbidden"),
        [(True, "✓", "✗"), (False, "✗", "✓"), (None, "○", "✗")],
    )
    def test_each_state_has_exactly_one_mark(self, success, expected_mark, forbidden):
        rendered = _injector()._format_experience_from_list(
            [{"context": "查天气", "result": "晴", "success": success}]
        )
        assert rendered.startswith(expected_mark), (
            f"success={success!r} 的渲染记号应为 {expected_mark!r}：{rendered!r}"
        )
        assert not rendered.startswith(forbidden), (
            f"success={success!r} 被渲染成 {forbidden!r}：{rendered!r}"
        )


class TestEkbRetrievalKeepsThreeStates:
    """面⑤-上游的另一条生产写入口：`chat_pipeline._retrieve_ekb_experience`。

    它把 EKB 命中转成 `ctx.experience_items`（池归档 + 去重优先级的输入）。
    旧写法 `mark = "✓" if hit.get("success") else "✗"` 与
    `"success": bool(hit.get("success"))` 两处都在折叠三态：`None` 既被渲染成
    `✗`，又被 `bool()` 折成 `False` —— 同一条经验在库里是"未测量"，
    到了消费方手上变成"失败"。
    """

    def _retrieve(self, monkeypatch, hits):
        from types import SimpleNamespace

        import neurova.skills.experience_knowledge_base as ekb_mod
        from neurova.agent.chat_pipeline import ChatContext, ChatPipeline

        class _FakeKb:
            def find_similar_experiences(self, **kwargs):
                return hits

        monkeypatch.setattr(ekb_mod, "get_experience_knowledge_base", lambda: _FakeKb())
        pipeline = ChatPipeline.__new__(ChatPipeline)
        pipeline._agent = SimpleNamespace(config=SimpleNamespace(agent_id="default"))
        ctx = ChatContext(user_input="查北京天气")
        pipeline._retrieve_ekb_experience(ctx)
        return ctx.experience_items

    def test_unmeasured_hit_keeps_its_state(self, monkeypatch):
        items = self._retrieve(monkeypatch, [
            {"id": 1, "context": {"user_input": "查北京天气"},
             "result": {"reply_excerpt": "晴"}, "success": None},
        ])
        assert items, "命中没进 experience_items"
        assert items[0]["success"] is None, (
            "EKB 未测量的命中被 `bool()` 折成失败（票 004 禁区）："
            f"{items[0]['success']!r}"
        )
        assert "✗" not in items[0]["content"], (
            f"未测量在内容里被渲染成失败记号：{items[0]['content']!r}"
        )

    def test_measured_states_keep_their_marks(self, monkeypatch):
        items = self._retrieve(monkeypatch, [
            {"id": 1, "context": {"user_input": "查北京天气"},
             "result": {"reply_excerpt": "晴"}, "success": True},
            {"id": 2, "context": {"user_input": "查上海天气"},
             "result": {"reply_excerpt": "阴"}, "success": False},
        ])
        assert [i["success"] for i in items] == [True, False], (
            f"真成功/真失败在传动轴被折叠：{[i['success'] for i in items]!r}"
        )
        assert items[0]["content"].startswith("✓")
        assert items[1]["content"].startswith("✗")
