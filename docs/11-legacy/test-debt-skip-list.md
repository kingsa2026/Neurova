# 测试债务 · 死模块 Skip 清单

> 背景：全量测试基线为 **1628 failed / 397 errors / 7518 passed**（9610 collected，2026-08-28）。
> 大量失败源于"测试写自从未实现或已重构的 API"。本清单记录**引用了不存在模块/名称**而被整体 skip 的测试文件，
> 待确认这些模块是"应实现而缺失"还是"已废弃"，再决定**补齐实现**或**删除测试**。
>
> 处理原则（用户确认）：全量重写对齐真实实现；对引用不存在模块的测试先 skip 并列清单。

## 状态图例
- ⏸️ SKIPPED：已整体 skip，等待决策
- ✅ FIXED：已重写对齐真实 API
- 🗑️ REMOVED：确认废弃后删除

## 一、引用了"完全不存在的模块"的测试（整体 skip）

| 测试文件 | 缺失模块/名称 | 相近存在物 | 状态 | 备注 |
|---|---|---|---|---|
| `tests/core/test_multi_agent_sleep_manager.py` | `neurova.core.multi_agent_sleep_manager`（`MultiAgentSleepManager` / `IdleTracker`） | `neurova.core.multi_agent_manager` | ⏸️ SKIPPED | 睡眠/空闲管理，疑似拆分或改名 |
| `tests/unit/core/test_define_action.py` | `neurova.core.define_action`（`defineAction` / `ActionRegistry`） | `neurova.core.file_utils`（仅拼写相近） | ⏸️ SKIPPED | 动作注册装饰器，未实现 |
| `tests/integration/test_evolution_unified.py` | `neurova.evolution.experience_caller`；`ToolWeightEntry` from `neurova.evolution` | `experience_feedback`；`AdaptiveToolWeights` | ⏸️ SKIPPED | 进化统一测试，部分名称已改 |
| `tests/integration/test_full_conflict_integration.py` | `neurova.core.闭环_manager`（非法模块名） | 无 | ⏸️ SKIPPED | 含明显错误的中文模块名；另引用已改名的 `conflict_detector`（现为 `conflict_detector_v2`） |

## 二、引用了"已改名/可修复"名称的测试（重写时修正 import，不算死测试）

| 测试文件 | 错误引用 | 真实存在物 | 处理 |
|---|---|---|---|
| `tests/execution_engine/test_tool_closed_loop.py` | `neurova.agent.tool_executor` | `neurova.tool_executor`（顶层） | 重写时改 import 路径 |
| `tests/integration/test_full_chain.py` | `create_default_skills` from `neurova.skill` | 待定位（`neurova.skills` 门面） | 重写时改 import |
| `tests/integration/test_memory_system.py` | `Memory` from `neurova.mem_core` | `MemCore`（类） | 重写时对齐类名 |
| `tests/unit/test_coverage_fast.py` / `test_coverage_simple.py` / `test_plugin_api.py` | `UPLOAD_DIR` from `...console` | `_CONSOLE_UPLOAD_DIR`（私有） | 重写时对齐或改测公共接口 |

## 三、待重写对齐的 Top 失败文件（按失败数排序，逐步推进）

| 测试文件 | 失败数 | 主要根因 | 状态 |
|---|---|---|---|
| `tests/unit/admin/test_resource_quota_manager.py` | 37 | 构造签名/配额 API 全变 | ✅ FIXED（23 passed） |
| `tests/unit/skills/test_skill_registry_comprehensive.py` | 47 | 被 skill_system split-brain 阻塞 | ✅ FIXED（17 passed，先修生产后重写） |
| `tests/unit/api/test_communication_protocol_comprehensive.py` | 45 | 握手协议签名变更 | ⏳ TODO |
| `tests/unit/core/test_analytics_models.py` | 42 | 数据类字段/枚举/帮助方法变更 | ✅ FIXED（21 passed） |
| `tests/unit/core/test_shared_config.py` | 36 | 配置结构/访问器/提供商数据变更 | ✅ FIXED（26 passed，并修复 config_path 未归一化 Path 的生产 bug） |
| `tests/unit/core/test_startup_manager.py` | 35 | register_module 签名/生命周期 API 变更 | ✅ FIXED（12 passed，并修复 ModuleInfo.state 不同步的生产 bug） |
| `tests/unit/core/test_acp_server.py` | 33 | ACP 数据类字段/枚举/服务 API 变更 | ✅ FIXED（25 passed） |
| ……（其余约 110 个文件，按失败数依次处理） | | | ⏳ TODO |

## 四、被"生产架构问题"阻塞的测试（需先修生产，再重写测试）

| 测试文件 | 阻塞的生产问题 | 状态 | 处理 |
|---|---|---|---|
| `tests/unit/skills/test_skill_registry_comprehensive.py` | **skill_system 模块/包同名遮蔽**：`neurova/skill_system.py`（744 行规范实现）被同名包 `neurova/skill_system/` 遮蔽；包 `__init__` 的 `__getattr__` 缺少 `"Skill"` 分支，导致 `from neurova.skill_system import Skill` 回退为无方法占位类，`SkillRegistry.register()` 必然 AttributeError | ✅ FIXED | 已在包 `__getattr__` 补上 `"Skill"` 分支（复用 standalone 模块缓存，与 SkillRegistry/SkillEvent 同模式），恢复真实 Skill；随后按 class A API 重写测试，17 passed。审计回归 23/23 不受影响 |
