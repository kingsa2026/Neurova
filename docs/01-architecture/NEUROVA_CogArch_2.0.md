# Neurova CogArch 2.0 - 认知增强架构设计方案

> **设计理念**：大脑（认知核）+ 小脑（执行引擎）+ 手脚（功能壳）的完美协同！

---

## 版本历史

| 版本 | 日期 | 说明 |
|-----|-----|------|
| 2.9 | 2026-05-12 | 新增系统设置功能：多语言支持（11种语言）、多用户管理与数据隔离、时区管理 |
| 2.8 | 2026-05-12 | 新增融合 QwenPaw 特性的 Neurova 安全体系 2.0（工具守卫 + 技能扫描 + 认证 + 认知安全）|
| 2.7 | 2026-05-12 | 新增融合 QwenPaw 特性的 Neurova 技能系统 2.0（公共池 + Agent 专属 + 自主进化）|
| 2.6 | 2026-05-12 | 新增多 Agent 架构（大脑/办公室、共用小脑/脑干/脊髓）的完整设计方案 |
| 2.5 | 2026-05-12 | 新增借鉴 QwenPaw 的 LLM 大模型配置、渠道管理和 Console 前端完整方案 |
| 2.4 | 2026-05-12 | 完整扫描 Neurova 项目，新增所有遗漏模块的映射和详细解释 |
| 2.3 | 2026-05-12 | 新增 LLM 配置、消息路由、渠道模块的详细映射和解释 |
| 2.2 | 2026-05-12 | 完善了 Sleep、Skill 系统映射，新增 CLI & Console/Shell 接口层设计 |
| 2.1 | 2026-05-12 | 添加现有 Neurova 模块到架构的完整映射 |
| 2.0 | 2026-05-12 | 新增执行引擎，完善认知-执行闭环 |
| 1.0 | 2026-05-12 | 初始认知核架构设计 |

---

## 二、多 Agent 架构设计（大脑/办公室 + 共用小脑/脑干/脊髓）

> **绝妙类比**：每个 Agent 都有自己的大脑（数据库）和办公室（工作目录），但所有 Agent 共用一套小脑（计划编排器）、脑干（执行引擎）和脊髓（基础设施）！

---

### 2.1 多 Agent 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                  SHARED CORE (多个 Agent 共用的部分)                    │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐    │
│  │  SHARED CEREBELLUM (共用小脑) + BRAINSTEM (脑干) + SPINAL CORD (脊髓)  │    │
│  │  ┌───────────────────────────────────────────────────────────────────────┐    │    │
│  │  │  Plan Orchestrator (共用小脑) - 所有 Agent 的任务编排        │    │    │
│  │  ├───────────────────────────────────────────────────────────────────────┤    │    │
│  │  │  Execution Engine (共用脑干/脊髓)                                     │    │    │
│  │  │  • Tool Engine (共用) • MCP (共用) • Workflow Engine (共用)  │    │    │
│  │  ├───────────────────────────────────────────────────────────────────────┤    │    │
│  │  │  Infrastructure (共用脊髓)                                             │    │    │
│  │  │  • Service Manager • Provider Manager • Event Bus • Config  │    │    │
│  │  └───────────────────────────────────────────────────────────────────────┘    │    │
│  └───────────────────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                             │
                      ┌──────────────────────┼──────────────────────┐
                      │                      │                      │
                      ▼                      ▼                      ▼
┌───────────────────────────┐  ┌───────────────────────────┐  ┌───────────────────────────┐
│   Agent "Alice"           │  │   Agent "Bob"             │  │   Agent "Charlie"         │
│  ┌─────────────────────┐  │  │  ┌─────────────────────┐  │  │  ┌─────────────────────┐  │
│  │  ALICE'S BRAIN      │  │  │  │  BOB'S BRAIN         │  │  │  │  CHARLIE'S BRAIN    │  │
│  │  (独立数据库)       │  │  │  │  (独立数据库)        │  │  │  │  (独立数据库)        │  │
│  │  • Memory Layer    │  │  │  │  • Memory Layer    │  │  │  │  • Memory Layer    │  │
│  │  • Meta Cog        │  │  │  │  • Meta Cog        │  │  │  │  • Meta Cog        │  │
│  │  • Persona         │  │  │  │  • Persona         │  │  │  │  • Persona         │  │
│  └─────────────────────┘  │  │  └─────────────────────┘  │  │  └─────────────────────┘  │
│  ┌─────────────────────┐  │  │  ┌─────────────────────┐  │  │  ┌─────────────────────┐  │
│  │  ALICE'S OFFICE    │  │  │  │  BOB'S OFFICE       │  │  │  │  CHARLIE'S OFFICE  │  │
│  │  (独立工作目录)     │  │  │  │  (独立工作目录)      │  │  │  │  (独立工作目录)     │  │
│  │  • Workspace       │  │  │  │  • Workspace       │  │  │  │  • Workspace       │  │
│  └─────────────────────┘  │  │  └─────────────────────┘  │  │  └─────────────────────┘  │
│  ┌─────────────────────┐  │  │  ┌─────────────────────┐  │  │  ┌─────────────────────┐  │
│  │  Cognition Core    │  │  │  │  Cognition Core    │  │  │  │  Cognition Core    │  │
│  │  (可共用，也可独立)  │  │  │  │  (可共用，也可独立)  │  │  │  │  (可共用，也可独立) │  │
│  └─────────────────────┘  │  │  └─────────────────────┘  │  │  └─────────────────────┘  │
└───────────────────────────┘  └───────────────────────────┘  └───────────────────────────┘
```

---

### 2.2 详细设计方案

| 组件 | 所有权 | 说明 |
|------|-------|------|
| **大脑（独立）** | 每个 Agent | 独立的记忆数据库（Memory Layer）、元认知、人格设定 |
| **办公室（独立）** | 每个 Agent | 独立的工作目录（Workspace）、文件存储、会话历史 |
| **小脑（共用）** | 所有 Agent | 统一的 Plan Orchestrator（任务编排器） |
| **脑干（共用）** | 所有 Agent | 统一的 Execution Engine（Tool Engine、MCP、Workflow） |
| **脊髓（共用）** | 所有 Agent | 统一的 Infrastructure（Service Manager、Provider Manager、Event Bus） |

---

### 2.3 借鉴 QwenPaw 的 MultiAgentManager

#### QwenPaw 的特点：
1. **Lazy Loading**：工作区只在第一次请求时才创建，节省资源
2. **Lifecycle Management**：启动、停止、重载工作区
3. **Thread-safe**：使用 async lock 进行并发访问控制
4. **Hot Reload**：可独立重载单个工作区，不影响其他工作区
5. **Parallel Startup**：多个 Agent 通过细粒度锁并行启动
6. **Zero-Downtime Reload**：零停机重载，带延迟清理

#### Neurova 的 MultiAgentManager 设计：

```python
# Neurova 专属的 MultiAgentManager（结合 QwenPaw 优点 + 我们的架构）

class MultiAgentManager:
    """
    多 Agent 管理器
    - 每个 Agent 有自己的大脑（Memory DB）和办公室（Workspace）
    - 所有 Agent 共用 Plan Orchestrator（小脑）、Execution Engine（脑干）和 Infrastructure（脊髓）
    - Lazy Loading + Parallel Startup + Hot Reload（借鉴 QwenPaw）
    """

    def __init__(self):
        # 大脑 + 办公室（每个 Agent 独立）
        self.agents: Dict[str, NeurovaAgent] = {}
        
        # 小脑 + 脑干（共用）
        self.shared_cerebellum: PlanOrchestrator = PlanOrchestrator()
        self.shared_brainstem: ExecutionEngine = ExecutionEngine()
        
        # 脊髓（共用基础设施）
        self.service_manager: ServiceManager = ServiceManager()
        self.provider_manager: LLMProviderManager = LLMProviderManager()
        self.event_bus: EventBus = EventBus()
        
        # 并发控制
        self._lock = asyncio.Lock()
        self._pending_starts: Dict[str, asyncio.Event] = {}
        self._cleanup_tasks: Set[asyncio.Task] = set()

    async def get_agent(self, agent_id: str) -> NeurovaAgent:
        """
        获取 Agent（Lazy Loading，借鉴 QwenPaw）
        - 如果 Agent 不存在，创建它的大脑（Memory DB）和办公室（Workspace）
        - 但小脑、脑干、脊髓是共用的，不需要重复创建
        """
        # 快速路径（无锁）
        if agent_id in self.agents:
            return self.agents[agent_id]
        
        # 检查并启动 Agent（借鉴 QwenPaw 的细粒度锁策略）
        # ...

    async def execute_with_shared_cerebellum(
        self, 
        agent_id: str, 
        input_context: Dict
    ) -> ExecutionResult:
        """
        共用小脑 + 脑干执行任务
        - Agent 的大脑提供记忆和人格
        - 共用小脑（Plan Orchestrator）来编排
        - 共用脑干（Execution Engine）来执行
        """
        agent = await self.get_agent(agent_id)
        
        # 第 1 步：用 Agent 自己的大脑做认知
        cognition = await agent.cognition_core.process(input_context)
        
        # 第 2 步：用共用的小脑来编排
        task_plan = await self.shared_cerebellum.orchestrate(
            cognition=cognition,
            agent_persona=agent.persona
        )
        
        # 第 3 步：用共用的脑干来执行
        result = await self.shared_brainstem.execute(task_plan)
        
        # 第 4 步：结果反馈到 Agent 自己的大脑（记忆巩固）
        await agent.memory_layer.consolidate(result)
        
        return result
```

---

### 2.4 内存和性能优化

| 优化项 | 说明 |
|------|------|
| **共用组件的单例模式** | Plan Orchestrator、Execution Engine、Provider Manager 等共用组件只创建一个实例 |
| **Lazy Loading** | 每个 Agent 只在第一次请求时才加载，节省资源 |
| **细粒度锁** | 借鉴 QwenPaw，允许并行初始化多个 Agent |
| **热重载** | 单个 Agent 重载不影响其他 Agent，零停机 |
| **记忆共享（可选）** | 允许 Agent 之间选择性地共享部分记忆，促进协作 |

---

### 2.5 Agent 配置结构

```yaml
agents:
  alice:
    # 大脑配置
    personality: "热情友好，善于沟通"
    constitution: "永远不说谎"
    memory_db_path: "./data/memory/alice.db"
    
    # 办公室配置
    workspace_dir: "./workspaces/alice"
    
    # LLM 配置（可覆盖共用配置）
    llm_provider: "openai"
    llm_model: "gpt-4o"
    
  bob:
    personality: "技术宅，喜欢分析"
    constitution: "代码必须有注释"
    memory_db_path: "./data/memory/bob.db"
    workspace_dir: "./workspaces/bob"

# 共用配置（小脑/脑干/脊髓）
shared:
  llm_providers:
    - name: "openai"
      api_key: "..."
    - name: "anthropic"
      api_key: "..."
  
  mcp_servers:
    - name: "file-utils"
      command: "..."
```

---

## 三、Neurova 技能系统 2.0（融合 QwenPaw 特性）

> **核心理念**：借鉴 QwenPaw 的公共池 + Agent 专属池架构，同时保持 Neurova 的自主打包、自主进化、经验调用特性！

---

### 3.1 技能系统整体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     NEUROVA SKILL SYSTEM 2.0                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  BUILT-IN SKILLS (内置技能层 - 只读)                            │   │
│  │  • 系统默认技能                                                  │   │
│  │  • 不可修改                                                      │   │
│  │  • 可同步到公共池                                                │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              ↓ (同步)                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  SHARED SKILL POOL (公共技能池 - 所有 Agent 共享)              │   │
│  │  ┌─────────────────────────────────────────────────────────┐   │   │
│  │  │ • 公共技能管理 (SkillPoolService)                      │   │   │
│  │  │ • 技能 Hub 连接 (SkillHubClient - 从市场下载)           │   │   │
│  │  │ • 内置技能同步                                          │   │   │
│  │  └─────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│         ↓ (导入/导出)        ↓ (导入/导出)         ↓ (导入/导出)         │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐        │
│  │ Agent Alice's   │ │ Agent Bob's     │ │ Agent Charlie's  │        │
│  │ Private Skills  │ │ Private Skills  │ │ Private Skills   │        │
│  ├──────────────────┤ ├──────────────────┤ ├──────────────────┤        │
│  │ • SkillService  │ │ • SkillService  │ │ • SkillService  │        │
│  │ • 自主打包      │ │ • 自主打包      │ │ • 自主打包      │        │
│  │ • 自主进化      │ │ • 自主进化      │ │ • 自主进化      │        │
│  │ • 经验调用      │ │ • 经验调用      │ │ • 经验调用      │        │
│  └──────────────────┘ └──────────────────┘ └──────────────────┘        │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  NEUROVA-SPECIFIC ENHANCEMENTS (Neurova 特色)                  │   │
│  │  ├─ SkillsEvolutionEngine (技能进化引擎)                        │   │
│  │  ├─ ExperienceCaller (经验调用系统)                             │   │
│  │  ├─ SkillPackager (自主打包工具)                                │   │
│  │  └─ ExperienceKnowledgeBase (经验知识库)                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  UI & API LAYER (借鉴 QwenPaw)                                  │   │
│  │  ├─ 技能列表 (公共池 + 专属池)                                 │   │
│  │  ├─ 技能创建/编辑/删除                                          │   │
│  │  ├─ 技能导入/导出 (ZIP 格式)                                    │   │
│  │  ├─ Hub 技能搜索与安装                                          │   │
│  │  ├─ 技能标签、配置、启用/禁用                                   │   │
│  │  ├─ 技能进化历史查看                                            │   │
│  │  ├─ 经验调用记录                                                │   │
│  │  └─ 技能效果评估面板                                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 3.2 核心组件设计

#### 3.2.1 四层存储架构

| 层级 | 说明 | 特点 |
|------|------|------|
| **内置技能层** | 系统默认技能 | 只读，不可修改，可同步到公共池 |
| **公共技能池** | 所有 Agent 共享 | 可从 Hub 安装，可自定义，版本管理 |
| **Agent 专属技能层** | 每个 Agent 独立 | 可从公共池导入，可自主创建，**自主进化** |
| **经验知识库** | 技能使用经验 | 使用记录、效果评估、智能推荐 |

#### 3.2.2 目录结构设计

```
neurova/
├── skills/
│   ├── builtin/                    # 内置技能 (只读)
│   │   ├── data_analysis/
│   │   ├── code_writing/
│   │   └── ...
│   │
│   ├── pool/                       # 公共技能池 (所有 Agent 共享)
│   │   ├── skill.json              # 公共池清单
│   │   ├── custom_skill_1/
│   │   ├── custom_skill_2/
│   │   └── ...
│   │
│   ├── hub_client.py               # Hub 客户端
│   ├── pool_service.py             # 公共池服务
│   ├── skill_service.py            # Agent 技能服务
│   ├── evolution_engine.py         # 技能进化引擎 (Neurova 特色)
│   ├── experience_caller.py        # 经验调用系统 (Neurova 特色)
│   ├── skill_packager.py           # 自主打包工具 (Neurova 特色)
│   └── security_scanner.py         # 技能安全扫描
│
└── workspaces/
    ├── alice/
    │   └── skills/                 # Alice 的专属技能
    │       ├── skill.json          # Alice 的技能清单
    │       ├── my_custom_skill/
    │       └── ...
    │
    └── bob/
        └── skills/                 # Bob 的专属技能
            └── ...
```

#### 3.2.3 核心服务类设计

```python
# 借鉴 QwenPaw + Neurova 特色

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from enum import Enum
from pathlib import Path

# ============ 数据模型 ============

class SkillSource(Enum):
    BUILTIN = "builtin"         # 内置技能
    POOL = "pool"               # 公共池
    AGENT_PRIVATE = "agent"     # Agent 专属
    HUB = "hub"                 # 从 Hub 安装
    AUTO_GENERATED = "auto"     # 自动生成 (Neurova 特色)

@dataclass
class SkillInfo:
    """技能信息模型 (借鉴 QwenPaw)"""
    name: str
    description: str = ""
    version_text: str = ""
    content: str = ""
    source: SkillSource = SkillSource.AGENT_PRIVATE
    references: Dict[str, Any] = None
    scripts: Dict[str, Any] = None
    emoji: str = ""
    tags: List[str] = None
    config: Dict[str, Any] = None
    enabled: bool = True
    
    # Neurova 特色字段
    evolution_history: List[Dict] = None  # 进化历史
    usage_statistics: Dict = None         # 使用统计
    experience_records: List[Dict] = None # 经验记录

@dataclass
class SkillEvolutionRecord:
    """技能进化记录 (Neurova 特色)"""
    version: str
    timestamp: str
    change_description: str
    performance_improvement: float
    feedback_source: str

@dataclass
class ExperienceRecord:
    """经验记录 (Neurova 特色)"""
    skill_name: str
    context: Dict
    result: Any
    success: bool
    timestamp: str
    feedback: str = ""

# ============ 公共池服务 ============

