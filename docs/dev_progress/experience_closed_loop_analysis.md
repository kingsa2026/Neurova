# 经验闭环架构分析报告

## 问题陈述

用户提出：**经验知识库目前只能"总结"，但 Agent 自己不会"复用"**。

目标：让经验（包括成长体系、技能、元认知等）形成 **"总结 → 记录 → 使用 → 同样的问题复用"** 的完整闭环。

---

## 当前架构分析

### 理论上的闭环流程

```
┌─────────────────┐
│  1. 总结 (Summarize)                              │
│     Agent 执行任务后，元认知模块进行反思，总结经验教训  │
└─────────────────┘
                    ↓
┌─────────────────┐
│  2. 记录 (Record)                                │
│     将经验记录到经验知识库（ExperienceKnowledgeBase） │
└─────────────────┘
                    ↓
┌─────────────────┐
│  3. 使用 (Retrieve)                              │
│     下次遇到类似问题时，从经验知识库检索相关经验      │
└─────────────────┘
                    ↓
┌─────────────────┐
│  4. 复用 (Reuse)                                │
│     根据检索到的经验，调整执行策略，避免重复错误      │
└─────────────────┘
```

### 实际架构状态

#### ✅ 已有模块（可实现部分功能）

| 模块 | 文件 | 功能 | 状态 |
|------|------|------|------|
| **ExperienceKnowledgeBase** | `skills/experience_knowledge_base.py` | 经验知识库，提供数据库存储、效果评估、智能推荐 | ✅ 已实现 |
| **ExperienceCaller** | `skills/experience_caller.py` | 经验调用系统，可查找相似经验、提取教训、推荐最佳实践 | ✅ 已实现 |
| **MetaCognition** | `cognitive_layers/meta_cognition_layer/meta_cognition.py` | 元认知模块，提供自我监控、自我反思、自我优化能力 | ✅ 已实现 |
| **CognitionOrchestrator** | `core/cognition_orchestrator.py` | 认知编排器，提供"观察→回忆→推理→行动→反思→学习"的认知-执行闭环 | ✅ 已实现 |
| **AgentSelfManager** | `cognitive_layers/memory_layer/agent_self.py` | Agent 自我管理模块，管理核心指令、心跳任务等 | ✅ 已实现 |
| **Growth API** | `api/endpoints/growth.py` | 成长系统接口，提供反思日志、问题队列、主动行为等 API | ✅ 已实现 |

#### ❌ 关键断点（闭环未形成）

| 阶段 | 问题 | 证据 |
|------|------|------|
| **1. 总结** | `MetaCognition.reflect()` 方法确实执行反思，但反思结果只保存在内存中（`_reflection_history`），**没有保存到 ExperienceKnowledgeBase** | `meta_cognition.py` 第 175-224 行：反思结果保存到 `self._reflection_history`，无外部调用 |
| **2. 记录** | `ExperienceKnowledgeBase.add_experience_record()` 方法存在，但**没有被任何模块调用** | 搜索整个代码库，没有找到调用 `add_experience_record()` 的代码 |
| **3. 使用** | `ExperienceCaller.find_similar_experiences()` 方法存在，但 Agent 在执行任务时**没有调用它** | `cognition_orchestrator.py` 的认知循环中没有调用经验检索 |
| **4. 复用** | 即使找到了相似经验，Agent **没有机制根据经验调整执行策略** | 决策阶段没有考虑检索到的经验 |

---

## 详细代码分析

### 断点 1：总结 → 记录（反思结果未保存）

**位置**：`cognitive_layers/meta_cognition_layer/meta_cognition.py` 第 175-224 行

```python
def reflect(self) -> ReflectionReport:
    """执行自我反思"""
    with self._lock:
        try:
            # 分析记忆模式
            pattern_analysis = self._analyze_memory_patterns()
            
            # 检测异常
            anomalies = self._detect_anomalies()
            
            # 生成洞察
            insights = self._generate_insights(pattern_analysis, anomalies)
            
            # ... 构建报告 ...
            
            # ❌ 问题：反思结果只保存在内存中，没有保存到 ExperienceKnowledgeBase
            self._reflection_history.append(report)
            
            return report
```

**同理**，`core/cognition_orchestrator.py` 第 722-747 行的 `_reflect()` 方法：

```python
def _reflect(self, observation, decision, execution_result):
    """反思阶段：自我反省"""
    reflection = {
        "observation_quality": 0.8,
        "decision_quality": 0.7,
        "execution_success": execution_result.get("status") == "executed",
        "insights": [],
        "timestamp": datetime.now().isoformat(),
    }
    
    # ❌ 问题：反思结果没有保存到 ExperienceKnowledgeBase
    return reflection
```

