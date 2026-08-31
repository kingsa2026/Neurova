# 多 Agent 协作机制设计

> **状态**: 已实现（对照代码核实） · 版本: v1.0.0-beta1
> **说明**: 本文档描述的功能已在 `neurova/` 对应模块实现，详见 [功能模块矩阵](../0-index/README.md)


## 1. 概述

### 1.1 设计目标
- 支持多个 Agent 协同工作
- 任务分解和分配
- Agent 间高效沟通
- 避免重复工作和冲突
- 支持 Agent 角色和专长
- 集体决策机制

### 1.2 Agent 类型

```
Agent 分类
├── 按功能
│   ├── 对话 Agent (Conversational Agent)
│   ├── 任务 Agent (Task Agent)
│   ├── 分析 Agent (Analytical Agent)
│   ├── 创意 Agent (Creative Agent)
│   └── 协调 Agent (Coordinator Agent)
│
├── 按权限
│   ├── 主 Agent (Master Agent)
│   ├── 工作 Agent (Worker Agent)
│   └── 监控 Agent (Monitor Agent)
│
└── 按自主性
    ├── 完全自主 (Fully Autonomous)
    ├── 半自主 (Semi-Autonomous)
    └── 被动响应 (Reactive)
```

## 2. Agent 数据模型

### 2.1 Agent 配置

```python
from typing import Dict, List, Optional, Any
from enum import Enum

class AgentStatus(Enum):
    IDLE = "idle"
    BUSY = "busy"
    WAITING = "waiting"
    ERROR = "error"
    OFFLINE = "offline"

class AgentRole(Enum):
    COORDINATOR = "coordinator"
    WORKER = "worker"
    SUPERVISOR = "supervisor"
    SPECIALIST = "specialist"

class AgentConfig:
    """Agent 配置 - 当前实现 (neurova/agent_core.py)"""
    def __init__(
        self,
        name: str = "智星",
        agent_id: str = "yi_ling",
        workspace_path: str = "",
        db_path: str = "",
        llm_api_key: str = "",
        llm_base_url: str = "https://api.openai.com/v1",
        llm_model: str = "gpt-4",
        llm_temperature: float = 0.7,
        max_tokens: int = 8192,
        enable_memory: bool = True,
        enable_streaming: bool = False,
        enable_active_skill_acquisition: bool = False,  # 主动技能获取
        llm_provider: str = "",  # LLM 服务商 ID
        enable_skill_packer: bool = False,  # 自动打包技能
        enable_cognitive_capabilities: bool = True,  # 认知能力
        enable_evolution: bool = True,  # 进化能力
        enable_experience_summary: bool = True,  # 经验总结

        # 个性和宪法配置
        personality: str = "",  # 个性设定
        constitution: str = "",  # 行为准则（宪法）
        behavior_rules: List[str] = None,  # 动态行为规则列表

        # TTS 配置
        enable_tts: bool = False,  # 是否启用 TTS
        tts_engine: str = "mock",  # TTS 引擎类型 (edge/moss_nano/mock)
        tts_voice: str = "mock",  # 音色名称
        tts_auto_download: bool = True,  # 是否自动下载模型
        
        # ASR 配置
        enable_asr: bool = False,  # 是否启用 ASR
        asr_engine: str = "mock",  # ASR 引擎类型 (funasr/whisper/mock)
        asr_voice: str = "zh",  # 语言
        asr_auto_download: bool = True,  # 是否自动下载模型
        
        # 活水上下文池配置
        enable_context_pool: bool = True,  # 是否启用活水上下文池
        enable_auto_tagging: bool = False,  # 是否启用自动标签生成
    ):
        self.name = name
        self.agent_id = agent_id
        self.workspace_path = workspace_path
        self.db_path = db_path
        self.llm_api_key = llm_api_key
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
        self.llm_temperature = llm_temperature
        self.max_tokens = max_tokens
        self.enable_memory = enable_memory
        self.enable_streaming = enable_streaming
        self.enable_active_skill_acquisition = enable_active_skill_acquisition
        self.llm_provider = llm_provider
        self.enable_skill_packer = enable_skill_packer
        self.enable_cognitive_capabilities = enable_cognitive_capabilities
        self.enable_evolution = enable_evolution
        self.enable_experience_summary = enable_experience_summary
        self.personality = personality
        self.constitution = constitution
        self.behavior_rules = behavior_rules or []
        self.enable_tts = enable_tts
        self.tts_engine = tts_engine
        self.tts_voice = tts_voice
        self.tts_auto_download = tts_auto_download
        self.enable_asr = enable_asr
        self.asr_engine = asr_engine
        self.asr_voice = asr_voice
        self.asr_auto_download = asr_auto_download
        self.enable_context_pool = enable_context_pool
        self.enable_auto_tagging = enable_auto_tagging
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 时间戳
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

@dataclass
class Task:
    """任务定义"""
    id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    title: str = ""
    description: str = ""
    content: str = ""
    
    # 任务类型
    task_type: str = "general"
    priority: int = 1  # 1-5, 5 最高
    
    # 分配
    assigned_to: Optional[str] = None
    created_by: Optional[str] = None
    
    # 状态
    status: str = "pending"  # pending, running, completed, failed, cancelled
    progress: float = 0.0  # 0.0 - 1.0
    
    # 依赖
    dependencies: List[str] = field(default_factory=list)
    
    # 结果
    result: Optional[str] = None
    error: Optional[str] = None
    
    # 时间
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    deadline: Optional[datetime] = None
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AgentMessage:
    """Agent 间消息"""
    id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:8]}")
    from_agent: str = ""
    to_agent: str = ""
    message_type: str = "text"  # text, task, result, request, response
    
    # 内容
    content: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    
    # 关联
    task_id: Optional[str] = None
    thread_id: Optional[str] = None
    reply_to: Optional[str] = None
    
    # 时间
    timestamp: datetime = field(default_factory=datetime.now)
    
    # 状态
    read: bool = False
    processed: bool = False
```