class SkillPoolService:
    """公共技能池服务 (借鉴 QwenPaw)"""
    
    def __init__(self, pool_dir: Path):
        self.pool_dir = pool_dir
        self.manifest_path = pool_dir / "skill.json"
    
    def list_skills(self) -> List[SkillInfo]:
        """列出公共池所有技能"""
        pass
    
    def add_skill(self, skill: SkillInfo, overwrite: bool = False) -> bool:
        """添加技能到公共池"""
        pass
    
    def delete_skill(self, skill_name: str) -> bool:
        """从公共池删除技能"""
        pass
    
    def sync_builtin_skills(self) -> None:
        """同步内置技能到公共池"""
        pass
    
    def import_from_hub(self, hub_url: str, version: str = "") -> SkillInfo:
        """从 Hub 导入技能 (借鉴 QwenPaw)"""
        pass
    
    def export_skill(self, skill_name: str, output_path: Path) -> bool:
        """导出技能为 ZIP"""
        pass

# ============ Agent 技能服务 ============

class SkillService:
    """Agent 技能服务 (借鉴 QwenPaw + Neurova 特色)"""
    
    def __init__(self, workspace_dir: Path, agent_id: str):
        self.workspace_dir = workspace_dir
        self.agent_id = agent_id
        self.skills_dir = workspace_dir / "skills"
    
    # ============ QwenPaw 风格的基础功能 ============
    
    def list_skills(self) -> List[SkillInfo]:
        """列出 Agent 的所有技能"""
        pass
    
    def create_skill(self, name: str, content: str, enable: bool = True) -> Optional[SkillInfo]:
        """创建新技能"""
        pass
    
    def save_skill(self, skill_name: str, content: str, target_name: str = None) -> bool:
        """保存技能"""
        pass
    
    def enable_skill(self, skill_name: str) -> bool:
        """启用技能"""
        pass
    
    def disable_skill(self, skill_name: str) -> bool:
        """禁用技能"""
        pass
    
    def delete_skill(self, skill_name: str) -> bool:
        """删除技能"""
        pass
    
    def import_from_pool(self, skill_name: str, overwrite: bool = False) -> bool:
        """从公共池导入技能"""
        pass
    
    def export_to_pool(self, skill_name: str, overwrite: bool = False) -> bool:
        """导出技能到公共池"""
        pass
    
    def import_from_zip(self, zip_path: Path, enable: bool = True) -> List[SkillInfo]:
        """从 ZIP 导入技能"""
        pass
    
    # ============ Neurova 特色功能 ============
    
    def evolve_skill(self, skill_name: str, feedback: Dict) -> SkillInfo:
        """自主进化技能 (Neurova 核心特色!)
        
        根据使用反馈自动优化技能
        """
        pass
    
    def package_skill(self, skill_name: str, output_path: Optional[Path] = None) -> Path:
        """自主打包技能 (Neurova 特色!)
        
        打包技能 + 使用经验 + 进化历史
        """
        pass
    
    def call_experience(self, skill_name: str, context: Dict) -> Optional[ExperienceRecord]:
        """经验调用 (Neurova 特色!)
        
        检索相似场景下的使用经验
        """
        pass
    
    def get_skill_stats(self, skill_name: str) -> Dict:
        """获取技能使用统计"""
        pass
    
    def record_usage(self, skill_name: str, context: Dict, result: Any, success: bool) -> None:
        """记录技能使用"""
        pass

# ============ 技能进化引擎 ============

class SkillsEvolutionEngine:
    """技能进化引擎 (Neurova 核心特色!)"""
    
    def __init__(self):
        pass
    
    def analyze_skill_performance(self, skill: SkillInfo) -> Dict:
        """分析技能性能"""
        pass
    
    def generate_improvement_suggestions(self, skill: SkillInfo) -> List[str]:
        """生成改进建议"""
        pass
    
    def evolve_skill(self, skill: SkillInfo, feedback: Dict) -> SkillInfo:
        """进化技能"""
        pass
    
    def auto_patch_skill(self, skill: SkillInfo, error_log: str) -> SkillInfo:
        """自动修补技能"""
        pass

# ============ 经验调用系统 ============

class ExperienceCaller:
    """经验调用系统 (Neurova 特色!)"""
    
    def __init__(self):
        pass
    
    def find_similar_experiences(self, skill_name: str, context: Dict, limit: int = 5) -> List[ExperienceRecord]:
        """找到相似的经验记录"""
        pass
    
    def extract_lessons_learned(self, experiences: List[ExperienceRecord]) -> List[str]:
        """从经验中提取教训"""
        pass
    
    def recommend_best_practices(self, skill_name: str) -> List[str]:
        """推荐最佳实践"""
        pass

# ============ 技能打包工具 ============

class SkillPackager:
    """自主打包工具 (Neurova 特色!)"""
    
    def __init__(self):
        pass
    
    def package_for_sharing(self, skill: SkillInfo, include_history: bool = True, include_stats: bool = True) -> Path:
        """打包用于分享"""
        pass
    
    def package_for_evolution(self, skill: SkillInfo) -> Path:
        """打包用于进化"""
        pass
    
    def unpack_package(self, package_path: Path) -> SkillInfo:
        """解包"""
        pass
```

---

### 3.3 UI & API 设计（借鉴 QwenPaw）

#### 3.3.1 API 端点设计

```python
# 借鉴 QwenPaw 的 API 设计

# 技能相关 API
/api/skills
    GET    /                          # 列出 Agent 的技能
    POST   /                          # 创建新技能
    POST   /refresh                   # 刷新技能清单

/api/skills/{skill_name}
    GET    /                          # 获取技能详情
    PUT    /                          # 保存技能
    DELETE /                          # 删除技能
    POST   /enable                    # 启用技能
    POST   /disable                   # 禁用技能
    GET    /config                    # 获取技能配置
    PUT    /config                    # 更新技能配置
    GET    /files/{file_path}         # 获取技能文件内容

/api/skills/batch
    POST   /enable                    # 批量启用
    POST   /disable                   # 批量禁用
    POST   /delete                    # 批量删除

/api/skills/upload
    POST   /                          # 上传技能 ZIP

# 公共池 API
/api/skills/pool
    GET    /                          # 列出公共池技能
    POST   /create                    # 在公共池创建技能
    PUT    /save                      # 保存公共池技能
    POST   /upload-zip                # 上传到公共池
    POST   /import-builtin            # 导入内置技能

/api/skills/pool/{skill_name}
    DELETE /                          # 删除公共池技能
    GET    /config                    # 获取配置
    PUT    /config                    # 更新配置

# 公共池与 Agent 同步
/api/skills/pool/{skill_name}/upload
    POST   /                          # Agent 技能 → 公共池

/api/skills/pool/{skill_name}/download
    POST   /                          # 公共池 → Agent

# Hub API (借鉴 QwenPaw)
/api/skills/hub
    GET    /search                    # 搜索 Hub 技能
    POST   /install/start             # 开始安装
    GET    /install/status/{task_id}  # 查看安装状态
    POST   /install/cancel/{task_id}  # 取消安装

# Neurova 特色 API
/api/skills/{skill_name}/neurova
    GET    /evolution-history         # 进化历史
    POST   /evolve                    # 触发进化
    GET    /stats                     # 使用统计
    GET    /experiences               # 经验记录
    POST   /package                   # 打包技能
```

#### 3.3.2 UI 功能清单

| 功能模块 | 说明 | 来源 |
|---------|------|------|
| 技能列表 | 显示公共池 + Agent 专属技能 | QwenPaw |
| 技能创建/编辑 | 可视化技能编辑器 | QwenPaw |
| 技能导入/导出 | ZIP 格式导入导出 | QwenPaw |
| Hub 技能商店 | 搜索、安装、评分 | QwenPaw |
| 技能配置 | 技能参数配置 | QwenPaw |
| 标签管理 | 技能分类标签 | QwenPaw |
| 公共池同步 | Agent ↔ 公共池 | QwenPaw |
| **技能进化历史** | 查看技能进化过程 | **Neurova 特色** |
| **经验调用面板** | 查看相似场景经验 | **Neurova 特色** |
| **技能效果评估** | 技能使用效果统计 | **Neurova 特色** |
| **自主打包** | 一键打包分享 | **Neurova 特色** |

---

### 3.4 与 QwenPaw 的对比与融合

| 特性 | QwenPaw | Neurova 2.0 |
|-----|---------|-------------|
| **存储架构** | 内置 + 公共池 + 工作区 | ✅ 相同 + **经验知识库** |
| **SkillService** | ✅ 完整 | ✅ 保留 + **进化功能** |
| **SkillPoolService** | ✅ 完整 | ✅ 保留 |
| **Hub 连接** | ✅ ClawHub | ✅ 保留 |
| **安全扫描** | ✅ | ✅ 保留 |
| **UI & API** | ✅ 完整 | ✅ 借鉴 + **特色功能** |
| **技能自主进化** | ❌ | ✅ **Neurova 核心特色** |
| **经验调用系统** | ❌ | ✅ **Neurova 核心特色** |
| **自主打包工具** | ❌ | ✅ **Neurova 核心特色** |
| **技能效果评估** | ❌ | ✅ **Neurova 核心特色** |

---

### 3.5 实施路线图

1. **Phase 1**: 实现基础架构（借鉴 QwenPaw）
   - SkillService, SkillPoolService
   - 四层存储结构
   - 基础 API

2. **Phase 2**: 添加 Neurova 特色功能
   - SkillsEvolutionEngine
   - ExperienceCaller
   - SkillPackager

3. **Phase 3**: UI 整合
   - 借鉴 QwenPaw 的 UI
   - 添加 Neurova 特色面板

4. **Phase 4**: 集成测试与优化
   - 完整流程测试
   - 性能优化

---

## 四、核心设计理念

### 1.1 生物学类比

| Neurova 模块 | 人脑对应 | 功能 |
|------------|--------|------|
| **认知编排器** | **大脑皮层** | 高级认知、推理、决策 |
| **计划与任务编排器** | **小脑** | 运动协调、精准执行、平衡控制 |
| **执行引擎** | **脑干 + 脊髓** | 基础执行、反射、自动化 |
| **记忆层** | **海马体 + 大脑皮层** | 记忆编码、存储、检索 |
| **元认知** | **前额叶皮层** | 自我监控、目标管理 |

### 1.2 「认知-执行-反馈」闭环

```
认知核（大脑）
    │
    │ 认知决策
    ▼
计划与任务编排器（小脑）← 精妙的类比！
    │
    │ 任务图/执行计划
    ▼
执行引擎（手脚）
    │
    │ 执行结果 + 观察数据
    ▼
反馈学习环
    │
    │ 经验 + 技能 + 认知调整
    ▼
回到认知核
```

---

## 四、整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│           INTERFACE LAYER (接口层 - 与用户交互)                │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    │
│  │  CLI         │    │  Web Console │    │  ACP Server  │    │
│  │  (本地终端)  │    │  (浏览器)    │    │  (第三方)    │    │
│  └──────────────┘    └──────────────┘    └──────────────┘    │
│         │                    │                    │             │
│         └────────────────────┼────────────────────┘             │
│                              ↕                                  │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  ChannelManager (渠道管理器)                          │  │
│  │  ┌──────┐ ┌────┐ ┌──────┐ ┌───────┐ ┌──────────┐  │  │
│  │  │Discord│ │QQ  │ │Feishu│ │Telegram│ │WebSocket│  │  │
│  │  └──────┘ └────┘ └──────┘ └───────┘ └──────────┘  │  │
│  └─────────────────────────────────────────────────────────┘  │
│                              ↕                                  │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  MessageRouter (消息路由器) + ApiRouter              │  │
│  └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ 用户请求（已路由）
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              NEUROVA COGNITIVE CORE (大脑 - 大脑皮层)            │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  Cognition Orchestrator (认知编排器)                      │ │
│  │  • 观察 → 回忆 → 推理 → 反思 → 学习                      │ │
│  └───────────────────────────────────────────────────────────┘ │
│         │                   │                   │             │
│         ▼                   ▼                   ▼             │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐      │
│  │ Memory Layer │   │ Meta Cog     │   │ Agent Persona│      │
│  │ (海马体)     │   │ (前额叶)     │   │ (人格层)     │      │
│  ├──────────────┤   ├──────────────┤   ├──────────────┤      │
│  │ Temporal KG  │   │ Self-Reflect │   │ Personality  │      │
│  │ EKI Optimizer│   │ Self-Optimize│   │ Constitution │      │
│  │ Working Mem  │   │ Skills-Evolve│   │ AutonomySys  │      │
│  │ Temperature  │   │ Goal-Tracking│   │ IntrinsicMot │      │
│  │ Sleep-Report │   │ GrowthLog    │   │ IdleTracker  │      │
│  │ MemoryStream │   │ QuestionQue  │   │              │      │
│  │ ConvBuffer   │   │              │   │              │      │
│  │ ConfDetector │   │              │   │              │      │
│  │ VersionCtrl  │   │              │   │              │      │
│  │ MemoryCache  │   │              │   │              │      │
│  │ MemorySecur  │   │              │   │              │      │
│  └──────────────┘   └──────────────┘   └──────────────┘      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ 认知决策
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│      PLAN & TASK ORCHESTRATOR (小脑 - 精准协调！)               │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  意图分析 → 复杂度识别 → 任务图生成 → 拓扑排序 → 执行    │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ 任务图
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│           EXECUTION ENGINE (手脚 - 强力执行)                    │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐      │
│  │ Tool Engine  │   │ Multi-Agent  │   │ Workflow     │      │
│  │ (工具引擎)   │   │ Colab (协作) │   │ Engine (流程)│      │
│  ├──────────────┤   ├──────────────┤   ├──────────────┤      │
│  │ MCP Protocol │   │ Role Assign  │   │ State Machine│      │
│  │ ToolGuard    │   │ Vote/Decide  │   │ Error Recov  │      │
│  │ Auto-Context │   │ Task Distrib │   │ Retry Logic  │      │
│  └──────────────┘   └──────────────┘   └──────────────┘      │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  Execution Monitor (执行监控器)                            │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ 执行结果 + 观察
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│           FEEDBACK & LEARNING LOOP (反馈学习环)                 │
│  结果验证 → 经验提取 → 技能进化 → 记忆巩固 → 认知调整          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              INFRASTRUCTURE LAYER (基础设施层)                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────┐ │
│  │ SvcManager   │ │  Workspace   │ │  EventBus    │ │ ConfigMgr│ │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────┘ │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────┐ │
│  │ StateMgr     │ │  ErrorHandler│ │  ModuleLib   │ │ PluginMg │ │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────┘ │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────┐ │
│  │ SleepConfig  │ │  MediaMgr    │ │  AttachMgr   │ │ Logger   │ │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## 四、Neurova 安全体系 2.0（借鉴 QwenPaw）

> **核心理念**：采用 QwenPaw 成熟的三层安全架构，结合 Neurova 的认知增强特性，构建全面的安全防护体系。

---

### 4.1 安全体系整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    NEUROVA SECURITY SYSTEM                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  1. 工具守卫 (Tool Guard) — 运行时安全检测               │   │
│  │  ├─ RuleBasedGuardian (YAML 正则规则)                    │   │
│  │  ├─ ShellEvasionGuardian (引号感知的 Shell 绕过检测)       │   │
│  │  └─ FilePathGuardian (敏感文件访问控制)                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  2. 技能扫描器 (Skill Scanner) — 技能安全预检            │   │
│  │  ├─ PatternAnalyzer (YAML 签名模式检测)                   │   │
│  │  ├─ 智能缓存 (基于文件 mtime)                              │   │
│  │  └─ 白名单机制 (内容哈希验证)                               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  3. Web 登录认证 (Auth System) — 访问控制                │   │
│  │  ├─ 密码加盐哈希存储                                       │   │
│  │  ├─ HMAC 签名令牌                                          │   │
│  │  └─ 本地免认证 (127.0.0.1)                                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  NEUROVA 特色增强 (Neurova-Specific)                   │   │
│  │  ├─ 认知安全检查 (Cognitive Safety Checker)              │   │
│  │  ├─ 记忆安全防护 (Memory Security Guard)                  │   │
│  │  └─ 自主技能安全评估 (Auto Skill Safety Audit)            │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

### 4.2 核心安全组件

#### 4.2.1 工具守卫 (Tool Guard)

**作用**：在 Agent 调用工具前实时检测危险模式，防止恶意操作。

```python
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Any, Optional

class GuardSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"
    SAFE = "SAFE"

class GuardThreatCategory(str, Enum):
    COMMAND_INJECTION = "command_injection"
    DATA_EXFILTRATION = "data_exfiltration"
    PATH_TRAVERSAL = "path_traversal"
    SENSITIVE_FILE_ACCESS = "sensitive_file_access"
    NETWORK_ABUSE = "network_abuse"
    CREDENTIAL_EXPOSURE = "credential_exposure"
    RESOURCE_ABUSE = "resource_abuse"
    PROMPT_INJECTION = "prompt_injection"
    CODE_EXECUTION = "code_execution"
    PRIVILEGE_ESCALATION = "privilege_escalation"

@dataclass
class GuardFinding:
    id: str
    rule_id: str
    category: GuardThreatCategory
    severity: GuardSeverity
    title: str
    description: str
    tool_name: str
    param_name: Optional[str] = None
    matched_value: Optional[str] = None
    matched_pattern: Optional[str] = None
    snippet: Optional[str] = None
    remediation: Optional[str] = None

@dataclass
class ToolGuardResult:
    tool_name: str
    params: Dict[str, Any]
    findings: List[GuardFinding]
    guard_duration_seconds: float = 0.0
    guardians_used: List[str] = None
    
    @property
    def is_safe(self) -> bool:
        return not any(
            f.severity in (GuardSeverity.CRITICAL, GuardSeverity.HIGH)
            for f in self.findings
        )
    
    @property
    def max_severity(self) -> GuardSeverity:
        if not self.findings:
            return GuardSeverity.SAFE
        # 按严重程度排序返回最高级别
        pass