### 断点 2：记录（经验未被保存）

**位置**：`skills/experience_knowledge_base.py`

```python
def add_experience_record(self, skill_name: str, exp: ExperienceRecord, ...):
    """添加经验记录"""
    # ✅ 方法已实现，但没有被任何模块调用
    # ...
```

**验证**：搜索整个代码库，没有找到调用 `add_experience_record()` 的代码。

### 断点 3：使用（经验未被检索）

**位置**：`core/cognition_orchestrator.py` 第 559-610 行

```python
def run_cognitive_cycle(self, input_context: Dict[str, Any]) -> CognitiveCycleResult:
    """实现认知-执行闭环"""
    # 1. 观察阶段
    observation = self._observe(input_context)
    
    # 2. 回忆阶段
    # ❌ 问题：这里应该调用 ExperienceCaller.find_similar_experiences()
    #    获取相关经验，但目前没有调用
    recalled_memories = self._recall(observation)
    
    # 3. 推理阶段
    decision = self._reason(observation, recalled_memories)
    
    # ...
```

### 断点 4：复用（经验未被应用）

**位置**：`core/cognition_orchestrator.py` 第 560-610 行

即使在第 2 阶段添加了经验检索，第 3 阶段（推理/决策）也没有机制根据检索到的经验调整决策策略。

---

## 解决方案：形成完整闭环

### 修改 1：连接反思和经验记录

**目标**：将反思结果保存到 ExperienceKnowledgeBase

**修改位置**：`cognitive_layers/meta_cognition_layer/meta_cognition.py` 的 `reflect()` 方法

```python
def reflect(self) -> ReflectionReport:
    """执行自我反思"""
    with self._lock:
        try:
            # ... 原有代码 ...
            
            # ✅ 新增：保存反思结果到经验知识库
            self._save_reflection_to_experience_kb(report)
            
            return report
            
        except Exception as e:
            logger.error(f"反思失败: {e}")
            return ReflectionReport(reflection_score=0.0)
    
    def _save_reflection_to_experience_kb(self, report: ReflectionReport):
        """保存反思结果到经验知识库"""
        try:
            from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase
            from neurova.skills.models import ExperienceRecord
            
            ekb = ExperienceKnowledgeBase()
            
            # 为每个洞察创建一个经验记录
            for insight in report.insights:
                exp = ExperienceRecord(
                    skill_name="meta-cognition",  # 元认知技能
                    context={"reflection_type": "meta-cognition", "insights": insight},
                    result={"reflection_score": report.reflection_score},
                    success=True,
                    timestamp=report.timestamp,
                    feedback=f"Insight: {insight}"
                )
                ekb.add_experience_record("meta-cognition", exp)
            
            ekb.close()
            logger.info(f"反思结果已保存到经验知识库: {len(report.insights)} 条洞察")
            
        except Exception as e:
            logger.error(f"保存反思结果到经验知识库失败: {e}")
```

**同理**，修改 `core/cognition_orchestrator.py` 的 `_reflect()` 方法：

```python
def _reflect(self, observation, decision, execution_result):
    """反思阶段：自我反省"""
    reflection = {
        "observation_quality": 0.8,
        "decision_quality": 0.7,
        "execution_success": execution_result.get("status") == "executed",
        "insights": [],
        "timestamp": datetime.now().isoformat(),
    }
    
    # ✅ 新增：保存反思结果到经验知识库
    self._save_reflection_to_experience_kb(reflection, observation, decision, execution_result)
    
    return reflection

def _save_reflection_to_experience_kb(self, reflection, observation, decision, execution_result):
    """保存反思结果到经验知识库"""
    try:
        from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase
        from neurova.skills.models import ExperienceRecord
        
        ekb = ExperienceKnowledgeBase()
        
        # 创建经验记录
        exp = ExperienceRecord(
            skill_name=decision.get("skill_name", "unknown"),
            context=observation,
            result=execution_result,
            success=reflection["execution_success"],
            timestamp=reflection["timestamp"],
            feedback=f"Decision quality: {reflection['decision_quality']}"
        )
        ekb.add_experience_record(decision.get("skill_name", "unknown"), exp)
        
        ekb.close()
        logger.info("反思结果已保存到经验知识库")
        
    except Exception as e:
        logger.error(f"保存反思结果到经验知识库失败: {e}")
```

### 修改 2：连接经验检索和执行

**目标**：在认知循环的"回忆"阶段，调用 ExperienceCaller 检索相关经验

**修改位置**：`core/cognition_orchestrator.py` 的 `run_cognitive_cycle()` 方法

