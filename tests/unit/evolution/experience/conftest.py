"""经验链路探针基座（工单 001）。

设计约束 —— 本批所有经验相关测试必须遵守：

1. **禁止用 MagicMock 冒充工具消息**。`MagicMock().get("success", True)` 恒真，
   正是 `post_chat_pipeline.py:1612` 那条聚合能长期恒真的原因之一。工具消息必须用
   本文件的 `tool_call_record` / `tool_result_record` 造，形态逐字段抄
   `neurova/agent/loops/base.py`（`:196-204` 的 `tool_call` 记录**没有** `success` 键；
   `:333-341` 的 `tool_result` 记录**有** `success` 键）。
2. **禁止在测试里手工传阈值绕过生产装配点**。判据是否生效，必须从
   `agent_core.py` 的生产构造点或本文件的探针改起，而不是给被测函数塞参数。
3. **禁止恒真断言**。`outcome in {"success","failure","partial"}` 这类
   （`tests/unit/evolution/test_experience_feedback.py:57,66,75` 现状）不能当验收：
   每条断言都要有一个"判据被破坏时必然转红"的反例。
4. **写验证一律挂临时 EKB 库**（`NEUROVA_EKB_DB`，见
   `experience_knowledge_base.py:43-46`）。`data/experience_knowledge.db` 是生产运行
   数据，只允许只读复核。
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from neurova.post_chat_pipeline import PostChatPipeline


def tool_call_record(tool_name: str, params: str = "{}") -> Dict[str, Any]:
    """`tool_call` 记录 —— 刻意**不带** `success` 键（真实形态即如此）。"""
    return {
        "type": "tool_call",
        "tool_name": tool_name,
        "params": params,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def tool_result_record(tool_name: str, success: bool,
                       result: str = "执行完成") -> Dict[str, Any]:
    """`tool_result` 记录 —— 客观成败只在这里携带。"""
    return {
        "type": "tool_result",
        "tool_name": tool_name,
        "tool_call_id": f"call_{tool_name}",
        "result": result,
        "success": success,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class RecordingEvolution:
    """进化编排器替身：只承担 `on_experience_recorded` 契约边界，并记录收到的成败。

    这是被测步骤的**协作方**边界，不是被测判据本身：`post_chat_pipeline.py:1612`
    聚合出的 `success` 既要去到 EKB 落库，也要走到这里，两处都要断言。
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def on_experience_recorded(self, *, text: str, task: str, tools: List[str],
                               success: Any, crystallizer: Any = None) -> Dict[str, Any]:
        self.calls.append({"text": text, "task": task, "tools": list(tools),
                           "success": success, "crystallizer": crystallizer})
        return {"success": True}


class ExperienceTurnProbe:
    """以生产构造点驱动经验写入链的探针。"""

    def __init__(self, pipeline: PostChatPipeline, evolution: RecordingEvolution,
                 db_path: Path) -> None:
        self.pipeline = pipeline
        self.evolution = evolution
        self.db_path = db_path
        self.turn_tool_messages: List[Dict[str, Any]] = []
        pipeline._get_dependency = lambda name: (
            evolution if name == "evolution" else None
        )

    def run_turn(self, user_input: str = "把报告导出成 PDF", reply: str = "已导出",
                 tool_messages: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """跑一轮经验记录步骤；`tool_messages` 必须是本文件的记录工厂产物。"""
        self.turn_tool_messages = list(tool_messages or [])
        asyncio.run(self.pipeline._step_record_experience(
            user_input=user_input, reply=reply, save_memory=True,
        ))
        return {
            "facade_success": (
                self.evolution.calls[-1]["success"] if self.evolution.calls else None
            ),
            "rows": self.experience_rows(),
        }

    def experience_rows(self) -> List[Dict[str, Any]]:
        if not self.db_path.exists():
            return []
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "select id, skill_name, context, success, confidence_score, agent_id, tags, "
                "evidence_state from experience_records order by id"
            )]
        finally:
            conn.close()


