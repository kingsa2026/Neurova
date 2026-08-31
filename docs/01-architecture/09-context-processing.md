# 上下文处理架构设计

## 1. 概述

### 1.1 设计目标

上下文处理系统是 Neurova 框架的核心组件,负责:
- 管理和维护 Agent 的对话上下文
- 为 LLM 构建高效的上下文窗口
- 智能控制上下文大小,避免超出 token 限制
- 上下文压缩和摘要生成
- 多轮对话上下文保持
- 跨 Agent 上下文共享

### 1.2 上下文分类

```
上下文系统
├── 对话上下文 (Dialogue Context)
│   ├── 当前对话历史
│   ├── 对话主题/意图
│   └── 对话状态
│
├── 记忆上下文 (Memory Context)
│   ├── 相关记忆片段
│   ├── 情感关联记忆
│   └── 用户偏好/特征
│
├── 系统上下文 (System Context)
│   ├── 系统提示词
│   ├── Agent 角色/人格
│   └── 能力/限制说明
│
├── 任务上下文 (Task Context)
│   ├── 当前任务信息
│   ├── 子任务状态
│   └── 任务约束条件
│
└── 环境上下文 (Environment Context)
    ├── 时间/地点信息
    ├── 可用工具/Skill
    └── 外部资源状态
```

## 2. 上下文数据模型

### 2.1 核心数据结构

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
import json
import uuid

class ContextType(Enum):
    """上下文类型"""
    DIALOGUE = "dialogue"
    MEMORY = "memory"
    SYSTEM = "system"
    TASK = "task"
    ENVIRONMENT = "environment"

class ContextPriority(Enum):
    """上下文优先级"""
    CRITICAL = 0    # 关键上下文,不可丢弃
    HIGH = 1        # 高优先级
    NORMAL = 2      # 普通优先级
    LOW = 3         # 低优先级,可被压缩/丢弃

@dataclass
class ContextMessage:
    """对话消息对象"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    role: str = "user"  # user, assistant, system, tool
    content: str = ""
    name: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Token 信息
    token_count: Optional[int] = None
    
    # 关联信息
    relates_to_memory_ids: List[str] = field(default_factory=list)
    relates_to_task_id: Optional[str] = None
    
    def estimate_tokens(self) -> int:
        """估算 token 数量"""
        # 简单估算: 1 个中文字符 ≈ 1.5 tokens, 1 个英文单词 ≈ 1.3 tokens
        chinese_chars = sum(1 for c in self.content if '\u4e00' <= c <= '\u9fff')
        english_words = len([w for w in self.content.split() if w.isascii()])
        return int(chinese_chars * 1.5 + english_words * 1.3) + 10  # 加上 role 等开销
    
    def to_llm_format(self) -> Dict:
        """转换为 LLM API 格式"""
        result = {"role": self.role, "content": self.content}
        if self.name:
            result["name"] = self.name
        return result

@dataclass
class Context:
    """上下文容器"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = ""
    session_id: Optional[str] = None
    type: ContextType = ContextType.DIALOGUE
    priority: ContextPriority = ContextPriority.NORMAL
    
    # 内容
    messages: List[ContextMessage] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Token 统计
    total_tokens: int = 0
    
    # 时间信息
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    
    # 标签
    tags: List[str] = field(default_factory=list)
    
    def add_message(self, message: ContextMessage):
        """添加消息并更新 token 计数"""
        self.messages.append(message)
        if message.token_count is None:
            message.token_count = message.estimate_tokens()
        self.total_tokens += message.token_count
        self.updated_at = datetime.now()
    
    def remove_oldest_message(self) -> Optional[ContextMessage]:
        """移除最旧的消息"""
        if self.messages:
            msg = self.messages.pop(0)
            if msg.token_count:
                self.total_tokens -= msg.token_count
            return msg
        return None
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'id': self.id,
            'agent_id': self.agent_id,
            'session_id': self.session_id,
            'type': self.type.value,
            'priority': self.priority.value,
            'messages': [m.to_dict() for m in self.messages],
            'total_tokens': self.total_tokens,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'tags': self.tags
        }
