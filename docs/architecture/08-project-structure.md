# Neurova 项目结构

## 当前文件结构

```
KingPolo/
├── .trae/
│   └── project_rules.md              # 项目规则和开发规范
│
├── docs/
│   └── architecture/
│       ├── 01-core-architecture.md   # 核心架构设计
│       ├── 02-memory-system.md       # 记忆系统架构
│       ├── 03-message-routing.md     # 消息路由系统
│       ├── 04-multi-agent-collaboration.md  # 多 Agent 协作
│       ├── 05-skill-system.md        # Skill 系统设计
│       ├── 06-plugin-cli-system.md   # 插件和 CLI 系统
│       └── 07-implementation-plan.md # 实现计划和 API 规范
│
└── README.md                         # 项目概述和快速开始
```

## 计划中的完整结构

```
neurova/
├── .trae/
│   └── project_rules.md              # ✓ 已完成
│
├── docs/
│   ├── architecture/                 # ✓ 已完成
│   │   ├── 01-core-architecture.md
│   │   ├── 02-memory-system.md
│   │   ├── 03-message-routing.md
│   │   ├── 04-multi-agent-collaboration.md
│   │   ├── 05-skill-system.md
│   │   ├── 06-plugin-cli-system.md
│   │   └── 07-implementation-plan.md
│   ├── api/                          # 待创建
│   │   └── api-reference.md
│   └── guides/                       # 待创建
│       ├── quickstart.md
│       ├── user-guide.md
│       └── developer-guide.md
│
├── neurova/
│   ├── __init__.py
│   ├── core/                     # 核心模块
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── orchestrator.py
│   │   ├── config.py
│   │   └── events.py
│   ├── memory/                   # 记忆系统
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   ├── models.py
│   │   ├── storage.py
│   │   └── core/
│   │       ├── vector_search.py  # 向量检索系统
│   │       ├── emotion.py        # 情感分析引擎
│   │       ├── conflict.py       # 冲突检测系统
│   │       └── sleep.py          # 睡眠整理系统
│   ├── messaging/                # 消息系统
│   │   ├── __init__.py
│   │   ├── router.py
│   │   ├── message.py
│   │   ├── event_bus.py
│   │   └── channels/
│   │       ├── base.py
│   │       ├── wechat.py
│   │       ├── telegram.py
│   │       └── webhook.py
│   ├── llm/                      # LLM 提供商
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── openai_provider.py
│   │   ├── presets.py            # LLM 预设配置管理器
│   │   └── test_presets.py       # 预设配置测试脚本
│   ├── skills/                   # Skill 系统
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   ├── base.py
│   │   ├── context.py
│   │   ├── public_library.py     # 公共技能库
│   │   ├── agent_library.py      # Agent 技能库
│   │   ├── skill_importer.py     # 技能导入器
│   │   ├── market_adapters.py    # 技能市场适配器
│   │   └── builtin/
│   │       ├── search.py
│   │       ├── calculator.py
│   │       └── file_ops.py
│   ├── plugins/                  # 插件系统
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   ├── models.py
│   │   └── loader.py
│   ├── cli/                      # CLI 工具
│   │   ├── __init__.py
│   │   └── commands.py
│   ├── api/                      # RESTful API
│   │   ├── __init__.py
│   │   ├── server.py
│   │   └── routes/
│   │       ├── agents.py
│   │       ├── skills.py
│   │       └── plugins.py
│   └── utils/                    # 工具函数
│       ├── __init__.py
│       ├── logging.py
│       ├── helpers.py
│       └── security.py
│   ├── llm_client.py             # LLM 客户端（支持预设配置）
│   ├── agent.py                  # Agent 核心
│   ├── context.py                # 上下文处理
│   ├── cli.py                    # CLI 入口
│   ├── webui.py                  # Web UI
│   ├── server.py                 # API 服务器
│   └── test_agent.py             # Agent 测试
│
├── tests/                            # 待创建
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── examples/                         # 待创建
│   ├── basic_agent.py
│   ├── multi_agent.py
│   └── custom_skill.py
│
├── config/                           # 待创建
│   ├── default.yaml
│   ├── development.yaml
│   └── production.yaml
│
├── requirements.txt                  # 待创建
├── requirements-dev.txt              # 待创建
├── setup.py                          # 待创建
├── Dockerfile                        # 待创建
└── docker-compose.yml                # 待创建
```

## 文档完成状态

### ✅ 已完成

1. **README.md** - 项目概述和快速开始指南
2. **01-core-architecture.md** - 核心架构设计文档
   - 整体架构分层
   - 核心组件设计
   - 数据流设计
   - 接口定义
3. **02-memory-system.md** - 记忆系统架构
   - SQLite 数据模型
   - 记忆管理器
   - 情感引擎
   - 记忆巩固和遗忘机制
4. **03-message-routing.md** - 消息路由系统
   - 消息模型
   - 路由规则引擎
   - 限流器和重试机制
   - 渠道适配器
5. **04-multi-agent-collaboration.md** - 多 Agent 协作
   - Agent 数据模型
   - Agent 编排器
   - 任务分配算法
   - 群聊机制
6. **05-skill-system.md** - Skill 系统设计
   - Skill 接口定义
   - Skill 管理器
   - 内置 Skill 实现
   - OpenClaw/Qwenpaw 兼容层
