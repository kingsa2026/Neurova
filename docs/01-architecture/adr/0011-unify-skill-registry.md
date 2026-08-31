# ADR 0011: 统一 SkillRegistry

- **Status**: Accepted
- **Date**: 2026-07-09
- **Decision Maker**: 工具层断点修复（zoom-out 根因修复）

## Context

存在 **2 个 API 不兼容的 `SkillRegistry`**，且 `agent_core.py:25` 的 import 与运行时实例不匹配：

| # | 文件 | `skills` 返回 | `register` 签名 | `register_skill` path | `__len__` | 声明 Protocol 基类 |
|---|------|---------------|------------------|-----------------------|-----------|-------------------|
| A | `neurova/skill_system.py:337` | `Dict[str, Skill]` | `register(skill) -> None` | 可选 | 无 | 满足 |
| B | `neurova/skills/registry.py:47` | `Dict[str, Tuple[Skill, Path]]` | `register(manifest, path) -> bool` | 必填 | 有（→ falsy bug） | 未声明 |

**运行时事实**：
- `agent_core.py:25` `from neurova.skills.registry import SkillRegistry`（class B）仅用作类型注解
- `agent_core.py:670` / `:1143` 实际通过 `create_default_skills()`（来自 `skill_system.py`）创建 class A 实例
- 类型注解（class B）与运行时实例（class A）不匹配

**根因引发的 bug 链**：
- class B 的 `__len__` 在空时返回 0 → `if registry:` 为 False → H12（空 registry falsy 检查）
- class B 的 `skills` 返回 tuple → orchestrator 直接迭代拿 tuple 当 Skill → H2（LLM 看到 `unknown_skill`）
- class B 的 `register(manifest, path)` 双参 → 协议调用方传单参 TypeError → 静默吞错
- class B 未声明 Protocol 基类 → `isinstance(x, SkillRegistryProtocol)` 失败

## Decision

**Class A（`skill_system.py:337` SkillRegistry）为唯一规范实现。**

### 收敛步骤

1. **`agent_core.py:25`** 修改 import：`from neurova.skill_system import SkillRegistry`（class A）
2. **`skills/registry.py:47`** class B 改为 re-export：`from neurova.skill_system import SkillRegistry`（删除 class B 整个定义体）
3. 保留 `skills/registry.py` 中 class B 的**其他独有类**（如有），仅替换 `SkillRegistry` 类定义
4. `SkillRegistryProtocol`（`skill_system.py:293`）保持不变，class A 已满足

### 不采纳的替代方案

- **让 class B 继承 class A**：class B 的 `skills` 返回 tuple 与 class A 的 `Dict[str, Skill]` 矛盾，继承后 `__len__` 仍需删除，且 tuple 解包逻辑需注入 — 复杂度高于直接 re-export
- **让 class A 兼容 class B 的 tuple 返回**：违反"放大视角修根因"原则，tuple 包装本身就是反模式

## Consequences

- **正向**：单一实现消除 falsy bug（H12）、tuple 未解包 bug（H2）、register 签名不匹配、isinstance 失败；`__len__` 消失使 `if registry:` 行为正常（但仍建议改 `is not None`）
- **负向**：若 class B 有独有方法被外部依赖，re-export 后 AttributeError。验证：grep `skills.registry.SkillRegistry.` 找独有方法调用
- **降级**：若 re-export 破坏性强，class B 保留为 `class SkillRegistry(SkillRegistryA): pass` 空继承

## References

- 实现：`neurova/skill_system.py:337`（规范）、`neurova/skills/registry.py`（re-export）
- Bug 编号：H10（两个 SkillRegistry API 不兼容）、H2（orchestrator 绕过 _unpack_skill）、H12（空 registry falsy 检查）
- 相关 ADR：无前序（首次定义）
- 审计证据：工具层 zoom-out 审计（2026-07-09）
