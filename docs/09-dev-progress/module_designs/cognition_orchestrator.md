# CognitionOrchestrator 模块设计文档

> **模块名称**：CognitionOrchestrator（认知编排器）  
> **对应生物器官**：大脑皮层  
> **设计版本**：1.0  
> **最后更新**：2026-05-12  
> **负责人**：cognition-dev

---

## 一、模块概述

### 1.1 功能定位

CognitionOrchestrator 是 Neurova CogArch 2.0 架构中的**认知编排器**，对应人脑的**大脑皮层**。负责高级认知功能，包括：

- **观察**（Observe）：收集和分析输入信息
- **回忆**（Recall）：从记忆系统中检索相关信息
- **推理**（Reason）：基于观察和回忆进行决策
- **行动**（Action）：将决策发送给小脑（PlanOrchestrator）执行
- **反思**（Reflect）：对执行结果进行自我反省
- **学习**（Learn）：巩固经验到记忆系统

### 1.2 核心职责

| 职责 | 说明 |
|------|------|
| 认知状态管理 | 管理注意力级别、记忆负载、学习率等认知状态 |
| 注意力管理 | 根据任务优先级动态调整注意力级别 |
| 记忆管理 | 管理短期、工作、长期记忆的存储和检索 |
| 技能选择 | 根据任务和认知状态选择合适的技能 |
| 认知-执行闭环 | 协调整个认知-执行-反馈循环 |

---

## 二、架构设计

### 2.1 类结构

```
CognitionOrchestrator
├── CognitiveState (数据类)
├── AttentionLevel (枚举)
├── MemoryType (枚举)
├── CognitiveCycleResult (数据类)
├── AttentionManager (内部类)
└── MemoryManager (内部类)
```

### 2.2 核心数据结构

#### CognitiveState（认知状态）

```python
@dataclass
class CognitiveState:
    attention: AttentionLevel = MEDIUM      # 注意力级别
    memory_load: float = 0.5               # 记忆负载 (0.0-1.0)
    learning_rate: float = 0.5              # 学习率 (0.0-1.0)
    context: Dict[str, Any] = {}            # 上下文信息
    metadata: Dict[str, Any] = {}          # 元数据
```

#### CognitiveCycleResult（认知循环结果）

```python
@dataclass
class CognitiveCycleResult:
    success: bool = False                   # 是否成功
    observation: Dict = {}                  # 观察结果
    recalled_memories: List[Dict] = []     # 回忆起的记忆
    decision: Dict = {}                    # 决策结果
    execution_result: Dict = {}            # 执行结果
    reflection: Dict = {}                  # 反思结果
    consolidation_result: Dict = {}        # 巩固结果
    execution_time: float = 0.0            # 执行时间
    metadata: Dict = {}                   # 元数据
```

### 2.3 认知状态机

```python
class CognitiveState(Enum):
    OBSERVING = "observing"      # 观察状态
    RECALLING = "recalling"      # 回忆状态
    REASONING = "reasoning"      # 推理状态
    ACTING = "acting"            # 行动状态
    REFLECTING = "reflecting"    # 反思状态
    LEARNING = "learning"        # 学习状态
```

---

## 三、核心方法实现

### 3.1 认知-执行闭环 `process_thought_cycle()`

```python
def process_thought_cycle(self, input_context: Dict[str, Any]) -> CognitiveCycleResult:
    """
    处理完整的认知循环
    
    实现认知-执行闭环：
    1. 观察（Observe）
    2. 回忆（Recall）
    3. 推理（Reason）
    4. 发送给小脑（Send to Cerebellum）
    5. 反思（Reflect）
    6. 巩固（Consolidate）
    
    Args:
        input_context: 输入上下文字典
        
    Returns:
        CognitiveCycleResult实例
    """
```

#### 执行流程

```
输入上下文
    │
    ▼
┌─────────────────┐
│  1. 观察阶段    │  ← _observe()
│  - 收集信息     │
│  - 分析输入     │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  2. 回忆阶段    │  ← _recall()
│  - 检索记忆     │
│  - 匹配相关信息 │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  3. 推理阶段    │  ← _reason()
│  - 做出决策     │
│  - 生成计划     │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  4. 行动阶段    │  ← _send_to_cerebellum()
│  - 发送给小脑   │
│  - 执行计划     │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  5. 反思阶段    │  ← _reflect()
│  - 评估执行结果 │
│  - 生成洞察     │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  6. 巩固阶段    │  ← _consolidate()
│  - 记忆巩固     │
│  - 经验学习     │
└─────────────────┘
    │
    ▼
返回 CognitiveCycleResult
```

### 3.2 注意力管理

```python
class AttentionManager:
    """注意力管理器"""
    
    def get_attention(self) -> AttentionLevel:
        """获取当前注意力级别"""
        
    def set_attention(self, level: AttentionLevel, reason: str = "") -> None:
        """设置注意力级别"""
        
    def should_switch_attention(self, task_priority: int) -> bool:
        """判断是否需要切换注意力"""
        # 规则：
        # - 当前不是 HIGH 且任务优先级 >= 8 → 需要切换
        # - 当前不是 CRITICAL 且任务优先级 >= 9 → 需要切换
```

### 3.3 记忆管理

```python
class MemoryManager:
    """记忆管理器"""
    
    def add_memory(self, content: str, memory_type: MemoryType, 
                  metadata: Optional[Dict] = None) -> str:
        """添加记忆"""
        # 支持三种记忆类型：SHORT_TERM, WORKING, LONG_TERM
        # 自动管理容量限制
        
    def retrieve_memory(self, memory_id: str) -> Optional[Dict]:
        """检索单条记忆"""
        
    def get_memories_by_type(self, memory_type: MemoryType) -> List[Dict]:
        """按类型获取记忆"""
```

