"""工单 015 · 结晶 LLM 裁决闸收进治理设置，且**读取时机**必须在裁决点。

原实现把开关读在 `PatternCrystallizer.__init__`（一次性快照）。收进治理面后
如果沿用一次性快照，"改配置"要重启进程才生效——那又是一个"治理页能改、
运行时不认"的幻影旋钮。本文件锁两件事：

1. 优先级与 `metacog_gate_enabled` 同口径（env 显式 0 > env 显式 1 > 治理 > 默认），
   三个方向都断言；
2. 闸的读取发生在**裁决时刻**：同一个实例存续期间改治理设置，下一次候选
   裁决必须跟着变。
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

_GATE_ENV = "NEUROVA_CRYSTALLIZATION_LLM_GATE"
_GATE_KEY = "crystallization_llm_gate_enabled"


class _FakeEngine:
    def __init__(self):
        self.stored = []

    def store(self, node):
        self.stored.append(node)

    def retrieve(self, query, limit=5, filters=None):
        return []


class CrystallizationGateGovernanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.settings_file = os.path.join(self.tmp, "governance_settings.json")
        self._env_patcher = patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ.pop(_GATE_ENV, None)
        self._settings_patcher = patch(
            "neurova.security.governance_settings.settings_path",
            return_value=Path(self.settings_file),
        )
        self._settings_patcher.start()

    def tearDown(self):
        self._settings_patcher.stop()
        self._env_patcher.stop()

    def _set_governance(self, enabled):
        with open(self.settings_file, "w", encoding="utf-8") as fh:
            json.dump({_GATE_KEY: enabled}, fh)

    def _crystallizer(self):
        engine = _FakeEngine()
        return PatternCrystallizer(engine=engine, state_path=os.path.join(self.tmp, "st.json")), engine

    @staticmethod
    def _observe(c, ctx):
        for _ in range(3):
            c.observe("web_search", ctx, True)

    def test_default_keeps_candidate_queued(self):
        """反向锁：什么都不配置时闸照旧开着——收口不得改变现网默认。"""
        c, engine = self._crystallizer()
        self._observe(c, "搜索 天气 资料")
        self.assertEqual(len(engine.stored), 0, "默认必须走 LLM 裁决，不得直写")
        self.assertEqual(len(c.list_pending()), 1)

    def test_governance_off_takes_effect_on_existing_instance(self):
        """读取时机：实例已构造，改治理设置后**下一次裁决**就要跟着变。

        构造期快照式读取会让这条断言永远红——那等于治理页上的开关是装饰品。
        """
        c, engine = self._crystallizer()
        self._observe(c, "搜索 天气 资料")
        self.assertEqual(len(c.list_pending()), 1, "前置：默认开，候选留队")

        self._set_governance(False)
        self._observe(c, "整理 报告 文档")

        self.assertEqual(len(engine.stored), 1, "治理关闸后新候选必须直写，不重启也要生效")
        self.assertEqual(len(c.list_pending()), 1, "只关掉后续裁决，已留队的候选不因此被放行")

    def test_governance_on_queues_when_env_absent(self):
        """方向③：env 未设置 ⇒ 治理面说话，True 即留队（与默认 False 相反才成立）。"""
        self._set_governance(True)
        c, engine = self._crystallizer()
        self._observe(c, "汇总 汇率 报表")
        self.assertEqual(len(engine.stored), 0, "治理开闸时不得直写")
        self.assertEqual(len(c.list_pending()), 1)

    def test_env_zero_forces_direct_write_over_governance_true(self):
        """方向①：env 显式 0 压过治理 True。"""
        self._set_governance(True)
        c, engine = self._crystallizer()
        with patch.dict(os.environ, {_GATE_ENV: "0"}):
            self._observe(c, "翻译 段落 英文")
        self.assertEqual(len(engine.stored), 1, "env 显式关闸必须直写")
        self.assertEqual(c.list_pending(), [])

    def test_env_one_forces_queuing_over_governance_false(self):
        """方向②：env 显式 1 压过治理 False。"""
        self._set_governance(False)
        c, engine = self._crystallizer()
        with patch.dict(os.environ, {_GATE_ENV: "1"}):
            self._observe(c, "解析 表格 csv")
        self.assertEqual(len(engine.stored), 0, "env 显式开闸必须留队裁决")
        self.assertEqual(len(c.list_pending()), 1)

    def test_judge_still_not_bypassed_when_gate_open_via_governance(self):
        """治理开闸 ⇒ 裁决链完整（judge 在位也不直写，闸不是装饰）。"""
        self._set_governance(True)
        c, engine = self._crystallizer()
        c.set_llm_judge(MagicMock())
        self._observe(c, "生成 摘要 长文")
        self.assertEqual(len(engine.stored), 0)
        self.assertEqual(len(c.list_pending()), 1)


if __name__ == "__main__":
    unittest.main()