## 3. Agent 编排器

### 3.1 核心编排器

```python
class AgentOrchestrator:
    """
    Agent 编排器
    管理 Agent 生命周期、任务分配、协调通信
    """
    
    def __init__(self, config: OrchestratorConfig):
        self.config = config
        self.agents: Dict[str, Agent] = {}
        self.task_manager = TaskManager()
        self.message_channel = AgentMessageChannel()
        self.coordinator = CoordinatorAgent()
        
        # 事件总线
        self.event_bus = EventBus()
        
        # 订阅事件
        self._subscribe_events()
    
    # ========== Agent 管理 ==========
    
    def create_agent(self, config: AgentConfig) -> Agent:
        """创建 Agent"""
        agent = Agent(config)
        self.agents[config.id] = agent
        
        # 初始化 Agent
        agent.initialize()
        
        # 发布事件
        self.event_bus.publish(Event(
            type='agent.created',
            data={'agent_id': config.id, 'config': config.to_dict()}
        ))
        
        return agent
    
    def destroy_agent(self, agent_id: str) -> bool:
        """销毁 Agent"""
        if agent_id not in self.agents:
            return False
        
        agent = self.agents[agent_id]
        agent.shutdown()
        
        del self.agents[agent_id]
        
        # 发布事件
        self.event_bus.publish(Event(
            type='agent.destroyed',
            data={'agent_id': agent_id}
        ))
        
        return True
    
    def get_agent(self, agent_id: str) -> Optional[Agent]:
        """获取 Agent"""
        return self.agents.get(agent_id)
    
    def list_agents(
        self,
        status: Optional[AgentStatus] = None,
        role: Optional[AgentRole] = None
    ) -> List[Agent]:
        """列出 Agent"""
        agents = list(self.agents.values())
        
        if status:
            agents = [a for a in agents if a.status == status]
        
        if role:
            agents = [a for a in agents if a.config.role == role]
        
        return agents
    
    # ========== 任务管理 ==========
    
    async def submit_task(
        self,
        task: Task,
        auto_assign: bool = True
    ) -> str:
        """
        提交任务
        - auto_assign: 是否自动分配
        """
        # 保存任务
        self.task_manager.add_task(task)
        
        # 自动分配
        if auto_assign:
            await self._assign_task(task)
        
        return task.id
    
    async def _assign_task(self, task: Task):
        """分配任务给合适的 Agent"""
        # 查找可用的 Agent
        candidates = self._find_suitable_agents(task)
        
        if not candidates:
            task.status = 'failed'
            task.error = 'No suitable agent available'
            return
        
        # 选择最佳 Agent
        best_agent = self._select_best_agent(candidates, task)
        
        # 分配任务
        task.assigned_to = best_agent.config.id
        task.status = 'assigned'
        
        # 发送任务给 Agent
        await best_agent.receive_task(task)
        
        # 发布事件
        self.event_bus.publish(Event(
            type='task.assigned',
            data={
                'task_id': task.id,
                'agent_id': best_agent.config.id
            }
        ))
    
    def _find_suitable_agents(self, task: Task) -> List[Agent]:
        """查找适合执行任务的 Agent"""
        suitable = []
        
        for agent in self.agents.values():
            # 检查状态
            if agent.status != AgentStatus.IDLE:
                continue
            
            # 检查能力
            if not self._agent_can_handle(agent, task):
                continue
            
            # 检查负载
            if agent.current_load >= agent.config.capabilities.max_concurrent_tasks:
                continue
            
            suitable.append(agent)
        
        return suitable
    
    def _agent_can_handle(self, agent: Agent, task: Task) -> bool:
        """检查 Agent 是否能处理任务"""
        # 检查技能匹配
        required_skills = task.metadata.get('required_skills', [])
        agent_skills = agent.config.skills
        
        for skill in required_skills:
            if skill not in agent_skills:
                return False
        
        return True
    
    def _select_best_agent(
        self,
        candidates: List[Agent],
        task: Task
    ) -> Agent:
        """选择最佳 Agent"""
        # 评分算法
        scored = []
        for agent in candidates:
            score = self._score_agent(agent, task)
            scored.append((score, agent))
        
        # 返回最高分
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]
    
    def _score_agent(self, agent: Agent, task: Task) -> float:
        """对 Agent 评分"""
        score = 0.0
        
        # 技能匹配度
        required_skills = task.metadata.get('required_skills', [])
        match_ratio = len(set(required_skills) & set(agent.config.skills)) / max(len(required_skills), 1)
        score += match_ratio * 40
        
        # 当前负载 (负载越低分越高)
        load_ratio = 1 - (agent.current_load / agent.config.capabilities.max_concurrent_tasks)
        score += load_ratio * 30
        
        # 历史成功率
        success_rate = agent.get_success_rate()
        score += success_rate * 30
        
        return score
    
    # ========== 任务协调 ==========
    
    async def decompose_task(self, task: Task) -> List[Task]:
        """
        分解复杂任务为子任务
        使用协调 Agent 进行任务分解
        """
        # 调用协调 Agent
        subtasks = await self.coordinator.decompose_task(task)
        
        # 建立依赖关系
        for i, subtask in enumerate(subtasks):
            if i > 0:
                subtask.dependencies.append(subtasks[i-1].id)
        
        return subtasks
    
    async def execute_workflow(
        self,
        workflow: Workflow
    ) -> WorkflowResult:
        """
        执行工作流
        """
        # 初始化工作流
        workflow.initialize()
        
        # 执行每个步骤
        for step in workflow.steps:
            # 创建任务
            task = Task(
                title=step.name,
                description=step.description,
                content=step.content,
                metadata=step.metadata
            )
            
            # 分配和执行
            await self.submit_task(task, auto_assign=True)
            
            # 等待完成
            await task.wait_for_completion()
            
            # 检查结果
            if task.status == 'failed':
                workflow.status = 'failed'
                workflow.error = task.error
                break
        
        return workflow.get_result()
    
    # ========== 事件处理 ==========
    
    def _subscribe_events(self):
        """订阅事件"""
        self.event_bus.subscribe('task.completed', self._on_task_completed)
        self.event_bus.subscribe('task.failed', self._on_task_failed)
        self.event_bus.subscribe('agent.status_changed', self._on_agent_status_changed)
    
    async def _on_task_completed(self, event: Event):
        """任务完成处理"""
        task_id = event.data['task_id']
        task = self.task_manager.get_task(task_id)
        
        if task:
            # 更新 Agent 状态
            if task.assigned_to:
                agent = self.get_agent(task.assigned_to)
                if agent:
                    agent.complete_task(task)
            
            # 检查是否有依赖此任务的其他任务
            dependent_tasks = self.task_manager.get_dependent_tasks(task_id)
            for dep_task in dependent_tasks:
                if self._all_dependencies_met(dep_task):
                    await self._assign_task(dep_task)
    
    async def _on_task_failed(self, event: Event):
        """任务失败处理"""
        task_id = event.data['task_id']
        task = self.task_manager.get_task(task_id)
        
        if task:
            # 重试逻辑
            retry_count = task.metadata.get('retry_count', 0)
            max_retries = task.metadata.get('max_retries', 3)
            
            if retry_count < max_retries:
                # 重新分配
                task.metadata['retry_count'] = retry_count + 1
                task.status = 'pending'
                task.assigned_to = None
                await self._assign_task(task)
            else:
                # 超过最大重试次数，标记为失败
                task.status = 'failed'
    
    def _all_dependencies_met(self, task: Task) -> bool:
        """检查所有依赖是否满足"""
        for dep_id in task.dependencies:
            dep_task = self.task_manager.get_task(dep_id)
            if not dep_task or dep_task.status != 'completed':
                return False
        return True
```