```python
def run_cognitive_cycle(self, input_context: Dict[str, Any]) -> CognitiveCycleResult:
    """实现认知-执行闭环"""
    # 1. 观察阶段
    observation = self._observe(input_context)
    
    # 2. 回忆阶段
    # ✅ 修改：调用 ExperienceCaller 检索相关经验
    recalled_memories = self._recall(observation)
    similar_experiences = self._retrieve_similar_experiences(observation)
    
    # 将相似经验添加到回忆记忆中
    if similar_experiences:
        recalled_memories["similar_experiences"] = similar_experiences
        logger.info(f"检索到 {len(similar_experiences)} 条相似经验")
    
    # 3. 推理阶段
    decision = self._reason(observation, recalled_memories, similar_experiences)
    
    # ...
    
def _retrieve_similar_experiences(self, observation: Dict) -> List:
    """检索相似经验"""
    try:
        from neurova.skills.experience_caller import ExperienceCaller
        
        caller = ExperienceCaller()
        
        # 从观察中提取上下文
        context = {
            "user_input": observation.get("user_input", ""),
            "topic": observation.get("topic", "")
        }
        
        # 检索相似经验
        skill_name = observation.get("skill_name", "unknown")
        similar = caller.find_similar_experiences(skill_name, context, limit=5)
        
        logger.info(f"检索到 {len(similar)} 条相似经验")
        return similar
        
    except Exception as e:
        logger.error(f"检索相似经验失败: {e}")
        return []
```

### 修改 3：连接经验复用

**目标**：在决策阶段，根据检索到的经验调整执行策略

**修改位置**：`core/cognition_orchestrator.py` 的 `_reason()` 方法

```python
def _reason(self, observation, recalled_memories, similar_experiences=None):
    """推理阶段：决策"""
    decision = {
        "action": "execute_skill",
        "skill_name": observation.get("skill_name", "unknown"),
        "confidence": 0.8,
        "timestamp": datetime.now().isoformat(),
    }
    
    # ✅ 新增：根据相似经验调整决策
    if similar_experiences:
        decision = self._adjust_decision_by_experience(decision, similar_experiences)
    
    return decision

def _adjust_decision_by_experience(self, decision, similar_experiences):
    """根据相似经验调整决策"""
    # 统计相似经验中的成功率
    success_count = sum(1 for exp in similar_experiences if exp.success)
    success_rate = success_count / len(similar_experiences) if similar_experiences else 0
    
    # 如果成功率低，降低置信度
    if success_rate < 0.5:
        decision["confidence"] *= 0.5
        decision["warning"] = f"该技能在历史相似场景下成功率较低 ({success_rate:.0%})"
        logger.info(f"根据经验调整决策：降低置信度 (成功率 {success_rate:.0%})")
    
    # 如果成功率高，提高置信度
    elif success_rate > 0.8:
        decision["confidence"] = min(1.0, decision["confidence"] * 1.2)
        decision["hint"] = f"该技能在历史相似场景下成功率较高 ({success_rate:.0%})"
        logger.info(f"根据经验调整决策：提高置信度 (成功率 {success_rate:.0%})")
    
    # 提取历史反馈
    feedbacks = [exp.feedback for exp in similar_experiences if exp.feedback]
    if feedbacks:
        decision["historical_feedback"] = feedbacks[:3]  # 最多3条
    
    return decision
```

---

## 完整闭环流程（修改后）

```
┌─────────────────┐
│  1. 总结 (Summarize)                              │
│     MetaCognition.reflect() 执行反思               │
│     ↓           │
│     ✅ 修改：保存反思结果到 ExperienceKnowledgeBase │
└─────────────────┘
                    ↓
┌─────────────────┐
│  2. 记录 (Record)                                │
│     ExperienceKnowledgeBase.add_experience_record() │
│     ↓           │
│     ✅ 已实现：经验记录保存到数据库                  │
└─────────────────┘
                    ↓
┌─────────────────┐
│  3. 使用 (Retrieve)                              │
│     CognitionOrchestrator.run_cognitive_cycle()    │
│     ↓           │
│     ✅ 修改：调用 ExperienceCaller.find_similar_experiences() │
│     检索相关经验                                   │
└─────────────────┘
                    ↓
┌─────────────────┐
│  4. 复用 (Reuse)                                │
│     CognitionOrchestrator._reason()               │
│     ↓           │
│     ✅ 修改：根据检索到的经验调整决策策略            │
│     - 如果历史成功率低，降低置信度                │
│     - 如果历史成功率高，提高置信度                │
│     - 提取历史反馈作为参考                        │
└─────────────────┘
                    ↓
┌─────────────────┐
│  5. 循环 (Loop)                                  │
│     下次执行任务时，再次执行步骤 3-4              │
│     实现真正的经验复用和持续改进                    │
└─────────────────┘
```

