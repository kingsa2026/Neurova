# 消息路由和通信系统设计

## 1. 概述

### 1.1 设计目标
- 支持多种通讯软件渠道接入（微信、Telegram、Slack等）
- 灵活的消息路由规则
- Agent间高效通信
- 避免信息风暴
- 消息优先级和限流
- 消息持久化和重试

### 1.2 核心组件

```
通信系统
├── 消息接收器 (Message Receivers)
│   ├── Webhook Receiver
│   ├── WebSocket Receiver
│   ├── Polling Receiver
│   └── STDIN Receiver
│
├── 消息路由器 (Message Router)
│   ├── 规则引擎
│   ├── 负载均衡
│   └── 限流器
│
├── 消息发送器 (Message Senders)
│   ├── Channel Adapters
│   ├── Webhook Sender
│   └── WebSocket Sender
│
├── 事件总线 (Event Bus)
│   ├── 发布/订阅
│   ├── 事件队列
│   └── 事件处理器
│
└── 渠道适配器 (Channel Adapters)
    ├── WeChat Adapter
    ├── Telegram Adapter
    ├── Slack Adapter
    ├── Discord Adapter
    └── HTTP Adapter
```

## 2. 消息模型

### 2.1 消息数据结构

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
import json
import uuid

class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    VIDEO = "video"
    FILE = "file"
    LOCATION = "location"
    LINK = "link"
    ACTION = "action"
    SYSTEM = "system"