### 3.2 Agent 实现

```python
class Agent:
    """
    Agent 基类
    """
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self.status = AgentStatus.OFFLINE
        self.current_tasks: List[Task] = []
        self.completed_tasks: List[Task] = []
        self.failed_tasks: List[Task] = []
        
        # 组件
        self.llm = self._create_llm()
        self.memory = None
        self.skills = {}
        
        # 消息队列
        self.message_queue = asyncio.Queue()
        
        # 状态
        self._running = False
    
    def initialize(self):
        """初始化 Agent"""
        # 初始化 LLM
        self.llm = self._create_llm()
        
        # 初始化记忆系统
        if self.config.memory_enabled:
            self.memory = MemoryManager(
                db_path="data/memory.db",
                agent_id=self.config.id
            )
        
        # 加载技能
        self._load_skills()
        
        # 更新状态
        self.status = AgentStatus.IDLE
    
    def _create_llm(self) -> LLMProvider:
        """创建 LLM 实例"""
        provider_map = {
            'openai': OpenAIProvider,
            'anthropic': AnthropicProvider
        }
        
        provider_class = provider_map.get(self.config.llm_provider)
        if not provider_class:
            raise ValueError(f"Unknown LLM provider: {self.config.llm_provider}")
        
        return provider_class(
            model=self.config.llm_model,
            **self.config.llm_config
        )
    
    def _load_skills(self):
        """加载技能"""
        skill_manager = SkillManager()
        for skill_name in self.config.skills:
            skill = skill_manager.load_skill(skill_name)
            self.skills[skill_name] = skill
    
    async def receive_message(self, message: Message):
        """接收消息"""
        await self.message_queue.put(message)
        
        # 如果空闲，开始处理
        if self.status == AgentStatus.IDLE:
            asyncio.create_task(self._process_messages())
    
    async def receive_task(self, task: Task):
        """接收任务"""
        self.current_tasks.append(task)
        self.status = AgentStatus.BUSY
        
        # 开始执行任务
        asyncio.create_task(self._execute_task(task))
    
    async def _process_messages(self):
        """处理消息队列"""
        self._running = True
        
        while self._running and not self.message_queue.empty():
            message = await self.message_queue.get()
            
            try:
                # 生成响应
                response = await self._generate_response(message)
                
                # 发送响应
                await self._send_response(message, response)
                
            except Exception as e:
                logger.error(f"Error processing message: {e}")
            
            self.message_queue.task_done()
        
        if self.message_queue.empty():
            self.status = AgentStatus.IDLE
    
    async def _execute_task(self, task: Task):
        """执行任务"""
        task.started_at = datetime.now()
        task.status = 'running'
        
        try:
            # 构建提示词
            prompt = self._build_task_prompt(task)
            
            # 调用 LLM
            response = await self.llm.generate_completion(
                prompt=prompt,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens
            )
            
            # 执行技能 (如果需要)
            if task.metadata.get('requires_skill'):
                skill_name = task.metadata['requires_skill']
                if skill_name in self.skills:
                    result = await self.skills[skill_name].execute(task)
                    response = result
            
            # 更新任务状态
            task.result = response
            task.status = 'completed'
            task.progress = 1.0
            
            # 移动到完成列表
            self.completed_tasks.append(task)
            self.current_tasks.remove(task)
            
        except Exception as e:
            task.error = str(e)
            task.status = 'failed'
            self.failed_tasks.append(task)
            self.current_tasks.remove(task)
        
        finally:
            task.completed_at = datetime.now()
            
            # 更新状态
            if not self.current_tasks:
                self.status = AgentStatus.IDLE
        
        # 发布事件
        self._publish_task_event(task)
    
    async def _generate_response(self, message: Message) -> str:
        """生成消息响应"""
        # 获取上下文记忆
        context_memories = []
        if self.memory:
            context_memories = self.memory.get_context_memories(
                query=message.content,
                max_count=5
            )
        
        # 构建提示词
        prompt = self._build_chat_prompt(message, context_memories)
        
        # 调用 LLM
        response = await self.llm.generate_chat(
            messages=prompt,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens
        )
        
        # 存储记忆
        if self.memory:
            self.memory.add_memory(Memory(
                id=generate_id(),
                agent_id=self.config.id,
                type=MemoryType.SHORT_TERM,
                category=MemoryCategory.CONVERSATION,
                content=message.content
            ))
        
        return response
    
    def _build_task_prompt(self, task: Task) -> str:
        """构建任务提示词"""
        prompt_parts = []
        
        # 系统提示词
        if self.config.system_prompt:
            prompt_parts.append(self.config.system_prompt)
        
        # 任务信息
        prompt_parts.append(f"""
# Task
**Title**: {task.title}
**Description**: {task.description}
**Content**: {task.content}

Please complete this task step by step.
""")
        
        return "\n\n".join(prompt_parts)
    
    def _build_chat_prompt(
        self,
        message: Message,
        context_memories: List[Memory]
    ) -> List[Dict]:
        """构建聊天提示词"""
        messages = []
        
        # 系统提示词
        if self.config.system_prompt:
            messages.append({
                'role': 'system',
                'content': self.config.system_prompt
            })
        
        # 添加上下文记忆
        if context_memories:
            context_text = "Relevant memories:\n"
            for mem in context_memories:
                context_text += f"- {mem.content}\n"
            messages.append({
                'role': 'system',
                'content': context_text
            })
        
        # 用户消息
        messages.append({
            'role': 'user',
            'content': message.content
        })
        
        return messages
    
    async def _send_response(self, original_message: Message, response: str):
        """发送响应"""
        response_message = Message(
            type=MessageType.TEXT,
            source=MessageSource.AGENT,
            sender_id=self.config.id,
            receiver_id=original_message.sender_id,
            content=response,
            reply_to=original_message.id
        )
        
        # 通过路由器发送
        await self.message_router.send_message(response_message)
    
    def _publish_task_event(self, task: Task):
        """发布任务事件"""
        event_type = 'task.completed' if task.status == 'completed' else 'task.failed'
        
        self.event_bus.publish(Event(
            type=event_type,
            data={
                'task_id': task.id,
                'agent_id': self.config.id,
                'result': task.result,
                'error': task.error
            }
        ))
    
    def complete_task(self, task: Task):
        """标记任务完成"""
        if task in self.current_tasks:
            self.current_tasks.remove(task)
        
        if not self.current_tasks:
            self.status = AgentStatus.IDLE
    
    def get_success_rate(self) -> float:
        """获取成功率"""
        total = len(self.completed_tasks) + len(self.failed_tasks)
        if total == 0:
            return 0.0
        return len(self.completed_tasks) / total
    
    @property
    def current_load(self) -> int:
        """当前负载"""
        return len(self.current_tasks)
    
    def shutdown(self):
        """关闭 Agent"""
        self._running = False
        self.status = AgentStatus.OFFLINE
```