7. **06-plugin-cli-system.md** - 插件和 CLI 系统
   - 插件管理器
   - CLI 命令设计
   - 插件开发模板
8. **07-implementation-plan.md** - 实现计划
   - 12 周实现计划
   - API 规范
   - 数据库设计
   - 测试策略
   - 部署方案
9. **project_rules.md** - 项目规则和开发规范

### 📋 待创建文档

1. **docs/api/api-reference.md** - 完整 API 参考文档
2. **docs/guides/quickstart.md** - 快速开始指南
3. **docs/guides/user-guide.md** - 用户指南
4. **docs/guides/developer-guide.md** - 开发者指南
5. **CHANGELOG.md** - 变更日志
6. **CONTRIBUTING.md** - 贡献指南

## 核心设计亮点

### 1. 分层架构
```
应用层 → Agent 层 → 通信层 → 核心层 → 基础设施层
```
- 清晰的职责分离
- 易于维护和扩展
- 支持独立测试

### 2. 记忆系统
- **短期记忆**: LRU 缓存，快速访问
- **长期记忆**: SQLite 持久化
- **情感关联**: 情感评分和标签
- **记忆巩固**: 自动转化重要记忆
- **遗忘机制**: 清理无用记忆

### 3. 消息路由
- **规则引擎**: 正则表达式匹配
- **智能路由**: 基于内容和上下文
- **限流防刷**: 令牌桶算法
- **重试机制**: 指数退避

### 4. 多 Agent 协作
- **任务分解**: 协调 Agent 自动分解复杂任务
- **智能分配**: 基于能力和负载分配
- **群组讨论**: 避免信息风暴
- **工作流引擎**: 支持复杂业务流程

### 5. Skill 系统
- **统一接口**: 标准化 Skill 实现
- **协议兼容**: OpenClaw/Qwenpaw 兼容
- **沙箱执行**: 安全隔离
- **链式调用**: 支持 Skill 组合

### 6. 插件系统
- **热插拔**: 动态加载/卸载
- **钩子机制**: 扩展点丰富
- **依赖管理**: 自动处理依赖
- **版本控制**: 语义化版本

## 技术特色

### 异步优先
- 全面使用 asyncio
- 高并发支持
- 非阻塞 I/O

### 类型安全
- 完整的类型注解
- mypy 静态检查
- 减少运行时错误

### 测试驱动
- 单元测试覆盖率 >85%
- 集成测试覆盖核心流程
- 性能测试确保指标

### 安全设计
- API 认证和授权
- 输入验证
- 沙箱隔离
- 加密存储

## 下一步行动

### 阶段 1: 环境搭建 (1-2 天)
- [ ] 创建 Git 仓库
- [ ] 设置虚拟环境
- [ ] 安装开发工具
- [ ] 配置 pre-commit 钩子

### 阶段 2: 核心框架实现 (2 周)
- [ ] 实现配置系统
- [ ] 实现日志系统
- [ ] 实现事件总线
- [ ] 实现 Agent 基类
- [ ] 实现 LLM 提供商

### 阶段 3: 记忆系统实现 (2 周)
- [ ] 实现 SQLite 存储层
- [ ] 实现记忆管理器
- [ ] 实现情感引擎
- [ ] 实现记忆巩固

### 阶段 4: 消息系统实现 (2 周)
- [ ] 实现消息路由器
- [ ] 实现渠道适配器
- [ ] 实现限流器
- [ ] 实现重试机制

### 阶段 5: Skill 系统实现 (2 周)
- [ ] 实现 Skill 管理器
- [ ] 实现内置 Skill
- [ ] 实现协议兼容层

### 阶段 6: 插件和 CLI 实现 (2 周)
- [ ] 实现插件管理器
- [ ] 实现 CLI 工具
- [ ] 实现 RESTful API

### 阶段 7: 测试和优化 (持续)
- [ ] 编写单元测试
- [ ] 编写集成测试
- [ ] 性能优化
- [ ] 文档完善

## 资源需求

### 人力资源
- 后端开发：2-3 人
- 测试工程师：1 人
- 文档工程师：1 人 (可兼职)

### 时间估算
- MVP (v0.1.0): 4 周
- Beta (v0.3.0): 12 周
- GA (v1.0.0): 14 周

### 基础设施
- GitHub 仓库
- CI/CD 流水线
- 文档网站 (GitBook/ReadTheDocs)
- PyPI 发布
- Docker Hub

## 风险和缓解

### 技术风险
- **LLM API 限制**: 实现本地模型支持作为备选
- **性能瓶颈**: 早期性能测试，及时优化
- **安全问题**: 安全审计，渗透测试

### 管理风险
- **范围蔓延**: 严格控制 MVP 范围
- **依赖风险**: 关键依赖备选方案
- **人员风险**: 知识共享，文档完善

## 成功指标

### 技术指标
- 代码覆盖率 >85%
- API 响应 <100ms (P95)
- 系统可用性 >99.9%
- 零严重安全漏洞

### 采用指标
- GitHub Stars >1000
- PyPI 下载量 >10000/月
- 活跃贡献者 >20
- 社区插件 >50

---

**最后更新**: 2026-05-05
**版本**: 1.0.0