class RecordingEngine:
    """只记录被存节点的存储引擎替身。

    被测判据是"门槛按谁的值算"，不是存储层；引擎在此只当收集器。
    """

    def __init__(self) -> None:
        self.stored: List[Any] = []

    def store(self, node: Any) -> Any:
        self.stored.append(node)
        return getattr(node, "id", len(self.stored))


@pytest.fixture
def crystallizer_with_registry_bridge():
    """真实 ExperienceFeedback + 真实 PatternCrystallizer，经生产同款桥接装配。

    返回 (feedback, crystallizer, engine)。thresholds 只能从 feedback 侧改 ——
    这正是工单 004 要证的"调登记表真的能改入库闸"。
    """
    from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
    from neurova.evolution.experience_feedback import ExperienceFeedback

    engine = RecordingEngine()
    feedback = ExperienceFeedback()
    cryst = PatternCrystallizer(engine=engine)
    feedback.attach_crystallizer(cryst)
    return feedback, cryst, engine


@pytest.fixture
def make_crystallizer():
    """构造 (真实结晶器, 记录引擎)。引擎只当收集器，被测判据是门槛与裁决流程。"""
    from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

    def _make(state_path: Optional[str] = None):
        engine = RecordingEngine()
        return PatternCrystallizer(engine=engine, state_path=state_path), engine

    return _make


@pytest.fixture
def approving_judge():
    """一律判"可复用"的裁决替身：只覆盖 `generate(prompt)` 这一契约。"""

    class _Judge:
        def __init__(self):
            self.prompts: List[str] = []

        async def generate(self, prompt: str) -> str:
            self.prompts.append(prompt)
            import json
            keys = [line.split("]")[0].lstrip("- [")
                    for line in prompt.splitlines() if line.startswith("- [")]
            return json.dumps({"verdicts": [
                {"key": key, "reusable": True, "reason": "跨会话稳定复用"} for key in keys
            ]}, ensure_ascii=False)

    return _Judge()


@pytest.fixture
def tool_records():
    """把两个记录工厂以 fixture 暴露：`--import-mode=importlib` 下不能 `import conftest`。"""
    return SimpleNamespace(call=tool_call_record, result=tool_result_record)


@pytest.fixture
def experience_probe(tmp_path, monkeypatch):
    """临时 EKB 库 + 最小 pipeline；驱动生产写入链。"""
    db_path = tmp_path / "experience_knowledge.db"
    monkeypatch.setenv("NEUROVA_EKB_DB", str(db_path))
    # 单例带着上次的连接与路径，必须经公共复位钩子切走（`reset_experience_knowledge_base`）
    from neurova.skills.experience_knowledge_base import reset_experience_knowledge_base

    reset_experience_knowledge_base()

    agent = SimpleNamespace(
        config=SimpleNamespace(agent_id="agent-probe-01"),
        session_id="session-probe-01",
        crystallizer=None,
    )
    pipeline = PostChatPipeline.__new__(PostChatPipeline)
    pipeline._agent = agent
    token = PostChatPipeline._step_results_ctx.set([])
    evolution = RecordingEvolution()
    probe = ExperienceTurnProbe(pipeline, evolution, db_path)
    # `_agt` 是 `self._agent` 的 property，_collect_tool_messages 由探针按轮次提供
    agent._collect_tool_messages = lambda: list(probe.turn_tool_messages)
    try:
        yield probe
    finally:
        PostChatPipeline._step_results_ctx.reset(token)
        # 复位到"未创建"，避免把临时库路径泄漏给后续用例
        reset_experience_knowledge_base()


@pytest.fixture(autouse=True)
def _isolate_muscle_memory_ledger(tmp_path, monkeypatch):
    """肌肉记忆归档留底目录隔离（防仓库 `docs/05-reports/` 被测试写入）。

    留底目录是模块级常量（指向仓内），测试里若不加隔离，每跑一次归档用例就往
    仓库里落一份带时间戳的副本——一次性文件不可回收，且会把"留底"变成噪声。
    """
    from scripts.diagnostics import muscle_memory_rearchive

    monkeypatch.setattr(muscle_memory_rearchive, "LEDGER_DIR",
                        tmp_path / "muscle-memory-ledger")
