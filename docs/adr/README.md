# Architecture Decision Records (ADR)

> 记录 Neurova 项目中具有长期影响的架构决策。每个 ADR 记录"为什么"而非"是什么"，避免未来重复讨论已定事项。

## ADR 索引

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [0001](./0001-unify-memory-dataclass.md) | 统一 Memory dataclass 三套 | Accepted | 2026-06-27 |
| [0002](./0002-retain-unified-memory-node.md) | 保留 UnifiedMemoryNode 作为第 4 套 dataclass | Accepted | 2026-06-27 |
| [0003](./0003-memory-system-architecture.md) | 记忆系统架构决策 | Accepted | 2026-06-27 |
| [0004](./0004-cognitive-storage-engine-lsm.md) | CognitiveStorageEngine LSM-Tree 五层架构 | Accepted | 2026-06-27 |
| [0005](./0005-neurova-recall-engine-signature.md) | NeurovaRecallEngine 签名统一 | Accepted | 2026-06-27 |
| [0006](./0006-embedding-factory.md) | embedding 工厂 + 单例模式 | Accepted | 2026-06-27 |
| [0007](./0007-semantic-search-api-rrf.md) | 语义搜索 API 端点 RRF 融合 | Accepted | 2026-06-27 |
| [0008](./0008-session-repository.md) | SessionRepository 统一会话存储接口 | Accepted | 2026-06-28 |

## 主题分类

### 记忆系统
- [ADR 0003: 记忆系统架构](./0003-memory-system-architecture.md) — 总体分层 + 深度模块
- [ADR 0001: 统一 Memory dataclass](./0001-unify-memory-dataclass.md) — 3+1 套 dataclass 量纲统一
- [ADR 0002: 保留 UnifiedMemoryNode](./0002-retain-unified-memory-node.md) — LSM-Tree 独立数据模型

### 存储层
- [ADR 0004: CognitiveStorageEngine LSM-Tree](./0004-cognitive-storage-engine-lsm.md) — 五层架构 L0-L4

### 检索层
- [ADR 0005: NeurovaRecallEngine 签名](./0005-neurova-recall-engine-signature.md) — `memory_manager` 唯一注入点
- [ADR 0006: embedding 工厂](./0006-embedding-factory.md) — 懒加载 + 单例 + 测试重置
- [ADR 0007: API 端点 RRF 融合](./0007-semantic-search-api-rrf.md) — Okapi BM25 + RRF 三路融合

### 会话存储
- [ADR 0008: SessionRepository 统一接口](./0008-session-repository.md) — 5 套会话存储收敛到 ABC

## ADR 编写规范

### 文件命名
`{编号}-{kebab-case-标题}.md`，编号从 0001 起递增，不回收。

### 必填字段
- **Status**: `Proposed` / `Accepted` / `Deprecated` / `Superseded by ADR-XXXX`
- **Date**: YYYY-MM-DD
- **Decision Maker**: 决策主体（团队 / 个人 / 重构阶段）

### 正文结构
1. **Context** — 决策背景 + 问题陈述 + 探索发现
2. **Decision** — 决策内容 + 关键设计 + 代码引用（含文件:行号链接）
3. **Consequences** — 正向 / 负向 / 降级策略 / 验证结果
4. **References** — 相关 ADR + 实现位置 + Bug 编号

### 编写原则
- **记录"为什么"**：决策理由比决策本身更重要
- **接地源码**：所有代码引用含 `file:///` 链接 + 行号
- **不重新诉讼**：Accepted 状态的 ADR 不因后续讨论而修改，需变更时新建 ADR 标记 `Superseded by`
- **领域词汇一致**：使用 [CONTEXT.md](../CONTEXT.md) 定义的领域术语，不引入临时命名

### 与 CONTEXT.md 的关系
- **ADR** 记录单点决策（为什么选 A 而非 B）
- **CONTEXT.md** 记录全局架构（系统由哪些模块组成、如何协作）
- ADR 引用 CONTEXT.md 词汇，CONTEXT.md 引用 ADR 作为决策依据

## 变更流程

1. 新建 ADR 文件，Status=`Proposed`
2. 团队评审，通过后 Status=`Accepted`
3. 在本 README 索引表追加条目
4. 若涉及全局架构，同步更新 [CONTEXT.md](../CONTEXT.md)
5. 若推翻既有 ADR，旧 ADR 改 Status=`Superseded by ADR-XXXX`，新 ADR 在 References 指向旧 ADR