```

### 2.2 上下文片段

```python
@dataclass
class ContextSnippet:
    """上下文片段 - 来自记忆、任务等的上下文信息"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_type: str = ""  # memory, task, environment, etc.
    source_id: str = ""
    content: str = ""
    relevance_score: float = 1.0  # 相关性评分 0.0-1.0
    priority: ContextPriority = ContextPriority.NORMAL
    token_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_system_message(self) -> ContextMessage:
        """转换为系统消息格式"""
        return ContextMessage(
            role="system",
            content=self.content,
            metadata={
                'source_type': self.source_type,
                'source_id': self.source_id,
                'relevance_score': self.relevance_score
            }
        )
```

### 2.3 上下文窗口配置

```python
@dataclass
class ContextWindowConfig:
    """上下文窗口配置"""
    max_tokens: int = 8000  # 最大 token 数
    max_messages: int = 50  # 最大消息数
    system_prompt_reserve: int = 500  # 系统提示词预留 token
    memory_reserve: int = 2000  # 记忆上下文预留 token
    
    # 压缩策略
    compression_enabled: bool = True
    compression_threshold: float = 0.8  # 达到 80% 时开始压缩
    summary_enabled: bool = True  # 是否启用摘要
    summary_ratio: float = 0.1  # 摘要比例为原内容的 10%
    
    # 保留策略
    keep_first_n_messages: int = 1  # 始终保留前 N 条消息
    keep_last_n_messages: int = 5   # 始终保留最后 N 条消息
    keep_system_messages: bool = True  # 保留系统消息
```

## 3. 上下文管理器架构

### 3.1 上下文管理器核心

```python
class ContextManager:
    """
    上下文管理器
    负责上下文的创建、存储、检索、更新和删除
    """
    
    def __init__(self, config: ContextConfig, memory_manager: MemoryManager):
        self.config = config
        self.memory_manager = memory_manager
        self.contexts: Dict[str, Context] = {}
        self.session_contexts: Dict[str, List[str]] = {}  # session_id -> context_ids
        self.context_cache = LRUCache(max_size=100)
    
    # ========== 上下文生命周期管理 ==========
    
    def create_context(
        self,
        agent_id: str,
        context_type: ContextType,
        session_id: Optional[str] = None,
        priority: ContextPriority = ContextPriority.NORMAL,
        config: Optional[ContextWindowConfig] = None
    ) -> Context:
        """
        创建上下文
        1. 生成唯一 ID
        2. 初始化上下文对象
        3. 注册到 session (如果有)
        4. 返回上下文对象
        """
        context = Context(
            agent_id=agent_id,
            session_id=session_id,
            type=context_type,
            priority=priority
        )
        
        # 存储
        self.contexts[context.id] = context
        
        # 注册到 session
        if session_id:
            if session_id not in self.session_contexts:
                self.session_contexts[session_id] = []
            self.session_contexts[session_id].append(context.id)
        
        # 加入缓存
        self.context_cache.put(context.id, context)
        
        return context
    
    def get_context(self, context_id: str) -> Optional[Context]:
        """获取上下文"""
        # 先查缓存
        if context := self.context_cache.get(context_id):
            return context
        
        # 从存储加载
        return self.contexts.get(context_id)
    
    def get_session_contexts(self, session_id: str) -> List[Context]:
        """获取 session 的所有上下文"""
        context_ids = self.session_contexts.get(session_id, [])
        return [self.contexts[cid] for cid in context_ids if cid in self.contexts]
    
    def update_context(self, context_id: str, updates: Dict) -> bool:
        """更新上下文"""
        context = self.get_context(context_id)
        if not context:
            return False
        
        for key, value in updates.items():
            if hasattr(context, key):
                setattr(context, key, value)
        
        context.updated_at = datetime.now()
        return True
    
    def delete_context(self, context_id: str) -> bool:
        """删除上下文"""
        if context_id not in self.contexts:
            return False
        
        context = self.contexts[context_id]
        
        # 从 session 中移除
        if context.session_id:
            session_ctx = self.session_contexts.get(context.session_id, [])
            if context_id in session_ctx:
                session_ctx.remove(context_id)
        
        # 删除
        del self.contexts[context_id]
        self.context_cache.remove(context_id)
        return True
    
    # ========== 上下文操作 ==========
    
    def add_message_to_context(
        self,
        context_id: str,
        message: ContextMessage
    ) -> bool:
        """添加消息到上下文"""
        context = self.get_context(context_id)
        if not context:
            return False
        
        context.add_message(message)
        return True
    
    def get_context_messages(
        self,
        context_id: str,
        limit: Optional[int] = None
    ) -> List[ContextMessage]:
        """获取上下文消息"""
        context = self.get_context(context_id)
        if not context:
            return []
        
        if limit:
            return context.messages[-limit:]
        return context.messages
    
    # ========== 上下文管理 ==========
    
    def cleanup_expired_contexts(self):
        """清理过期上下文"""
        now = datetime.now()
        expired_ids = [
            cid for cid, ctx in self.contexts.items()
            if ctx.expires_at and ctx.expires_at < now
        ]
        
        for ctx_id in expired_ids:
            self.delete_context(ctx_id)
    
    def consolidate_contexts(self):
        """合并相关上下文"""
        # 找出同一 session 的上下文
        for session_id, context_ids in self.session_contexts.items():
            if len(context_ids) < 2:
                continue
            
            contexts = [self.contexts[cid] for cid in context_ids if cid in self.contexts]
            
            # 合并相同类型的上下文
            grouped = {}
            for ctx in contexts:
                if ctx.type not in grouped:
                    grouped[ctx.type] = []
                grouped[ctx.type].append(ctx)
            
            for ctx_type, ctx_list in grouped.items():
                if len(ctx_list) > 1:
                    self._merge_contexts(ctx_list)
    
    def _merge_contexts(self, contexts: List[Context]):
        """合并多个上下文"""
        if not contexts:
            return
        
        # 保留第一个上下文
        primary = contexts[0]
        
        # 合并其他上下文的消息
        for ctx in contexts[1:]:
            for msg in ctx.messages:
                primary.add_message(msg)
            
            # 删除已合并的上下文
            self.delete_context(ctx.id)
```

### 3.2 上下文会话管理

```python
class ContextSession:
    """
    上下文会话
    管理单个会话的完整上下文生命周期
    """
    
    def __init__(
        self,
        session_id: str,
        agent_id: str,
        context_manager: ContextManager,
        config: Optional[ContextWindowConfig] = None
    ):
        self.session_id = session_id
        self.agent_id = agent_id
        self.context_manager = context_manager
        self.config = config or ContextWindowConfig()
        
        # 创建主对话上下文
        self.dialogue_context = context_manager.create_context(
            agent_id=agent_id,
            context_type=ContextType.DIALOGUE,
            session_id=session_id,
            priority=ContextPriority.CRITICAL
        )
        
        # 上下文历史
        self.message_history: List[ContextMessage] = []
        self.summary: Optional[str] = None
    
    def add_user_message(self, content: str) -> ContextMessage:
        """添加用户消息"""
        message = ContextMessage(
            role="user",
            content=content
        )
        self.dialogue_context.add_message(message)
        self.message_history.append(message)
        return message
    
    def add_assistant_message(self, content: str) -> ContextMessage:
        """添加助手消息"""
        message = ContextMessage(
            role="assistant",
            content=content
        )
        self.dialogue_context.add_message(message)
        self.message_history.append(message)
        return message
    
    def add_system_message(self, content: str) -> ContextMessage:
        """添加系统消息"""
        message = ContextMessage(
            role="system",
            content=content,
            timestamp=datetime.now()
        )
        self.dialogue_context.add_message(message)
        return message
    
    def get_context_for_llm(self) -> List[Dict]:
        """获取用于 LLM 的上下文"""
        # 1. 获取窗口内的消息
        messages = self._get_window_messages()
        
        # 2. 转换为 LLM 格式
        return [msg.to_llm_format() for msg in messages]
    
    def _get_window_messages(self) -> List[ContextMessage]:
        """获取窗口内的消息"""
        # 应用窗口策略
        all_messages = self.dialogue_context.messages
        
        if len(all_messages) <= self.config.keep_first_n_messages + self.config.keep_last_n_messages:
            return all_messages
        
        # 保留首尾
        first_n = all_messages[:self.config.keep_first_n_messages]
        last_n = all_messages[-self.config.keep_last_n_messages:]
        
        # 中间部分可能需要摘要
        middle = all_messages[self.config.keep_first_n_messages:-self.config.keep_last_n_messages]
        
        return first_n + middle + last_n
    
    def generate_summary(self) -> str:
        """生成对话摘要"""
        if not self.message_history:
            return ""
        
        # 提取关键信息
        topics = self._extract_topics()
        decisions = self._extract_decisions()
        user_preferences = self._extract_user_preferences()
        
        # 构建摘要
        summary_parts = []
        
        if topics:
            summary_parts.append(f"讨论主题: {', '.join(topics)}")
        
        if decisions:
            summary_parts.append(f"达成决策: {', '.join(decisions)}")
        
        if user_preferences:
            summary_parts.append(f"用户偏好: {', '.join(user_preferences)}")
        
        self.summary = " | ".join(summary_parts)
        return self.summary
    
    def _extract_topics(self) -> List[str]:
        """提取对话主题"""
        # 使用关键词提取或 LLM 生成
        pass
    
    def _extract_decisions(self) -> List[str]:
        """提取达成的决策"""
        # 分析对话中的决策点
        pass
    
    def _extract_user_preferences(self) -> List[str]:
        """提取用户偏好"""
        # 分析用户表达的偏好
        pass
```

## 4. 上下文构建器架构

### 4.1 上下文构建器核心

```python
class ContextBuilder:
    """
    上下文构建器
    负责为 LLM 构建完整的上下文
    """
    
    def __init__(
        self,
        context_manager: ContextManager,
        memory_manager: MemoryManager,
        emotion_engine: EmotionEngine,
        config: ContextWindowConfig
    ):
        self.context_manager = context_manager
        self.memory_manager = memory_manager
        self.emotion_engine = emotion_engine
        self.config = config
    
    def build_context_for_query(
        self,
        agent_id: str,
        query: str,
        session_id: Optional[str] = None
    ) -> List[Dict]:
        """
        为查询构建完整上下文
        返回 LLM API 可用的消息列表
        """
        messages = []
        
        # 1. 添加系统提示词
        system_prompt = self._build_system_prompt(agent_id)
        messages.append(ContextMessage(role="system", content=system_prompt))
        
        # 2. 添加相关记忆上下文
        memory_contexts = self._get_memory_context(agent_id, query)
        for ctx in memory_contexts:
            messages.append(ctx.to_system_message())
        
        # 3. 添加对话历史
        if session_id:
            session = self._get_or_create_session(session_id, agent_id)
            dialogue_messages = session.get_context_for_llm()
            messages.extend(dialogue_messages)
        
        # 4. 添加当前查询
        messages.append(ContextMessage(role="user", content=query))
        
        # 5. 检查并控制 token 数量
        messages = self._fit_to_token_limit(messages)
        
        return [m.to_llm_format() for m in messages]
    
    def _build_system_prompt(self, agent_id: str) -> str:
        """
        构建系统提示词
        包含: Agent 角色、能力、约束、行为准则
        """
        agent_config = self._get_agent_config(agent_id)
        
        prompt_parts = []
        
        # 角色定义
        if agent_config.get('role'):
            prompt_parts.append(f"你是{agent_config['role']}。")
        
        # 能力说明
        if agent_config.get('capabilities'):
            capabilities = ', '.join(agent_config['capabilities'])
            prompt_parts.append(f"你的能力包括: {capabilities}。")
        
        # 行为准则
        if agent_config.get('guidelines'):
            prompt_parts.append(f"行为准则: {agent_config['guidelines']}。")
        
        # 当前时间
        prompt_parts.append(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}。")
        
        return " ".join(prompt_parts)
    
    def _get_memory_context(
        self,
        agent_id: str,
        query: str,
        max_tokens: int = 2000
    ) -> List[ContextSnippet]:
        """
        获取相关记忆上下文
        """
        # 从记忆系统检索相关记忆
        memories = self.memory_manager.search_memories(
            query=query,
            limit=10
        )
        
        # 转换为上下文片段
        snippets = []
        total_tokens = 0
        
        for memory in memories:
            snippet = ContextSnippet(
                source_type="memory",
                source_id=memory.id,
                content=memory.content,
                relevance_score=memory.weight,
                priority=ContextPriority.HIGH if memory.weight > 0.8 else ContextPriority.NORMAL
            )
            snippet.token_count = snippet.estimate_tokens()
            
            # 检查 token 限制
            if total_tokens + snippet.token_count > max_tokens:
                break
            
            snippets.append(snippet)
            total_tokens += snippet.token_count
        
        return snippets
    
    def _fit_to_token_limit(
        self,
        messages: List[ContextMessage]
    ) -> List[ContextMessage]:
        """
        将消息列表适配到 token 限制内
        """
        total_tokens = sum(m.estimate_tokens() for m in messages)
        max_tokens = self.config.max_tokens - self.config.system_prompt_reserve
        
        if total_tokens <= max_tokens:
            return messages
        
        # 需要压缩或截断
        return self._compress_messages(messages, max_tokens)
    
    def _compress_messages(
        self,
        messages: List[ContextMessage],
        max_tokens: int
    ) -> List[ContextMessage]:
        """压缩消息列表"""
        # 优先级: 保留系统消息 > 高优先级 > 普通 > 低优先级
        
        # 1. 分离不可压缩的消息
        critical = [m for m in messages if m.role == "system"]
        critical_tokens = sum(m.estimate_tokens() for m in critical)
        
        # 2. 可压缩的消息
        compressible = [m for m in messages if m.role != "system"]
        
        # 3. 按优先级排序
        compressible.sort(key=lambda m: m.metadata.get('priority', ContextPriority.NORMAL).value)
        
        # 4. 从低优先级开始移除
        result = critical.copy()
        available_tokens = max_tokens - critical_tokens
        
        for msg in compressible:
            msg_tokens = msg.estimate_tokens()
            if msg_tokens <= available_tokens:
                result.append(msg)
                available_tokens -= msg_tokens
        
        return result
```

### 4.2 系统提示词构建器

```python
class SystemPromptBuilder:
    """
    系统提示词构建器
    负责动态构建系统提示词
    """
    
    def __init__(self):
        self.templates: Dict[str, str] = {}
    
    def build(
        self,
        agent_config: Dict,
        context_info: Optional[Dict] = None,
        capabilities: Optional[List[str]] = None,
        constraints: Optional[List[str]] = None
    ) -> str:
        """构建系统提示词"""
        sections = []
        
        # 1. 身份定义
        sections.append(self._build_identity(agent_config))
        
        # 2. 行为准则
        sections.append(self._build_guidelines(agent_config))
        
        # 3. 能力说明
        if capabilities:
            sections.append(self._build_capabilities(capabilities))
        
        # 4. 约束条件
        if constraints:
            sections.append(self._build_constraints(constraints))
        
        # 5. 上下文信息
        if context_info:
            sections.append(self._build_context_info(context_info))
        
        return "\n\n".join(sections)
    
    def _build_identity(self, config: Dict) -> str:
        """构建身份定义"""
        name = config.get('name', 'AI助手')
        role = config.get('role', '通用助手')
        
        return f"你是 {name}, 一个{role}。"
    
    def _build_guidelines(self, config: Dict) -> str:
        """构建行为准则"""
        guidelines = config.get('guidelines', [])
        if isinstance(guidelines, list):
            return "行为准则:\n" + "\n".join(f"- {g}" for g in guidelines)
        return f"行为准则: {guidelines}"
    
    def _build_capabilities(self, capabilities: List[str]) -> str:
        """构建能力说明"""
        return "你可以使用以下能力:\n" + "\n".join(f"- {c}" for c in capabilities)
    
    def _build_constraints(self, constraints: List[str]) -> str:
        """构建约束条件"""
        return "注意以下约束:\n" + "\n".join(f"- {c}" for c in constraints)
    
    def _build_context_info(self, context: Dict) -> str:
        """构建上下文信息"""
        parts = []
        
        if 'time' in context:
            parts.append(f"当前时间: {context['time']}")
        
        if 'location' in context:
            parts.append(f"当前位置: {context['location']}")
        
        if 'user_info' in context:
            parts.append(f"用户信息: {context['user_info']}")
        
        return "上下文信息:\n" + "\n".join(parts)
```

## 5. 上下文窗口管理

### 5.1 上下文窗口管理器

```python
class ContextWindowManager:
    """
    上下文窗口管理器
    负责管理上下文窗口的大小和内容
    """
    
    def __init__(self, config: ContextWindowConfig):
        self.config = config
        self.token_counter = TokenCounter()
    
    def calculate_available_tokens(
        self,
        model_max_tokens: int,
        system_prompt_tokens: int,
        query_tokens: int
    ) -> int:
        """
        计算可用于对话历史的 token 数量
        """
        return model_max_tokens - system_prompt_tokens - query_tokens - 100  # 预留 100 tokens 给响应
    
    def select_messages_for_window(
        self,
        messages: List[ContextMessage],
        available_tokens: int
    ) -> List[ContextMessage]:
        """
        选择适合窗口的消息
        策略:
        1. 始终保留前 N 条消息
        2. 始终保留后 N 条消息
        3. 中间消息按优先级和时间选择
        """
        if not messages:
            return []
        
        # 保留首尾
        first_n = messages[:self.config.keep_first_n_messages]
        last_n = messages[-self.config.keep_last_n_messages:]
        
        first_tokens = sum(m.estimate_tokens() for m in first_n)
        last_tokens = sum(m.estimate_tokens() for m in last_n)
        
        available_for_middle = available_tokens - first_tokens - last_tokens
        
        # 中间消息
        middle = messages[
            self.config.keep_first_n_messages:-self.config.keep_last_n_messages
        ]
        
        selected_middle = self._select_middle_messages(middle, available_for_middle)
        
        return first_n + selected_middle + last_n
    
    def _select_middle_messages(
        self,
        messages: List[ContextMessage],
        available_tokens: int
    ) -> List[ContextMessage]:
        """选择中间消息"""
        # 按相关性/优先级排序
        scored = [
            (self._score_message(m), m)
            for m in messages
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        
        selected = []
        total_tokens = 0
        
        for score, msg in scored:
            msg_tokens = msg.estimate_tokens()
            if total_tokens + msg_tokens <= available_tokens:
                selected.append(msg)
                total_tokens += msg_tokens
        
        # 恢复原始顺序
        selected.sort(key=lambda m: m.timestamp)
        
        return selected
    
    def _score_message(self, message: ContextMessage) -> float:
        """为消息评分"""
        score = 1.0
        
        # 新消息权重更高
        age_hours = (datetime.now() - message.timestamp).total_seconds() / 3600
        recency_score = max(0, 1 - age_hours / 24)  # 24 小时内有效
        score += recency_score * 0.3
        
        # 长消息可能包含更多信息
        length_score = min(len(message.content) / 1000, 1.0)
        score += length_score * 0.2
        
        # 用户消息通常更重要
        if message.role == "user":
            score += 0.2
        
        return score
    
    def check_window_pressure(
        self,
        current_tokens: int,
        max_tokens: int
    ) -> float:
        """
        检查窗口压力
        返回 0.0-1.0, 1.0 表示已满
        """
        return current_tokens / max_tokens
    
    def should_compress(
        self,
        current_tokens: int,
        max_tokens: int
    ) -> bool:
        """判断是否需要压缩"""
        pressure = self.check_window_pressure(current_tokens, max_tokens)
        return pressure >= self.config.compression_threshold
```

### 5.2 Token 计数器

```python
class TokenCounter:
    """
    Token 计数器
    准确计算文本的 token 数量
    """
    
    def __init__(self, model_name: str = "gpt-4"):
        self.model_name = model_name
        self._tiktoken_encoder = None
        self._load_encoder()
    
    def _load_encoder(self):
        """加载 tokenizer"""
        try:
            import tiktoken
            self._tiktoken_encoder = tiktoken.encoding_for_model(self.model_name)
        except ImportError:
            self._tiktoken_encoder = None
    
    def count_tokens(self, text: str) -> int:
        """计算 token 数量"""
        if self._tiktoken_encoder:
            return len(self._tiktoken_encoder.encode(text))
        
        # 回退估算方法
        return self._estimate_tokens(text)
    
    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数量"""
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        english_words = len([w for w in text.split() if w.isascii()])
        
        return int(chinese_chars * 1.5 + english_words * 1.3)
    
    def count_message_tokens(self, messages: List[Dict]) -> int:
        """计算消息列表的 token 数量"""
        total = 0
        for msg in messages:
            # 每条消息有基础开销
            total += 4  # role + content 开销
            
            if 'name' in msg:
                total += 1  # name 开销
            
            total += self.count_tokens(msg.get('content', ''))
        
        total += 2  # 回复的额外开销
        return total
