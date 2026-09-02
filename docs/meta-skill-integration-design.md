# Meta-skill 直接集成设计文档

## 目标
将 Meta-skill 的 4 个核心能力直接集成到 Neurova 的现有技能系统中，不采用渐进式方法，因为 Neurova 是未发布的框架。

## 现有技能系统分析

### 已有模块（类似 Meta-skill 的能力）
1. **task_decomposer.py** → 部分实现 skill-chain-planner
   - `decompose()` 分解任务为子任务
   - `analyze_skill_needs()` 分析技能需求
   - 缺少：技能链执行、技能链优化

2. **auto_skill_improver.py** → 部分实现 prompt-optimizer
   - `analyze_skill_performance()` 分析技能性能
   - `get_improvement_suggestions()` 获取改进建议
   - 缺少：实际应用改进、提示词优化

3. **skill_need_analyzer.py** → 部分实现 skill-for-skills
   - `analyze_and_acquire()` 从市场获取现有技能
   - 缺少：生成新技能、技能创建

4. **skill_packager.py** → 无直接对应（Neurova 特有）
   - 打包技能用于分享和进化

### 缺失的 Meta-skill 能力
1. **skill-for-skills**：生成新技能（不是从市场获取）
2. **project-to-skill**：将现有项目/代码转换为可复用技能
3. **skill-chain-executor**：执行技能链（多个技能按顺序执行）
4. **prompt-optimizer**：优化技能提示词以提高性能

## 新模块设计

### 1. skill_generator.py（技能生成器）
**职责**：根据需求描述生成新技能的代码和配置。
**接口**：
```python
class SkillGenerator:
    async def generate_skill(self, requirement: str, context: dict = None) -> SkillGenerationResult
    async def refine_skill(self, skill_id: str, feedback: str) -> SkillRefinementResult
    async def validate_skill(self, skill_code: str) -> SkillValidationResult
```

### 2. project_to_skill.py（项目转技能器）
**职责**：将现有项目或代码片段转换为可复用的技能。
**接口**：
```python
class ProjectToSkillConverter:
    async def analyze_project(self, project_path: str) -> ProjectAnalysisResult
    async def extract_skill(self, analysis: ProjectAnalysisResult, skill_name: str) -> ExtractedSkill
    async def package_as_skill(self, extracted: ExtractedSkill) -> SkillPackage
```

### 3. skill_chain_executor.py（技能链执行器）
**职责**：执行技能链，管理技能间的依赖和数据流。
**接口**：
```python
class SkillChainExecutor:
    async def execute_chain(self, chain: SkillChain, initial_input: dict) -> ChainExecutionResult
    async def pause_chain(self, chain_id: str) -> bool
    async def resume_chain(self, chain_id: str) -> bool
    async def get_chain_status(self, chain_id: str) -> ChainStatus
```

### 4. prompt_optimizer.py（提示优化器）
**职责**：优化技能提示词以提高性能和准确性。
**接口**：
```python
class PromptOptimizer:
    async def analyze_prompt(self, prompt: str, skill_context: dict = None) -> PromptAnalysis
    async def optimize_prompt(self, prompt: str, optimization_goal: OptimizationGoal) -> OptimizedPrompt
    async def test_prompt_variants(self, variants: list[str], test_cases: list[dict]) -> TestResults
```

## 现有模块增强

### 1. task_decomposer.py 增强为 skill-chain-planner
**新增方法**：
- `plan_skill_chain()`：规划技能执行链
- `optimize_chain()`：优化技能链顺序
- `estimate_chain_cost()`：估算技能链执行成本

### 2. auto_skill_improver.py 增强为 prompt-optimizer
**新增方法**：
- `optimize_skill_prompt()`：优化技能提示词
- `generate_prompt_variants()`：生成提示词变体
- `run_prompt_ab_test()`：运行 A/B 测试

## 数据模型扩展（models.py）

### 新增数据类
1. **SkillGenerationResult**：技能生成结果
2. **ProjectAnalysisResult**：项目分析结果
3. **SkillChain**：技能链定义
4. **ChainExecutionResult**：技能链执行结果
5. **PromptAnalysis**：提示词分析结果
6. **OptimizedPrompt**：优化后的提示词

## 集成点

### 与 Agent 集成
1. 在 `agent_core.py` 中初始化新模块
2. 在 `chat()` 方法中支持技能生成和链执行
3. 在 `post_chat_pipeline.py` 中添加技能优化步骤

### 与 EvolutionEngine 集成
1. 将技能生成和优化纳入进化循环
2. 使用进化算法优化提示词变体

### 与 ExperienceCaller 集成
1. 收集技能使用经验用于生成和优化
2. 使用经验指导技能链规划

## 测试策略

### Tracer Bullet 测试（TDD）
1. **技能生成测试**：验证生成的技能可执行
2. **项目转技能测试**：验证转换的技能保留核心功能
3. **技能链执行测试**：验证链执行和数据流
4. **提示优化测试**：验证优化后性能提升

### 集成测试
1. Agent 使用新技能的端到端测试
2. 进化循环中的技能优化测试
3. 经验收集和技能改进测试

## 实施顺序

### Phase 1：接口设计和测试骨架
1. 定义所有新数据类
2. 创建测试骨架文件
3. 实现模块占位符

### Phase 2：核心实现
1. 实现 `skill_generator.py`
2. 实现 `project_to_skill.py`
3. 实现 `skill_chain_executor.py`
4. 实现 `prompt_optimizer.py`

### Phase 3：增强现有模块
1. 增强 `task_decomposer.py`
2. 增强 `auto_skill_improver.py`

### Phase 4：集成和测试
1. 集成到 Agent 核心
2. 集成到进化系统
3. 端到端测试

## 风险和缓解

### 风险1：生成的技能质量不可控
**缓解**：添加技能验证和测试步骤，使用进化算法优化生成策略。

### 风险2：技能链执行复杂度高
**缓解**：从简单线性链开始，逐步支持复杂依赖。

### 风险3：提示优化可能过拟合
**缓解**：使用多样化测试集，添加正则化约束。

## 预期收益

1. **技能自动生成**：减少手动编码，提高开发效率
2. **项目知识复用**：将现有项目转换为可复用技能
3. **复杂任务处理**：通过技能链处理多步骤任务
4. **性能持续优化**：自动优化提示词提高技能性能

## 验收标准

1. 所有新模块有完整的单元测试覆盖
2. 与现有技能系统无缝集成
3. 提供示例用例和文档
4. 性能基准测试通过