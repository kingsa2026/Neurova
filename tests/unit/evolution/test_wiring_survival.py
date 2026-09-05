"""接线存活扫描（第三遍审计固化：防并行覆盖回归）。

背景：2026-09-04~05 五批改动 + 三遍审计期间，并行会话重写 handler 曾把
C11 record_skill_usage 调用覆盖丢失（签名扫描当场抓出重接）。本测试把
全部改动的关键签名固化为契约——任何一次覆盖/回滚都会在这里红。

每条签名对应一个已审计的闭环传动轴；删改前请先更新本文件并说明理由。
"""

import io
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

# (文件, [签名...])——签名是闭环传动轴的代码锚点
WIRING_CHECKS = {
    "neurova/evolution/closed_loop.py": [
        "def _apply_lazy_decay",           # A 版思想②惰性衰减
        "def _windowed_success_rate",       # A 版思想①滑动窗口
        "def configure",                    # RSI 活表入口
        "def get_effective_multiplier",     # 动态阈值齿轮消费
        "def bootstrap_evolution_protections",  # C5 防护装配
        "window: Deque",                    # 窗口存储
    ],
    "neurova/cognitive_layers/memory_layer/tool_memory_integration.py": [
        "def _sync_weight_params",          # RSI 参数转发
        "def success_bonus",                # property 转发
        "def tool_weights",                 # 附着同步
    ],
    "neurova/agent_core.py": [
        "record_reuse",                     # Skill 断点#1 传动轴
        "a.evolution.tool_lifecycle",       # C3 生命周期单例
        "record_skill_usage",               # C11 使用计数（曾遭覆盖丢失）
        "crystallizer_state.json",          # C9 状态持久化接线
    ],
    "neurova/evolution/genetic_engine.py": [
        "skill_service",                    # 断点#2 持久化
        "register_auto_skill",              # 落盘调用
    ],
    "neurova/evolution/skill_improver.py": [
        "def apply_improvement",            # 断点#3 回写
        "def revert_last_improvement",      # C13 回滚
        "_applied_signatures",              # 同签名去重
        "version_after",                    # 回滚校验
        "config.setdefault",                # revisions 追加
    ],
    "neurova/post_chat_pipeline.py": [
        "apply_improvement",                # 提案走 apply
        "skill_service=skill_service",      # genetic 注册持久化
    ],
    "neurova/evolution/evolution_facade.py": [
        "get_top_patterns(k=top_n)",        # C4 透传
    ],
    "neurova/context/orchestrator.py": [
        "def render_tools_description",     # A1/A4
        "def _apply_visibility_gate",       # A2
        "def dedupe_experience_sources",    # D1
        "model_invocable",                  # B2
        "def _apply_tool_search_compaction",  # A6
        "tool_search_directory",            # X1 修复
        "NEUROVA_HIDE_DEGRADED_TOOLS",      # A2 门控
    ],
    "neurova/tool_executor.py": [
        "deps_warning",                     # B3 依赖声明
        "handle_control_tool",              # A6 拦截
        "has_grant",                        # E3 授权短路
    ],
    "neurova/evolution/skill_encapsulation.py": [
        "_review_gate",                     # C10 评审闸
        "def list_pending_templates",
        "def approve_template",
        "NEUROVA_SKILL_REVIEW_GATE",
    ],
    "neurova/skills/skill_service.py": [
        "def record_skill_usage",           # C11
        "def get_skill_usage",
    ],
    "neurova/cognitive_layers/memory_layer/pattern_crystallizer.py": [
        "def _save_buffer_state",           # C9
        "def _load_buffer_state",
    ],
    "neurova/evolution/rsi/integration_manager.py": [
        "def _write_optimization_receipt",  # C12
    ],
    "neurova/agent/chat_pipeline.py": [
        "redact_tool_messages_for_channel",  # E2
        "def _check_command_dispatch",       # B4
        "def _active_memory_escalation",     # D3
        'metadata.get("command_dispatched")',  # X4 ctx 轮次态
        "_is_past_seeking",                  # D3 判据
    ],
    "neurova/security/privacy_gate.py": [
        "def redact_tool_messages_for_channel",
    ],
    "neurova/context/tool_search.py": [
        "def apply_tool_search_compaction",  # A6
        "def search_catalog",
        "def handle_control_tool",
    ],
    "neurova/security/mcp_grants.py": [
        "def mint_grant",                    # E3
        "def parse_mcp_tool_name",
    ],
    "neurova/api/endpoints/governance.py": [
        "mint_grant",                        # E3 铸造点
    ],
    "neurova/api/endpoints/skill_pool_api.py": [
        "def list_pending_skills",           # X5 审批面
        "def approve_pending_skill",
        "def reject_pending_skill",
    ],
    "start_server.py": [
        "bootstrap_evolution_protections()",  # C5 接线
        "NEUROVA_RSI_RECEIPTS",               # C12 接线
    ],
}


@pytest.mark.parametrize("rel_path,signatures", sorted(WIRING_CHECKS.items()))
def test_wiring_signatures_alive(rel_path, signatures):
    """闭环传动轴签名存活：任何覆盖/回滚在此变红。"""
    path = REPO / rel_path
    assert path.exists(), f"文件缺失（被删除？）: {rel_path}"
    content = path.read_text(encoding="utf-8")
    for sig in signatures:
        assert sig in content, (
            f"接线签名丢失（疑似被并行覆盖）: {rel_path} :: {sig!r}——"
            "请核对审计台账 docs/Neurova_OpenClaw工具技能专项对比_2026-09-04.md §10 后再决定恢复或更新契约"
        )


def test_dead_a_version_stays_deleted():
    """A 版死代码保持删除态（曾因 stash 操作复活一次）。"""
    assert not (REPO / "neurova" / "evolution" / "tool_weights.py").exists(), (
        "evolution/tool_weights.py（A 版死代码）不应回——若有意恢复请先更新融合契约"
    )


def test_audit_report_present():
    """审计台账在场（曾被并行清理波及删除一次，已重建）。"""
    assert (REPO / "docs" / "Neurova_OpenClaw工具技能专项对比_2026-09-04.md").exists()