```

## 6. 上下文压缩机制

### 6.1 上下文压缩器

```python
class ContextCompressor:
    """
    上下文压缩器
    使用多种策略压缩上下文
    """
    
    def __init__(
        self,
        llm_provider: LLMProvider,
        config: ContextWindowConfig
    ):
        self.llm_provider = llm_provider
        self.config = config
    
    def compress(
        self,
        messages: List[ContextMessage],
        target_tokens: int,
        strategy: str = "auto"
    ) -> List[ContextMessage]:
        """
        压缩消息列表到目标 token 数量
        """
        current_tokens = sum(m.estimate_tokens() for m in messages)
        
        if current_tokens <= target_tokens:
            return messages
        
        if strategy == "auto":
            return self._auto_compress(messages, target_tokens)
        elif strategy == "summary":
            return self._summary_compress(messages, target_tokens)
        elif strategy == "truncate":
            return self._truncate_compress(messages, target_tokens)
        elif strategy == "selective":
            return self._selective_compress(messages, target_tokens)
        
        return messages
    
    def _auto_compress(
        self,
        messages: List[ContextMessage],
        target_tokens: int
    ) -> List[ContextMessage]:
        """自动压缩 - 组合多种策略"""
        # 策略 1: 摘要中间部分
        result = self._summary_compress(messages, target_tokens)
        
        # 如果还不够,继续选择性压缩
        current_tokens = sum(m.estimate_tokens() for m in result)
        if current_tokens > target_tokens:
            result = self._selective_compress(result, target_tokens)
        
        return result
    
    def _summary_compress(
        self,
        messages: List[ContextMessage],
        target_tokens: int
    ) -> List[ContextMessage]:
        """摘要压缩 - 使用 LLM 生成摘要"""
        if not self.config.summary_enabled:
            return messages
        
        # 保留首尾
        first_n = messages[:self.config.keep_first_n_messages]
        last_n = messages[-self.config.keep_last_n_messages:]
        
        middle = messages[
            self.config.keep_first_n_messages:-self.config.keep_last_n_messages
        ]
        
        if not middle:
            return messages
        
        # 生成中间部分的摘要
        summary = self._generate_summary(middle)
        
        summary_message = ContextMessage(
            role="system",
            content=f"[历史对话摘要]\n{summary}",
            metadata={'compressed': True, 'original_messages': len(middle)}
        )
        
        return first_n + [summary_message] + last_n
    
    def _generate_summary(self, messages: List[ContextMessage]) -> str:
        """使用 LLM 生成摘要"""
        # 构建摘要请求
        conversation_text = "\n".join(
            f"{m.role}: {m.content}" for m in messages
        )
        
        prompt = f"""请总结以下对话的关键信息,包括:
1. 主要讨论的主题
2. 达成的共识或决策
3. 用户的偏好和需求
4. 重要的事实和信息

对话内容:
{conversation_text}

请用简洁的中文总结,不超过 200 字。"""

        try:
            response = self.llm_provider.generate_completion(
                prompt=prompt,
                max_tokens=300
            )
            return response.text
        except Exception as e:
            # 降级为简单摘要
            return self._simple_summary(messages)
    
    def _simple_summary(self, messages: List[ContextMessage]) -> str:
        """简单摘要 - 不依赖 LLM"""
        topics = []
        for msg in messages:
            if len(msg.content) > 50:
                topics.append(msg.content[:50] + "...")
        
        return "历史对话涉及以下主题:\n" + "\n".join(f"- {t}" for t in topics[:5])
    
    def _selective_compress(
        self,
        messages: List[ContextMessage],
        target_tokens: int
    ) -> List[ContextMessage]:
        """选择性压缩 - 按优先级保留重要消息"""
        # 评分并排序
        scored = [
            (self._score_message(m), m)
            for m in messages
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        
        result = []
        total_tokens = 0
        
        for score, msg in scored:
            msg_tokens = msg.estimate_tokens()
            if total_tokens + msg_tokens <= target_tokens:
                result.append(msg)
                total_tokens += msg_tokens
        
        # 恢复原始顺序
        result.sort(key=lambda m: m.timestamp)
        
        return result
    
    def _truncate_compress(
        self,
        messages: List[ContextMessage],
        target_tokens: int
    ) -> List[ContextMessage]:
        """截断压缩 - 从旧到新移除消息"""
        result = []
        total_tokens = 0
        
        # 从新到旧添加,直到达到目标
        for msg in reversed(messages):
            msg_tokens = msg.estimate_tokens()
            if total_tokens + msg_tokens <= target_tokens:
                result.insert(0, msg)
                total_tokens += msg_tokens
        
        return result
    
    def _score_message(self, message: ContextMessage) -> float:
        """为消息评分"""
        score = 1.0
        
        # 新消息权重
        age_hours = (datetime.now() - message.timestamp).total_seconds() / 3600
        score += max(0, 1 - age_hours / 24) * 0.3
        
        # 用户消息权重
        if message.role == "user":
            score += 0.2
        
        # 长消息权重
        score += min(len(message.content) / 1000, 1.0) * 0.2
        
        return score
```

### 6.2 渐进式压缩策略

```python
class ProgressiveCompressor:
    """
    渐进式压缩器
    根据窗口压力逐步应用更激进的压缩策略
    """
    
    def __init__(
        self,
        compressor: ContextCompressor,
        config: ContextWindowConfig
    ):
        self.compressor = compressor
        self.config = config
    
    def compress_by_pressure(
        self,
        messages: List[ContextMessage],
        current_tokens: int,
        max_tokens: int
    ) -> List[ContextMessage]:
        """
        根据压力程度选择压缩策略
        """
        pressure = current_tokens / max_tokens
        
        if pressure < 0.6:
            # 低压: 不压缩
            return messages
        
        elif pressure < 0.8:
            # 中压: 轻度压缩 - 移除低优先级消息
            return self._light_compress(messages, max_tokens)
        
        elif pressure < 0.9:
            # 高压: 中度压缩 - 摘要中间部分
            target = int(max_tokens * 0.7)
            return self.compressor.compress(messages, target, strategy="summary")
        
        else:
            # 极高压: 激进压缩
            target = int(max_tokens * 0.5)
            return self.compressor.compress(messages, target, strategy="auto")
    
    def _light_compress(
        self,
        messages: List[ContextMessage],
        max_tokens: int
    ) -> List[ContextMessage]:
        """轻度压缩"""
        # 移除低优先级和低相关性的消息
        result = []
        total_tokens = 0
        
        for msg in messages:
            priority = msg.metadata.get('priority', ContextPriority.NORMAL)
            
            # 跳过低优先级消息
            if priority == ContextPriority.LOW:
                continue
            
            msg_tokens = msg.estimate_tokens()
            if total_tokens + msg_tokens <= max_tokens:
                result.append(msg)
                total_tokens += msg_tokens
        
        return result
```

## 7. 上下文使用流程

### 7.1 完整对话流程

```
用户输入 → 接收消息
            ↓
   [1] 构建上下文
        ├─ 系统提示词
        ├─ 相关记忆
        ├─ 对话历史
        └─ 任务信息
            ↓
   [2] 检查窗口压力
        ├─ 计算 token 数量
        └─ 是否需要压缩?
            ↓
   [3] 压缩上下文 (如需要)
        ├─ 选择压缩策略
        └─ 执行压缩
            ↓
   [4] 调用 LLM
        ├─ 发送上下文
        └─ 接收响应
            ↓
   [5] 更新上下文
        ├─ 添加用户消息
        ├─ 添加助手响应
        └─ 更新记忆
            ↓
   [6] 返回响应给用户
```

### 7.2 多 Agent 协作上下文流程

```
协调 Agent 接收任务
            ↓
   分解任务到子任务
            ↓
   为每个子任务创建上下文
        ├─ 系统提示词 (子任务角色)
        ├─ 相关记忆
        ├─ 任务描述
        └─ 约束条件
            ↓
   分配给专业 Agent 执行
            ↓
   收集各 Agent 结果
            ↓
   合并上下文
        ├─ 整合子任务结果
        ├─ 生成汇总
        └─ 更新主上下文
            ↓
   返回最终结果
```

## 8. 配置示例

### 8.1 上下文配置

```yaml
# context.yaml
context:
  # 窗口配置
  window:
    max_tokens: 8000
    max_messages: 50
    system_prompt_reserve: 500
    memory_reserve: 2000
    
    keep_first_n_messages: 1
    keep_last_n_messages: 5
    
    # 压缩配置
    compression:
      enabled: true
      threshold: 0.8  # 80% 时开始压缩
      strategy: "auto"  # auto, summary, truncate, selective
      summary_ratio: 0.1
    
    # Token 配置
    token_counter:
      model: "gpt-4"
      use_tiktoken: true
  
  # 会话配置
  session:
    max_duration_minutes: 60
    idle_timeout_minutes: 15
    auto_summary: true
    summary_interval_messages: 20
  
  # 记忆集成
  memory_integration:
    enabled: true
    max_memories: 10
    max_tokens: 2000
    min_relevance_score: 0.5
  
  # 情感集成
  emotion_integration:
    enabled: true
    include_emotion_context: true
    emotion_influence_weight: 0.2
```

### 8.2 Agent 上下文配置

```yaml
# agents/assistant_context.yaml
agent:
  id: "assistant"
  name: "智能助手"
  
  context:
    # 系统提示词模板
    system_prompt:
      template: "default"
      custom_sections:
        - "你善于倾听和理解用户需求"
        - "请用简洁、友好的语言回复"
    
    # 能力上下文
    capabilities:
      - "搜索网络信息"
      - "回答问题"
      - "执行计算"
      - "管理日程"
    
    # 约束上下文
    constraints:
      - "不要提供医疗建议"
      - "不要访问用户隐私数据"
      - "回复不超过 500 字"
    
    # 窗口配置
    window:
      max_tokens: 4000
      keep_last_n_messages: 10
```

## 9. 性能优化

### 9.1 缓存策略

```python
class ContextCache:
    """上下文缓存"""
    
    def __init__(self, max_size: int = 100):
        self.cache = LRUCache(max_size)
        self.hit_count = 0
        self.miss_count = 0
    
    def get(self, key: str) -> Optional[Context]:
        """获取缓存"""
        context = self.cache.get(key)
        if context:
            self.hit_count += 1
        else:
            self.miss_count += 1
        return context
    
    def put(self, key: str, context: Context):
        """存入缓存"""
        self.cache.put(key, context)
    
    def get_hit_rate(self) -> float:
        """获取命中率"""
        total = self.hit_count + self.miss_count
        if total == 0:
            return 0.0
        return self.hit_count / total
```

### 9.2 批量操作

```python
class ContextBatchOperations:
    """上下文批量操作"""
    
    def batch_add_messages(
        self,
        context_id: str,
        messages: List[ContextMessage]
    ):
        """批量添加消息"""
        context = self.context_manager.get_context(context_id)
        if not context:
            return
        
        for msg in messages:
            context.add_message(msg)
        
        # 一次性更新 token 计数
        context.total_tokens = sum(
            m.estimate_tokens() for m in context.messages
        )
    
    def batch_compress(
        self,
        context_ids: List[str],
        target_tokens: int
    ):
        """批量压缩上下文"""
        for ctx_id in context_ids:
            messages = self.context_manager.get_context_messages(ctx_id)
            compressed = self.compressor.compress(messages, target_tokens)
            self.context_manager.update_context(
                ctx_id,
                {'messages': compressed}
            )
```

## 10. 监控指标

### 10.1 关键指标

```python
class ContextMetrics:
    """上下文指标"""
    
    def __init__(self):
        self.total_contexts_created = 0
        self.total_messages_processed = 0
        self.total_compressions = 0
        self.avg_context_size_tokens = 0
        self.avg_compression_ratio = 0.0
        self.window_pressure_events = 0
        self.token_overflows = 0
    
    def record_context_created(self):
        """记录上下文创建"""
        self.total_contexts_created += 1
    
    def record_message_processed(self, token_count: int):
        """记录消息处理"""
        self.total_messages_processed += 1
        self._update_avg_context_size(token_count)
    
    def record_compression(
        self,
        original_tokens: int,
        compressed_tokens: int
    ):
        """记录压缩"""
        self.total_compressions += 1
        ratio = compressed_tokens / original_tokens if original_tokens > 0 else 1.0
        self.avg_compression_ratio = (
            (self.avg_compression_ratio * (self.total_compressions - 1) + ratio)
            / self.total_compressions
        )
    
    def record_window_pressure(self):
        """记录窗口压力事件"""
        self.window_pressure_events += 1
    
    def record_token_overflow(self):
        """记录 token 溢出"""
        self.token_overflows += 1
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            'total_contexts_created': self.total_contexts_created,
            'total_messages_processed': self.total_messages_processed,
            'total_compressions': self.total_compressions,
            'avg_context_size_tokens': self.avg_context_size_tokens,
            'avg_compression_ratio': self.avg_compression_ratio,
            'window_pressure_events': self.window_pressure_events,
            'token_overflows': self.token_overflows
        }
