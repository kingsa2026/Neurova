"""Issue #68 · 17 维分类形成闭环 —— 分类引擎唯一 + remember 真自动分类（红绿灯 TDD）。

修复前的三个结构性问题（本文件逐条锁死）：

1. **两套分类器**：`auto_classifier.MemoryAutoClassifier` 自带 7/6/4 三个私有枚举
   （文档口径的"17 维"就凑自它），但**全仓零消费者**；生产真正落库的是
   `models.py` 的 MemoryCategory(7)/MemoryType(7)/MemoryPerspective(4)，而唯一被
   调用的 `modules/classifier_module.py` 又自带 6 个硬编码关键词桶
   （personal/work/knowledge/conversation/emotion/technical）——与 MemoryCategory
   **同名不同集、数量也不同**（general 只在兜底分支出现，experience/reflection/
   user_preference/tool_usage 四个生产值永远认不出来）。
2. **remember 不自动分类**：`auto_classify` 只写在注释里（manager.py 的 kwargs），
   没有任何分支消费它 ⇒ 库里 99% 是 general。
3. **声称能分类的 API 恒 500**：`api/endpoints/memory/eki.py` 以两参调用一参方法，
   再按 `result["category"][0]` 取值（真实返回是 `{"memory_id","categories","tags"}`）。

落定契约：
1. 三个分类枚举**身份即 models.py 的枚举**（`is` 断言，不只是"值相同"）——
   任何重新定义第二套值域的做法都会让本文件变红；
2. `ClassifierModule.classify` 的值域 ⊆ MemoryCategory 且**不含** personal/work/
   technical 这类无对应枚举的历史桶；
3. `remember(auto_classify=True)` 只补未声明项，推断证据落
   `metadata["_auto_classified"]`；显式声明项不被覆盖，且不写证据；
4. `auto_classify=False`（默认）行为与历史默认值等价（general/semantic/first_person）；
5. `classify_memory()` 的返回契约与 API 响应模型逐字段对齐（字符串值 + 单列置信度）。
"""

from __future__ import annotations

import pytest

from neurova.cognitive_layers.memory_layer.auto_classifier import MemoryAutoClassifier
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import (
    MemoryCategory,
    MemoryPerspective,
    MemoryType,
)


@pytest.fixture()
def mgr(tmp_path):
    m = MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="cls-agent",
        neuser_id="neu",
        user_id="u1",
        enable_buffer=False,
    )
    yield m
    m.close()


# ──────────────────────────────────────────────────────────────────
# 1. 词汇表唯一：三枚举身份即 models.py 的枚举
# ──────────────────────────────────────────────────────────────────


class TestSingleVocabulary:
    def test_category_type_is_memory_category(self):
        from neurova.cognitive_layers.memory_layer import auto_classifier as ac

        assert ac.CategoryType is MemoryCategory, (
            "auto_classifier 重新定义了第二套分类枚举——分类值域必须只有 models.py 一处"
        )

    def test_memory_type_enum_is_memory_type(self):
        from neurova.cognitive_layers.memory_layer import auto_classifier as ac

        assert ac.MemoryTypeEnum is MemoryType, (
            "auto_classifier 重新定义了第二套记忆类型枚举（历史上缺 workflow_experience）"
        )

    def test_perspective_type_is_memory_perspective(self):
        from neurova.cognitive_layers.memory_layer import auto_classifier as ac

        assert ac.PerspectiveType is MemoryPerspective

    def test_engine_outputs_canonical_values_only(self):
        """引擎产出的每个维度值都必须能被 models.py 的枚举解出。"""
        result = MemoryAutoClassifier().classify("用户喜欢深色模式，我先把日志抓下来再汇总")
        assert MemoryCategory(result["category"].value) is result["category"]
        assert MemoryType(result["memory_type"].value) is result["memory_type"]
        assert MemoryPerspective(result["perspective"].value) is result["perspective"]

    def test_workflow_experience_is_classifiable(self):
        """workflow_experience 必须能被引擎认出来（历史上该类型根本不在私有枚举里）。"""
        result = MemoryAutoClassifier().classify("工作流：先抓取页面，再汇总，最后导出报告")
        assert result["memory_type"] is MemoryType.WORKFLOW_EXPERIENCE


# ──────────────────────────────────────────────────────────────────
# 2. ClassifierModule 值域收敛（删掉 6 个硬编码异名桶）
# ──────────────────────────────────────────────────────────────────


