# -*- coding: utf-8 -*-
"""E4 人格特质接行为注入（四域审计 2026-11-18 修复卡 E4）。

缺陷（双轨脱钩）：人格特质 JSON（`personality_persistence.py` 独立持久源
`data/<agent_id>/personality.json`，前端 AgentPersonalityPage 在用）**只存不用**
——真正进 prompt 的只有 `personality.md` 文本轨（agent.personality 字符串），
特质/价值观/沟通与决策风格对 agent 行为零影响。

用户拍板：按「接线」执行（不做诚实化降级）。`/personality/evolve` 501 诚实桩不动。

锁定行为：
1. communication_style / decision_style / traits / values 编译进人格段，
   与 personality.md 文本轨**同一组装点**（特质段紧邻文本轨条目之后）。
2. 渲染有界（具名常量），超限诚实截断且读数面可见。
3. 特质段随会话身份快照冻结：特质 JSON 变化 → 新会话信封随之变化，
   同会话中途不漂移。
4. 空特质不注入空段。
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neurova.api.endpoints import personality_persistence as pp
from neurova.context.orchestrator import ContextOrchestrator

AGENT_ID = "agent_e4"
TRAITS_HEADER = "人格特质档案"
PERSONALITY_MD_TEXT = "独特性格印记XYZ"


@pytest.fixture(autouse=True)
def _isolate_personality_root(tmp_path, monkeypatch):
    """人格特质持久源隔离：工作区根已由全局 autouse 夹具指到 tmp_path，
    这里再显式钉一次数据根，双保险防写穿共享目录。"""
    monkeypatch.setenv("NEUROVA_AGENT_WORKSPACES_DIR", str(tmp_path / "agentWorkspaces"))
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "dataRoot"))


def _build_orchestrator():
    mock_agent = MagicMock()
    mock_agent.config = MagicMock()
    mock_agent.config.name = "e4"
    mock_agent.config.agent_id = AGENT_ID
    mock_agent.config.constitution = ""
    mock_agent.config.behavior_rules = []
    mock_agent.config.workspace_path = ""
    mock_agent.memory_manager = MagicMock()
    mock_agent.context_builder = MagicMock()
    mock_agent.tool_router = MagicMock()
    mock_agent._skill_registry = MagicMock()
    mock_agent.soul = "你是测试助手"
    mock_agent.personality = PERSONALITY_MD_TEXT
    mock_agent.conversation_history = []
    mock_agent.growth_log_manager = MagicMock()
    mock_agent.user_id = "u1"
    mock_agent.agent_id = AGENT_ID
    return ContextOrchestrator(mock_agent, use_pool=True)


async def _build_messages(orchestrator, user_input="你好"):
    with patch.object(
        orchestrator, "get_tools_description", new_callable=AsyncMock
    ) as tools:
        tools.return_value = "可用工具：file_read"
        return await orchestrator.build_context(user_input=user_input)


def _system_msgs(messages):
    return [str(m.get("content", "")) for m in messages if m.get("role") == "system"]


def _system_text(messages):
    return "\n".join(_system_msgs(messages))


@pytest.mark.asyncio
async def test_styles_traits_values_reach_personality_section(_isolate_personality_root):
    """红灯：特质 JSON 落盘后，新会话信封的人格段含风格/特质/价值观文本。"""
    pp.save_personality_data(
        AGENT_ID,
        {
            "communication_style": "简洁直接",
            "decision_style": "数据驱动",
            "values": ["诚实", "勇敢"],
            "traits": {"开放性": 0.9, "尽责性": 0.7},
        },
    )
    orchestrator = _build_orchestrator()
    msgs = _system_msgs(await _build_messages(orchestrator))
    text = "\n".join(msgs)
    assert "简洁直接" in text, "沟通风格必须进入 system_instructions"
    assert "数据驱动" in text, "决策风格必须进入 system_instructions"
    assert "诚实" in text and "勇敢" in text, "价值观必须进入 system_instructions"
    assert "开放性" in text, "特质摘要必须进入 system_instructions"
    assert TRAITS_HEADER in text, "特质段段头必须可见（读数面）"
    # 同一组装点：特质段紧邻 personality.md 文本轨之后
    idx_md = next(i for i, s in enumerate(msgs) if PERSONALITY_MD_TEXT in s)
    idx_traits = next(i for i, s in enumerate(msgs) if TRAITS_HEADER in s)
    assert idx_traits == idx_md + 1, "特质段必须紧邻人格文本轨（同一组装点，不造第二入口）"


@pytest.mark.asyncio
async def test_empty_traits_inject_nothing(_isolate_personality_root):
    """空特质（空 dict / 缺文件）不注入空段。"""
    pp.save_personality_data(AGENT_ID, {})
    orchestrator = _build_orchestrator()
    text = _system_text(await _build_messages(orchestrator))
    assert TRAITS_HEADER not in text


@pytest.mark.asyncio
async def test_missing_traits_file_inject_nothing(_isolate_personality_root):
    """从未写过 personality.json 也不注入空段。"""
    orchestrator = _build_orchestrator()
    text = _system_text(await _build_messages(orchestrator))
    assert TRAITS_HEADER not in text


@pytest.mark.asyncio
async def test_traits_change_reflected_in_new_session(_isolate_personality_root):
    """特质 JSON 变化 → 新会话信封人格段随之变化。"""
    pp.save_personality_data(
        AGENT_ID, {"communication_style": "简洁直接", "decision_style": "数据驱动"}
    )
    orchestrator = _build_orchestrator()
    text1 = _system_text(await _build_messages(orchestrator))
    assert "简洁直接" in text1

    pp.save_personality_data(
        AGENT_ID, {"communication_style": "温和委婉", "decision_style": "数据驱动"}
    )
    orchestrator2 = _build_orchestrator()
    text2 = _system_text(await _build_messages(orchestrator2))
    assert "温和委婉" in text2, "新会话必须吃到新特质"
    assert "简洁直接" not in text2, "旧特质不得残留到新会话"


@pytest.mark.asyncio
async def test_traits_frozen_within_session(_isolate_personality_root):
    """特质段随会话身份快照冻结：同会话中途改特质不漂移当前 prompt。"""
    pp.save_personality_data(AGENT_ID, {"communication_style": "简洁直接"})
    orchestrator = _build_orchestrator()

    from neurova.agent.session_snapshot import SessionSnapshotCache

    orchestrator._agent._frozen_identity_snapshot = SessionSnapshotCache._read_live(
        orchestrator._agent
    )
    text1 = _system_text(await _build_messages(orchestrator))
    assert "简洁直接" in text1

    pp.save_personality_data(AGENT_ID, {"communication_style": "温和委婉"})
    text2 = _system_text(await _build_messages(orchestrator))
    assert "简洁直接" in text2, "同会话内特质必须保持快照时点形态"
    assert "温和委婉" not in text2


@pytest.mark.asyncio
async def test_traits_section_truncated_bounded(_isolate_personality_root):
    """超总长上限诚实截断且标注可见。"""
    long_value = "价值" * pp.PERSONALITY_TRAITS_MAX_CHARS
    pp.save_personality_data(AGENT_ID, {"values": [long_value]})
    orchestrator = _build_orchestrator()
    text = _system_text(await _build_messages(orchestrator))
    assert "已截断" in text, "截断必须诚实标注（读数面可见）"
    assert long_value not in text