```

## 11. 测试用例

### 11.1 单元测试

```python
def test_context_creation():
    manager = ContextManager(config, memory_manager)
    context = manager.create_context(
        agent_id="test_agent",
        context_type=ContextType.DIALOGUE
    )
    assert context.agent_id == "test_agent"
    assert context.type == ContextType.DIALOGUE

def test_add_message():
    context = Context(agent_id="test")
    message = ContextMessage(role="user", content="你好")
    context.add_message(message)
    assert len(context.messages) == 1
    assert context.total_tokens > 0

def test_context_window():
    config = ContextWindowConfig(max_tokens=1000, keep_last_n_messages=3)
    window_mgr = ContextWindowManager(config)
    
    # 添加超过窗口的消息
    messages = [
        ContextMessage(role="user", content=f"Message {i}")
        for i in range(20)
    ]
    
    selected = window_mgr.select_messages_for_window(messages, 800)
    assert len(selected) <= 20  # 不超过总数

def test_context_compression():
    compressor = ContextCompressor(llm_provider, config)
    messages = [
        ContextMessage(role="user", content="Long message " * 100)
        for _ in range(10)
    ]
    
    compressed = compressor.compress(messages, target_tokens=500)
    compressed_tokens = sum(m.estimate_tokens() for m in compressed)
    assert compressed_tokens <= 500