class TestClassifierModuleVocabulary:
    def test_defined_categories_is_exactly_memory_category(self):
        from neurova.cognitive_layers.memory_layer.modules.classifier_module import (
            ClassifierModule,
        )

        module = ClassifierModule()
        assert module.defined_categories == [c.value for c in MemoryCategory]

    def test_no_legacy_buckets_in_source(self):
        """历史 6 桶（personal/work/technical 等）不得再出现在模块源码里。"""
        from pathlib import Path

        src = Path(
            "neurova/cognitive_layers/memory_layer/modules/classifier_module.py"
        ).read_text(encoding="utf-8")
        for bucket in ('"personal"', '"work"', '"technical"', '"emotion"'):
            assert bucket not in src, f"ClassifierModule 仍自带无对应枚举的关键词桶 {bucket}"

    def test_classify_returns_canonical_values(self):
        from neurova.cognitive_layers.memory_layer.modules.classifier_module import (
            ClassifierModule,
        )

        module = ClassifierModule()
        cats = module.classify("mid-1", "用户喜欢深色模式")
        assert cats, "分类结果不得为空"
        for c in cats:
            assert c in {v.value for v in MemoryCategory}, f"产出非枚举分类: {c}"

    def test_classify_values_are_multi_label_candidates(self):
        """命中多个桶时全部返回（由调用方决定取最佳），不再只给一个标签。"""
        from neurova.cognitive_layers.memory_layer.modules.classifier_module import (
            ClassifierModule,
        )

        module = ClassifierModule()
        cats = module.classify("mid-2", '我想学习这个概念，并且喜欢用代码实现"知识"')
        assert len(cats) >= 1

    def test_add_category_rule_rejects_unknown_category(self):
        from neurova.cognitive_layers.memory_layer.modules.classifier_module import (
            ClassifierModule,
        )

        module = ClassifierModule()
        with pytest.raises(ValueError):
            module.add_category_rule("personal", ["我"])

    def test_add_category_rule_extends_engine(self):
        """扩展热词走唯一引擎（值域不新增），且真的生效。"""
        from neurova.cognitive_layers.memory_layer.modules.classifier_module import (
            ClassifierModule,
        )

        module = ClassifierModule()
        module.add_category_rule(MemoryCategory.KNOWLEDGE.value, ["ZZZ专有词"])
        engine = module._ensure_engine()
        assert engine.classify("ZZZ专有词 是一段材料")["category"] is MemoryCategory.KNOWLEDGE


# ──────────────────────────────────────────────────────────────────
# 3. remember(auto_classify=True) 真分类 + 留痕
# ──────────────────────────────────────────────────────────────────


