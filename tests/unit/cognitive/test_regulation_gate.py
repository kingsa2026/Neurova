"""调控门（regulation gate）契约测试——V3 行为改变闭环的最后一公里

check_tool_advisory 产出 avoid_tool 教训 → tool_executor 消费：
- env NEUROVA_METACOG_GATE=="1" 时，命中活跃 avoid_tool 教训的工具被拦截
- 默认关（新扩展点默认关约束），关闭时零行为变化
- 拦截返回结构化建议（含教训 text 与 recommendation），不计工具故障
- 同批：/lessons 端点与 check_tool_advisory 过期口径一致（expires_at 过滤）
"""

import os
import unittest
from pathlib import Path

from neurova.cognitive_layers.meta_cognition_layer.ledger import (
    get_meta_ledger,
    reset_meta_ledger,
)
from neurova.cognitive_layers.meta_cognition_layer.self_model import (
    get_self_model_engine,
    reset_self_model_engine,
)

AGENT = "gate_agent"


def _seed_avoid_lesson(tool="bad_tool"):
    ledger = get_meta_ledger(AGENT)
    for _ in range(5):
        ledger.write_event(agent_id=AGENT, process_type="tool", description=tool, success=True)
    for _ in range(45):
        ledger.write_event(agent_id=AGENT, process_type="tool", description=tool, success=False)
    engine = get_self_model_engine(AGENT)
    report = engine.reflect(trigger="test")
    assert any(l["subject"] == tool and l["recommendation"] == "avoid_tool" for l in report["lessons"]), (
        "种子数据必须产出 avoid_tool 教训"
    )
    return engine


class RegulationGateTest(unittest.TestCase):
    def setUp(self):
        reset_self_model_engine()
        reset_meta_ledger()
        os.environ.pop("NEUROVA_METACOG_GATE", None)

    def tearDown(self):
        os.environ.pop("NEUROVA_METACOG_GATE", None)
        reset_self_model_engine()
        reset_meta_ledger()

    def _executor(self):
        from types import SimpleNamespace
        from neurova.tool_executor import ToolExecutor

        agent = SimpleNamespace(config=SimpleNamespace(agent_id=AGENT))
        executor = ToolExecutor.__new__(ToolExecutor)
        executor._agent = agent
        return executor

    def test_gate_denies_tool_when_enabled(self):
        """门开 + 活跃 avoid_tool 教训 → 拦截，返回结构化建议。"""
        _seed_avoid_lesson()
        os.environ["NEUROVA_METACOG_GATE"] = "1"
        executor = self._executor()

        verdict = executor._metacog_gate_check("bad_tool")
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict["recommendation"], "avoid_tool")
        self.assertIn("text", verdict)

    def test_gate_passes_tool_without_lesson(self):
        """门开 + 无教训 → None（放行）。"""
        _seed_avoid_lesson()
        os.environ["NEUROVA_METACOG_GATE"] = "1"
        executor = self._executor()
        self.assertIsNone(executor._metacog_gate_check("good_tool"))

    def test_gate_disabled_by_default(self):
        """默认关：即使有活跃教训也不拦截（零行为变化）。"""
        _seed_avoid_lesson()
        executor = self._executor()
        self.assertIsNone(executor._metacog_gate_check("bad_tool"))

    def test_advisory_expires(self):
        """过期教训不再拦截（与 /lessons 端点过滤口径一致化前的调控门语义）。"""
        engine = _seed_avoid_lesson()
        # 手动把活跃教训改过期
        import datetime
        ledger = get_meta_ledger(AGENT)
        result = ledger.list_records(agent_id=AGENT, page=1, size=50, kind="lesson")
        self.assertTrue(result["items"])
        expired = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
        with ledger._lock:
            ledger._conn.execute(
                "UPDATE meta_records SET metadata=json_set(metadata, '$.expires_at', ?)"
                " WHERE agent_id=? AND kind='lesson'",
                (expired, AGENT),
            )
            ledger._conn.commit()
        self.assertIsNone(engine.check_tool_advisory("bad_tool"), "过期教训不得拦截")


class RegulationGateGovernanceSettingTest(unittest.TestCase):
    """开关来源收口（反思反哺闭环审计 2026-09-19）

    根因：门控只读裸 env NEUROVA_METACOG_GATE，而生产没有任何配置面写它
    （全仓唯一设值处是本文件的用例）→ 教训的硬拦截臂在真实部署里恒关，
    自模型反思产出的 avoid_tool 教训没有任何一条能改变工具执行。
    改为与 Step9.96 成本门控同口径：env 显式设 0 强制关 > env 显式设 1 >
    治理设置 metacog_gate_enabled > 内置默认关。
    """

    def setUp(self):
        reset_self_model_engine()
        reset_meta_ledger()
        os.environ.pop("NEUROVA_METACOG_GATE", None)
        self._orig_settings = os.environ.get("NEUROVA_GOVERNANCE_SETTINGS")
        import tempfile

        self._settings_file = Path(tempfile.mkdtemp()) / "governance_settings.json"
        os.environ["NEUROVA_GOVERNANCE_SETTINGS"] = str(self._settings_file)

    def tearDown(self):
        os.environ.pop("NEUROVA_METACOG_GATE", None)
        if self._orig_settings is None:
            os.environ.pop("NEUROVA_GOVERNANCE_SETTINGS", None)
        else:
            os.environ["NEUROVA_GOVERNANCE_SETTINGS"] = self._orig_settings
        reset_self_model_engine()
        reset_meta_ledger()

    def _executor(self):
        from types import SimpleNamespace

        from neurova.tool_executor import ToolExecutor

        executor = ToolExecutor.__new__(ToolExecutor)
        executor._agent = SimpleNamespace(config=SimpleNamespace(agent_id=AGENT))
        return executor

    def test_gate_enabled_by_governance_setting(self):
        """治理设置开 → 生产无需 env 即可拦截（配置面可用性判据）。"""
        _seed_avoid_lesson()
        from neurova.security.governance_settings import save_governance_settings

        self.assertTrue(save_governance_settings({"metacog_gate_enabled": True}))
        self.assertIsNotNone(self._executor()._metacog_gate_check("bad_tool"))

    def test_gate_stays_off_without_setting(self):
        """设置缺省（新建配置文件）→ 默认关，接线不得反向扩大拦截面。"""
        _seed_avoid_lesson()
        self.assertFalse(self._settings_file.exists(), "前置：设置文件应尚未创建")
        self.assertIsNone(self._executor()._metacog_gate_check("bad_tool"))

    def test_env_zero_overrides_governance_setting(self):
        """env 显式设 0 是运维后门，优先级高于治理设置。"""
        _seed_avoid_lesson()
        from neurova.security.governance_settings import save_governance_settings

        save_governance_settings({"metacog_gate_enabled": True})
        os.environ["NEUROVA_METACOG_GATE"] = "0"
        self.assertIsNone(self._executor()._metacog_gate_check("bad_tool"))

    def test_env_one_still_enables_gate(self):
        """既有 env=1 运维口径保持有效（不得因收口而失效）。"""
        _seed_avoid_lesson()
        os.environ["NEUROVA_METACOG_GATE"] = "1"
        self.assertIsNotNone(self._executor()._metacog_gate_check("bad_tool"))


if __name__ == "__main__":
    unittest.main()
