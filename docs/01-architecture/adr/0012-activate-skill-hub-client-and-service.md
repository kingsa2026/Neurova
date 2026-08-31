# ADR 0012: 激活技能仓库客户端与技能服务深度模块

- **Status**: Accepted
- **Date**: 2026-07-14
- **Decision Maker**: 技能导入功能架构深化（zoom-out + improve-codebase-architecture）

## Context

技能导入功能存在 **两套互不相通的实现**：

### Stub 链（被引用但全是模拟）

| 模块 | 文件 | stub 方法 | 证据 |
|------|------|-----------|------|
| 市场导入模块 | `neurova/skills/market_importer.py` | `search_skills`(L122) / `import_skill`(L185) / `check_updates`(L254) | 注释"模拟搜索/导入/版本检查"，返回硬编码数据 |
| 技能需求分析 | `neurova/skills/skill_need_analyzer.py` | `_install_skill`(L273) / `_is_skill_installed`(L152) | 注释"简化实现"，`time.sleep(0.1)` + 内存 dict，永远返回 False |

被调用者：`AgentSkillManager`（agent_skill_manager.py:79,93）、`marketplace.py`（5 处 `get_market_importer()`）

### 真实实现（完整但完全孤立，零调用者）

| 模块 | 文件 | 能力 | 调用者数 |
|------|------|------|---------|
| 技能仓库客户端 | `neurova/skills/hub_client.py:236` `SkillHubClient` | 真实 HTTP 请求 GitHub/ClawHub/LobeHub + 重试退避 + ZIP/TAR 解压 + 多源搜索 + 版本检查 | 0 |
| 技能服务模块 | `neurova/skills/skill_service.py:20` `SkillService` | 真实 zip 解压 + manifest.json 持久化 + importlib 动态模块加载 + 安装/卸载/启用/禁用/调用 | 0 |
| 技能链执行器 | `neurova/skills/skill_chain_executor.py:28` `SkillChainExecutor` | execute_chain/pause/resume/cancel 完整（但因 SkillService 未注入走 stub 分支） | 0 |

**根因**：`skills/__init__.py:107-191` 的 try 块全 `pass`，不实际导入这些子模块。`AgentSkillManager._init_importer` 实例化的是 stub `MarketImporter`，而非真实的 `SkillHubClient`。

### Deletion Test

- 删除 `MarketImporter`：复杂度消失（stub 不提供任何能力），调用方改用 `SkillHubClient` 后获得真实下载 — **通过**
- 删除 `SkillNeedAnalyzer._install_skill` stub：复杂度消失（time.sleep 无价值），改委托 `SkillService.install_skill` 后获得真实安装 — **通过**

## Decision

### 1. 用 SkillHubClient 替换 stub MarketImporter

- `AgentSkillManager` 持有 `SkillHubClient` 实例（而非 `MarketImporter`）
- `MarketImporter` 类保留为兼容 Adapter（内部委托 `SkillHubClient`），或直接删除
- 搜索/下载/安装/更新全部走 `SkillHubClient` 的真实 HTTP 链

### 2. 用 SkillService 替换 stub SkillNeedAnalyzer._install_skill

- `SkillNeedAnalyzer` 持有 `SkillService` 实例
- `_install_skill` 委托 `SkillService.install_skill`（真实 zip 解压 + importlib 加载）
- `_is_skill_installed` 委托 `SkillService.is_installed`（真实 manifest 检查）

### 3. 激活 SkillChainExecutor

- `SkillChainExecutor` 接受 `SkillService` 注入（已设计但从未被注入）
- `_execute_step` 的 `skill_service is None` stub 分支不再触发

### 4. 修复 skills/__init__.py 空导入

- `try: pass except ImportError` 块改为真实导入 `hub_client`/`skill_service`/`skill_chain_executor`

## 不采纳的替代方案

- **让 MarketImporter 变真实**：MarketImporter 的 Interface（search_skills/import_skill/check_updates）与 SkillHubClient 高度重叠，重新实现是重复劳动。SkillHubClient 已是完整深度 Module，激活它 Leverage 更高
- **保留两套并行**：两套实现维护成本高，且 stub 链的"模拟"行为会误导调用方（如 _is_skill_installed 永远 False 导致无限重装）

## Consequences

- `AgentSkillManager.acquire_skill` 需对齐 `SkillHubClient` 的真实 Interface（候选 4 修复签名不匹配）
- `MarketImporter` 的 `get_market_importer()` 单例工厂需重定向到 `SkillHubClient`
- `marketplace.py` 端点需改用 `SkillHubClient`
- 首次激活后需验证 HTTP 请求在无网络环境下的降级行为