class ToolGuardEngine:
    """工具守卫引擎 - 协调所有守卫"""
    
    def __init__(self, guardians: List = None):
        self._guardians = guardians or self._default_guardians()
    
    def _default_guardians(self) -> List:
        return [
            FilePathToolGuardian(),      # 敏感文件检测
            RuleBasedToolGuardian(),     # 规则检测
            ShellEvasionGuardian(),      # Shell 绕过检测
        ]
    
    def guard(self, tool_name: str, params: Dict[str, Any]) -> ToolGuardResult:
        """执行工具调用守卫"""
        result = ToolGuardResult(tool_name=tool_name, params=params, findings=[])
        for guardian in self._guardians:
            findings = guardian.guard(tool_name, params)
            result.findings.extend(findings)
        return result
```

**内置规则覆盖**：
- 危险文件操作 (rm -rf, chmod 777)
- 低级磁盘操作 (mkfs, dd)
- 资源滥用 (fork bomb, 重启服务)
- 代码执行 (管道执行, base64 解码执行)
- 权限提升 (sudo, su)
- 反向 Shell

**Agent 审批级别**：
- `STRICT`：所有调用需人工审批
- `SMART`：低风险自动放行，高风险需审批
- `AUTO`：仅被规则标记的需审批（默认）
- `OFF`：关闭守卫

#### 4.2.2 技能扫描器 (Skill Scanner)

**作用**：在技能启用前扫描安全威胁，检测恶意代码。

```python
from pathlib import Path
from dataclasses import dataclass

class ScanMode(str, Enum):
    BLOCK = "block"        # 拦截不安全技能
    WARN = "warn"          # 仅警告
    OFF = "off"            # 关闭扫描

@dataclass
class Finding:
    id: str
    rule_id: str
    category: str
    severity: GuardSeverity
    title: str
    description: str
    file_path: str
    line_number: int
    matched_pattern: str
    remediation: str

@dataclass
class ScanResult:
    skill_name: str
    skill_directory: str
    findings: List[Finding]
    scan_duration_seconds: float
    is_safe: bool

class SkillScanner:
    """技能安全扫描器"""
    
    def __init__(self, policy: ScanPolicy = None):
        self._policy = policy or ScanPolicy.default()
        self._analyzers = [PatternAnalyzer(policy)]
    
    def scan_skill(self, skill_dir: Path, skill_name: str = None) -> ScanResult:
        """扫描技能目录"""
        # 1. 发现文件（跳过符号链接、验证路径边界）
        files = self._discover_files(skill_dir)
        # 2. 运行分析器
        all_findings = []
        for analyzer in self._analyzers:
            findings = analyzer.analyze(skill_dir, files)
            all_findings.extend(findings)
        # 3. 构建结果
        return ScanResult(
            skill_name=skill_name or skill_dir.name,
            skill_directory=str(skill_dir),
            findings=all_findings,
            scan_duration_seconds=0.0,
            is_safe=not any(f.severity in (GuardSeverity.CRITICAL, GuardSeverity.HIGH) for f in all_findings)
        )
    
    def _discover_files(self, skill_dir: Path) -> List[SkillFile]:
        """安全的文件发现 - 防止路径遍历攻击"""
        result = []
        for p in skill_dir.rglob("*"):
            if p.is_symlink():
                continue  # 跳过符号链接
            real = p.resolve()
            if not real.is_relative_to(skill_dir):
                continue  # 验证在技能目录边界内
            # 检查大小、扩展名...
            result.append(SkillFile.from_path(p, skill_dir))
        return result
```

**扫描模式**：
- `block`：拦截不安全技能
- `warn`：仅警告，允许使用（默认）
- `off`：关闭扫描

**白名单机制**：基于内容哈希的安全白名单，技能内容改变则白名单失效。

#### 4.2.3 Web 登录认证 (Auth System)

**作用**：保护控制台免受未授权访问。

```python
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

class AuthSystem:
    """认证系统"""
    
    def __init__(self, secret_store: SecretStore):
        self._secret_store = secret_store
    
    def hash_password(self, password: str, salt: bytes = None) -> tuple[bytes, bytes]:
        """加盐 SHA-256 哈希密码"""
        if salt is None:
            salt = secrets.token_bytes(16)
        hashed = hashlib.sha256(salt + password.encode()).digest()
        return salt, hashed
    
    def create_token(self, user_id: str) -> str:
        """创建 HMAC 签名令牌（7 天过期）"""
        payload = {
            "user_id": user_id,
            "exp": (datetime.utcnow() + timedelta(days=7)).timestamp(),
            "iat": datetime.utcnow().timestamp(),
        }
        # 使用 JWT-like 格式，HMAC 签名
        pass
    
    def verify_token(self, token: str) -> Optional[str]:
        """验证令牌，返回用户 ID 或 None"""
        pass
    
    def is_local_request(self, client_ip: str) -> bool:
        """检查是否为本地请求（免认证）"""
        return client_ip in ("127.0.0.1", "::1")
```

**安全特性**：
- 密码加盐 SHA-256 哈希
- HMAC-SHA256 签名令牌
- 仅用 Python 标准库，无外部依赖
- 文件权限 0o600 保护
- 本地请求（127.0.0.1）免认证

---

### 4.3 Neurova 特色安全增强

#### 4.3.1 认知安全检查器 (Cognitive Safety Checker)

利用 Neurova 的认知能力进行高级安全检查：

```python
class CognitiveSafetyChecker:
    """认知安全检查器 - Neurova 特色"""
    
    async def check_intent_safety(self, intent: str, context: Dict) -> SafetyCheckResult:
        """检查用户意图是否安全"""
        # 使用认知核进行安全评估
        safety_prompt = f"""评估以下用户请求的安全性:
请求: {intent}
上下文: {context}

请从以下方面评估:
1. 是否涉及危险操作
2. 是否存在伦理问题
3. 是否违反核心指令
4. 是否存在隐私风险

返回 JSON 格式的评估结果。"""
        
        assessment = await self._cognitive_orchestrator.process(safety_prompt)
        return SafetyCheckResult(assessment)
    
    async def monitor_execution_safety(self, execution_trace: List) -> bool:
        """实时监控执行安全"""
        # 在执行过程中持续检查安全状态
        pass
```

#### 4.3.2 记忆安全防护 (Memory Security Guard)

保护敏感记忆不被泄露：

```python
class MemorySecurityGuard:
    """记忆安全防护"""
    
    def __init__(self):
        self._sensitive_patterns = [
            r"password\s*[=:]\s*[^\s]+",
            r"api[_-]?key\s*[=:]\s*[^\s]+",
            r"private\s*key",
            r"secret\s*[=:]",
        ]
    
    def sanitize_memory(self, memory_content: str) -> str:
        """清理记忆中的敏感信息"""
        sanitized = memory_content
        for pattern in self._sensitive_patterns:
            sanitized = re.sub(pattern, "[REDACTED]", sanitized, flags=re.I)
        return sanitized
    
    def should_remember(self, content: str) -> bool:
        """判断是否应该记住某内容"""
        # 检查是否包含过于敏感的信息
        pass
```

#### 4.3.3 自主技能安全评估 (Auto Skill Safety Audit)

结合技能进化系统的安全审计：

```python
class AutoSkillSafetyAuditor:
    """自主技能安全审计器"""
    
    def __init__(self, skill_scanner: SkillScanner, skill_evolution: SkillsEvolutionEngine):
        self._scanner = skill_scanner
        self._evolution = skill_evolution
    
    async def audit_new_skill(self, skill: SkillInfo) -> SkillInfo:
        """审计新生成的技能"""
        # 1. 静态扫描
        scan_result = self._scanner.scan_skill(skill.directory)
        if not scan_result.is_safe:
            # 2. 尝试自动修复
            fixed_skill = await self._evolution.auto_fix_security_issues(skill, scan_result.findings)
            return fixed_skill
        return skill
    
    def audit_skill_evolution(self, old_skill: SkillInfo, new_skill: SkillInfo) -> bool:
        """审计技能进化过程的安全性"""
        # 检查技能进化是否引入新的安全问题
        pass
```

---

### 4.4 配置文件结构

```yaml
# neurova_config.yaml
security:
  # 工具守卫配置
  tool_guard:
    enabled: true
    guarded_tools: null        # null 表示守护所有工具
    denied_tools: []           # 无条件禁止的工具
    custom_rules: []           # 自定义规则
    disabled_rules: []         # 禁用的内置规则
    shell_evasion_checks:
      command_substitution: false
      obfuscated_flags: false
  
  # 文件防护配置
  file_guard:
    enabled: true
    sensitive_files:
      - "~/.ssh/"
      - "~/.neurova.secret/"
      - "/etc/passwd"
      - "/etc/shadow"
      - ".env"
      - "secrets/"
  
  # 技能扫描器配置
  skill_scanner:
    mode: "warn"               # block / warn / off
    timeout: 30                # 扫描超时（秒）
    whitelist: []              # 白名单技能（内容哈希）
  
  # Web 认证配置
  auth:
    enabled: false
    allow_no_auth_hosts:
      - "127.0.0.1"
      - "::1"
  
  # Neurova 特色安全
  neurova_safety:
    cognitive_check: true
    memory_sanitization: true
    auto_skill_audit: true
```

---

### 4.5 API 设计

```python
# 安全相关 API 端点

# 工具守卫
/api/security/tool-guard/status
/api/security/tool-guard/config      # GET/POST
/api/security/tool-guard/rules       # 规则管理

# 技能扫描
/api/security/skill-scanner/scan
/api/security/skill-scanner/whitelist
/api/security/skill-scanner/alerts

# 认证
/api/auth/login
/api/auth/register
/api/auth/status
/api/auth/logout
/api/auth/reset-password

# Neurova 特色
/api/security/cognitive/check
/api/security/memory/sanitize
/api/security/skill-audit/run
```

---

## 五、系统设置功能

### 5.1 概述

Neurova 系统设置功能提供三个核心模块：
1. **多语言支持** - 11种语言的国际化界面
2. **多用户管理** - 用户隔离、权限管理
3. **时间区管理** - 自定义时区、时间校准

### 5.2 多语言系统架构

#### 支持的语言

| 代码 | 语言 | 本地化名称 |
|------|------|----------|
| zh-CN | 简体中文 | 简体中文 |
| zh-TW | 繁体中文 | 繁體中文 |
| bo | 藏语 | བོད་ཡིག |
| en | 英语 | English |
| ru | 俄语 | Русский |
| ja | 日语 | 日本語 |
| ko | 韩语 | 한국어 |
| ar | 阿拉伯语 | العربية |
| fr | 法语 | Français |
| it | 意大利语 | Italiano |
| de | 德语 | Deutsch |

#### 目录结构

```
neurova/
├── language/
│   ├── locales/
│   │   ├── zh-CN.json
│   │   ├── zh-TW.json
│   │   ├── bo.json
│   │   ├── en.json
│   │   ├── ru.json
│   │   ├── ja.json
│   │   ├── ko.json
│   │   ├── ar.json
│   │   ├── fr.json
│   │   ├── it.json
│   │   └── de.json
│   ├── index.ts              # 前端 language 初始化
│   └── utils.ts              # 语言工具函数
```

#### 后端语言服务设计

```python
from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum
import json
from pathlib import Path

class Language(str, Enum):
    ZH_CN = "zh-CN"
    ZH_TW = "zh-TW"
    BO = "bo"
    EN = "en"
    RU = "ru"
    JA = "ja"
    KO = "ko"
    AR = "ar"
    FR = "fr"
    IT = "it"
    DE = "de"
    
    @classmethod
    def default(cls) -> "Language":
        return cls.EN
    
    @classmethod
    def display_name(cls, lang: "Language") -> str:
        return {
            cls.ZH_CN: "简体中文",
            cls.ZH_TW: "繁體中文",
            cls.BO: "བོད་ཡིག",
            cls.EN: "English",
            cls.RU: "Русский",
            cls.JA: "日本語",
            cls.KO: "한국어",
            cls.AR: "العربية",
            cls.FR: "Français",
            cls.IT: "Italiano",
            cls.DE: "Deutsch",
        }[lang]

@dataclass
class Translation:
    key: str
    value: str
    namespace: str = "common"

class LanguageService:
    def __init__(self, locales_dir: Path):
        self.locales_dir = locales_dir
        self._translations: Dict[Language, Dict[str, Dict[str, str]]] = {}
        self._load_all_locales()
    
    def _load_all_locales(self):
        for lang in Language:
            file_path = self.locales_dir / f"{lang.value}.json"
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    self._translations[lang] = json.load(f)
    
    def t(self, key: str, lang: Language, **kwargs) -> str:
        """获取翻译"""
        if lang not in self._translations:
            lang = Language.default()
        
        keys = key.split('.')
        value = self._translations.get(lang, {})
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return key
        
        if kwargs:
            try:
                return value.format(**kwargs)
            except (KeyError, ValueError):
                pass
        return value
    
    def get_available_languages(self) -> list[Language]:
        return list(self._translations.keys())
    
    def get_language_info(self, lang: Language) -> Dict:
        return {
            "code": lang.value,
            "displayName": Language.display_name(lang),
            "isRtl": lang == Language.AR  # 阿拉伯语是从右到左
        }
```

#### 前端 language 配置（参考 QwenPaw）

```typescript
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import zhCN from "./locales/zh-CN.json";
import zhTW from "./locales/zh-TW.json";
import bo from "./locales/bo.json";
import en from "./locales/en.json";
import ru from "./locales/ru.json";
import ja from "./locales/ja.json";
import ko from "./locales/ko.json";
import ar from "./locales/ar.json";
import fr from "./locales/fr.json";
import it from "./locales/it.json";
import de from "./locales/de.json";

const resources = {
  "zh-CN": { translation: zhCN },
  "zh-TW": { translation: zhTW },
  "bo": { translation: bo },
  "en": { translation: en },
  "ru": { translation: ru },
  "ja": { translation: ja },
  "ko": { translation: ko },
  "ar": { translation: ar },
  "fr": { translation: fr },
  "it": { translation: it },
  "de": { translation: de },
};

i18n
  .use(initReactI18next)
  .init({
    resources,
    lng: localStorage.getItem("language") || "en",
    fallbackLng: "en",
    interpolation: {
      escapeValue: false,
    },
  });

export default i18n;
```

#### 语言设置 API

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/settings/language", tags=["settings"])

class LanguageUpdate(BaseModel):
    language: str

@router.get("", summary="获取当前语言设置")
async def get_language():
    return {
        "language": current_user.language if current_user else "en",
        "availableLanguages": [
            {
                "code": lang.value,
                "displayName": Language.display_name(lang),
                "isRtl": lang == Language.AR,
            }
            for lang in Language
        ]
    }

@router.put("", summary="更新语言设置")
async def update_language(update: LanguageUpdate):
    try:
        lang = Language(update.language)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的语言代码")
    
    if current_user:
        current_user.language = update.language
        save_user_settings(current_user)
    else:
        save_global_setting("language", update.language)
    
    return {"language": update.language, "success": True}
```

### 5.3 多用户管理与数据隔离（完整设计）

> **设计理念**：通过用户组、资源配额、权限管理和数据隔离，实现完整的多用户管理系统！

---

#### 5.3.1 用户组定义（UserGroup）

> **核心概念**：用户不再直接拥有角色，而是属于某个**用户组**，每个用户组有不同的**资源配额**和**权限集合**！

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

class UserGroupType(str, Enum):
    """用户组类型"""
    SUPER_ADMIN = "super_admin"  # 超级管理员（所有权限）
    ADMIN = "admin"              # 管理员
    DEVELOPER = "developer"      # 开发者
    USER = "user"                # 普通用户
    GUEST = "guest"              # 访客
    CUSTOM = "custom"            # 自定义用户组

@dataclass
class UserGroup:
    """用户组定义"""
    
    group_id: str
    name: str
    description: str
    group_type: UserGroupType
    
    # 资源配额
    quota: ResourceQuota
    
    # 权限集合
    permissions: Set[Permission]
    
    # 元数据
    is_system: bool = False  # 是否是系统内置用户组
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
```

**预定义用户组**：

| 用户组 | 说明 | Agent数量 | 项目数量 | LLM调用/天 | 存储空间 |
|--------|------|----------|----------|-------------|----------|
| **超级管理员** | 所有权限 | 无限制 | 无限制 | 无限制 | 无限制 |
| **管理员** | 大部分权限 | 100 | 100 | 10,000 | 10 GB |
| **开发者** | 较高权限 | 20 | 50 | 5,000 | 5 GB |
| **普通用户** | 基本权限 | 5 | 10 | 1,000 | 1 GB |
| **访客** | 有限权限 | 1 | 2 | 100 | 100 MB |

---

#### 5.3.2 资源配额管理（ResourceQuota）

> **核心概念**：每个用户组有自己的**资源配额**，限制用户可使用的资源！

```python
@dataclass
class ResourceQuota:
    """资源配额定义"""
    
    # Agent配额
    max_agents: int = 5
    
    # 项目配额
    max_projects: int = 10
    
    # LLM配额
    max_llm_calls_per_day: int = 1000
    max_llm_tokens_per_day: int = 100000
    
    # 存储配额
    max_storage_mb: int = 1024
    max_file_size_mb: int = 10
    
    # 技能配额
    max_private_skills: int = 50
    
    # 协作配额
    max_collab_projects: int = 5
    max_team_members: int = 10
    
    # 其他配额
    max_api_calls_per_day: int = 5000
    max_concurrent_sessions: int = 3
