"""008 · 肌肉记忆要真的能复用：中文指纹 + 规范参数 + 成功票回流（D4 终态）。

三条必修：
| # | 落点 | 现状 | 要求 |
|---|---|---|---|
| a | `_extract_keywords` | `\\w\\s` + `split()` ⇒ 中文整句一个 token，"指纹相等"≈"整串相等" | 字符 n-gram 口径（自研、零新增依赖） |
| b | 写侧参数 | 存的是降级后的 `{"_raw": …}` | 复用 `tool_executor._parse_params` 单源，存规范 dict |
| c | 现网脏条目 | `agent_workspaces/kai/.../muscle_l2.json` 2 条 | 作废重攒且可回退（归档名挂原文件后，**不删除**） |
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory

DIRTY_L2 = [{
    "id": "4b21fc785c8076be", "tool_name": "weather",
    "query_fingerprint": "你能不能再次试一试",
    "vector_fingerprint": "862691f5ea391093",
    "parameters": {"_raw": 'location="许昌", city="许昌"'},
    "result_summary": "", "level": "l2", "success_count": 2, "failure_count": 0,
    "consecutive_successes": 2, "last_used": 1787748120.246597,
    "created_at": 1787748120.2431674, "metadata": {"tool_source": "builtin"},
}]


class TestChineseFingerprint:
    """换实体近似句必须能命中（旧实现在 0.6/0.343 处断层）。"""

    @pytest.mark.parametrize("first,second", [
        ("许昌今天天气怎么样", "许昌明天天气怎么样"),
        ("帮我查一下许昌的天气", "帮我查一下北京的天气"),
        ("今天天气如何", "今天的天气如何"),
        ("查一下明天下雨吗", "查一下后天有没有雨"),
    ])
    def test_near_miss_queries_share_fingerprint_tokens(self, first, second):
        memory = MuscleMemory()
        fp_first = memory._extract_keywords(first)
        fp_second = memory._extract_keywords(second)
        assert fp_first, "中文整句必须切得出指纹 token"
        tokens_first = {t for t in fp_first.split(",") if t}
        tokens_second = {t for t in fp_second.split(",") if t}
        assert tokens_first & tokens_second, (
            f"近似问法没有任何共享 token，指纹等于整串相等：{tokens_first} vs {tokens_second}"
        )

    def test_entity_swap_confidence_reaches_hit_threshold(self):
        """换实体（今天→明天）的 confidence 必须 ≥ 0.85 且命中候选（票面判据）。"""
        memory = MuscleMemory()
        memory.record_usage(
            tool_name="weather", query="许昌今天天气怎么样",
            parameters={"location": "许昌"}, success=True,
        )
        matches = memory.match_by_query("许昌明天天气怎么样")
        assert matches, "近似问法没有命中任何候选（指纹口径仍是整串）"
        _, confidence = matches[0]
        assert confidence >= 0.85, f"换实体近似句的置信度只有 {confidence}"

    def test_unrelated_query_still_misses(self):
        """反向锁：放宽口径不能放宽到"什么都命中"。"""
        memory = MuscleMemory()
        memory.record_usage(
            tool_name="weather", query="许昌今天天气怎么样",
            parameters={"location": "许昌"}, success=True,
        )
        assert memory.match_by_query("帮我写一段 Python 排序代码") == [], (
            "无关问法也被召回了，等于把召回面放宽成噪声"
        )


class TestCanonicalParams:
    """写侧参数必须走规范 dict（复用单源 key=value 解析器）。"""

    def test_raw_string_params_are_normalized_on_write(self):
        memory = MuscleMemory()
        item = memory.record_usage(
            tool_name="weather",
            query="许昌天气怎么样",
            parameters={"_raw": 'location="许昌", city="许昌"'},
            success=True,
        )
        assert "_raw" not in item.parameters, (
            f"降级参数被原样存下（命中后必然被参数校验拒）：{item.parameters}"
        )
        assert item.parameters.get("location") == "许昌"
        assert item.parameters.get("city") == "许昌"

    def test_clean_dict_is_untouched(self):
        memory = MuscleMemory()
        item = memory.record_usage(
            tool_name="weather", query="许昌天气怎么样",
            parameters={"location": "许昌"}, success=True,
        )
        assert item.parameters == {"location": "许昌"}


class TestDirtyArchiveIsReversible:
    """现网脏条目作废重攒，且作废动作可回退（归档不删除）。"""

    def test_archive_script_name_is_reversible(self, tmp_path):
        from scripts.diagnostics.muscle_memory_rearchive import archive_dirty_memory

        target = tmp_path / "muscle_l2.json"
        target.write_text(json.dumps(DIRTY_L2, ensure_ascii=False), encoding="utf-8")
        archived = archive_dirty_memory(target)
        assert archived is not None and archived.exists(), "归档副本没落盘，动作不可回退"
        assert archived.name.startswith("muscle_l2.json.pre-muscle-ngram-")
        assert target.exists() and json.loads(target.read_text(encoding="utf-8")) == [], (
            "脏条目没有被清空重攒"
        )
        assert json.loads(archived.read_text(encoding="utf-8")) == DIRTY_L2, (
            "归档内容与原文件不一致，回退后丢数据"
        )
