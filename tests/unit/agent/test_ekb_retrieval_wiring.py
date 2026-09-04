"""EKB → ctx.experience_items 传动轴测试（经验结晶闭环审计 2026-09-04 修复 ⑤）

断点：ctx.experience_items 在 chat_pipeline 中无任何生产方（恒空），
orchestrator 池路径的 [经验] 归档/注入/统计三个消费方永远吃不到数据——
EKB 每轮写入（数千条）但主聊天路径永不复用（写了没人读）。
修复：ChatPipeline 统一检索阶段新增 _retrieve_ekb_experience，按当前输入查
EKB（≤3 条）填充该字段；失败静默不阻断主流程。
"""

from unittest.mock import MagicMock

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline


def _bare_pipeline():
    """绕过 __init__ 装配，只测检索方法本身"""
    return ChatPipeline.__new__(ChatPipeline)


def _patch_ekb(monkeypatch, find):
    import neurova.skills.experience_knowledge_base as ekb_mod

    fake_kb = MagicMock()
    fake_kb.find_similar_experiences = find
    monkeypatch.setattr(
        ekb_mod, "get_experience_knowledge_base", lambda: fake_kb
    )


class TestEkbRetrievalFillsDeadField:
    def test_hit_fills_experience_items(self, monkeypatch):
        def find(**kwargs):
            assert kwargs["context"]["user_input"] == "帮我查北京天气"
            return [
                {
                    "context": {"user_input": "查北京天气怎么样"},
                    "result": {"reply_excerpt": "北京今天晴，25 度"},
                    "success": 1,
                },
                {
                    "context": {"user_input": "上海天气"},
                    "result": {"output": "旧契约键"},
                    "success": 0,
                },
            ]

        _patch_ekb(monkeypatch, find)
        pipeline = _bare_pipeline()
        ctx = ChatContext(user_input="帮我查北京天气")

        pipeline._retrieve_ekb_experience(ctx)

        assert len(ctx.experience_items) == 2
        first = ctx.experience_items[0]
        assert first["source"] == "ekb"
        assert "北京今天晴" in first["content"]
        assert first["content"].startswith("✓")
        second = ctx.experience_items[1]
        assert second["content"].startswith("✗")
        assert "旧契约键" in second["content"]

    def test_no_hit_leaves_field_empty(self, monkeypatch):
        _patch_ekb(monkeypatch, lambda **kwargs: [])
        pipeline = _bare_pipeline()
        ctx = ChatContext(user_input="冷门问题")

        pipeline._retrieve_ekb_experience(ctx)

        assert ctx.experience_items == []

    def test_query_failure_is_silent(self, monkeypatch):
        def find(**kwargs):
            raise RuntimeError("db locked")

        _patch_ekb(monkeypatch, find)
        pipeline = _bare_pipeline()
        ctx = ChatContext(user_input="任意")

        pipeline._retrieve_ekb_experience(ctx)  # 不得抛出

        assert ctx.experience_items == []

    def test_prefilled_items_not_overwritten(self, monkeypatch):
        """上游真有预检索条目时不覆盖（Phase 4 契约保留）"""
        _patch_ekb(
            monkeypatch,
            lambda **kwargs: (_ for _ in ()).throw(AssertionError("不应查询")),
        )
        pipeline = _bare_pipeline()
        ctx = ChatContext(user_input="q")
        ctx.experience_items = [{"content": "池内经验", "source": "pool"}]

        pipeline._retrieve_ekb_experience(ctx)

        assert ctx.experience_items == [{"content": "池内经验", "source": "pool"}]