## 4. 协调 Agent

### 4.1 协调器实现

```python
class CoordinatorAgent(Agent):
    """
    协调 Agent
    负责任务分解、资源分配、冲突解决
    """
    
    def __init__(self, config: AgentConfig = None):
        if not config:
            config = AgentConfig(
                name="Coordinator",
                role=AgentRole.COORDINATOR,
                system_prompt="""You are a coordinator responsible for:
1. Decomposing complex tasks into smaller subtasks
2. Assigning tasks to appropriate agents
3. Resolving conflicts between agents
4. Monitoring overall workflow progress

Always think step by step and make optimal decisions.""",
                skills=['task_decomposition', 'resource_allocation']
            )
        
        super().__init__(config)
    
    async def decompose_task(self, task: Task) -> List[Task]:
        """
        分解任务为子任务
        """
        # 构建分解提示词
        prompt = f"""
Please decompose the following task into smaller, manageable subtasks:

**Task**: {task.title}
**Description**: {task.description}
**Content**: {task.content}

For each subtask, provide:
1. Title
2. Description
3. Required skills
4. Estimated complexity (1-10)
5. Dependencies (if any)

Format the response as JSON array.
"""
        
        # 调用 LLM
        response = await self.llm.generate_completion(prompt)
        
        # 解析响应
        try:
            subtasks_data = json.loads(response)
            subtasks = []
            
            for i, data in enumerate(subtasks_data):
                subtask = Task(
                    title=data['title'],
                    description=data['description'],
                    content=f"Subtask {i+1} of {task.id}",
                    metadata={
                        'required_skills': data.get('required_skills', []),
                        'complexity': data.get('complexity', 5),
                        'parent_task_id': task.id
                    }
                )
                subtasks.append(subtask)
            
            return subtasks
        except Exception as e:
            logger.error(f"Failed to decompose task: {e}")
            # 返回原任务
            return [task]
    
    async def resolve_conflict(
        self,
        agent1: str,
        agent2: str,
        conflict: str
    ) -> str:
        """解决 Agent 间冲突"""
        prompt = f"""
There is a conflict between agents:
- Agent 1: {agent1}
- Agent 2: {agent2}
- Conflict: {conflict}

Please provide a resolution strategy.
"""
        
        response = await self.llm.generate_completion(prompt)
        return response
```