---

## 四、集成设计

### 4.1 与 Memory Layer 集成

```python
# 使用 AgentMemoryLayer 进行持久化存储
from neurova.cognitive_layer.memory_layer.memory_layer import AgentMemoryLayer

class CognitionOrchestrator:
    def __init__(self, agent_id: str, db_path: str):
        # 初始化记忆层
        self.memory_layer = AgentMemoryLayer(
            agent_id=agent_id,
            db_path=db_path,
        )
        
    def _recall(self, query: str, observation: Dict) -> List[Dict]:
        """从记忆层检索"""
        return self.memory_layer.recall(
            query=query,
            limit=10,
        )
```

### 4.2 与 Meta Cognition Layer 集成

```python
# 使用 MetaCognition 进行自我监控和反思
from neurova.cognitive_layer.meta_cognition_layer.meta_cognition import MetaCognition
from neurova.cognitive_layer.meta_cognition_layer.self_reflection import SelfReflection
from neurova.cognitive_layer.meta_cognition_layer.self_optimization import SelfOptimization

class CognitionOrchestrator:
    def __init__(self):
        # 初始化元认知模块
        self.meta_cognition = MetaCognition(
            agent_id=self.agent_id,
            memory_layer=self.memory_layer,
        )
        self.self_reflection = SelfReflection(self.memory_layer)
        self.self_optimization = SelfOptimization(self.memory_layer)
        
    def _reflect(self, observation, decision, execution_result) -> Dict:
        """使用 SelfReflection 进行反思"""
        patterns = self.self_reflection.analyze_memory_patterns()
        anomalies = self.self_reflection.detect_anomalies()
        insights = self.self_reflection.generate_insights()
        
        return {
            "patterns": patterns,
            "anomalies": anomalies,
            "insights": insights,
        }
```

### 4.3 与 PlanOrchestrator 集成

```python
# 将决策发送给 PlanOrchestrator（小脑）执行
from neurova.core.plan_orchestrator import PlanOrchestrator

class CognitionOrchestrator:
    def __init__(self):
        # 初始化 PlanOrchestrator
        self.plan_orchestrator = PlanOrchestrator()
        
    def _send_to_cerebellum(self, decision: Dict) -> Dict:
        """发送给小脑执行"""
        # 将决策转化为执行计划
        plan = self.plan_orchestrator.orchestrate(
            cognition=decision,
            agent_persona=self.persona,
        )
        
        # 执行计划
        result = self.plan_orchestrator.execute(plan)
        
        return result
```

---

## 五、单元测试

### 5.1 测试覆盖

| 测试类 | 测试方法数 | 覆盖功能 |
|--------|------------|----------|
| TestCognitiveState | 4 | 认知状态创建、转换、序列化 |
| TestAttentionManager | 5 | 注意力管理、切换判断 |
| TestMemoryManager | 7 | 记忆增删改查、容量限制 |
| TestCognitionOrchestrator | 12 | 编排器核心功能 |
| TestIntegration | 1 | 完整工作流程集成测试 |

**总计**：29 个测试用例，覆盖率 > 80%

### 5.2 测试文件

- `tests/test_cognition_orchestrator.py`

---

## 六、使用说明

### 6.1 基本使用

```python
from neurova.cognitive import CognitionOrchestrator, AttentionLevel

# 创建编排器
orchestrator = CognitionOrchestrator()

# 更新认知状态
orchestrator.update_cognitive_state(
    attention=AttentionLevel.HIGH,
    memory_load=0.8,
    learning_rate=0.9,
)

# 处理任务
result = orchestrator.process_task(
    task_description="Analyze data",
    task_priority=8,
)

# 执行完整认知循环
cycle_result = orchestrator.process_thought_cycle(
    input_context={"query": "user input"},
)
```

### 6.2 与技能注册表集成

```python
from neurova.skill.registry import SkillRegistry

# 创建注册表
registry = SkillRegistry()
registry.register_skill(...)

# 设置到编排器
orchestrator.set_registry(registry)

# 选择技能
skills = orchestrator.select_skill_for_task("task description")
```

---

## 七、性能优化

### 7.1 线程安全

- 所有公共方法都使用 `threading.RLock()` 保证线程安全
- `get_cognitive_state()` 返回深拷贝，防止外部修改

### 7.2 记忆管理

- 短期记忆容量限制：10 条
- 工作记忆容量限制：5 条
- 自动清理最旧记忆

### 7.3 历史记录限制

- 注意力切换历史：最多 100 条
- 认知循环历史：最多 50 条

---

## 八、已知限制与未来改进

### 8.1 当前限制

1. **记忆检索简化**：当前使用简单字符串匹配，未来应集成向量检索
2. **推理引擎简化**：当前使用规则推理，未来应集成 LLM
3. **技能选择简化**：当前使用标签匹配，未来应使用语义相似度

### 8.2 未来改进

1. 集成 LLM 进行高级认知推理
2. 实现基于向量的语义记忆检索
3. 添加认知状态持久化
4. 实现分布式认知（多 Agent 协作）

---

## 九、附录

### 9.1 文件清单

| 文件路径 | 说明 |
|----------|------|
| `neurova/cognitive.py` | 主模块实现 |
| `neurova/skill/__init__.py` | 兼容性桥接层 |
| `tests/test_cognition_orchestrator.py` | 单元测试（29个用例） |
| `docs/dev_progress/module_designs/cognition_orchestrator.md` | 本设计文档 |

### 9.2 依赖模块

- `neurova.cognitive_layer.memory_layer`
- `neurova.cognitive_layer.meta_cognition_layer`
- `neurova.core.plan_orchestrator`
- `neurova.skill.registry`

---

**文档状态**：初稿完成  
**下一步**：集成测试、性能测试、文档完善