```

### 11.2 集成测试

```python
def test_full_context_building_flow():
    """测试完整的上下文构建流程"""
    # 初始化组件
    memory_manager = MemoryManager(":memory:", "test_agent")
    context_manager = ContextManager(config, memory_manager)
    builder = ContextBuilder(context_manager, memory_manager, emotion_engine, config)
    
    # 添加一些记忆
    memory_manager.add_memory(Memory(
        id="mem_1",
        agent_id="test_agent",
        type=MemoryType.LONG_TERM,
        category=MemoryCategory.CONVERSATION,
        content="用户喜欢 Python 编程"
    ))
    
    # 构建上下文
    context = builder.build_context_for_query(
        agent_id="test_agent",
        query="Python 学习建议",
        session_id="test_session"
    )
    
    # 验证上下文包含必要部分
    assert any(m['role'] == 'system' for m in context)
    assert any(m['role'] == 'user' for m in context)
    assert len(context) > 0
```

## 12. 扩展点

### 12.1 自定义压缩策略

```python
class CustomCompressor(ContextCompressor):
    """自定义压缩器"""
    
    def my_compression_strategy(
        self,
        messages: List[ContextMessage],
        target_tokens: int
    ) -> List[ContextMessage]:
        """实现自定义压缩逻辑"""
        pass