```

**配额检查示例**：

```python
# 用户尝试创建Agent
quota_manager = ResourceQuotaManager(...)

# 检查Agent配额
allowed, error = quota_manager.check_agent_quota(user_id, group_type)
if not allowed:
    raise HTTPException(status_code=403, detail=error)

# 配额充足，允许创建
quota_manager.increment_agent_count(user_id)
```

---

#### 5.3.3 权限定义（Permission）

> **核心概念**：细粒度的权限控制，每个用户组有不同的权限集合！

```python
class Permission(str, Enum):
    """系统权限定义"""
    
    # 用户管理权限
    USER_CREATE = "user:create"
    USER_READ = "user:read"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"
    USER_BACKUP = "user:backup"
    
    # Agent管理权限
    AGENT_CREATE = "agent:create"
    AGENT_READ = "agent:read"
    AGENT_UPDATE = "agent:update"
    AGENT_DELETE = "agent:delete"
    AGENT_PUBLISH = "agent:publish"
    
    # 项目管理权限
    PROJECT_CREATE = "project:create"
    PROJECT_READ = "project:read"
    PROJECT_UPDATE = "project:update"
    PROJECT_DELETE = "project:delete"
    PROJECT_SHARE = "project:share"
    
    # 技能管理权限
    SKILL_PUBLIC_READ = "skill:public:read"
    SKILL_PUBLIC_WRITE = "skill:public:write"
    SKILL_PRIVATE_READ = "skill:private:read"
    SKILL_PRIVATE_WRITE = "skill:private:write"
    SKILL_INSTALL = "skill:install"
    SKILL_PUSH_TO_AGENT = "skill:push"
    
    # LLM管理权限
    LLM_CUSTOM_ADD = "llm:custom:add"
    LLM_CALL = "llm:call"
    
    # 协作管理权限
    COLLABORATION_CREATE = "collab:create"
    COLLABORATION_SHARE = "collab:share"
    
    # 系统管理权限
    SYSTEM_CONFIG = "system:config"
    SYSTEM_BACKUP = "system:backup"
```

**权限检查示例**：

```python
# 检查用户是否有创建Agent的权限
if not group_manager.check_permission(user_group_id, Permission.AGENT_CREATE):
    raise HTTPException(status_code=403, detail="无权创建Agent")