class MessageSource(Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
    GROUP = "group"
    CHANNEL = "channel"

class MessagePriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3

class ChannelType(Enum):
    WECHAT = "wechat"
    TELEGRAM = "telegram"
    SLACK = "slack"
    DISCORD = "discord"
    WEBHOOK = "webhook"
    WEBSOCKET = "websocket"
    CLI = "cli"
    INTERNAL = "internal"

@dataclass
class Message:
    """核心消息类"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType = MessageType.TEXT
    source: MessageSource = MessageSource.USER
    channel: ChannelType = ChannelType.INTERNAL
    
    # 内容
    content: str = ""
    raw_content: Any = None  # 原始消息内容
    
    # 发送者/接收者
    sender_id: str = ""
    sender_name: str = ""
    receiver_id: str = ""
    receiver_name: str = ""
    
    # 群组/频道
    group_id: Optional[str] = None
    channel_id: Optional[str] = None
    
    # 元数据
    priority: MessagePriority = MessagePriority.NORMAL
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 时间戳
    timestamp: datetime = field(default_factory=datetime.now)
    created_at: datetime = field(default_factory=datetime.now)
    
    # 关联
    thread_id: Optional[str] = None  # 消息线程
    reply_to: Optional[str] = None  # 回复的消息ID
    
    # 路由信息
    route_targets: List[str] = field(default_factory=list)  # 路由目标 Agent
    route_history: List[str] = field(default_factory=list)  # 路由历史
    
    # 处理状态
    processed: bool = False
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'type': self.type.value,
            'source': self.source.value,
            'channel': self.channel.value,
            'content': self.content,
            'sender_id': self.sender_id,
            'sender_name': self.sender_name,
            'receiver_id': self.receiver_id,
            'receiver_name': self.receiver_name,
            'group_id': self.group_id,
            'channel_id': self.channel_id,
            'priority': self.priority.value,
            'metadata': self.metadata,
            'timestamp': self.timestamp.isoformat(),
            'created_at': self.created_at.isoformat(),
            'thread_id': self.thread_id,
            'reply_to': self.reply_to,
            'route_targets': self.route_targets,
            'route_history': self.route_history,
            'processed': self.processed,
            'error': self.error
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Message':
        return cls(
            id=data['id'],
            type=MessageType(data['type']),
            source=MessageSource(data['source']),
            channel=ChannelType(data['channel']),
            content=data['content'],
            raw_content=data.get('raw_content'),
            sender_id=data['sender_id'],
            sender_name=data['sender_name'],
            receiver_id=data['receiver_id'],
            receiver_name=data['receiver_name'],
            group_id=data.get('group_id'),
            channel_id=data.get('channel_id'),
            priority=MessagePriority(data['priority']),
            metadata=data.get('metadata', {}),
            timestamp=datetime.fromisoformat(data['timestamp']),
            created_at=datetime.fromisoformat(data['created_at']),
            thread_id=data.get('thread_id'),
            reply_to=data.get('reply_to'),
            route_targets=data.get('route_targets', []),
            route_history=data.get('route_history', []),
            processed=data.get('processed', False),
            error=data.get('error')
        )

@dataclass
class Event:
    """事件对象"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

## 3. 消息路由器

### 3.1 路由规则引擎

```python
from typing import Callable, Dict, List, Optional, Pattern
import re
from dataclasses import dataclass

@dataclass
class RoutingRule:
    """路由规则"""
    id: str
    name: str
    pattern: str  # 正则表达式
    pattern_compiled: Pattern = None  # 编译后的正则
    
    # 匹配条件
    channel: Optional[ChannelType] = None
    sender_id: Optional[str] = None
    group_id: Optional[str] = None
    priority: int = 0  # 规则优先级
    
    # 动作
    targets: List[str] = field(default_factory=list)  # 目标 Agent ID
    transform: Optional[Callable] = None  # 消息转换函数
    block: bool = False  # 是否阻止继续匹配
    
    # 条件
    condition: Optional[Callable] = None  # 自定义条件函数
    
    def __post_init__(self):
        if self.pattern:
            self.pattern_compiled = re.compile(self.pattern)

class RoutingRuleEngine:
    """
    路由规则引擎
    支持多规则匹配、优先级、转换
    """
    
    def __init__(self):
        self.rules: List[RoutingRule] = []
        self.default_target: Optional[str] = None
        self._rule_index: Dict[str, List[RoutingRule]] = {}
    
    def add_rule(self, rule: RoutingRule):
        """添加路由规则"""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
        self._rebuild_index()
    
    def remove_rule(self, rule_id: str):
        """移除路由规则"""
        self.rules = [r for r in self.rules if r.id != rule_id]
        self._rebuild_index()
    
    def match(self, message: Message) -> List[str]:
        """
        匹配消息，返回目标 Agent ID 列表
        """
        matched_targets = []
        
        for rule in self.rules:
            if self._rule_matches(rule, message):
                matched_targets.extend(rule.targets)
                
                # 如果有转换函数，应用转换
                if rule.transform:
                    message = rule.transform(message)
                
                # 如果阻止继续匹配，停止
                if rule.block:
                    break
        
        # 如果没有匹配到任何规则，使用默认目标
        if not matched_targets and self.default_target:
            matched_targets.append(self.default_target)
        
        return matched_targets
    
    def _rule_matches(self, rule: RoutingRule, message: Message) -> bool:
        """检查规则是否匹配消息"""
        # 频道过滤
        if rule.channel and message.channel != rule.channel:
            return False
        
        # 发送者过滤
        if rule.sender_id and message.sender_id != rule.sender_id:
            return False
        
        # 群组过滤
        if rule.group_id and message.group_id != rule.group_id:
            return False
        
        # 内容匹配
        if rule.pattern_compiled:
            if not rule.pattern_compiled.search(message.content):
                return False
        
        # 自定义条件
        if rule.condition:
            if not rule.condition(message):
                return False
        
        return True
    
    def _rebuild_index(self):
        """重建索引以提高匹配效率"""
        self._rule_index.clear()
        for rule in self.rules:
            if rule.channel:
                key = f"channel:{rule.channel.value}"
                if key not in self._rule_index:
                    self._rule_index[key] = []
                self._rule_index[key].append(rule)
```

### 3.2 消息路由器

```python
class MessageRouter:
    """
    消息路由器
    负责消息的接收、分发、限流、重试
    """
    
    def __init__(self, config: RouterConfig):
        self.config = config
        self.rule_engine = RoutingRuleEngine()
        self.message_queue = PriorityQueue()
        self.rate_limiter = RateLimiter()
        self.retry_manager = RetryManager()
        self.metrics = RouterMetrics()
    
    def route_message(self, message: Message) -> List[str]:
        """
        路由消息，返回目标 Agent 列表
        """
        # 记录开始时间
        start_time = time.time()
        
        # 限流检查
        if not self.rate_limiter.check(message.sender_id):
            message.error = "Rate limit exceeded"
            self.metrics.increment('rate_limited')
            return []
        
        # 匹配路由规则
        targets = self.rule_engine.match(message)
        
        # 记录路由结果
        self.metrics.record_routing(
            message_id=message.id,
            targets=targets,
            duration=time.time() - start_time
        )
        
        return targets
    
    async def dispatch_message(
        self,
        message: Message,
        targets: List[str]
    ):
        """
        分发消息到目标 Agent
        """
        # 创建分发任务
        tasks = []
        for target in targets:
            task = self._send_to_agent(message, target)
            tasks.append(task)
        
        # 并发执行
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理失败的重试
        for target, result in zip(targets, results):
            if isinstance(result, Exception):
                await self.retry_manager.schedule_retry(
                    message=message,
                    target=target,
                    error=result
                )
    
    async def _send_to_agent(
        self,
        message: Message,
        target: str
    ) -> bool:
        """发送消息到 Agent"""
        try:
            # 获取 Agent 通信端点
            agent = self.agent_registry.get_agent(target)
            if not agent:
                raise ValueError(f"Agent not found: {target}")
            
            # 发送消息
            await agent.receive_message(message)
            
            # 更新路由历史
            message.route_history.append(target)
            
            return True
        except Exception as e:
            raise
    
    def add_rule(self, rule: RoutingRule):
        """添加路由规则"""
        self.rule_engine.add_rule(rule)
    
    def set_default_target(self, target: str):
        """设置默认目标"""
        self.rule_engine.default_target = target
```

### 3.3 限流器

```python
from collections import defaultdict
from time import time

class RateLimiter:
    """
    限流器
    基于令牌桶算法实现
    """
    
    def __init__(
        self,
        rate: int = 60,  # 每分钟请求数
        burst: int = 10  # 突发容量
    ):
        self.rate = rate
        self.burst = burst
        self.tokens: Dict[str, float] = defaultdict(lambda: burst)
        self.last_update: Dict[str, float] = defaultdict(time)
    
    def check(self, key: str) -> bool:
        """检查是否允许请求"""
        now = time()
        
        # 补充令牌
        elapsed = now - self.last_update[key]
        self.tokens[key] = min(
            self.burst,
            self.tokens[key] + elapsed * (self.rate / 60)
        )
        self.last_update[key] = now
        
        # 检查令牌
        if self.tokens[key] >= 1:
            self.tokens[key] -= 1
            return True
        
        return False
    
    def get_remaining(self, key: str) -> int:
        """获取剩余令牌数"""
        return int(self.tokens[key])
```

### 3.4 重试管理器

```python
class RetryManager:
    """
    重试管理器
    指数退避策略
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.pending_retries: Dict[str, asyncio.Task] = {}
    
    async def schedule_retry(
        self,
        message: Message,
        target: str,
        error: Exception
    ):
        """调度重试"""
        retry_key = f"{message.id}:{target}"
        
        if retry_key in self.pending_retries:
            return
        
        # 计算重试次数
        retry_count = self._get_retry_count(retry_key)
        
        if retry_count >= self.max_retries:
            # 超过最大重试次数，记录失败
            await self._handle_failure(message, target, error)
            return
        
        # 计算延迟
        delay = min(
            self.base_delay * (2 ** retry_count),
            self.max_delay
        )
        
        # 调度重试
        task = asyncio.create_task(
            self._retry_after(delay, message, target)
        )
        self.pending_retries[retry_key] = task
    
    async def _retry_after(
        self,
        delay: float,
        message: Message,
        target: str
    ):
        """延迟后重试"""
        await asyncio.sleep(delay)
        
        try:
            agent = self.agent_registry.get_agent(target)
            await agent.receive_message(message)
        except Exception as e:
            await self.schedule_retry(message, target, e)
        finally:
            retry_key = f"{message.id}:{target}"
            self.pending_retries.pop(retry_key, None)
```

## 4. 事件总线

### 4.1 事件发布/订阅

```python
from typing import Callable, Dict, List, Any
from dataclasses import dataclass, field
import asyncio

EventHandler = Callable[[Event], Any]

class EventBus:
    """
    事件总线
    支持同步/异步事件处理、优先级、过滤
    """
    
    def __init__(self):
        self._handlers: Dict[str, List[tuple[int, EventHandler]]] = {}
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
    
    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        priority: int = 0
    ):
        """
        订阅事件
        - event_type: 事件类型
        - handler: 事件处理函数
        - priority: 优先级 (越高越先执行)
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        
        self._handlers[event_type].append((priority, handler))
        self._handlers[event_type].sort(key=lambda x: x[0], reverse=True)
    
    def unsubscribe(
        self,
        event_type: str,
        handler: EventHandler
    ):
        """取消订阅"""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                (p, h) for p, h in self._handlers[event_type]
                if h != handler
            ]
    
    async def publish(
        self,
        event: Event,
        blocking: bool = False
    ):
        """
        发布事件
        - blocking: 是否阻塞等待处理完成
        """
        if blocking:
            await self._publish_sync(event)
        else:
            await self._publish_async(event)
    
    async def _publish_async(self, event: Event):
        """异步发布"""
        await self._event_queue.put(event)
    
    async def _publish_sync(self, event: Event):
        """同步发布 - 等待所有处理器完成"""
        handlers = self._handlers.get(event.type, [])
        
        tasks = []
        for _, handler in handlers:
            if asyncio.iscoroutinefunction(handler):
                task = asyncio.create_task(handler(event))
            else:
                task = asyncio.create_task(
                    asyncio.to_thread(handler, event)
                )
            tasks.append(task)
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def start(self):
        """启动事件处理循环"""
        self._running = True
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=1.0
                )
                await self._publish_sync(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Event processing error: {e}")
    
    def stop(self):
        """停止事件处理"""
        self._running = False
```

## 5. 渠道适配器

### 5.1 适配器基类

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class ChannelAdapter(ABC):
    """
    渠道适配器抽象基类
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config.get('enabled', True)
        self.name = self.__class__.__name__
    
    @abstractmethod
    async def start(self):
        """启动适配器"""
        pass
    
    @abstractmethod
    async def stop(self):
        """停止适配器"""
        pass
    
    @abstractmethod
    async def send_message(self, message: Message) -> bool:
        """发送消息"""
        pass
    
    @abstractmethod
    def parse_incoming(self, raw_data: Any) -> Message:
        """解析 incoming 消息"""
        pass
    
    @abstractmethod
    def format_outgoing(self, message: Message) -> Any:
        """格式化 outgoing 消息"""
        pass
    
    async def health_check(self) -> bool:
        """健康检查"""
        return True
```

### 5.2 微信适配器

```python
class WeChatAdapter(ChannelAdapter):
    """
    微信适配器
    支持微信公众号、企业微信
    """
    
    async def start(self):
        """启动 Webhook 服务器"""
        self.app = Flask(__name__)
        
        @self.app.route('/webhook', methods=['POST'])
        def handle_webhook():
            raw_data = request.get_json()
            message = self.parse_incoming(raw_data)
            # 发送到消息路由器
            self.message_router.route_message(message)
            return 'ok'
        
        # 启动 Flask 服务器
        self.server = threading.Thread(
            target=self.app.run,
            kwargs={
                'host': self.config.get('host', '0.0.0.0'),
                'port': self.config.get('port', 8080)
            }
        )
        self.server.start()
    
    def parse_incoming(self, raw_data: Dict) -> Message:
        """解析微信消息"""
        msg_type = raw_data.get('MsgType', 'text')
        
        message = Message(
            type=MessageType.TEXT,
            source=MessageSource.USER,
            channel=ChannelType.WECHAT,
            sender_id=raw_data.get('FromUserName', ''),
            content=raw_data.get('Content', ''),
            raw_content=raw_data,
            metadata={
                'msg_id': raw_data.get('MsgId'),
                'create_time': raw_data.get('CreateTime')
            }
        )
        
        # 类型映射
        if msg_type == 'image':
            message.type = MessageType.IMAGE
            message.content = raw_data.get('PicUrl', '')
        elif msg_type == 'voice':
            message.type = MessageType.VOICE
            message.content = raw_data.get('MediaId', '')
        
        return message
    
    def format_outgoing(self, message: Message) -> Dict:
        """格式化回复消息"""
        response = {
            'ToUserName': message.receiver_id,
            'FromUserName': message.sender_id,
            'CreateTime': int(datetime.now().timestamp()),
            'MsgType': 'text',
            'Content': message.content
        }
        
        if message.type == MessageType.IMAGE:
            response['MsgType'] = 'image'
            response['Image'] = {'MediaId': message.content}
        
        return response
    
    async def send_message(self, message: Message) -> bool:
        """发送消息到微信"""
        formatted = self.format_outgoing(message)
        # 调用微信 API 发送
        return True
```

### 5.3 Telegram 适配器

```python
class TelegramAdapter(ChannelAdapter):
    """
    Telegram 适配器
    """
    
    async def start(self):
        """启动 Telegram Bot"""
        self.bot = Bot(token=self.config['bot_token'])
        self.update_queue = asyncio.Queue()
        
        # 启动轮询
        self.polling_task = asyncio.create_task(self._poll_updates())
    
    async def _poll_updates(self):
        """轮询更新"""
        offset = None
        while self.enabled:
            try:
                updates = await self.bot.get_updates(
                    offset=offset,
                    timeout=60
                )
                
                for update in updates:
                    message = self.parse_incoming(update)
                    await self.message_router.route_message(message)
                    offset = update.update_id + 1
                    
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(5)
    
    def parse_incoming(self, update: Any) -> Message:
        """解析 Telegram 更新"""
        tg_message = update.message
        
        message = Message(
            type=MessageType.TEXT,
            source=MessageSource.USER,
            channel=ChannelType.TELEGRAM,
            sender_id=str(tg_message.from_user.id),
            sender_name=tg_message.from_user.first_name or '',
            content=tg_message.text or '',
            group_id=str(tg_message.chat.id) if tg_message.chat.type != 'private' else None,
            raw_content=update.to_dict()
        )
        
        return message
    
    async def send_message(self, message: Message) -> bool:
        """发送消息到 Telegram"""
        chat_id = message.receiver_id or message.group_id
        
        if message.type == MessageType.TEXT:
            await self.bot.send_message(
                chat_id=chat_id,
                text=message.content,
                parse_mode='Markdown'
            )
        
        return True
```

## 6. Agent 内部通信

### 6.1 Agent 消息传递

```python
class AgentMessageChannel:
    """
    Agent 间消息传递通道
    支持点对点、广播、群组消息
    """
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.agent_channels: Dict[str, asyncio.Queue] = {}
        
        # 订阅 Agent 消息事件
        self.event_bus.subscribe(
            'agent.message',
            self._handle_agent_message
        )
    
    async def send_to_agent(
        self,
        from_agent: str,
        to_agent: str,
        message: Message
    ):
        """发送消息给 Agent"""
        # 添加路由历史
        message.route_history.append(from_agent)
        
        # 发送到目标 Agent 的队列
        if to_agent not in self.agent_channels:
            self.agent_channels[to_agent] = asyncio.Queue()
        
        await self.agent_channels[to_agent].put(message)
        
        # 发布事件
        await self.event_bus.publish(Event(
            type='agent.message',
            data={
                'from': from_agent,
                'to': to_agent,
                'message': message.to_dict()
            },
            source=from_agent
        ))
    
    async def broadcast(
        self,
        from_agent: str,
        message: Message,
        exclude: List[str] = None
    ):
        """广播消息给所有 Agent"""
        exclude = exclude or []
        
        for agent_id in self.agent_channels:
            if agent_id not in exclude:
                await self.send_to_agent(from_agent, agent_id, message)
    
    async def create_group(
        self,
        name: str,
        members: List[str]
    ) -> str:
        """创建 Agent 群组"""
        group_id = f"group:{name}:{uuid.uuid4().hex[:8]}"
        
        # 订阅群组消息
        self.event_bus.subscribe(
            f'agent.group.{group_id}',
            self._handle_group_message
        )
        
        return group_id
    
    async def send_to_group(
        self,
        from_agent: str,
        group_id: str,
        message: Message
    ):
        """发送消息到群组"""
        await self.event_bus.publish(Event(
            type=f'agent.group.{group_id}',
            data={
                'from': from_agent,
                'message': message.to_dict()
            },
            source=from_agent
        ))
```

### 6.2 避免信息风暴机制

```python
class MessageStormPreventer:
    """
    信息风暴防护器
    防止 Agent 间消息泛滥
    """
    
    def __init__(self):
        self.message_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.time_windows: Dict[str, float] = {}
        self.window_size = 60  # 1分钟窗口
        self.max_messages_per_window = 20  # 每分钟最多20条消息
        self.cooldown_period = 10  # 冷却期 10 秒
    
    async def check_and_throttle(
        self,
        from_agent: str,
        to_agent: str,
        message: Message
    ) -> bool:
        """
        检查是否应该限制消息
        返回 True 表示允许发送
        """
        # 检查是否在冷却期
        cooldown_key = f"{from_agent}:{to_agent}"
        if cooldown_key in self.time_windows:
            if time.time() - self.time_windows[cooldown_key] < self.cooldown_period:
                # 在冷却期内，检查消息内容是否有实质性更新
                if not self._has_substantive_update(message):
                    return False
        
        # 检查消息频率
        current_window = int(time.time() / self.window_size)
        count_key = f"{from_agent}:{to_agent}:{current_window}"
        
        self.message_counts[from_agent][to_agent] += 1
        
        if self.message_counts[from_agent][to_agent] > self.max_messages_per_window:
            # 超过限制，设置冷却期
            self.time_windows[cooldown_key] = time.time()
            return False
        
        return True
    
    def _has_substantive_update(self, message: Message) -> bool:
        """检查消息是否有实质性更新"""
        # 检查消息长度
        if len(message.content) < 10:
            return False
        
        # 检查是否包含关键词
        substantive_keywords = [
            '完成', '结果', '错误', '需要', '确认',
            'done', 'result', 'error', 'need', 'confirm'
        ]
        
        for keyword in substantive_keywords:
            if keyword in message.content:
                return True
        
        return False
    
    def reset_count(self, from_agent: str, to_agent: str):
        """重置计数"""
        self.message_counts[from_agent][to_agent] = 0
```

## 7. 配置示例

### 7.1 路由配置

```yaml
# routing.yaml
routing:
  # 默认目标
  default_target: "assistant"
  
  # 规则列表
  rules:
    - id: "rule_1"
      name: "数据查询路由"
      pattern: ".*(查询|统计|分析).*"
      targets: ["analyst"]
      priority: 10
      channel: "wechat"
    
    - id: "rule_2"
      name: "技术支持路由"
      pattern: ".*(帮助|问题|报错).*"
      targets: ["support_agent"]
      priority: 10
    
    - id: "rule_3"
      name: "群组消息广播"
      group_id: "support_group"
      targets: ["support_agent", "analyst"]
      priority: 5
      
  # 限流配置
  rate_limit:
    enabled: true
    requests_per_minute: 60
    burst_size: 10
```

### 7.2 渠道配置

```yaml
# channels.yaml
channels:
  wechat:
    enabled: true
    type: "public_account"  # 或 "enterprise"
    webhook_url: "http://0.0.0.0:8080/webhook"
    app_id: "${WECHAT_APP_ID}"
    app_secret: "${WECHAT_APP_SECRET}"
    
  telegram:
    enabled: true
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    
  slack:
    enabled: false
    bot_token: "${SLACK_BOT_TOKEN}"
    signing_secret: "${SLACK_SIGNING_SECRET}"
    app_id: "${SLACK_APP_ID}"
```

## 8. 监控指标

### 8.1 关键指标

```python
class RouterMetrics:
    """路由指标收集"""
    
    def __init__(self):
        self.total_messages = 0
        self.routed_messages = 0
        self.failed_messages = 0
        self.rate_limited = 0
        self.routing_latencies = []
        self.target_distribution: Dict[str, int] = defaultdict(int)
    
    def record_routing(
        self,
        message_id: str,
        targets: List[str],
        duration: float
    ):
        """记录路由"""
        self.total_messages += 1
        self.routed_messages += len(targets)
        self.routing_latencies.append(duration)
        
        for target in targets:
            self.target_distribution[target] += 1
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        avg_latency = (
            sum(self.routing_latencies) / len(self.routing_latencies)
            if self.routing_latencies else 0
        )
        
        return {
            'total_messages': self.total_messages,
            'routed_messages': self.routed_messages,
            'failed_messages': self.failed_messages,
            'rate_limited': self.rate_limited,
            'avg_latency_ms': avg_latency * 1000,
            'target_distribution': dict(self.target_distribution)
        }
```