---

## 实施计划

### 阶段 1：修复断点 1（总结 → 记录）

**任务**：
1. 修改 `cognitive_layers/meta_cognition_layer/meta_cognition.py` 的 `reflect()` 方法
2. 修改 `core/cognition_orchestrator.py` 的 `_reflect()` 方法
3. 添加单元测试验证反思结果已保存到经验知识库

**验证**：
```python
# 测试反思结果是否保存到经验知识库
from neurova.cognitive_layers.meta_cognition_layer.meta_cognition import MetaCognition
from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase

# 创建元认知实例
meta = MetaCognition(agent_id="test-agent")

# 执行反思
report = meta.reflect()

# 检查经验知识库中是否有记录
ekb = ExperienceKnowledgeBase()
records = ekb.get_experience_records("meta-cognition")
assert len(records) > 0, "反思结果未保存到经验知识库"

ekb.close()
```

### 阶段 2：修复断点 2（记录 → 使用）

**任务**：
1. 修改 `core/cognition_orchestrator.py` 的 `run_cognitive_cycle()` 方法
2. 添加 `_retrieve_similar_experiences()` 方法
3. 添加单元测试验证经验检索功能

**验证**：
```python
# 测试认知循环中是否检索相似经验
from neurova.core.cognition_orchestrator import CognitionOrchestrator

# 创建认知编排器实例
orchestrator = CognitionOrchestrator(...)

# 运行认知循环
result = orchestrator.run_cognitive_cycle({
    "user_input": "分析这段代码",
    "topic": "code-analysis",
    "skill_name": "code-analysis"
})

# 检查是否检索到相似经验
assert "similar_experiences" in result.observation, "未检索相似经验"
```

### 阶段 3：修复断点 3（使用 → 复用）

**任务**：
1. 修改 `core/cognition_orchestrator.py` 的 `_reason()` 方法
2. 添加 `_adjust_decision_by_experience()` 方法
3. 添加单元测试验证决策调整功能

**验证**：
```python
# 测试决策是否根据经验调整
from neurova.core.cognition_orchestrator import CognitionOrchestrator
from neurova.skills.models import ExperienceRecord

# 创建认知编排器实例
orchestrator = CognitionOrchestrator(...)

# 添加一些测试经验（成功率高）
# ... (省略添加经验的代码)

# 运行认知循环
result = orchestrator.run_cognitive_cycle({
    "user_input": "分析这段代码",
    "topic": "code-analysis",
    "skill_name": "code-analysis"
})

# 检查决策是否调整
assert "confidence" in result.decision, "决策未调整"
if result.decision.get("historical_feedback"):
    print(f"决策已根据历史经验调整，历史反馈: {result.decision['historical_feedback']}")
```

### 阶段 4：集成测试

**任务**：
1. 创建完整的集成测试，验证整个闭环
2. 测试场景：执行任务 → 反思 → 保存经验 → 再次执行相似任务 → 检索经验 → 调整决策
3. 验证持续改进效果

---

## 预期效果

修改后，系统将形成完整的经验闭环：

1. **自动总结**：Agent 每次执行任务后，自动反思并保存结果到经验知识库
2. **自动记录**：经验知识库统一存储所有经验记录，支持查询和分析
3. **自动使用**：下次遇到相似问题时，自动检索相关经验
4. **自动复用**：根据检索到的经验，自动调整执行策略，避免重复错误

**具体表现**：
- 如果某个技能在历史相似场景下成功率低，Agent 会自动降低置信度，谨慎使用
- 如果某个技能在历史相似场景下成功率高，Agent 会自动提高置信度，优先使用
- 如果历史经验中有有用的反馈，Agent 会自动参考这些反馈

---

## 总结

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 经验只能总结，不能复用 | 反思结果未保存到经验知识库 | 修改 `reflect()` 方法，保存结果到 EKB |
| 经验知识库未被使用 | 没有模块调用 `add_experience_record()` | 在反思后自动调用，保存经验 |
| 经验未被检索 | 认知循环中没有调用经验检索 | 在"回忆"阶段调用 `find_similar_experiences()` |
| 经验未被应用 | 决策阶段没有考虑检索到的经验 | 修改 `_reason()` 方法，根据经验调整决策 |

通过修复这 4 个断点，系统将形成完整的 **"总结 → 记录 → 使用 → 复用"** 经验闭环，真正实现经验的积累和复用。