## 5. 群聊机制

### 5.1 Agent 群组

```python
class AgentGroup:
    """
    Agent 群组
    支持多 Agent 讨论和协作
    """
    
    def __init__(
        self,
        name: str,
        members: List[str],
        orchestrator: AgentOrchestrator
    ):
        self.name = name
        self.member_ids = members
        self.orchestrator = orchestrator
        self.message_history: List[Message] = []
        self.max_history = 100  # 最多保留 100 条消息
        
        # 风暴防护
        self.storm_preventer = MessageStormPreventer()
        
        # 话题跟踪
        self.current_topics: Dict[str, List[str]] = {}
    
    async def send_message(
        self,
        from_agent: str,
        content: str,
        topic: Optional[str] = None
    ):
        """发送消息到群组"""
        # 检查风暴限制
        for member_id in self.member_ids:
            if not await self.storm_preventer.check_and_throttle(
                from_agent, member_id, content
            ):
                logger.warning(f"Message throttled: {from_agent} -> {member_id}")
                return
        
        # 创建消息
        message = Message(
            type=MessageType.TEXT,
            source=MessageSource.AGENT,
            channel=ChannelType.INTERNAL,
            sender_id=from_agent,
            group_id=self.name,
            content=content,
            metadata={'topic': topic} if topic else {}
        )
        
        # 添加到历史
        self.message_history.append(message)
        if len(self.message_history) > self.max_history:
            self.message_history.pop(0)
        
        # 更新话题
        if topic:
            if topic not in self.current_topics:
                self.current_topics[topic] = []
            self.current_topics[topic].append(content)
        
        # 广播给所有成员
        for member_id in self.member_ids:
            if member_id != from_agent:
                agent = self.orchestrator.get_agent(member_id)
                if agent:
                    await agent.receive_message(message)
    
    async def discuss_topic(
        self,
        topic: str,
        initiator: str,
        max_rounds: int = 5
    ) -> str:
        """
        组织话题讨论
        返回讨论总结
        """
        # 发送初始话题
        await self.send_message(
            from_agent=initiator,
            content=f"Let's discuss: {topic}",
            topic=topic
        )
        
        # 收集观点
        contributions = []
        for round in range(max_rounds):
            # 每个成员发表观点
            for member_id in self.member_ids:
                agent = self.orchestrator.get_agent(member_id)
                if agent and agent.status == AgentStatus.IDLE:
                    # 请求观点
                    prompt = f"Please share your thoughts on: {topic}"
                    response = await agent.generate_response(prompt)
                    contributions.append({
                        'agent': member_id,
                        'content': response
                    })
                    
                    # 分享到群组
                    await self.send_message(
                        from_agent=member_id,
                        content=response,
                        topic=topic
                    )
        
        # 总结讨论
        summary = await self._summarize_discussion(topic, contributions)
        return summary
    
    async def _summarize_discussion(
        self,
        topic: str,
        contributions: List[Dict]
    ) -> str:
        """总结讨论"""
        # 使用协调 Agent 总结
        coordinator = self.orchestrator.coordinator
        
        prompt = f"""
Please summarize the following discussion on "{topic}":

{json.dumps(contributions, indent=2)}

Provide a concise summary with key points and conclusions.
"""
        
        summary = await coordinator.llm.generate_completion(prompt)
        return summary
```

