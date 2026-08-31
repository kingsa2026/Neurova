# ADR 0013: 统一技能市场端点（4 套→1 套）

- **Status**: Accepted
- **Date**: 2026-07-14
- **Decision Maker**: 技能导入功能架构深化（zoom-out + improve-codebase-architecture）

## Context

存在 **4 套功能高度重叠的技能市场端点**，均为 shallow module：

| # | 文件 | 路由前缀 | 性质 | 前端是否调用 |
|---|------|---------|------|-------------|
| A | `neurova/api/endpoints/skill_market.py` | `/api/v1/skill-market` | 全 stub（硬编码 + 内存 list） | 是（installSkillFromUrl/Zip） |
| B | `neurova/api/endpoints/skills_market.py` | `/api/v1/skills-market` | demo 数据（`_init_sample_skills`） | 否（死路由） |
| C | `neurova/api/endpoints/marketplace.py` | `/api/v1/marketplace` | 调用 stub MarketImporter | 否（死路由） |
| D | `neurova/api/endpoints/skill_pool_api.py` | `/api/v1/skill-pool` | 空 dict，`_get_spm()` 定义但不调用 | 是（getPublicSkills 等） |

**功能重叠矩阵**：

| 功能 | A | B | C | D |
|------|---|---|---|---|
| 安装 | `POST /install` (stub) | `POST /install` (demo) | `POST /skills/{id}/install` (调stub) | `POST /public/{id}/install` (空) |
| 已安装列表 | `GET /installed` | `GET /installed` | `GET /installed` | `GET /private` |
| 搜索/列表 | `POST /search` | `GET /skills` | `GET /skills` | `GET /public` |

**前端集成断裂**（`NeurUI/src/api/modules/skill-pool.ts`）：
- 11 个前端函数中 5+ 个因路径不匹配必然 404（如 `POST /skill-pool/{id}/install` vs 后端 `/skill-pool/public/{id}/install`）
- 2 个调用 stub 端点 A
- 前端与完整端点 C 零集成

**Deletion Test**：删除 A/B/C 任 3 套，复杂度不增加反而减少 — 强通过。

## Decision

### 1. 保留 D（skill_pool_api.py）为唯一规范端点

- 路由前缀 `/api/v1/skill-pool` 保持不变
- 后端接入 ADR 0012 激活的 `SkillHubClient` + `SkillService`
- 端点方法调用真实实现（非空 dict / 非 stub）

### 2. 删除 A/B/C

- 删除 `skill_market.py`（stub）
- 删除 `skills_market.py`（demo）
- 删除 `marketplace.py`（调 stub importer）
- 从 `api/endpoints/__init__.py:177-272` 的 `register_endpoint_routers` 移除对应 include_router

### 3. 对齐前端 skill-pool.ts 路由

- 修正 5+ 个路径不匹配的函数（如 `POST /skill-pool/{id}/install` → `POST /skill-pool/public/{id}/install`，或后端改为 `/skill-pool/{id}/install`）
- `installSkillFromUrl`/`installSkillFromZip` 改调 D 端点（而非已删除的 A 端点）

### 4. 激活 skill_pool_api.py 的 _get_spm()

- 端点方法改用 `_get_spm()`（SkillPoolManager）而非直接读写空 dict

## 修订记录

### 修订 0013-A (2026-07-15): SkillService 取代 SkillPoolManager 作为 /private 端点数据源

**Status**: Supersedes §4 (方向变更)

**背景**:
- 原决策 §4 要求激活 `_get_spm()` 桥接 `SkillPoolManager` (`neurova/skill_system/skill_pool_manager.py`)
- 实际审查发现 `SkillPoolManager` 是 **user 语义** (`owner_user_id` / `skills/private/<user>/`),
  而前端 `skill-pool.ts:54` 的 `getPrivateSkills(agentId)` / `getAgentSkills(agentId)` 是 **agent 语义**
- ADR 0011 已确立 `SkillRegistry` (class A `skill_system.py:337`) 为唯一规范 SkillRegistry 实现,
  其 `SkillService` (`neurova/skills/skill_service.py`) 是 agent 语义的技能服务
- 强行用 `SkillPoolManager` (user 语义) 桥接 agent 语义的前端会产生阻抗失配

**新方向**:
- `GET /private` 直接调用 `SkillService(agent_id=agent_id).list_skills()`,聚合 `_private_skills` (API 内存) + `SkillService.list_skills()` (磁盘 manifest) 两源
- `GET /agent/{agent_id}/skills` 直接调用 `SkillService(agent_id=agent_id).list_skills()` (原 `return []` 是 split-brain 根因)
- `_get_spm()` 删除 (死代码, 零调用方) — 见 s5 修复
- `AutoSkillBuilder.register_to_skill_registry` 桥接 `SkillService.register_auto_skill` 持久化自动生成的技能 (s3 修复)

**与原决策的差异**:
| 维度 | 原决策 §4 | 修订 0013-A |
|------|----------|-------------|
| 数据源 | SkillPoolManager (user 语义) | SkillService (agent 语义) |
| 桥接函数 | `_get_spm()` | 直接 import + 构造 `SkillService(agent_id=...)` |
| 语义匹配 | user ≠ agent (前端阻抗失配) | agent = agent (一致) |
| `_get_spm()` | 激活 | 删除 (死代码) |

**未变更部分**:
- §1 保留 D (skill_pool_api.py) 为唯一规范端点 — 仍然有效
- §2 删除 A/B/C — 仍然有效
- §3 对齐前端 skill-pool.ts 路由 — 仍然有效 (s4 进一步将参数名 user_id → agent_id 对齐前端)

**遗留技术债**:
- `SkillPoolManager` (`neurova/skill_system/skill_pool_manager.py`) 仍存在,其 `metadata.json` (含 shared_with / pushed_to_agents / rating) 成为孤儿数据. 后续可考虑:(1) 迁移到 SkillService 扩展;(2) 标记 deprecated;(3) 删除模块.
- `POST /private/{skill_id}/share` 和 `POST /private/{skill_id}/push` 端点仍返回空 stub,未接入真实 SkillService.

## 不采纳的替代方案

- **保留 C（marketplace.py）作为规范**：C 调用的是 stub MarketImporter，且前端零集成。D 已被前端调用 9 个函数，迁移成本更低
- **保留 4 套并行，各司其职**：4 套 Interface 高度重叠，维护成本 4 倍，且 2 套是死路由。Shallow module 爆炸

## Consequences

- `api/endpoints/__init__.py` 需移除 3 个 include_router
- 前端 `skill-pool.ts` 需修正路由路径
- `skill_pool_api.py` 需接入 `SkillHubClient`/`SkillService`（依赖 ADR 0012 先落地）
- 需验证删除后无其他模块 import 被删端点