```

### 12.2 上下文插件

```python
class ContextPlugin(ABC):
    """上下文插件接口"""
    
    @abstractmethod
    def enhance_context(self, context: Context) -> Context:
        """增强上下文"""
        pass
    
    @abstractmethod
    def filter_context(self, context: Context) -> Context:
        """过滤上下文"""
        pass

class TimeAwareContextPlugin(ContextPlugin):
    """时间感知上下文插件"""
    
    def enhance_context(self, context: Context) -> Context:
        # 添加时间相关的上下文信息
        context.metadata['time_of_day'] = self._get_time_period()
        return context
    
    def _get_time_period(self) -> str:
        hour = datetime.now().hour
        if hour < 6:
            return "深夜"
        elif hour < 12:
            return "上午"
        elif hour < 18:
            return "下午"
        else:
            return "晚上"
```

## 13. 与现有系统集成

### 13.1 与记忆系统集成

上下文处理系统与记忆系统紧密集成:

```
上下文构建器 → 记忆管理器 → 检索相关记忆 → 转换为上下文片段 → 添加到 LLM 上下文
```

### 13.2 与情感系统集成

情感系统为上下文提供情感维度:

```
情感引擎 → 分析当前情感状态 → 影响上下文选择 → 调整回复风格
```

### 13.3 与消息路由集成

消息路由系统使用上下文信息进行智能路由:

```
消息 → 提取上下文 → 匹配路由规则 → 选择目标 Agent
```
