"""洞察镜像 thought 条目防回归（TDD 红灯先行）。

根因：V3 融合后条目列表/统计只读 kind='thought'，但全系统唯一 thought
写入方是页面"创建"按钮——自动反思产出的洞察落 kind='lesson'，条目卡片
在自然使用下恒空（2026-09-16 用户报告）。

新契约：SelfModelEngine.reflect 产出洞察时镜像一条 kind='thought' 记录，
使元认知页"条目卡片"自动出现数据：
- 镜像条目 content = 洞察 text，context = 'insight:{operator}'，
  metadata 记 lesson_operator + 产出 trigger，可追溯回教训；
- 同一算子+工具签名的教训已镜像过（活跃期内）不重复刷屏；
- 活跃期内同签名教训再次产出 → 不新增镜像（防每 10 分钟一轮的周期反思
  把条目卡片刷成同文案洪流）；
- 镜像不落 kind='lesson'/'reflection'（反思页时间线与调控门窗口不受污染）；
- 无洞察时不产任何镜像；
- 前端消费端点 GET /{agent}/metacognition 在反思后能读到镜像条目。
"""

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.cognitive_layers.meta_cognition_layer.ledger import (
    MetaLedger,
    get_meta_ledger,
    reset_meta_ledger,
)
from neurova.cognitive_layers.meta_cognition_layer.self_model import (
    get_self_model_engine,
    reset_self_model_engine,
)

AGENT = "mirror_agent"


def _feed_tool_events(ledger, tool, successes, failures, context=None):
    meta = dict(context or {})
    for _ in range(successes):
        ledger.write_event(agent_id=AGENT, process_type="tool", description=tool, success=True, metadata=meta)
    for _ in range(failures):
        ledger.write_event(agent_id=AGENT, process_type="tool", description=tool, success=False, metadata=meta)


def _mirror_thoughts(ledger):
    return ledger.list_records(agent_id=AGENT, kind="thought")["items"]


class TestLessonThoughtMirror(unittest.TestCase):
    def setUp(self):
        reset_self_model_engine()
        reset_meta_ledger()
        self.engine = get_self_model_engine(AGENT)
        self.ledger = get_meta_ledger(AGENT)

    def tearDown(self):
        reset_self_model_engine()
        reset_meta_ledger()

    def test_lessons_mirror_as_thought_entries(self):
        """反思产出洞察 → 台账出现镜像 thought 条目（content=洞察 text）。"""
        _feed_tool_events(self.ledger, "web_search", 5, 45)  # 10% 成功率 → drift 教训
        self.engine.reflect(trigger="test")
        mirrored = _mirror_thoughts(self.ledger)
        self.assertTrue(mirrored, "洞察必须镜像为 thought 条目，否则元认知页条目卡片恒空")
        self.assertTrue(any("web_search" in it["content"] for it in mirrored))

    def test_mirror_is_not_lesson_or_reflection(self):
        """镜像只落 kind='thought'，反思时间线与调控门窗口不得被污染。"""
        _feed_tool_events(self.ledger, "web_search", 5, 45)
        self.engine.reflect(trigger="test")
        history = self.ledger.reflection_history(AGENT)
        self.assertEqual(len(history), 1, "镜像不得混入反思时间线")
        lesson_rows = self.ledger.list_records(agent_id=AGENT, kind="lesson")["items"]
        self.assertTrue(lesson_rows)
        for it in lesson_rows:
            self.assertNotIn(
                "lesson_subject",
                it.get("metadata") or {},
                "镜像不得写成 lesson kind（lesson_subject 是镜像条目专属标记）",
            )

    def test_mirror_dedup_within_active_window(self):
        """同签名教训在活跃期内再次产出 → 不重复镜像（防周期反思刷屏）。"""
        _feed_tool_events(self.ledger, "web_search", 5, 45)
        self.engine.reflect(trigger="first")
        first = _mirror_thoughts(self.ledger)
        self.assertTrue(first)
        # 不补新事件：算子复跑同批次台账 → 同签名教训再次产出
        self.engine.reflect(trigger="second")
        second = _mirror_thoughts(self.ledger)
        self.assertEqual(
            len(second),
            len(first),
            "同签名教训在活跃期内重复产出不得新增镜像条目",
        )

    def test_mirror_rewrites_after_expiry(self):
        """教训过期（TTL 归零）后同签名复跑 → 允许新镜像（活跃性窗口外重开）。"""
        _feed_tool_events(self.ledger, "web_search", 5, 45)
        self.engine.reflect(trigger="first")
        first = _mirror_thoughts(self.ledger)
        self.assertTrue(first)
        # 强制全部镜像条目过期：反映射活跃窗口语义 = 台账中已无该签名活跃条目
        with self.ledger._lock:
            self.ledger._conn.execute("UPDATE meta_records SET created_at = ?", ("2020-01-01T00:00:00+00:00",))
            self.ledger._conn.commit()
        self.engine.reflect(trigger="second")
        second = _mirror_thoughts(self.ledger)
        # 每个签名（本批次产出 drift+sequence 两条教训）各重新镜像一条
        self.assertEqual(len(second), len(first) * 2, "过期后同签名教训应重新镜像")

    def test_no_lessons_no_mirror(self):
        """空产出（无洞察）不得产生镜像条目。"""
        self.engine.reflect(trigger="empty")
        self.assertEqual(_mirror_thoughts(self.ledger), [])

    def test_mirror_metadata_carries_lesson_traceability(self):
        """溯源快照：镜像条目 metadata 必须自含原始教训的算子/条件/发现/建议/证据。

        前端"点击展开溯源"直接消费镜像条目自身，不再回查 lesson 记录
        （lesson 有 24h TTL 且被裁剪回收，条目卡片须自含其生命周期内的全量事实）。
        """
        _feed_tool_events(self.ledger, "web_search", 5, 45)
        self.engine.reflect(trigger="trace_check")
        mirrored = _mirror_thoughts(self.ledger)
        self.assertTrue(mirrored)
        by_op = {}
        for it in mirrored:
            meta = it.get("metadata") or {}
            self.assertEqual(meta.get("lesson_subject"), "web_search")
            self.assertIn(meta.get("lesson_operator"), ("drift", "sequence"))
            self.assertIn(meta.get("reflection_trigger"), ("trace_check",))
            self.assertIn("condition", meta)
            self.assertIn("finding", meta)
            self.assertIsInstance(meta.get("evidence"), dict)
            self.assertTrue(meta.get("evidence"), "证据快照不得为空——这是可追溯性的核心")
            by_op[meta.get("lesson_operator")] = meta
        # 建议快照与原始教训逐字一致（drift→avoid_tool，sequence→review）
        self.assertEqual(by_op["drift"]["recommendation"], "avoid_tool")
        self.assertEqual(by_op["sequence"]["recommendation"], "review")

    def test_api_entries_visible_after_reflect(self):
        """前端消费端点在反思后能读到镜像条目（条目卡片自动出现数据的最终闭环）。"""
        _feed_tool_events(self.ledger, "web_search", 5, 45)
        self.engine.reflect(trigger="api")
        app = FastAPI()
        from neurova.api.endpoints import metacognition_api

        app.include_router(metacognition_api.router, prefix="/api/v1/metacognition")
        client = TestClient(app)
        data = client.get(f"/api/v1/metacognition/{AGENT}/metacognition").json()["data"]
        self.assertGreaterEqual(data["total"], 1)
        self.assertTrue(any("web_search" in it["content"] for it in data["items"]))


if __name__ == "__main__":
    unittest.main()