class TestRememberAutoClassify:
    def test_preference_content_is_classified_on_write(self, mgr):
        mid = mgr.remember("用户喜欢在清晨跑步，这是我的偏好", auto_classify=True)
        mem = mgr._memories[mid]
        assert mem.category is MemoryCategory.USER_PREFERENCE, (
            "声明了 auto_classify 却仍落 general —— 自动分类没有接线"
        )

    def test_default_off_keeps_historical_fallback(self, mgr):
        """不传 auto_classify ⇒ 与历史默认值（general/semantic/first_person）等价。"""
        mid = mgr.remember("用户喜欢在清晨跑步，这是我的偏好")
        mem = mgr._memories[mid]
        assert mem.category is MemoryCategory.GENERAL
        assert mem.memory_type is MemoryType.SEMANTIC
        assert mem.perspective is MemoryPerspective.FIRST_PERSON

    def test_declared_dimension_is_not_overridden(self, mgr):
        """写入侧显式声明的维度优先于推断（写入侧最了解这条是什么）。"""
        mid = mgr.remember(
            "用户喜欢在清晨跑步，这是我的偏好",
            category=MemoryCategory.CONVERSATION.value,
            auto_classify=True,
        )
        mem = mgr._memories[mid]
        assert mem.category is MemoryCategory.CONVERSATION
        evidence = mem.metadata["_auto_classified"]
        assert "category" not in evidence["inferred"], "显式声明的维度不该被记成推断项"
        assert "memory_type" in evidence["inferred"]

    def test_evidence_is_recorded_for_audit(self, mgr):
        mid = mgr.remember("用户喜欢在清晨跑步，这是我的偏好", auto_classify=True)
        evidence = mgr._memories[mid].metadata.get("_auto_classified")
        assert evidence is not None, "推断出来的分类必须留下证据（否则无从审计）"
        assert evidence["inferred"] == ["category", "memory_type", "perspective"]
        assert 0.0 < evidence["confidence"] <= 1.0
        assert evidence["reasoning"]

    def test_fully_declared_write_records_no_evidence(self, mgr):
        """三项全声明 ⇒ 引擎不推断，也不留"猜的"痕迹。"""
        mid = mgr.remember(
            "用户喜欢在清晨跑步",
            category=MemoryCategory.USER_PREFERENCE.value,
            memory_type=MemoryType.SEMANTIC.value,
            perspective=MemoryPerspective.FIRST_PERSON.value,
            auto_classify=True,
        )
        assert "_auto_classified" not in mgr._memories[mid].metadata

    def test_evidence_survives_restart(self, tmp_path):
        first = MemoryManager(
            db_path=str(tmp_path / "mem.db"), agent_id="cls-agent",
            neuser_id="neu", user_id="u1", enable_buffer=False,
        )
        mid = first.remember("用户偏好深色模式", auto_classify=True)
        first.close()
        reopened = MemoryManager(
            db_path=str(tmp_path / "mem.db"), agent_id="cls-agent",
            neuser_id="neu", user_id="u1", enable_buffer=False,
        )
        try:
            assert reopened._memories[mid].category is MemoryCategory.USER_PREFERENCE
            assert reopened._memories[mid].metadata["_auto_classified"]["inferred"]
        finally:
            reopened.close()

    def test_classification_context_reaches_engine(self, mgr):
        """classification_context 此前是 kwargs 黑洞；现在透传给引擎（情感亲和）。"""
        mid = mgr.remember(
            "一段中性叙述，没有任何分类关键词",
            auto_classify=True,
            classification_context={"emotion": "nostalgia"},
        )
        # nostalgia 的亲和性 EXPERIENCE=0.5 触发增强 → 不再是 general
        assert mgr._memories[mid].category is MemoryCategory.EXPERIENCE

    def test_empty_content_does_not_crash(self, mgr):
        mid = mgr.remember("   ", auto_classify=True)
        assert mgr._memories[mid].category is MemoryCategory.GENERAL

    def test_counter_visible_in_stats(self, mgr):
        mgr.remember("用户喜欢在清晨跑步", auto_classify=True)
        mgr.remember("一条普通记录")
        stats = mgr.get_stats()
        assert stats["auto_classified_count"] == 1, "自动分类计数必须可见（0 是异常态）"
        assert stats["by_category"].get("user_preference") == 1

    def test_classified_row_is_retrievable_by_category(self, mgr):
        mid = mgr.remember("用户喜欢在清晨跑步，这是我的偏好", auto_classify=True)
        hits = mgr.recall(
            query="清晨跑步", category=MemoryCategory.USER_PREFERENCE.value, limit=10
        )
        assert [h["id"] for h in hits] == [mid], "分类写到了行上，却没进 category 检索面"


# ──────────────────────────────────────────────────────────────────
# 4. classify_memory 契约（端点 500 的另一半根因）
# ──────────────────────────────────────────────────────────────────


class TestClassifyMemoryContract:
    def test_two_arg_signature(self, mgr):
        """端点以 (content, context) 两参调用 —— 签名必须真接受两参。"""
        result = mgr.classify_memory("用户喜欢深色模式", {"emotion": "joy"})
        assert isinstance(result, dict)

    def test_returns_string_values_with_separate_confidence(self, mgr):
        """category/type/perspective 是字符串值，置信度单列（不是 (值, 置信度) 元组）。"""
        result = mgr.classify_memory("用户喜欢深色模式")
        for key in ("category", "type", "perspective"):
            assert isinstance(result[key], str), f"{key} 必须是字符串值：{result[key]!r}"
            assert isinstance(result[f"{key}_confidence"], float)
        assert MemoryCategory(result["category"])
        assert MemoryType(result["type"])

    def test_no_longer_defined_the_17_dim_private_enums(self):
        """仓库里不得再有第二套 7/6/4 分类枚举的独立定义。"""
        from pathlib import Path

        src = Path(
            "neurova/cognitive_layers/memory_layer/auto_classifier.py"
        ).read_text(encoding="utf-8")
        assert "class CategoryType(Enum)" not in src
        assert "class MemoryTypeEnum(Enum)" not in src
        assert "class PerspectiveType(Enum)" not in src