## 6. 工作流引擎

### 6.1 工作流定义

```python
@dataclass
class WorkflowStep:
    """工作流步骤"""
    id: str
    name: str
    description: str
    content: str
    agent_role: Optional[str] = None
    required_skills: List[str] = field(default_factory=list)
    timeout: int = 300
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Workflow:
    """工作流"""
    id: str = field(default_factory=lambda: f"wf_{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    steps: List[WorkflowStep] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed
    error: Optional[str] = None
    results: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def initialize(self):
        """初始化工作流"""
        self.status = 'running'
        self.started_at = datetime.now()
    
    def get_result(self) -> Dict:
        """获取结果"""
        return {
            'workflow_id': self.id,
            'name': self.name,
            'status': self.status,
            'results': self.results,
            'error': self.error,
            'duration': (self.completed_at or datetime.now() - self.started_at).total_seconds()
        }

class WorkflowEngine:
    """
    工作流引擎
    执行和管理复杂工作流
    """
    
    def __init__(self, orchestrator: AgentOrchestrator):
        self.orchestrator = orchestrator
        self.active_workflows: Dict[str, Workflow] = {}
    
    async def execute_workflow(self, workflow: Workflow) -> WorkflowResult:
        """执行工作流"""
        self.active_workflows[workflow.id] = workflow
        
        try:
            workflow.initialize()
            
            # 执行每个步骤
            for step in workflow.steps:
                # 创建任务
                task = Task(
                    title=step.name,
                    description=step.description,
                    content=step.content,
                    metadata={
                        'required_skills': step.required_skills,
                        'timeout': step.timeout
                    }
                )
                
                # 分配合适的 Agent
                if step.agent_role:
                    agents = self.orchestrator.list_agents(
                        role=AgentRole(step.agent_role)
                    )
                    if agents:
                        task.assigned_to = agents[0].config.id
                
                # 执行任务
                await self.orchestrator.submit_task(task, auto_assign=True)
                await task.wait_for_completion(timeout=step.timeout)
                
                # 检查结果
                if task.status == 'failed':
                    workflow.status = 'failed'
                    workflow.error = task.error
                    break
                
                # 保存结果
                workflow.results[step.id] = task.result
            
            # 更新状态
            workflow.status = 'completed'
            workflow.completed_at = datetime.now()
            
            return workflow.get_result()
            
        except Exception as e:
            workflow.status = 'failed'
            workflow.error = str(e)
            raise
        finally:
            del self.active_workflows[workflow.id]
```

## 7. 配置示例

### 7.1 Agent 配置

```yaml
# agents.yaml
agents:
  - id: "assistant"
    name: "智能助手"
    role: "worker"
    llm:
      provider: "openai"
      model: "gpt-4"
    skills:
      - "conversation"
      - "search"
      - "calculator"
    system_prompt: |
      You are a helpful assistant.
      Always be polite and provide accurate information.
    temperature: 0.7
    max_tokens: 2048
    
  - id: "analyst"
    name: "数据分析师"
    role: "specialist"
    llm:
      provider: "anthropic"
      model: "claude-3-opus"
    skills:
      - "data_analysis"
      - "statistics"
      - "visualization"
    system_prompt: |
      You are a data analyst expert.
      Provide detailed analysis and insights.
    temperature: 0.5
    
  - id: "coordinator"
    name: "协调员"
    role: "coordinator"
    llm:
      provider: "openai"
      model: "gpt-4"
    skills:
      - "task_decomposition"
      - "resource_allocation"
    system_prompt: |
      You are a coordinator.
      Decompose tasks and assign to appropriate agents.
```