# 权限充足，允许创建
create_agent(...)
```

---

#### 5.3.4 增强用户模型（EnhancedUserModel）

> **核心概念**：用户与用户组关联，通过用户组获取权限和配额！

```python
class EnhancedUserModel:
    """增强用户数据模型"""
    
    def __init__(
        self,
        data_dir: Path,
        db_path: str = "data/users.db",
        group_manager: Optional[UserGroupManager] = None,
        quota_manager: Optional[ResourceQuotaManager] = None,
    ):
        self.data_dir = data_dir
        self.db_path = db_path
        self.group_manager = group_manager
        self.quota_manager = quota_manager
        
        self._init_db()
        self._migrate_db()  # 从旧表迁移数据
    
    def create_user(
        self,
        username: str,
        password: str,
        email: str = None,
        group_type: UserGroupType = UserGroupType.USER,
    ) -> Optional[Dict]:
        """创建新用户，关联到用户组"""
        # 加密密码
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        
        # 插入数据库
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO enhanced_users (username, email, password_hash, group_type)
            VALUES (?, ?, ?, ?)
        ''', (username, email, password_hash, group_type.value))
        conn.commit()
        
        user_id = cursor.lastrowid
        return self.get_user_by_id(user_id)
    
    def get_user_permissions(self, user_id: int) -> Set[Permission]:
        """获取用户的权限集合（通过用户组）"""
        user = self.get_user_by_id(user_id)
        if not user:
            return set()
        
        group = self.group_manager.get_group_by_type(
            UserGroupType(user['group_type'])
        )
        
        if not group:
            return set()
        
        return group.permissions
    
    def get_user_quota(self, user_id: int) -> Optional[ResourceQuota]:
        """获取用户的资源配额（通过用户组）"""
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        
        return self.group_manager.get_user_quota(user['group_type'])
```

**数据库表结构（enhanced_users）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| username | TEXT | 用户名（唯一） |
| email | TEXT | 邮箱（唯一） |
| password_hash | TEXT | bcrypt加密的密码 |
| **group_type** | TEXT | **用户组类型** |
| status | TEXT | 状态（active/inactive/locked） |
| language | TEXT | 语言设置 |
| timezone | TEXT | 时区设置 |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |
| last_login | TEXT | 最后登录时间 |

---

#### 5.3.5 技能池隔离（SkillPoolManager）

> **核心概念**：公共技能池 + 专属技能池，用户隔离，不能进入其他用户的专属技能池！

**技能池类型**：

| 类型 | 说明 | 可见性 |
|------|------|--------|
| **公共技能池** | 所有用户可访问 | 所有用户可见 |
| **专属技能池** | 用户隔离 | 仅所有者可见，可共享 |

```python
class SkillPoolManager:
    """技能池管理器"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.public_pool_dir = data_dir / "skills" / "public"
        self.private_pool_base_dir = data_dir / "skills" / "private"
    
    # ============================================================
    # 公共技能池操作
    # ============================================================
    
    def list_public_skills(self, user_id: str) -> List[SkillMetadata]:
        """列出公共技能池中的技能（所有用户可访问）"""
        return list(self._public_skills.values())
    
    def install_public_skill(self, skill_id: str, user_id: str, 
                            target_agent_id: str) -> bool:
        """
        安装公共技能到用户的Agent
        
        公共技能可以被任何用户安装到自己的Agent
        """
        # 复制技能到用户的专属技能池
        self._copy_public_skill_to_private(skill_id, user_id)
        
        # 推送到Agent
        return self.push_skill_to_agent(
            skill_id, user_id, target_agent_id, 
            is_public=True
        )
    
    # ============================================================
    # 专属技能池操作
    # ============================================================
    
    def list_private_skills(self, user_id: str) -> List[SkillMetadata]:
        """
        列出用户的专属技能
        
        用户只能查看自己的专属技能，除非技能被共享
        """
        return [
            s for s in self._private_skills.values()
            if s.owner_user_id == user_id or user_id in s.shared_with
        ]
    
    def create_private_skill(self, skill_id: str, name: str,
                              user_id: str, visibility: SkillVisibility) -> SkillMetadata:
        """创建专属技能（用户隔离）"""
        # 只能创建到自己的专属技能池
        key = f"{user_id}:{skill_id}"
        skill = SkillMetadata(
            skill_id=skill_id,
            name=name,
            pool_type=SkillPoolType.PRIVATE,
            visibility=visibility,
            owner_user_id=user_id,
        )
        
        self._private_skills[key] = skill
        self._save_metadata()
        
        return skill
    
    def share_private_skill(self, skill_id: str, owner_id: str, 
                             target_user_id: str) -> bool:
        """
        共享专属技能给另一个用户
        
        用户只能共享自己的技能
        """
        key = f"{owner_id}:{skill_id}"
        skill = self._private_skills.get(key)
        if not skill:
            return False
        
        # 只能共享自己的技能
        if skill.owner_user_id != owner_id:
            return False
        
        skill.visibility = SkillVisibility.SHARED
        skill.shared_with.add(target_user_id)
        
        return True
    
    def push_skill_to_agent(self, skill_id: str, user_id: str, 
                             agent_id: str) -> bool:
        """
        推送技能给Agent
        
        用户只能将技能推送给自己的Agent
        """
        skill = self._private_skills.get(f"{user_id}:{skill_id}")
        if not skill:
            return False
        
        # 推送给Agent
        skill.pushed_to_agents.add(agent_id)
        
        # TODO: 实际推送逻辑（将技能文件复制到Agent的工作目录）
        return True
```

**技能池隔离示意图**：

```
公共技能池（所有用户可访问）
├── skill-A
├── skill-B
└── skill-C

专属技能池（用户隔离）
├── user-1/
│   ├── my-skill-1  # 仅user-1可见
│   └── my-skill-2  # 仅user-1可见
├── user-2/
│   ├── my-skill-3  # 仅user-2可见
│   └── my-skill-4  # 仅user-2可见（可共享给user-1）
└── user-3/
    └── my-skill-5  # 仅user-3可见
```

---

#### 5.3.6 协作模块隔离（CollaborationIsolationManager）

> **核心概念**：项目、文件、工作流按用户隔离，用户只能看到自己参与的项目！

```python
class CollaborationIsolationManager:
    """协作模块隔离管理器"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.projects_dir = data_dir / "projects"
    
    def create_project(self, name: str, description: str,
                       owner_user_id: str) -> Project:
        """
        创建项目（自动按用户隔离）
        
        项目所有者自动成为团队成员（OWNER角色）
        """
        project = Project(
            project_id=f"proj_{secrets.token_hex(8)}",
            name=name,
            description=description,
            owner_user_id=owner_user_id,
            members=[
                ProjectMember(
                    user_id=owner_user_id,
                    role=MemberRole.OWNER,
                )
            ],
        )
        
        # 创建项目目录
        project_dir = self.projects_dir / project.project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建子目录
        (project_dir / "files").mkdir(exist_ok=True)
        (project_dir / "workflows").mkdir(exist_ok=True)
        
        return project
    
    def get_project(self, project_id: str, user_id: str) -> Optional[Project]:
        """
        获取项目（带权限检查）
        
        用户只能查看自己参与的项目
        """
        project = self._projects.get(project_id)
        if not project:
            return None
        
        # 检查权限：只有项目成员才能查看
        if not project.has_member(user_id):
            return None
        
        return project
    
    def list_user_projects(self, user_id: str) -> List[Project]:
        """
        列出用户参与的所有项目
        
        用户只能看到自己参与的项目
        """
        return [
            p for p in self._projects.values()
            if p.has_member(user_id) and p.status != ProjectStatus.DELETED
        ]
    
    def add_project_member(self, project_id: str, owner_user_id: str,
                             target_user_id: str, role: MemberRole) -> bool:
        """
        添加项目成员
        
        只有OWNER和ADMIN可以添加成员
        """
        project = self.get_project(project_id, owner_user_id)
        if not project:
            return False
        
        if not project.can_manage_members(owner_user_id):
            return False
        
        # 添加成员
        project.members.append(
            ProjectMember(
                user_id=target_user_id,
                role=role,
                added_by=owner_user_id,
            )
        )
        
        return True
```

**协作模块隔离示意图**：

```
项目隔离（按用户）
├── user-1的项目/
│   ├── project-A（user-1是OWNER，user-2是EDITOR）
│   └── project-B（user-1是OWNER，user-3是VIEWER）
├── user-2的项目/
│   └── project-C（user-2是OWNER）
└── user-3的项目/
    └── project-D（user-3是OWNER，user-1是EDITOR）

文件隔离（按项目）
├── project-A/
│   └── files/
│       ├── file-1.txt  # 仅project-A的成员可访问
│       └── file-2.txt
└── project-B/
    └── files/
        └── file-3.txt  # 仅project-B的成员可访问
```

---

#### 5.3.7 管理员功能（AdminService）

> **核心概念**：管理员可以创建用户、备份用户资料、删除用户（含所有数据）！

```python
class AdminService:
    """管理员服务"""
    
    def __init__(
        self,
        data_dir: Path,
        user_model: EnhancedUserModel,
        group_manager: UserGroupManager,
        skill_manager: SkillPoolManager,
        collab_manager: CollaborationIsolationManager,
    ):
        self.data_dir = data_dir
        self.user_model = user_model
        self.group_manager = group_manager
        self.skill_manager = skill_manager
        self.collab_manager = collab_manager
    
    # ============================================================
    # 用户管理
    # ============================================================
    
    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        group_type: UserGroupType = UserGroupType.USER,
    ) -> Dict:
        """创建用户（管理员功能）"""
        # 检查用户名是否已存在
        existing = self.user_model.get_user_by_username(username)
        if existing:
            raise ValueError(f"用户名已存在: {username}")
        
        # 创建用户
        user = self.user_model.create_user(
            username=username,
            password=password,
            email=email,
            group_type=group_type,
        )
        
        # 初始化用户工作空间
        self._init_user_workspace(user["id"])
        
        return user
    
    def delete_user(self, user_id: int, backup_before_delete: bool = True) -> Dict:
        """
        删除用户（管理员功能）
        
        会清理用户的所有相关数据：
        - Agent工作区
        - 协作项目
        - 专属技能池
        - 文件
        - 记忆
        """
        # 备份用户资料（如果需要）
        if backup_before_delete:
            backup = self.backup_user(user_id)
        
        # 清理用户数据
        cleanup_summary = self._cleanup_user_data(user_id)
        
        # 删除用户（从数据库中）
        self.user_model.delete_user(user_id)
        
        return {
            "user_id": user_id,
            "backup_id": backup.backup_id if backup_before_delete else None,
            "cleanup_summary": cleanup_summary,
        }
    
    def _cleanup_user_data(self, user_id: int) -> Dict:
        """
        清理用户的所有数据
        
        返回清理摘要
        """
        summary = {
            "agents_deleted": 0,
            "projects_deleted": 0,
            "skills_deleted": 0,
            "files_deleted": 0,
        }
        
        # 1. 清理Agent工作区
        agents_dir = self.data_dir / "user_workspaces" / str(user_id) / "agents"
        if agents_dir.exists():
            agent_count = len(list(agents_dir.iterdir()))
            shutil.rmtree(agents_dir)
            summary["agents_deleted"] = agent_count
        
        # 2. 清理协作项目
        projects_deleted = self.collab_manager.admin_delete_user_projects(str(user_id))
        summary["projects_deleted"] = projects_deleted
        
        # 3. 清理专属技能池
        skills_deleted = self.skill_manager.admin_delete_user_skills(str(user_id))
        summary["skills_deleted"] = skills_deleted
        
        # 4. 删除整个用户工作空间
        user_workspace = self.data_dir / "user_workspaces" / str(user_id)
        if user_workspace.exists():
            shutil.rmtree(user_workspace)
        
        return summary
    
    # ============================================================
    # 用户资料备份
    # ============================================================
    
    def backup_user(self, user_id: int) -> UserBackup:
        """
        备份用户资料
        
        备份内容包括：
        - 用户数据库记录
        - Agent配置
        - 专属技能
        - 项目数据
        - 设置文件
        """
        # 获取用户信息
        user = self.user_model.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"用户不存在: {user_id}")
        
        # 创建备份
        backup_id = f"backup_{secrets.token_hex(8)}"
        backup_filename = f"{user['username']}_{backup_id}.tar.gz"
        backup_path = self.data_dir / "backups" / backup_filename
        
        # 打包用户数据
        import tarfile
        with tarfile.open(backup_path, "w:gz") as tar:
            # 备份用户数据库记录
            user_data = json.dumps(user, indent=2, ensure_ascii=False)
            import io
            user_data_bytes = user_data.encode()
            info = tarfile.TarInfo(name=f"{user['username']}/user.json")
            info.size = len(user_data_bytes)
            tar.addfile(info, io.BytesIO(user_data_bytes))
            
            # 备份用户工作空间
            user_workspace = self.data_dir / "user_workspaces" / str(user_id)
            if user_workspace.exists():
                tar.add(user_workspace, arcname=f"{user['username']}/workspace")
        
        # 创建备份记录
        backup = UserBackup(
            backup_id=backup_id,
            user_id=user_id,
            username=user['username'],
            backup_at=datetime.utcnow(),
            backup_file=backup_path,
            backup_size=backup_path.stat().st_size,
        )
        
        return backup
```

**删除用户的数据清理示意图**：

```
删除用户（user-1）

清理前：
├── user_workspaces/
│   └── user-1/           # 用户工作空间
│       ├── agents/        # Agent工作区（5个Agent）
│       ├── skills/        # 专属技能池（10个技能）
│       ├── projects/      # 项目数据（3个项目）
│       ├── files/         # 文件（100个文件）
│       └── memories/     # 记忆
└── projects/
    ├── proj-A/           # user-1是OWNER
    └── proj-B/           # user-1是EDITOR

清理后：
├── user_workspaces/
│   └── user-1/         # 已删除
└── projects/
    ├── proj-A/           # 已删除（因为user-1是OWNER）
    └── proj-B/           # 保留（但user-1被移除出团队成员）
```

---

#### 5.3.8 资源配额检查和限制

> **核心概念**：在用户执行操作时检查配额，超限时拒绝操作！

```python
class ResourceQuotaManager:
    """资源配额管理器"""
    
    def __init__(
        self,
        data_dir: Path,
        group_manager: UserGroupManager,
    ):
        self.data_dir = data_dir
        self.group_manager = group_manager
        
        # 用户资源使用量: user_id -> ResourceUsage
        self._usage: Dict[str, ResourceUsage] = {}
    
    def check_agent_quota(self, user_id: str, group_type: UserGroupType) -> tuple[bool, str]:
        """
        检查Agent配额
        
        返回: (是否允许, 错误信息)
        """
        quota = self.get_user_quota(user_id, group_type)
        usage = self._get_or_create_usage(user_id)
        
        if usage.agent_count >= quota.max_agents:
            return False, f"Agent数量已达上限（{quota.max_agents}）"
        
        return True, ""
    
    def check_llm_call_quota(self, user_id: str, group_type: UserGroupType) -> tuple[bool, str]:
        """
        检查LLM调用次数配额
        
        返回: (是否允许, 错误信息)
        """
        quota = self.get_user_quota(user_id, group_type)
        usage = self._get_or_create_usage(user_id)
        
        # 检查是否需要重置每日使用量
        usage.check_daily_reset()
        
        if usage.daily_llm_calls >= quota.max_llm_calls_per_day:
            return False, f"今日LLM调用次数已达上限（{quota.max_llm_calls_per_day}）"
        
        return True, ""
    
    def increment_agent_count(self, user_id: str, count: int = 1):
        """增加Agent数量（创建Agent后调用）"""
        usage = self._get_or_create_usage(user_id)
        usage.agent_count += count
        self._save_usage()
    
    def increment_llm_call(self, user_id: str, tokens: int = 0):
        """增加LLM调用次数和Token消耗（调用LLM后调用）"""
        usage = self._get_or_create_usage(user_id)
        usage.check_daily_reset()
        usage.daily_llm_calls += 1
        usage.daily_llm_tokens += tokens
        self._save_usage()
```

**配额检查流程示例**：

```
用户尝试创建Agent：

1. 获取用户的资源配额（通过用户组）
   quota = get_user_quota(user_id, group_type)
   
2. 获取用户的资源使用量
   usage = get_usage(user_id)
   
3. 检查配额
   if usage.agent_count >= quota.max_agents:
       return error("Agent数量已达上限")
       
4. 配额充足，允许创建
   create_agent(...)
   
5. 更新资源使用量
   increment_agent_count(user_id)
```

---

#### 5.3.9 用户管理API

> **核心概念**：提供完整的用户管理API，支持管理员操作和普通用户操作！

```python
# 用户管理 API
router = APIRouter(prefix="/settings/users", tags=["settings"])

@router.get("", summary="列出用户（仅管理员）")
async def list_users():
    """仅管理员可查看所有用户"""
    if not current_user or current_user.group_type != UserGroupType.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    
    users = user_model.list_users()
    return [{
        "user_id": u["id"],
        "username": u["username"],
        "group_type": u["group_type"],
        "status": u["status"],
        "created_at": u["created_at"],
    } for u in users]

@router.post("", summary="创建用户（仅管理员）")
async def create_user(user_data: UserCreate):
    """管理员创建用户"""
    if not current_user or current_user.group_type != UserGroupType.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    
    user = admin_service.create_user(
        username=user_data.username,
        email=user_data.email,
        password=user_data.password,
        group_type=UserGroupType(user_data.group_type),
    )
    
    return {"user_id": user["id"], "username": user["username"], "success": True}

@router.delete("/{user_id}", summary="删除用户（仅管理员）")
async def delete_user(user_id: int, backup_before_delete: bool = True):
    """管理员删除用户（含所有数据）"""
    if not current_user or current_user.group_type != UserGroupType.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    
    result = admin_service.delete_user(user_id, backup_before_delete)
    
    return {"success": True, "result": result}

@router.get("/quota", summary="获取用户配额状态")
async def get_quota_status():
    """获取当前用户的配额状态"""
    if not current_user:
        raise HTTPException(status_code=401, detail="未登录")
    
    quota_status = user_model.get_user_quota_status(current_user.id)
    
    return quota_status
```

---

#### 5.3.10 总结

**多用户管理系统的核心设计**：

1. **用户组（UserGroup）**：
   - 用户属于某个用户组
   - 每个用户组有不同的资源配额和权限集合
   - 预定义5种用户组：超级管理员、管理员、开发者、普通用户、访客

2. **资源配额（ResourceQuota）**：
   - 限制用户可使用的资源
   - 包括：Agent数量、项目数量、LLM调用次数、存储空间等
   - 在用户执行操作时检查配额

3. **权限管理（Permission）**：
   - 细粒度的权限控制
   - 每个用户组有不同的权限集合
   - 在执行操作前检查权限

4. **技能池隔离**：
   - 公共技能池：所有用户可访问
   - 专属技能池：用户隔离，不能进入其他用户的专属技能池
   - 技能可以共享给其他用户
   - 技能可以推送给自己的Agent

5. **协作模块隔离**：
   - 项目按用户隔离，用户只能看到自己参与的项目
   - 文件按项目隔离，只有项目成员可访问
   - 工作流按项目隔离

6. **管理员功能**：
   - 创建用户（指定用户组）
   - 备份用户资料（打包所有数据）
   - 删除用户（清理所有相关数据）
   - 更新用户资料（用户名、密码、用户组等）

7. **数据隔离**：
   - 每个用户有独立的工作空间
   - 用户数据物理隔离
   - 删除用户时清理所有数据

---

#### 用户管理 API

```python
# 用户管理 API
router = APIRouter(prefix="/settings/users", tags=["settings"])

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: UserRole = UserRole.USER

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None

class PasswordChange(BaseModel):
    old_password: str
    new_password: str

@router.get("", summary="列出用户（仅管理员）")
async def list_users():
    if not current_user or current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return [{"user_id": u.user_id, "username": u.username, "role": u.role, "status": u.status} for u in user_manager.list_users(current_user.user_id)]

@router.post("", summary="创建用户（仅管理员）")
async def create_user(user_data: UserCreate):
    if not current_user or current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    user = user_manager.create_user(user_data.username, user_data.email, user_data.password, user_data.role)
    return {"user_id": user.user_id, "username": user.username, "success": True}

@router.get("/profile", summary="获取当前用户信息")
async def get_profile():
    if not current_user:
        raise HTTPException(status_code=401, detail="未登录")
    return {
        "user_id": current_user.user_id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role,
        "language": current_user.language,
        "timezone": current_user.timezone,
        "created_at": current_user.created_at.isoformat()
    }

@router.put("/profile", summary="更新用户信息")
async def update_profile(update: UserUpdate):
    if not current_user:
        raise HTTPException(status_code=401, detail="未登录")
    
    if update.username:
        current_user.username = update.username
    if update.email:
        current_user.email = update.email
    if update.language:
        current_user.language = update.language
    if update.timezone:
        current_user.timezone = update.timezone
    
    user_manager.update_user(current_user)
    return {"success": True}

@router.post("/change-password", summary="修改密码")
async def change_password(password_data: PasswordChange):
    if not current_user:
        raise HTTPException(status_code=401, detail="未登录")
    
    success = user_manager.change_password(
        current_user.user_id, 
        password_data.old_password, 
        password_data.new_password
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="原密码错误")
    
    return {"success": True}

@router.delete("/{user_id}", summary="删除用户（仅管理员）")
async def delete_user(user_id: str):
    if not current_user or current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    if user_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    
    success = user_manager.delete_user(user_id)
    return {"success": success}
```

### 5.4 系统时间与时区管理

#### 时区服务设计

```python
from datetime import datetime, timezone, timedelta
import pytz
from typing import Dict, List, Optional
from pydantic import BaseModel

class TimezoneInfo(BaseModel):
    name: str
    display_name: str
    offset: str  # "+08:00"
    offset_minutes: int
    is_dst: bool

class TimezoneService:
    def __init__(self):
        self._common_timezones = [
            "UTC",
            "Asia/Shanghai",
            "Asia/Tokyo",
            "Asia/Seoul",
            "Asia/Dubai",
            "Europe/London",
            "Europe/Paris",
            "Europe/Berlin",
            "America/New_York",
            "America/Los_Angeles",
            "America/Sao_Paulo",
            "Australia/Sydney",
            "Pacific/Auckland",
            "Asia/Kolkata",
        ]
    
    def get_all_timezones(self) -> List[TimezoneInfo]:
        result = []
        for tz_name in pytz.all_timezones:
            tz = pytz.timezone(tz_name)
            now = datetime.now(tz)
            offset = now.utcoffset()
            offset_minutes = int(offset.total_seconds() / 60) if offset else 0
            is_dst = bool(now.dst())
            
            result.append(TimezoneInfo(
                name=tz_name,
                display_name=self._format_tz_display_name(tz_name, offset),
                offset=self._format_offset(offset),
                offset_minutes=offset_minutes,
                is_dst=is_dst
            ))
        return result
    
    def get_common_timezones(self) -> List[TimezoneInfo]:
        all_tzs = {t.name: t for t in self.get_all_timezones()}
        return [all_tzs[name] for name in self._common_timezones if name in all_tzs]
    
    def _format_offset(self, offset: Optional[timedelta]) -> str:
        if offset is None:
            return "±00:00"
        total_minutes = int(offset.total_seconds() / 60)
        hours = abs(total_minutes) // 60
        minutes = abs(total_minutes) % 60
        sign = "+" if total_minutes >= 0 else "-"
        return f"{sign}{hours:02d}:{minutes:02d}"
    
    def _format_tz_display_name(self, tz_name: str, offset: Optional[timedelta]) -> str:
        offset_str = self._format_offset(offset)
        return f"({offset_str}) {tz_name}"
    
    def get_user_local_time(self, user_timezone: str, utc_time: Optional[datetime] = None) -> datetime:
        """将 UTC 时间转换为用户的本地时间"""
        if utc_time is None:
            utc_time = datetime.utcnow()
        
        tz = pytz.timezone(user_timezone)
        return utc_time.replace(tzinfo=pytz.UTC).astimezone(tz)
    
    def get_current_utc_time(self) -> datetime:
        """获取当前 UTC 时间"""
        return datetime.utcnow().replace(tzinfo=pytz.UTC)
    
    def format_time_for_user(self, user_timezone: str, utc_time: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
        """格式化用户本地时间"""
        local_time = self.get_user_local_time(user_timezone, utc_time)
        return local_time.strftime(format_str)
```

#### 时区设置 API

```python
# 时区设置 API
router = APIRouter(prefix="/settings/timezone", tags=["settings"])

class TimezoneUpdate(BaseModel):
    timezone: str

@router.get("", summary="获取时区设置")
async def get_timezone_settings():
    return {
        "timezone": current_user.timezone if current_user else "UTC",
        "currentUtcTime": timezone_service.get_current_utc_time().isoformat(),
        "commonTimezones": timezone_service.get_common_timezones(),
        "allTimezonesCount": len(pytz.all_timezones)
    }

@router.get("/search", summary="搜索时区")
async def search_timezones(q: str = "", limit: int = 20):
    all_tzs = timezone_service.get_all_timezones()
    q_lower = q.lower()
    
    filtered = [
        tz for tz in all_tzs
        if q_lower in tz.name.lower() or q_lower in tz.display_name.lower()
    ]
    return {"timezones": filtered[:limit]}

@router.put("", summary="更新时区设置")
async def update_timezone(update: TimezoneUpdate):
    try:
        pytz.timezone(update.timezone)
    except pytz.exceptions.UnknownTimeZoneError:
        raise HTTPException(status_code=400, detail="无效的时区")
    
    if current_user:
        current_user.timezone = update.timezone
        user_manager.update_user(current_user)
    else:
        save_global_setting("timezone", update.timezone)
    
    now = timezone_service.get_current_utc_time()
    local_time = timezone_service.get_user_local_time(update.timezone, now)
    
    return {
        "timezone": update.timezone,
        "success": True,
        "currentLocalTime": local_time.isoformat()
    }

@router.get("/current", summary="获取当前时间信息")
async def get_current_time():
    user_tz = current_user.timezone if current_user else "UTC"
    utc_now = timezone_service.get_current_utc_time()
    local_now = timezone_service.get_user_local_time(user_tz, utc_now)
    
    return {
        "utc": utc_now.isoformat(),
        "local": local_now.isoformat(),
        "timezone": user_tz,
        "timestamp": utc_now.timestamp()
    }
```

### 5.5 系统设置综合 API

```python
# 系统设置 API
router = APIRouter(prefix="/settings", tags=["settings"])

class SystemSettings(BaseModel):
    language: str
    timezone: str
    theme: Optional[str] = "light"
    notifications: Optional[bool] = True

@router.get("", summary="获取系统设置")
async def get_system_settings():
    settings = {
        "language": "en",
        "timezone": "UTC",
        "theme": "light",
        "notifications": True
    }
    
    if current_user:
        settings["language"] = current_user.language
        settings["timezone"] = current_user.timezone
        
        if current_user.settings_file.exists():
            with open(current_user.settings_file) as f:
                user_settings = json.load(f)
                settings.update(user_settings)
    
    return settings

@router.put("", summary="更新系统设置")
async def update_settings(settings: SystemSettings):
    if current_user:
        current_user.language = settings.language
        current_user.timezone = settings.timezone
        
        user_settings = {
            "language": settings.language,
            "timezone": settings.timezone,
            "theme": settings.theme,
            "notifications": settings.notifications
        }
        
        with open(current_user.settings_file, 'w') as f:
            json.dump(user_settings, f, indent=2)
        
        user_manager.update_user(current_user)
    
    return {"success": True, "settings": settings}
```

---

## 六、核心模块详细设计

### 3.1 认知核（大脑皮层）

#### Cognition Orchestrator（认知编排器）

```python
class CognitiveState(Enum):
    OBSERVING = "observing"         # 观察状态 - 收集信息
    REASONING = "reasoning"         # 推理状态 - 分析问题
    RECALLING = "recalling"         # 回忆状态 - 从记忆中检索
    REFLECTING = "reflecting"       # 反思状态 - 自我反省
    ACTING = "acting"               # 行动状态 - 执行任务
    LEARNING = "learning"           # 学习状态 - 从经验中学习

class CognitionOrchestrator:
    """
    认知编排器 - 协调所有认知模块，模拟真正的思维流程
    """
    
    async def process_thought_cycle(self, input_context: Dict) -> CognitiveCycleResult:
        """执行完整的思维周期"""
        # 1. 观察与感知
        observation = await self._observe(input_context)
        
        # 2. 记忆检索（时序知识图谱 + 工作记忆 + EKI）
        recalled_memories = await self._recall(observation)
        
        # 3. 推理与决策
        decision = await self._reason(observation, recalled_memories)
        
        # 4. 发送给小脑（执行编排器）
        execution_result = await self._send_to_cerebellum(decision)
        
        # 5. 反思与学习
        reflection = await self._reflect(
            observation, recalled_memories, decision, execution_result
        )
        
        # 6. 记忆巩固
        await self._consolidate(reflection)
        
        return CognitiveCycleResult(...)
```

#### Memory Layer（记忆层 - 三层架构）

```
记忆层
├── 工作记忆 (Working Memory) - 短期高激活
│   ├── 单轮压缩
│   ├── 多轮状态折叠
│   └── 计划缓存
├── 情景记忆 (Episodic Memory) - 中期有上下文
│   ├── 时序知识图谱
│   └── 对话历史
└── 语义记忆 (Semantic Memory) - 长期固化
    ├── 知识与事实
    ├── 核心指令
    ├── 自我模型
    └── 用户画像
```

---

### 3.2 计划与任务编排器（小脑 - 核心亮点！）

**类比：小脑负责运动协调、精准度、平衡控制**

```python
class TaskComplexity(Enum):
    SIMPLE = "simple"           # 单步，直接执行
    COMPOUND = "compound"       # 多步，有顺序
    PARALLEL = "parallel"       # 可并行执行
    DAG = "dag"                 # 有向无环图（复杂依赖）
    ITERATIVE = "iterative"     # 需要循环迭代

class TaskNode:
    """任务节点"""
    id: str
    description: str
    tool: Optional[str] = None
    agent: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout: int = 300

class PlanOrchestrator:
    """
    计划与任务编排器 - 小脑
    
    核心功能：
    - 把认知决策转化为可执行的计划
    - 任务分解与协调
    - 执行过程中的动态调整
    """
    
    async def decompose_intent(self, intent: str, context: Dict) -> Plan:
        """
        意图分解 - 小脑的核心功能
        """
        # 1. 分析复杂度
        complexity = await self._analyze_complexity(intent)
        
        # 2. 生成任务图
        if complexity == TaskComplexity.SIMPLE:
            return await self._create_simple_plan(intent)
        elif complexity == TaskComplexity.COMPOUND:
            return await self._create_sequential_plan(intent)
        elif complexity == TaskComplexity.DAG:
            return await self._create_dag_plan(intent)
        
    async def execute_plan(self, plan: Plan) -> PlanResult:
        """执行计划"""
        # 拓扑排序 → 并行执行无依赖节点 → 处理失败 → 返回结果
        
    async def adjust_plan(self, plan: Plan, feedback: ExecutionFeedback) -> Plan:
        """
        动态调整计划 - 小脑的平衡功能
        """
```

---

### 3.3 执行引擎（手脚）

#### Tool Engine（工具引擎）

```python
class ToolEngine:
    """
    智能工具引擎
    """
    
    async def select_tools(self, context: ToolCallingContext) -> List[ToolSelection]:
        """智能工具选择"""
        
    async def prepare_arguments(self, tool: ToolDef, context: Dict) -> Dict:
        """自动参数填充 - 结合记忆"""
        
    async def execute_with_safeguards(self, tool: ToolDef, args: Dict) -> Any:
        """安全执行 - ToolGuard"""
        
    async def chain_tools(self, tool_calls: List[ToolCall]) -> Any:
        """工具链"""
```

#### Multi-Agent Collaboration Engine

```python
class CollaborationStrategy(Enum):
    HIERARCHICAL = "hierarchical"  # 主从模式
    CONSENSUS = "consensus"        # 共识模式
    DELEGATION = "delegation"      # 委托模式
    PARALLEL_EXPERTS = "parallel"  # 并行专家

class AgentColabEngine:
    """多 Agent 协作引擎"""
    
    async def form_team(self, task: str) -> List[Role]:
        """组建团队"""
        
    async def coordinate_team(self, team: List[Agent], strategy: CollaborationStrategy):
        """协调协作"""
```

#### Workflow Engine

```python
class WorkflowState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    ROLLED_BACK = "rolled_back"

class WorkflowEngine:
    """状态机驱动的工作流引擎"""
    
    async def run(self, workflow: Workflow, input_data: Dict) -> WorkflowResult:
        """运行"""
        
    async def resume(self, workflow_id: str, event_data: Dict):
        """从等待中恢复"""
        
    async def rollback(self, workflow_id: str, to_step: Optional[str] = None):
        """回滚"""
```

#### Execution Monitor

```python
class ExecutionMonitor:
    """执行监控器"""
    
    def get_execution_trace(self, execution_id: str) -> ExecutionTrace:
        """获取完整执行链路追踪 - 用于调试、学习、回放"""
```

---

## 六、完整闭环示例

```
用户请求："帮我做一个 AI 项目的市场分析报告"
    │
    ▼
【认知核 - 大脑皮层】
    - 观察：理解需求 → 市场分析 + 报告
    - 回忆：之前做过的类似项目
    - 推理：这是一个复杂任务，需要分解
    │
    ▼
【计划与任务编排器 - 小脑】
    - 分析复杂度：DAG
    - 生成任务图：
      ① 搜索最新市场数据（工具）
      ② 分析竞争对手（Agent 协作）
      ③ 生成报告大纲（并行）
      ④ 编写完整报告（Workflow）
    - 拓扑排序，准备执行
    │
    ▼
【执行引擎 - 手脚】
    - ① 调用搜索工具 → 成功
    - ② Agent 协作：数据分析师 + 竞争情报专家
    - ③ 并行生成大纲
    - ④ 工作流：章节 1→2→3→4
    - 执行监控全程跟踪
    │
    ▼
【反馈学习环】
    - 结果验证
    - 提取经验："市场分析通常需要这 5 个步骤"
    - 技能进化：自动生成"市场分析"技能
    - 记忆巩固：存入时序知识图谱
    - 认知调整：下次更高效
```

---

## 七、Neurova 架构标准

### NCS - Neurova Cognitive Standard（认知标准）
- 认知可观察：完整的认知流回放
- 记忆接口：所有模块支持记忆片段读写
- EKI 兼容：所有参数支持贝叶斯优化

### NES - Neurova Execution Standard（执行标准 - 新增）
1. **任务可分解标准**
   - 任何任务都必须可分解为 `TaskNode`
   - 支持复杂度自动识别
2. **可观测执行标准**
   - 完整的执行追踪（Execution Trace）
   - 所有工具调用可审计
3. **容错与恢复标准**
   - 每个任务必须有重试策略
   - 支持部分回滚

---

## 八、目录结构设计

```
neurova/
├── core/
│   ├── cognitive_orchestrator.py    # 认知编排器
│   ├── plan_orchestrator.py         # 计划编排器（小脑）
│   ├── cognitive_stream.py
│   └── ...
│
├── cognitive_layers/
│   ├── memory_layer/
│   ├── meta_cognition_layer/
│   └── emotion_context_layer/
│
├── execution_engine/            # 新增：执行引擎
│   ├── tool_engine.py
│   ├── agent_colab.py
│   ├── workflow_engine.py
│   └── execution_monitor.py
│
├── capabilities/
├── api/
├── storage/
└── utils/
```

---

## 九、与 QwenPaw 的本质区别

| 维度 | QwenPaw | Neurova CogArch 2.0 |
|-----|---------|---------------------|
| 核心理念 | Workspace + Service Manager | 大脑 + 小脑 + 手脚 |
| 设计焦点 | 工程化 | 认知增强 + 强执行力 |
| 流程 | 服务调用 → 执行 | 思维周期 → 小脑协调 → 强力执行 → 学习 |
| 记忆 | 简单存储 | 三层记忆 + EKI 优化 |
| 元认知 | 无 | 一等公民 |
| 执行协调 | Service 依赖 | 小脑（专门的编排器） |

---

## 十、现有 Neurova 模块到 CogArch 2.0 的完整映射

### 8.1 整体映射图

```
CogArch 2.0 架构          现有 Neurova 模块
─────────────────────────────────────────────────────────
【认知核 - 大脑皮层】
├─ 认知编排器            ➔ 待实现（协调所有现有模块）
├─ 记忆层（海马体）
│  ├─ 工作记忆           ➔ [working_memory.py]
│  ├─ 情景记忆           ➔ [temporal_knowledge_graph.py]
│  ├─ 语义记忆           ➔ [storage.py, models.py]
│  └─ 睡眠巩固           ➔ [sleep.py] (后台整理记忆、生成梦境报告)
├─ 元认知层（前额叶）
│  ├─ 自我反思           ➔ [self_reflection.py]
│  ├─ 自我优化           ➔ [self_optimization.py]
│  ├─ 技能进化           ➔ [skills_manager.py] (技能沉淀、自动修补、进化)
│  └─ 元认知             ➔ [meta_cognition.py]
└─ 情感与情境层
   ├─ 情感分析           ➔ [emotion.py]
   └─ 情境感知           ➔ [time_awareness.py, context_injector.py]

【计划编排器 - 小脑】     ➔ 待实现（协调现有模块执行）

【执行引擎 - 手脚】
├─ 工具引擎              ➔ 待实现
├─ 多 Agent 协作         ➔ [multi_agent_manager.py], [projects/team_manager.py]
├─ 工作流引擎            ➔ [projects/workflow_engine.py] (雏形)
└─ 执行监控器            ➔ 待实现

【功能壳 / 能力层】
├─ 项目协作              ➔ [projects/project_manager.py], [projects/task_board.py]
├─ 文件流                ➔ [projects/file_flow.py]
├─ 渠道连接              ➔ [channels/*] (discord.py, qq.py, feishu.py 等)
├─ 媒介管理              ➔ [media/manager.py]
├─ 模型生成              ➔ [llm/generators/*] (text_to_image 等)
└─ 安全防护              ➔ [memory/core/security.py]

【基础设施层】
├─ 存储抽象              ➔ [memory/core/storage.py]
├─ 向量搜索              ➔ [memory/core/vector_search.py]
├─ 缓存系统              ➔ [memory/core/cache.py]
├─ 事件总线              ➔ [core/event_bus.py]
├─ 配置管理              ➔ [core/config_manager.py]
├─ 工作空间              ➔ [core/workspace.py], [core/multi_agent_manager.py]
├─ 服务管理              ➔ [core/service_manager.py]
└─ 日志系统              ➔ [core/logger.py]
```

---

### 8.2 详细映射表

| CogArch 2.0 位置 | 现有文件路径 | 模块名 | 状态 | 说明 |
|----------------|------------|-------|------|------|
| **认知核** | | | | |
| (待实现) | | Cognition Orchestrator | ❌ 待实现 | 协调所有模块的核心 |
| **记忆层 - 工作记忆** | neurova/memory/core/working_memory.py | WorkingMemoryAugmenter | ✅ 已实现 | 单轮压缩 + 多轮折叠 + 计划缓存 |
| **记忆层 - 情景记忆** | neurova/memory/core/temporal_knowledge_graph.py | TemporalKnowledgeGraph | ✅ 已实现 | 时序知识图谱 |
| **记忆层 - 语义记忆** | neurova/memory/core/storage.py | MemoryStorage | ✅ 已实现 | 存储引擎 |
| | neurova/memory/core/models.py | Models | ✅ 已实现 | SelfModel, UserProfile, Memory 等 |
| | neurova/memory/core/temperature.py | TemperatureEngine | ✅ 已实现 | 记忆温度系统（艾宾浩斯遗忘曲线）|
| | neurova/memory/core/bayesian_eki/ | EKICognitiveOptimizer | ✅ 已实现 | 贝叶斯认知优化器（Neurova 核心亮点！）|
| | neurova/memory/core/sleep.py | SleepConsolidation | ✅ 已实现 | 睡眠巩固 |
| | neurova/memory/core/compression.py | MemoryCompressor | ✅ 已实现 | 记忆压缩 |
| | neurova/memory/core/vector_search.py | VectorSearch | ✅ 已实现 | 向量搜索 |
| **元认知层** | neurova/memory/core/meta_cognition.py | MetaCognition | ✅ 已实现 | 元认知系统 |
| | neurova/memory/core/self_reflection.py | SelfReflection | ✅ 已实现 | 自我反思 |
| | neurova/memory/core/self_optimization.py | SelfOptimization | ✅ 已实现 | 自我优化 |
| | neurova/memory/core/skills_manager.py | SkillsManager | ✅ 已实现 | **技能自动生成 + 进化 + 修补**（可完善为执行层的 SkillEngine）|
| **认知核 - 睡眠巩固** | neurova/memory/core/sleep.py | SleepConsolidation | ✅ 已实现 | **记忆整理 + 梦境报告**（记忆层的后台巩固系统）|
| **情感与情境层** | neurova/memory/core/emotion.py | EmotionAnalyzer | ✅ 已实现 | 情感分析 |
| | neurova/memory/core/time_awareness.py | TimeAwareness | ✅ 已实现 | 时间感知 |
| | neurova/memory/core/context_injector.py | ContextInjector | ✅ 已实现 | 上下文注入 |
| **记忆增强模块** | neurova/memory/core/proactive_recall.py | ProactiveRecall | ✅ 已实现 | 主动回忆 |
| | neurova/memory/core/proactive_question.py | ProactiveQuestion | ✅ 已实现 | 主动提问 + 好奇心驱动 |
| | neurova/memory/core/auto_classifier.py | MemoryAutoClassifier | ✅ 已实现 | 自动分类 |
| | neurova/memory/core/agent_self.py | AgentSelfManager | ✅ 已实现 | 自我管理（核心指令 + 心跳任务）|
| **计划编排器（小脑）** | | PlanOrchestrator | ❌ 待实现 | 任务分解 + 协调执行 |
| **执行引擎** | | ToolEngine | ❌ 待实现 | 智能工具调用 |
| | | ExecutionMonitor | ❌ 待实现 | 执行追踪 + 监控 |
| | neurova/core/multi_agent_manager.py | MultiAgentManager | ✅ 雏形 | 多 Agent 协作 |
| | neurova/projects/workflow_engine.py | WorkflowEngine | ⚠️ 雏形 | 工作流引擎（需要增强）|
| **功能壳 / 项目协作** | neurova/projects/project_manager.py | ProjectManager | ✅ 已实现 | 项目管理 |
| | neurova/projects/task_board.py | TaskBoard | ✅ 已实现 | 任务看板 |
| | neurova/projects/team_manager.py | TeamManager | ✅ 已实现 | 团队管理 |
| | neurova/projects/file_flow.py | FileFlow | ✅ 已实现 | 文件流 |
| **功能壳 / 渠道连接** | neurova/channels/manager.py | ChannelManager | ✅ 已实现 | 渠道管理 |
| | neurova/channels/discord.py | DiscordChannel | ✅ 已实现 | Discord |
| | neurova/channels/qq.py | QQChannel | ✅ 已实现 | QQ |
| | neurova/channels/feishu.py | FeishuChannel | ✅ 已实现 | 飞书 |
| | neurova/channels/telegram.py | TelegramChannel | ✅ 已实现 | Telegram |
| | ... | ... | ... | ... |
| **功能壳 / 媒介管理** | neurova/media/manager.py | MediaManager | ✅ 已实现 | 媒介管理 |
| **功能壳 / 模型生成** | neurova/llm/generators/ | *Generator | ✅ 已实现 | text_to_image, video_to_video 等 |
| **接口层 - 消息路由** | neurova/router.py | MessageRouter | ✅ 已实现 | 消息类型识别、路由到正确的处理模块 |
| **基础设施 - LLM 配置** | neurova/llm/provider_manager.py | LLMProviderManager | ✅ 已实现 | 统一管理多个 API Key 和服务商配置 |
| **基础设施 - 预设管理** | neurova/llm/presets.py | LLMPresetRegistry | ✅ 已实现 | 模型预设配置管理 |
| **接口层 - CLI** | neurova/cli.py | NeurovaCLI | ✅ 已实现 | 命令行交互界面（chat, recall, skills等）|
| **接口层 - Console/Shell** | (借鉴QwenPaw) | ConsoleChannel | ✅ 可借鉴 | Web控制台接口（streaming, upload等）|
| **接口层 - API 路由** | neurova/core/api_router.py | ApiRouter | ✅ 已实现 | API 路由管理 |
| **接口层 - API 标准** | neurova/core/api_standard.py | ApiStandard | ✅ 已实现 | API 标准定义 |
| **功能壳 / 渠道连接** | neurova/channels/manager.py | ChannelManager | ✅ 已实现 | 渠道管理 |
| | neurova/channels/discord.py | DiscordChannel | ✅ 已实现 | Discord |
| | neurova/channels/qq.py | QQChannel | ✅ 已实现 | QQ |
| | neurova/channels/feishu.py | FeishuChannel | ✅ 已实现 | 飞书 |
| | neurova/channels/telegram.py | TelegramChannel | ✅ 已实现 | Telegram |
| | ... | ... | ... | ... |
| **认知核 - 自治系统** | neurova/agent/autonomy_system.py | AutonomySystem | ✅ 已实现 | 自治系统（自主行为）|
| **认知核 - 人格** | neurova/agent/personality.py | Personality | ✅ 已实现 | 人格设定 |
| **认知核 - 宪法/基本指令** | neurova/agent/constitution.py | Constitution | ✅ 已实现 | 基本指令（核心原则）|
| **认知核 - 内在动机** | neurova/core/intrinsic_motivation.py | IntrinsicMotivation | ✅ 已实现 | 内在动机驱动 |
| **认知核 - 闲置追踪** | neurova/core/idle_tracker.py | IdleTracker | ✅ 已实现 | 闲置状态追踪 |
| **元认知层 - 成长日志** | neurova/memory/core/growth_log.py | GrowthLog | ✅ 已实现 | 成长日志（学习记录）|
| **元认知层 - 问题队列** | neurova/memory/core/question_queue.py | QuestionQueue | ✅ 已实现 | 问题队列（待解决问题）|
| **记忆层 - 对话缓冲区** | neurova/memory/core/conversation_buffer.py | ConversationBuffer | ✅ 已实现 | 对话缓冲区 |
| **记忆层 - 记忆流** | neurova/memory/core/memory_stream.py | MemoryStream | ✅ 已实现 | 记忆流 |
| **记忆层 - 冲突检测** | neurova/memory/core/conflict.py | ConflictDetector | ✅ 已实现 | 记忆冲突检测 |
| **记忆层 - 版本控制** | neurova/memory/core/version_control.py | VersionControl | ✅ 已实现 | 记忆版本控制 |
| **记忆层 - 缓存** | neurova/memory/core/cache.py | MemoryCache | ✅ 已实现 | 记忆缓存 |
| **记忆层 - 安全** | neurova/memory/core/security.py | MemorySecurity | ✅ 已实现 | 记忆安全（防护）|
| **功能壳 - 附件管理** | neurova/core/attachment_manager.py | AttachmentManager | ✅ 已实现 | 附件管理 |
| | neurova/memory/core/attachment_manager.py | AttachmentManager (Memory) | ✅ 已实现 | 记忆中的附件管理 |
| **基础设施 - 插件系统** | neurova/plugins/plugin_manager.py | PluginManager | ✅ 已实现 | 插件管理 |
| | neurova/plugins/base_plugin.py | BasePlugin | ✅ 已实现 | 插件基类 |
| | neurova/plugins/plugin_lifecycle.py | PluginLifecycle | ✅ 已实现 | 插件生命周期管理 |
| | neurova/plugins/plugin_manifest.py | PluginManifest | ✅ 已实现 | 插件清单 |
| | neurova/plugins/plugin_api_registry.py | PluginApiRegistry | ✅ 已实现 | 插件 API 注册 |
| **基础设施 - 模块库** | neurova/core/module_lib.py | ModuleLib | ✅ 已实现 | 模块库管理 |
| **基础设施 - 模块追踪** | neurova/core/module_tracker.py | ModuleTracker | ✅ 已实现 | 模块追踪 |
| **基础设施 - 基础模块** | neurova/core/base_module.py | BaseModule | ✅ 已实现 | 基础模块类 |
| **基础设施 - 状态管理** | neurova/core/state_manager.py | StateManager | ✅ 已实现 | 状态管理 |
| **基础设施 - 错误处理** | neurova/core/error_handler.py | ErrorHandler | ✅ 已实现 | 错误处理 |
| **基础设施 - 睡眠配置** | neurova/core/sleep_config_manager.py | SleepConfigManager | ✅ 已实现 | 睡眠配置管理 |
| **基础设施 - 睡眠阶段配置** | neurova/core/sleep_phase_config_manager.py | SleepPhaseConfigManager | ✅ 已实现 | 睡眠阶段配置管理 |
| **基础设施 - 多代理睡眠** | neurova/core/multi_agent_sleep_manager.py | MultiAgentSleepManager | ✅ 已实现 | 多代理睡眠管理 |
| **基础设施** | neurova/core/service_manager.py | ServiceManager | ✅ 已实现 | 服务管理（借鉴 QwenPaw）|
| | neurova/core/workspace.py | Workspace | ✅ 已实现 | 工作空间（借鉴 QwenPaw）|
| | neurova/core/event_bus.py | EventBus | ✅ 已实现 | 事件总线 |
| | neurova/core/config_manager.py | ConfigManager | ✅ 已实现 | 配置管理 |
| | neurova/core/logger.py | Logger | ✅ 已实现 | 日志系统 |

---

### 8.3 Neurova 现有模块分析 - 优势与缺失

#### ✅ 已有的核心优势（强于 QwenPaw）
1. **认知系统** - 完整的元认知、自我反思、自我优化
2. **记忆系统** - EKI 贝叶斯优化 + 时序知识图谱 + 工作记忆增强 + 温度系统
3. **项目协作** - 完整的项目管理 + 任务看板 + 团队管理 + 文件流
4. **情感与好奇** - 情感分析 + 主动提问 + 好奇心驱动
5. **技能进化** - 技能自动生成 + 修补 + 进化

#### ❌ 缺失的关键执行层模块（小脑 + 手脚）
1. **PlanOrchestrator** - 任务分解与编排（小脑核心）
2. **ToolEngine** - 智能工具调用、参数填充、工具链
3. **ExecutionMonitor** - 完整的执行追踪、监控、超时处理
4. **增强的 WorkflowEngine** - 状态机、暂停/恢复、回滚
5. **安全系统** - ToolGuard 类似的防护机制（QwenPaw 有）

#### ⚠️ 已有但需要整合的模块
1. **MultiAgentManager** - 已有雏形，需要整合到执行引擎中
2. **WorkflowEngine** - 项目里有雏形，需要增强

---

### 8.4 核心系统详解

#### 8.4.1 Skill 系统 - 位置与发展方向

**当前位置**：`neurova/memory/core/skills_manager.py` → **元认知层（技能进化）**

**现有功能**：
- ✅ 技能自动生成（从任务中沉淀）
- ✅ 技能匹配（关键词/模式/分类）
- ✅ 技能自动修补
- ✅ 技能压缩（清理过时技能）

**未来发展方向**：
1. **保留在元认知层** - SkillsManager 继续负责技能的进化、学习、沉淀
2. **新增 SkillEngine（在执行引擎）** - 专门负责技能的执行、调用、组合
   - SkillEngine = 负责"用技能"
   - SkillsManager = 负责"学技能、进化技能"

```
技能系统完整架构：
├─ SkillsManager (元认知层)   → 学习、沉淀、进化、修补
└─ SkillEngine (执行层)        → 执行、组合、调用技能
```

---

#### 8.4.2 Sleep 睡眠系统 - 位置与功能

**当前位置**：`neurova/memory/core/sleep.py` → **记忆层的后台巩固系统**

**现有功能**：
- ✅ 合并相似记忆
- ✅ 归档低温记忆
- ✅ 生成梦境报告
- ✅ 阶段特定整理（浅睡期/REM期/深睡期/休眠期）
- ✅ 持久化梦境报告到数据库

**生物学类比**：
- **记忆编码**（清醒时） → 海马体
- **记忆巩固**（睡眠时） → 海马体 → 大脑皮层（长期记忆）
- **梦境** = 记忆回放与重组

**在 CogArch 2.0 中的角色**：
- 后台记忆整理引擎
- 通过心跳任务（AgentSelfManager）定时触发
- 作为记忆层的"清洁工" + "整理师"

---

### 8.5 MCP & ACP - 标准协议集成

这两个是 QwenPaw 中非常有价值的标准协议，完全可以借鉴到 Neurova 中！

---

#### 8.5.1 MCP (Model Context Protocol)

**MCP 是什么**：
- 标准化的工具连接协议
- 支持 Stdio（本地子进程）和 HTTP（远程）两种传输方式
- 支持热重载
- 统一的工具调用接口

**QwenPaw 中的实现**：
- `MCPClientManager` - 管理 MCP 客户端生命周期
- `HttpStatefulClient` / `StdIOStatefulClient` - 两种传输方式
- 支持配置驱动，热更新

**在 CogArch 2.0 中的位置**：**执行引擎 - 工具层**

```
MCP 架构映射：
┌─────────────────────────────────────────────────────────┐
│  ToolEngine (工具引擎)                                │
│  ┌───────────────────────────────────────────────────┐  │
│  │ MCPClientManager (MCP 客户端管理器)            │  │
│  │  ├─ StdIOStatefulClient (本地工具)            │  │
│  │  └─ HttpStatefulClient (远程工具)             │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Neurova 可以借鉴的点**：
1. **配置驱动** - 从配置文件加载 MCP 工具
2. **热重载** - 更新配置无需重启
3. **统一工具接口** - 无论是本地还是远程，都用相同的方式调用
4. **工具发现** - 自动获取可用的工具和资源

---

#### 8.5.2 ACP (Agent Control Protocol)

**ACP 是什么**：
- 标准化的 Agent 控制协议
- 支持会话管理（新建/加载/恢复/关闭）
- 支持流式输出（delta 增量更新）
- 支持工具调用和思考过程可视化
- 支持模型切换
- 支持配置管理

**QwenPaw 中的实现**：
- `QwenPawACPAgent` - ACP 协议实现
- 完整的 Workspace 集成
- 流式输出转换（从 snapshot 到 delta）

**在 CogArch 2.0 中的位置**：**接口层 - API/协议适配层**

```
ACP 架构映射：
┌─────────────────────────────────────────────────────────┐
│  Interface Layer (接口层)                           │
│  ┌───────────────────────────────────────────────────┐  │
│  │  REST API          ACP Server (ACP 服务)      │  │
│  │  WebSocket          └─ 会话管理               │  │
│  │  Channels           └─ 流式输出               │  │
│  │  MCP                └─ 工具调用               │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Neurova 可以借鉴的点**：
1. **标准化协议** - 支持第三方客户端（如 Zed、OpenCode 等）连接
2. **会话管理** - 完整的会话生命周期
3. **流式输出** - 思考过程和工具调用的可视化
4. **模型切换** - 运行时切换模型
5. **配置选项** - 动态配置会话参数

---

#### 8.5.3 完整的协议栈

```
Neurova CogArch 2.0 完整协议栈：

┌─────────────────────────────────────────────────────────┐
│  ACP (Agent Control Protocol) - 外部接口         │
│  - 会话管理                                      │
│  - 流式输出                                      │
│  - 工具调用                                      │
│  - 模型切换                                      │
└─────────────────────────────────────────────────────────┘
                      ↕
┌─────────────────────────────────────────────────────────┐
│  Cognition Orchestrator (认知编排器) - 内部     │
└─────────────────────────────────────────────────────────┘
                      ↕
┌─────────────────────────────────────────────────────────┐
│  Plan Orchestrator (小脑) - 任务分解与执行       │
└─────────────────────────────────────────────────────────┘
                      ↕
┌─────────────────────────────────────────────────────────┐
│  MCP (Model Context Protocol) - 工具层          │
│  - 本地工具 (Stdio)                            │
│  - 远程工具 (HTTP)                             │
└─────────────────────────────────────────────────────────┘
```

---

### 8.6 CLI & Console/Shell - 命令行与 Web 界面接口

这两个是与用户直接交互的接口层，Neurova 已有 CLI，QwenPaw 有完善的 Web Console，我们可以借鉴结合！

---

#### 8.6.1 CLI (命令行接口)

**当前位置**：`neurova/cli.py` → **接口层 - CLI**

**现有功能**：
- ✅ `chat <消息>` - 与忆灵对话
- ✅ `recall <关键词>` - 检索记忆
- ✅ `remember <内容>` - 添加记忆
- ✅ `memories` - 列出记忆（支持温度排序、分类筛选）
- ✅ `skills` - 列出所有技能
- ✅ `exec <技能名>` - 执行技能
- ✅ `stats` - 显示系统统计
- ✅ `config` - 显示配置
- ✅ `decay` - 执行温度衰减
- ✅ `crystallize` - 固化记忆
- ✅ 优雅的 ASCII 界面设计

**在 CogArch 2.0 中的位置**：
```
接口层：
┌─────────────────────────────────────────────────────────┐
│  CLI (命令行) - 本地交互                             │
│  ├─ Chat & Memory commands                           │
│  ├─ Skill execution & management                     │
│  └─ System config & monitoring                       │
└─────────────────────────────────────────────────────────┘
         ↕ connects to Workspace & Cognition Orchestrator
```

**未来发展方向**：
1. **增强 CLI 功能**
   - 支持流式输出（QwenPaw 那样）
   - 支持文件上传（类似 QwenPaw 的 console/upload）
   - 支持会话管理（切换会话、加载历史会话）

2. **与 CogArch 集成**
   - CLI 作为一个标准接口层，连接到 Workspace
   - 直接调用 Cognition Orchestrator，而不是旧的 Agent 类

---

#### 8.6.2 Console/Shell (Web 控制台)

**借鉴来源**：QwenPaw 的 `console.py` → **接口层 - Web Console**

**QwenPaw 中的功能**：
- ✅ `/console/chat` - 聊天接口（streaming response）
- ✅ `/console/chat/stop` - 停止运行中的对话
- ✅ `/console/upload` - 文件上传
- ✅ `/console/debug/backend-logs` - 调试日志查看
- ✅ `/console/push-messages` - 推送消息和审批请求
- ✅ 会话管理（session_id 支持）
- ✅ 自动标题生成（后台任务）
- ✅ 支持重连（reconnect=true）

**在 CogArch 2.0 中的位置**：
```
接口层：
┌─────────────────────────────────────────────────────────┐
│  Web Console (Web 控制台) - 浏览器交互            │
│  ├─ Streaming Chat API                                │
│  ├─ File Upload API                                  │
│  ├─ Session Management API                           │
│  ├─ Debug & Logs API                                 │
│  └─ Approval & Push Messages API                     │
└─────────────────────────────────────────────────────────┘
         ↕ connects to Workspace & Execution Engine
```

**Neurova 可以借鉴的点**：
1. **流式响应 (SSE)** - Server-Sent Events，实时展示 Agent 思考和工具调用
2. **任务追踪器 (TaskTracker)** - 支持停止、重连、状态追踪
3. **推送消息系统** - 用于异步事件和用户通知
4. **审批系统** - 用于需要用户确认的敏感操作（类似 QwenPaw 的 ToolGuard）
5. **文件上传与处理** - 完善的文件管理机制
6. **调试界面** - 查看后端日志和系统状态

---

#### 8.6.3 完整的接口层架构

```
Neurova CogArch 2.0 接口层架构：

┌─────────────────────────────────────────────────────────────────┐
│                         接口层                                │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    │
│  │  CLI         │    │  Web Console │    │  ACP Server  │    │
│  │  (本地终端)  │    │  (浏览器)    │    │  (第三方)    │    │
│  └──────────────┘    └──────────────┘    └──────────────┘    │
│         │                    │                    │             │
│         └────────────────────┼────────────────────┘             │
│                              ↕                                  │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  REST API & WebSocket Gateway (统一入口)              │  │
│  │  - Session routing                                     │  │
│  │  - Protocol transformation (ACP ↔ Internal)           │  │
│  │  - Streaming endpoint management                      │  │
│  └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│  Workspace & Cognition Orchestrator (内部核心)                │
└─────────────────────────────────────────────────────────────────┘
```

---

### 8.7 LLM 配置、消息路由、渠道模块 - 接口与基础设施详解

这几个模块是 Neurova 系统的"连接层"，负责连接用户与内部核心！

---

#### 8.7.1 LLM 大模型配置管理（ProviderManager）

**当前位置**：`neurova/llm/provider_manager.py` → **基础设施层**

**现有功能**：
- ✅ `ProviderConfig` - 服务商配置（API Key、Base URL、默认模型等）
- ✅ `LLMProviderManager` - 统一管理多个 API Key 和服务商配置
- ✅ 配置持久化存储（JSON 文件）
- ✅ 服务商选择和模型切换能力
- ✅ 支持自定义服务商添加
- ✅ 集成 `LLMPresetRegistry`（预设管理）

**在 CogArch 2.0 中的作用**：
- 为执行引擎和认知核提供 LLM 调用能力
- 支持认知核选择最优模型（结合 EKI 优化）
- 为 ACP Server 提供模型切换功能

**未来发展方向**：
- 与 EKI 优化器集成，自动选择最优模型和参数
- 支持调用成本统计和优化建议

---

#### 8.7.2 消息路由模块（MessageRouter）

**当前位置**：`neurova/router.py` → **接口层 - 消息路由**

**现有功能**：
- ✅ `MessageType` - 消息类型枚举（CHAT、COMMAND、SKILL_REQUEST、IMAGE、VIDEO 等）
- ✅ `Message` - 消息对象（内容、类型、发送者、元数据）
- ✅ `MessageRouter` - 消息路由器
  - 识别消息类型
  - 路由到正确的处理器（Skill/记忆/对话处理器）
  - 支持自定义路由规则
  - 提供回退机制

**在 CogArch 2.0 中的位置**：
```
接口层：
┌─────────────────────────────────────────────────────────┐
│  MessageRouter (消息路由器)                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │  接收消息 → 类型识别 → 路由决策 → 分发执行    │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
    ↓              ↓              ↓            ↓
  Skill        记忆系统        对话处理      生成请求
  执行         操作           (Agent)       (图像/视频)
```

**未来发展方向**：
- 与 PlanOrchestrator 集成，智能路由复杂任务
- 支持基于意图的路由（不仅仅是类型）
- 路由决策可学习优化

---

#### 8.7.3 消息渠道模块（Channels）

**当前位置**：`neurova/channels/*` → **功能壳 / 渠道连接**

**现有功能**：
- ✅ `ChannelManager` - 统一渠道管理
- ✅ 多种渠道实现：
  - DiscordChannel、QQChannel、FeishuChannel、TelegramChannel
  - WechatChannel、DingtalkChannel、MqttChannel、WebSocketChannel
  - APIChannel（Webhook）
- ✅ 媒介支持（图片、语音、视频、文档）
- ✅ 会话管理和消息分发

**在 CogArch 2.0 中的位置**：
```
接口层（Channels）：
┌─────────────────────────────────────────────────────────┐
│  ChannelManager (渠道管理器)                          │
│  ┌──────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Discord  │ │ QQ      │ │ Feishu   │ │ Telegram │  │
│  │ Channel  │ │ Channel │ │ Channel  │ │ Channel  │  │
│  └──────────┘ └─────────┘ └──────────┘ └──────────┘  │
│  ┌──────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Wechat   │ │ Dingtalk│ │ WebSocket│ │  API     │  │
│  └──────────┘ └─────────┘ └──────────┘ └──────────┘  │
└─────────────────────────────────────────────────────────┘
         ↓ 统一消息格式
    MessageRouter（路由层）
```

**未来发展方向**：
- 与 Workspace 集成，每个 Workspace 可以有自己的渠道配置
- 渠道健康监控和自动故障切换
- 支持渠道特定的配置和优化

---

#### 8.7.4 完整数据流（从用户输入到响应输出）

```
用户（通过某个渠道）
      ↓
   Channel（接收原始消息）
      ↓ 转换为统一 Message 对象
   MessageRouter（识别类型）
      ↓ 路由决策
      ├─────────────────┬─────────────────┬─────────────────┐
      ↓                 ↓                 ↓                 ↓
  Skill执行        记忆系统操作      Agent对话处理       生成请求
      └─────────────────┴─────────────────┴─────────────────┘
                        ↓
            PlanOrchestrator（复杂任务）
                        ↓
            Cognition Orchestrator（认知核）
                        ↓
            LLMProviderManager（选择模型）
                        ↓
            响应生成
                        ↓
            MessageRouter（包装响应）
                        ↓
            Channel（发送回用户）
```

---

### 8.8 新发现的核心模块详解

通过完整扫描 Neurova 项目，我们发现了以下重要的功能模块，它们是 CogArch 2.0 架构的重要组成部分！

---

#### 8.8.1 Agent 层（认知核的人格与自治系统）

**所在位置**：`neurova/agent/`

| 模块 | 位置 | 说明 | 在架构中的角色 |
|-----|-----|-----|--------------|
| **AutonomySystem** | `autonomy_system.py` | 自治系统 | **认知核** - 自主行为管理 |
| **Constitution** | `constitution.py` | 宪法/基本指令 | **认知核** - 核心原则与价值观 |
| **Personality** | `personality.py` | 人格设定 | **认知核** - 性格特征与行为风格 |

**重要性**：这是 Neurova 区别于 QwenPaw 的重要特色！提供了人格化的基础，让 Agent 有自己的性格、价值观和自主行为能力！

---

#### 8.8.2 认知核增强模块（动机与注意力）

**所在位置**：`neurova/core/`

| 模块 | 位置 | 说明 | 在架构中的角色 |
|-----|-----|-----|--------------|
| **IntrinsicMotivation** | `intrinsic_motivation.py` | 内在动机 | **认知核** - 好奇心与主动探索驱动 |
| **IdleTracker** | `idle_tracker.py` | 闲置追踪 | **认知核** - 检测闲置状态，触发自主活动 |

**重要性**：这两个模块让 Neurova 具备主动思考和主动探索的能力！

---

#### 8.8.3 记忆系统增强模块

**所在位置**：`neurova/memory/core/`

| 模块 | 位置 | 说明 | 在架构中的角色 |
|-----|-----|-----|--------------|
| **GrowthLog** | `growth_log.py` | 成长日志 | **元认知层** - 学习记录与成长追踪 |
| **QuestionQueue** | `question_queue.py` | 问题队列 | **元认知层** - 待解决问题管理 |
| **ConversationBuffer** | `conversation_buffer.py` | 对话缓冲区 | **记忆层** - 最近对话的临时存储 |
| **MemoryStream** | `memory_stream.py` | 记忆流 | **记忆层** - 流式记忆访问 |
| **ConflictDetector** | `conflict.py` | 冲突检测 | **记忆层** - 检测记忆冲突 |
| **VersionControl** | `version_control.py` | 版本控制 | **记忆层** - 记忆版本管理 |
| **MemoryCache** | `cache.py` | 缓存 | **记忆层** - 热记忆快速访问 |
| **MemorySecurity** | `security.py` | 安全 | **记忆层** - 记忆安全防护 |
| **AttachmentManager (Memory)** | `attachment_manager.py` | 附件管理 | **记忆层** - 记忆中附件的管理 |

---

#### 8.8.4 基础设施增强模块

**所在位置**：`neurova/core/`

| 模块 | 位置 | 说明 | 在架构中的角色 |
|-----|-----|-----|--------------|
| **ApiRouter** | `api_router.py` | API 路由 | **接口层** - API 路由管理 |
| **ApiStandard** | `api_standard.py` | API 标准 | **接口层** - API 标准定义 |
| **AttachmentManager (Core)** | `attachment_manager.py` | 附件管理 | **功能壳** - 附件统一管理 |
| **BaseModule** | `base_module.py` | 基础模块类 | **基础设施** - 所有模块的基类 |
| **StateManager** | `state_manager.py` | 状态管理 | **基础设施** - 全局状态管理 |
| **ErrorHandler** | `error_handler.py` | 错误处理 | **基础设施** - 统一错误处理 |
| **ModuleLib** | `module_lib.py` | 模块库 | **基础设施** - 模块管理与加载 |
| **ModuleTracker** | `module_tracker.py` | 模块追踪 | **基础设施** - 追踪模块使用情况 |
| **SleepConfigManager** | `sleep_config_manager.py` | 睡眠配置 | **基础设施** - 睡眠配置管理 |
| **SleepPhaseConfigManager** | `sleep_phase_config_manager.py` | 睡眠阶段配置 | **基础设施** - 睡眠阶段配置管理 |
| **MultiAgentSleepManager** | `multi_agent_sleep_manager.py` | 多代理睡眠 | **基础设施** - 多代理睡眠协调 |

---

#### 8.8.5 插件系统（可扩展能力）

**所在位置**：`neurova/plugins/`

| 模块 | 位置 | 说明 | 在架构中的角色 |
|-----|-----|-----|--------------|
| **PluginManager** | `plugin_manager.py` | 插件管理器 | **基础设施** - 插件安装、启用、禁用 |
| **BasePlugin** | `base_plugin.py` | 插件基类 | **基础设施** - 所有插件的基类 |
| **PluginLifecycle** | `plugin_lifecycle.py` | 插件生命周期 | **基础设施** - 管理插件的生命周期 |
| **PluginManifest** | `plugin_manifest.py` | 插件清单 | **基础设施** - 插件元数据定义 |
| **PluginApiRegistry** | `plugin_api_registry.py` | 插件 API 注册 | **基础设施** - 插件向核心暴露 API |

---

#### 8.8.6 功能壳 - 附件与媒体

| 模块 | 位置 | 说明 | 在架构中的角色 |
|-----|-----|-----|--------------|
| **AttachmentManager (Core)** | `neurova/core/attachment_manager.py` | 附件管理 | **功能壳** - 统一管理附件 |
| **AttachmentManager (Memory)** | `neurova/memory/core/attachment_manager.py` | 记忆附件管理 | **记忆层** - 管理记忆中的附件 |
| **MediaManager** | `neurova/media/manager.py` | 媒体管理 | **功能壳** - 媒体文件处理与管理 |

---

### 8.9 完整的 Neurova 功能模块总结

#### 核心特色（Neurova 特有，超越 QwenPaw）

1. **完整的认知系统**
   - Cognition Orchestrator（待实现）
   - MetaCognition（元认知）
   - SelfReflection（自我反思）
   - SelfOptimization（自我优化）
   - AutonomySystem（自治系统）
   - Constitution（基本指令/价值观）
   - Personality（人格设定）
   - IntrinsicMotivation（内在动机）
   - IdleTracker（闲置追踪）

2. **强大的记忆系统**
   - EKI Bayesian Optimizer（贝叶斯认知优化）
   - TemporalKnowledgeGraph（时序知识图谱）
   - WorkingMemory（工作记忆增强）
   - MemoryTemperature（记忆温度系统）
   - SleepConsolidation（睡眠巩固）
   - GrowthLog（成长日志）
   - QuestionQueue（问题队列）
   - MemoryStream（记忆流）
   - ConflictDetector（冲突检测）
   - VersionControl（版本控制）
   - MemorySecurity（安全防护）

3. **完整的项目协作系统**
   - ProjectManager（项目管理）
   - TaskBoard（任务看板）
   - TeamManager（团队管理）
   - FileFlow（文件流）
   - WorkflowEngine（工作流）

4. **情感与交互系统**
   - EmotionAnalyzer（情感分析）
   - ContextInjector（上下文注入）
   - TimeAwareness（时间感知）
   - ProactiveQuestion（主动提问）
   - ProactiveRecall（主动回忆）
   - ProactiveQuestion（好奇心驱动）

5. **技能系统**
   - SkillsManager（技能管理与进化）
   - 技能自动生成
   - 技能修补
   - 技能压缩

#### 基础设施（与 QwenPaw 互补）

1. **接口层**
   - CLI（命令行界面）
   - Web Console（Web 控制台，借鉴 QwenPaw）
   - Channels（多渠道连接：Discord、QQ、飞书、Telegram、微信、钉钉等）
   - MessageRouter（消息路由）
   - ApiRouter（API 路由）
   - ApiStandard（API 标准）
   - ACP Server（Agent 控制协议，借鉴 QwenPaw）

2. **执行引擎（待完善）**
   - PlanOrchestrator（任务编排器，小脑）
   - ToolEngine（工具引擎，借鉴 QwenPaw 的 MCP）
   - WorkflowEngine（工作流引擎）
   - MultiAgentManager（多代理协作）
   - ExecutionMonitor（执行监控）

3. **基础设施**
   - ServiceManager（服务管理，借鉴 QwenPaw）
   - Workspace（工作空间，借鉴 QwenPaw）
   - EventBus（事件总线）
   - ConfigManager（配置管理）
   - Logger（日志系统）
   - StateManager（状态管理）
   - ErrorHandler（错误处理）
   - ModuleLib（模块库）
   - ModuleTracker（模块追踪）
   - PluginSystem（插件系统）
   - SleepConfigManager（睡眠配置）
   - MultiAgentSleepManager（多代理睡眠管理）
   - LLMProviderManager（LLM 提供商管理）
   - LLMPresetRegistry（LLM 预设管理）

---

## 十一、借鉴 QwenPaw：LLM 大模型配置与渠道（含前端）

通过分析 QwenPaw 的实现，我们可以借鉴以下优秀设计：

---

### 9.1 LLM 大模型配置管理（借鉴 QwenPaw 的 Provider 系统）

#### QwenPaw 的优点：
- **统一 Provider 基类和 Provider Manager**
  - 支持多个内置 Provider（OpenAI、Anthropic、Gemini、Ollama、LM Studio、OpenRouter 等）
  - 统一的接口和配置管理
- **Model Info 元数据**
  - 模型 ID、名称
  - 是否支持图像、视频
  - 能力探测来源
- **Model Slot Config（模型槽配置）**
  - 灵活的模型配置方式
- **安全的密钥存储（Secret Store）**
  - 密钥加密存储
- **能力缓存（Model Capability Cache）**
- **重试和速率限制（Rate Limiter）**
- **多模态探测（Multimodal Prober）**

#### Neurova 的改进方案：
**现有 Neurova 已有：**
- LLMProviderManager
- LLMPresetRegistry

**需要新增的：**
1. **统一 Provider 基类**
   - 参考 QwenPaw 的 `Provider` 基类
   - 标准接口：`get_available_models()`, `create_chat_model()`, `test_connection()`
2. **内置 Provider 支持**
   - OpenAI（兼容）
   - Anthropic
   - Gemini
   - Ollama
   - LM Studio
   - OpenRouter
3. **密钥安全存储**
   - 加密存储
4. **模型能力缓存**
   - 减少重复探测请求
5. **重试和速率限制**
   - 增加稳定性

---

### 9.2 消息渠道（借鉴 QwenPaw 的 Console 设计）

#### QwenPaw 的渠道系统：
- **Console 渠道（核心）**
  - Web UI 界面（基于 React + TypeScript + Vite）
  - 实时 WebSocket 通信
  - 文件上传
  - 消息追踪

#### Neurova 的现有渠道 + 改进：
**现有 Neurova 已有：**
- ChannelManager
- Discord、QQ、飞书、Telegram、微信、钉钉、WebSocket、API 等多种渠道

**需要借鉴 QwenPaw 的：**
1. **Console 渠道的 Web UI（借鉴 QwenPaw 的 console 前端）**
   - 会话管理（创建、加载、恢复、关闭）
   - 模型选择器（实时切换）
   - 流式渲染输出
   - 文件上传
   - 消息搜索
   - 任务追踪（支持停止/重连）
   - 多语言支持（i18n）
   - 主题切换（暗色/亮色）
2. **后端 API 路由**
   - `/console` 相关路由（参考 `console.py`）
   - 静态资源服务（参考 `console_static.py`）

---

### 9.3 Console 前端架构（借鉴 QwenPaw）

#### QwenPaw 的 console 前端架构：
```
console/
├── src/
│   ├── api/
│   │   ├── modules/          # API 模块
│   │   │   ├── acp.ts       # ACP 协议
│   │   │   ├── chat.ts      # 聊天
│   │   │   ├── provider.ts  # LLM 提供商
│   │   │   ├── skill.ts     # 技能
│   │   │   └── ...
│   │   ├── types/           # TypeScript 类型定义
│   │   └── config.ts        # API 配置
│   ├── pages/               # 页面
│   │   ├── Chat/            # 聊天页
│   │   ├── Agent/           # Agent 配置页
│   │   ├── Control/         # 控制页（渠道、定时任务、会话）
│   │   └── Settings/        # 设置页
│   ├── components/          # 组件库
│   ├── layouts/             # 布局
│   └── App.tsx              # 入口
└── public/                  # 静态资源
```

#### Neurova 可以借鉴的前端页面功能：

| 页面 | Neurova 已有 | 需要借鉴 QwenPaw |
|-----|-------------|---------------|
| **Chat** | WebUI 存在 | 模型选择器、会话管理、消息搜索、流式渲染、任务追踪 |
| **Agent/Config** | 部分功能 | 上下文管理、工具调用级别、LLM 重试/速率限制、React Agent 配置 |
| **Agent/Skills** | 有 | 技能导入、冲突检测、技能可视化 |
| **Agent/Tools** | 有 | MCP 配置管理 |
| **Agent/Workspace** | 有 | 文件编辑器、文件浏览 |
| **Control/Channels** | 有 | 渠道卡片、二维码认证、渠道图标 |
| **Control/CronJobs** | 部分 | 定时任务管理、CRON 解析 |
| **Control/Sessions** | 有 | 会话管理、筛选 |
| **Settings/Models** | 有 | 提供商管理、远程/本地模型配置、能力探测 |
| **Settings/Security** | 没有 | ToolGuard、SkillScanner、Shell Evasion 防护 |
| **Settings/Backups** | 有 | 备份创建、恢复、导入 |
| **Settings/TokenUsage** | 没有 | Token 用量统计、图表 |

---

### 9.4 LLM 提供商与模型配置页面设计（借鉴 QwenPaw）

#### 后端：
1. **Provider Manager API**（参考 QwenPaw 的 `provider_manager.py`）
   - 列出所有提供商
   - 测试连接
   - 配置管理
   - 模型能力探测
   - 密钥安全存储
2. **模型槽配置**

#### 前端：
1. **Models 页面**（参考 QwenPaw 的 `Settings/Models`）
   - 远程提供商卡片（ProviderCard）
   - 本地提供商卡片（LocalProviderCard）
   - 提供商配置弹窗（ProviderConfigModal）
   - 模型管理弹窗（ModelManageModal）
   - OpenRouter 筛选
   - 连接测试反馈
   - 能力探测状态

---

## 十二、迭代规划

### 阶段 0：完善基础设施（借鉴 QwenPaw）
- [ ] 统一 Provider 基类和 Provider Manager（借鉴 QwenPaw 的 provider 系统）
- [ ] 内置 Provider 支持：OpenAI、Anthropic、Gemini、Ollama、LM Studio、OpenRouter
- [ ] 密钥安全存储与加密
- [ ] 模型能力缓存
- [ ] 重试和速率限制
- [ ] 多模态能力探测

### 阶段 1：建立多 Agent 管理基础（共用小脑/脑干/脊髓）
- [ ] 实现 MultiAgentManager（借鉴 QwenPaw，结合我们的架构）
- [ ] Lazy Loading + 细粒度锁 + 并行启动
- [ ] 每个 Agent 的独立大脑（Memory DB）和办公室（Workspace）
- [ ] 共用小脑（Plan Orchestrator）的初始化
- [ ] 共用脑干（Execution Engine）的初始化
- [ ] 共用脊髓（Service Manager、Provider Manager、Event Bus）的初始化
- [ ] 零停机重载（Hot Reload）

### 阶段 2：认知和执行核心
- [ ] 实现 Cognition Orchestrator 基础版
- [ ] 实现 Plan Orchestrator（小脑）核心（共用）
- [ ] 重构现有 MemoryManager 为三层记忆（每个 Agent 独立）
- [ ] 保持 API 兼容

### 阶段 3：执行引擎（共用脑干）
- [ ] MCPClientManager (MCP 客户端管理器)
- [ ] StdIOStatefulClient / HttpStatefulClient (MCP 客户端)
- [ ] Tool Engine（集成 MCP，共用）
- [ ] Execution Monitor（共用）
- [ ] 基础 Workflow Engine（共用）

### 阶段 4：接口层（完善 Console 后端 API）
- [ ] CLI 增强（支持多 Agent 切换）
- [ ] MultiAgentManager API（列出 Agent、创建 Agent、重载 Agent）
- [ ] Web Console API（借鉴 QwenPaw 的 console.py）
- [ ] Console 静态资源服务（借鉴 QwenPaw 的 console_static.py）
- [ ] Provider Manager API（借鉴 QwenPaw）
  - [ ] 列出提供商
  - [ ] 配置管理
  - [ ] 连接测试
  - [ ] 模型能力探测
- [ ] Channel Manager API（增强，支持 Agent 级别配置）
- [ ] TaskTracker（任务追踪器，支持停止/重连）
- [ ] Console 推送消息系统（WebSocket）

### 阶段 5：协议层
- [ ] ACP Server (Agent Control Protocol 服务)
- [ ] 会话管理 (new/load/resume/close)
- [ ] 流式输出 (delta 更新)
- [ ] 模型切换
- [ ] 配置管理

### 阶段 6：Web Console 前端（借鉴 QwenPaw 的 console 前端）
- [ ] 基础项目架构（React + TypeScript + Vite）
- [ ] Agent 选择器（多 Agent 切换）
- [ ] Chat 页面
  - [ ] 会话管理
  - [ ] 模型选择器
  - [ ] 流式渲染
  - [ ] 文件上传
  - [ ] 消息搜索
  - [ ] 任务追踪
- [ ] Agent 页面
  - [ ] 配置管理
  - [ ] 技能管理（技能导入、冲突检测）
  - [ ] 工具管理（MCP 配置）
  - [ ] 工作区管理（文件编辑、浏览）
- [ ] Control 页面
  - [ ] 渠道管理（渠道卡片、二维码认证）
  - [ ] 定时任务（Cron 管理）
  - [ ] 会话管理
- [ ] Settings 页面
  - [ ] Models 页（提供商管理、模型配置）
  - [ ] Security 页（ToolGuard、SkillScanner）
  - [ ] Backups 页（创建、恢复、导入）
  - [ ] Token Usage 页（用量统计、图表）
- [ ] 多语言支持（i18n）
- [ ] 主题切换（暗色/亮色）

### 阶段 7：完善闭环
- [ ] 完整认知-执行-反馈循环（Agent 独立，小脑/脑干共用）
- [ ] 技能自动进化（每个 Agent 独立进化）
- [ ] 认知流 + 执行追踪回放

### 阶段 8：高级多 Agent 功能
- [ ] Multi-Agent Colab Engine（多个 Agent 协作）
- [ ] 选择性记忆共享（Agent 间协作）
- [ ] 更高级的推理能力

---

## 十三、灵感来源与致谢

- **小脑类比**：感谢用户的绝妙洞察！
- **多 Agent 架构类比**：感谢用户提出的「大脑/办公室 + 共用小脑/脑干/脊髓」绝妙类比！
- **QwenPaw**：工程化架构、工具系统、安全机制、MCP/ACP 协议实现、Web Console、MultiAgentManager
- **MCP (Model Context Protocol)**：标准化的工具连接协议
- **ACP (Agent Control Protocol)**：标准化的 Agent 控制协议
- **认知科学**：记忆三层模型、认知循环理论
- **Neurova 现有模块**：EKI 优化器、时序知识图谱、工作记忆增强、CLI
- **命令行界面**：Python `cmd` 模块、丰富的交互功能

---

**文档状态**：迭代中，欢迎补充想法！
