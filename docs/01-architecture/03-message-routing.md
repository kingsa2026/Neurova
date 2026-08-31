# 消息路由和通信系统设计

> **状态**: 已实现（对照代码核实） · 版本: v1.0.0-beta1
> **说明**: 本文档描述的功能已在 `neurova/` 对应模块实现，详见 [功能模块矩阵](../0-index/README.md)


## 1. 概述

### 1.1 设计目标
- 支持 14 种通信渠道统一接入
- 灵活的消息路由规则
- Agent 间高效通信
- 避免信息风暴
- 消息优先级和限流
- 消息持久化和重试

### 1.2 支持的渠道

| 渠道 | 适配器文件 | 接入模式 | 说明 |
|------|-----------|---------|------|
| 飞书 | `feishu.py` | Stream/Webhook | `lark-oapi` SDK，WebSocket 长连接 |
| 钉钉 | `dingtalk.py` | Stream/Webhook | `dingtalk-stream` SDK |
| 企业微信 | `wecom.py` | Stream/Webhook | WebSocket 智能机器人 + 回调 XML |
| 微信 | `wechat.py` | Webhook | 公众号/小程序 |
| Telegram | `telegram.py` | Polling/Webhook | `python-telegram-bot` |
| Discord | `discord.py` | WebSocket | `discord.py` |
| QQ | `qq.py` | WebSocket | QQ 机器人 |
| MQTT | `mqtt.py` | MQTT | IoT 设备接入 |
| WebSocket | `websocket.py` | WebSocket | 原生 WebSocket |
| SIP | `sip.py` | SIP | 语音通话 |
| Webhook | `base.py` | HTTP | 通用 Webhook |
| 移动设备 | `mobile_pairing.py` | QR 码配对 | 手机 App 对接 |
| CLI | - | STDIN | 命令行交互 |
| API | - | HTTP | REST API 直接调用 |

### 1.3 核心组件

```
通信系统
├── ChannelManager (渠道管理器)
│   ├── 生命周期管理
│   ├── 适配器注册/发现
│   └── 健康监控
│
├── ChannelAdapter (适配器基类)
│   ├── connect() / disconnect()
│   ├── send_message()
│   └── parse_incoming()
│
├── MessageRouter (消息路由器)
│   ├── 规则引擎
│   ├── 负载均衡
│   └── 限流器
│
├── EventBus (事件总线)
│   ├── 发布/订阅
│   ├── 事件队列
│   └── 事件处理器
│
└── 14 种渠道适配器
    ├── feishu.py (飞书)
    ├── dingtalk.py (钉钉)
    ├── wecom.py (企业微信)
    ├── wechat.py (微信)
    ├── telegram.py (Telegram)
    ├── discord.py (Discord)
    ├── qq.py (QQ)
    ├── mqtt.py (MQTT)
    ├── websocket.py (WebSocket)
    ├── sip.py (SIP)
    ├── webhook.py (Webhook)
    ├── mobile_pairing.py (移动设备)
    └── ...
```

## 2. 消息模型

### 2.1 消息数据结构

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from enum import Enum

class MessageChannel(str, Enum):
    """消息渠道枚举 - 14 种渠道"""
    WECHAT = "wechat"
    FEISHU = "feishu"
    DINGTALK = "dingtalk"
    WECOM = "wecom"
    WEBHOOK = "webhook"
    API = "api"
    TELEGRAM = "telegram"
    WEBSOCKET = "websocket"
    SIP = "sip"
    QQBOT = "qqbot"
    QQ = "qq"
    QCLAW = "qclaw"
    MQTT = "mqtt"
    DISCORD = "discord"
    MOBILE = "mobile"
    XIAOYI = "xiaoyi"

class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    VIDEO = "video"
    FILE = "file"
    LOCATION = "location"
    LINK = "link"
    ACTION = "action"
    SYSTEM = "system"

class MessageSource(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
    GROUP = "group"
    CHANNEL = "channel"

class MessagePriority(int, Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3

@dataclass
class ChannelMessage:
    """渠道消息 - 跨平台统一消息格式"""
    channel_type: str              # feishu / dingtalk / wecom
    message_id: str                # 平台消息 ID
    sender_id: str                 # 发送者 ID
    sender_name: str               # 发送者名称
    content: str                   # 消息文本内容
    message_type: str = "text"     # text / image / file / ...
    chat_id: str = ""              # 会话 ID（群聊/私聊）
    chat_type: str = "p2p"         # p2p / group
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_event: Dict[str, Any] = field(default_factory=dict)  # 原始事件
    metadata: Dict[str, Any] = field(default_factory=dict)   # 附加元数据

    def to_dict(self) -> Dict[str, Any]:
        return {
            'channel_type': self.channel_type,
            'message_id': self.message_id,
            'sender_id': self.sender_id,
            'sender_name': self.sender_name,
            'content': self.content,
            'message_type': self.message_type,
            'chat_id': self.chat_id,
            'chat_type': self.chat_type,
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata
        }

@dataclass
class Event:
    """事件对象"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
```

## 3. 渠道适配器

### 3.1 适配器基类

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable, Coroutine

class ChannelAdapter(ABC):
    """
    渠道适配器抽象基类
    
    设计原则:
    - 适配器不需要知道消息如何被处理，只需收发
    - 所有平台差异封装在具体适配器中
    - ChannelManager 负责生命周期和路由
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config.get('enabled', True)
        self.name = self.__class__.__name__
        self._message_handler: Optional[Callable] = None
    
    @abstractmethod
    async def connect(self):
        """连接到平台"""
        pass
    
    @abstractmethod
    async def disconnect(self):
        """断开连接"""
        pass
    
    @abstractmethod
    async def send_message(self, message: ChannelMessage) -> bool:
        """发送消息"""
        pass
    
    @abstractmethod
    def parse_incoming(self, raw_data: Any) -> ChannelMessage:
        """解析 incoming 消息"""
        pass
    
    @abstractmethod
    def format_outgoing(self, message: ChannelMessage) -> Any:
        """格式化 outgoing 消息"""
        pass
    
    def set_message_handler(self, handler: Callable[[ChannelMessage], Coroutine]):
        """设置消息处理器"""
        self._message_handler = handler
    
    async def health_check(self) -> bool:
        """健康检查"""
        return True
```

### 3.2 飞书适配器

```python
class FeishuAdapter(ChannelAdapter):
    """
    飞书适配器
    
    支持两种接入模式:
    1. Stream 模式（WebSocket 长连接）- 推荐，无需公网 IP
    2. Webhook 模式 - HTTP 回调，需要公网 URL
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.app_id = config.get('app_id', '')
        self.app_secret = config.get('app_secret', '')
        self.use_stream = config.get('use_stream', True)
        self.encrypt_key = config.get('encrypt_key', '')
        self.verification_token = config.get('verification_token', '')
    
    async def connect(self):
        """连接到飞书"""
        if self.use_stream:
            await self._connect_stream()
        else:
            await self._connect_webhook()
    
    async def _connect_stream(self):
        """Stream 模式连接"""
        import lark_oapi as lark
        
        self.client = lark.Client.builder() \
            .app_id(self.app_id) \
            .app_secret(self.app_secret) \
            .build()
        
        # 注册事件处理器
        self.client.register_event_handler(self._handle_event)
        
        # 启动 WebSocket 长连接
        await self.client.start()
    
    async def _connect_webhook(self):
        """Webhook 模式连接"""
        # 启动 HTTP 服务器监听回调
        pass
    
    async def send_message(self, message: ChannelMessage) -> bool:
        """发送消息到飞书"""
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
        
        request = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(CreateMessageRequestBody.builder()
                .receive_id(message.chat_id)
                .msg_type("text")
                .content(json.dumps({"text": message.content}))
                .build()) \
            .build()
        
        response = await self.client.im.v1.message.create(request)
        return response.success()
    
    def parse_incoming(self, raw_data: Any) -> ChannelMessage:
        """解析飞书消息"""
        event = raw_data.event
        message = event.message
        
        return ChannelMessage(
            channel_type="feishu",
            message_id=message.message_id,
            sender_id=event.sender.sender_id.open_id,
            sender_name=event.sender.sender_id.open_id,
            content=message.content,
            message_type=message.message_type,
            chat_id=message.chat_id,
            chat_type=message.chat_type,
            raw_event=raw_data
        )
```

### 3.3 钉钉适配器

```python
class DingTalkAdapter(ChannelAdapter):
    """
    钉钉适配器
    
    支持两种接入模式:
    1. Stream 模式（WebSocket 长连接）- 推荐
    2. Webhook 模式 - HTTP 回调
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.app_key = config.get('app_key', '')
        self.app_secret = config.get('app_secret', '')
        self.robot_code = config.get('robot_code', '')
        self.use_stream = config.get('use_stream', True)
    
    async def connect(self):
        """连接到钉钉"""
        if self.use_stream:
            await self._connect_stream()
        else:
            await self._connect_webhook()
    
    async def _connect_stream(self):
        """Stream 模式连接"""
        from dingtalk_stream import DingtalkStream
        
        self.client = DingtalkStream(
            client_id=self.app_key,
            client_secret=self.app_secret
        )
        
        # 注册回调
        self.client.register_callback(
            "/v1.0/im/bot/messages/get",
            self._handle_message
        )
        
        # 启动长连接
        await self.client.start()
    
    async def send_message(self, message: ChannelMessage) -> bool:
        """发送消息到钉钉"""
        from dingtalk_stream import ChatbotMessage
        
        msg = ChatbotMessage()
        msg.sender_nick = "Neurova"
        msg.text = {"content": message.content}
        
        await self.client.send_message(
            conversation_id=message.chat_id,
            msg_type="text",
            content=json.dumps(msg)
        )
        return True
    
    def parse_incoming(self, raw_data: Any) -> ChannelMessage:
        """解析钉钉消息"""
        return ChannelMessage(
            channel_type="dingtalk",
            message_id=raw_data.message_id,
            sender_id=raw_data.sender_id,
            sender_name=raw_data.sender_nick,
            content=raw_data.text.content,
            chat_id=raw_data.conversation_id,
            chat_type=raw_data.conversation_type,
            raw_event=raw_data
        )
```

### 3.4 企业微信适配器

```python
class WeComAdapter(ChannelAdapter):
    """
    企业微信适配器
    
    支持两种接入模式:
    1. WebSocket 智能机器人 - 推荐
    2. 回调模式 - HTTP 回调 + XML 解析
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.corp_id = config.get('corp_id', '')
        self.agent_id = config.get('agent_id', '')
        self.token = config.get('token', '')
        self.encoding_aes_key = config.get('encoding_aes_key', '')
        self.use_websocket = config.get('use_websocket', True)
    
    async def connect(self):
        """连接到企业微信"""
        if self.use_websocket:
            await self._connect_websocket()
        else:
            await self._connect_callback()
    
    async def _connect_websocket(self):
        """WebSocket 智能机器人模式"""
        # 启动 WebSocket 连接
        pass
    
    async def _connect_callback(self):
        """回调模式"""
        # 启动 HTTP 服务器监听回调
        pass
    
    async def send_message(self, message: ChannelMessage) -> bool:
        """发送消息到企业微信"""
        import requests
        
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send"
        data = {
            "touser": message.sender_id,
            "msgtype": "text",
            "agentid": self.agent_id,
            "text": {"content": message.content}
        }
        
        # 获取 access_token
        token = await self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        response = requests.post(url, json=data, headers=headers)
        return response.json().get("errcode") == 0
    
    def parse_incoming(self, raw_data: Any) -> ChannelMessage:
        """解析企业微信消息"""
        # XML 解析
        import xml.etree.ElementTree as ET
        root = ET.fromstring(raw_data)
        
        return ChannelMessage(
            channel_type="wecom",
            message_id=root.find("MsgId").text,
            sender_id=root.find("FromUserName").text,
            sender_name="",
            content=root.find("Content").text if root.find("Content") is not None else "",
            chat_id=root.find("FromUserName").text,
            raw_event=raw_data
        )
```

### 3.5 其他渠道适配器

| 渠道 | 适配器类 | 主要特性 |
|------|---------|---------|
| 微信 | `WeChatAdapter` | 公众号/小程序，Webhook 模式 |
| Telegram | `TelegramAdapter` | Bot API，Polling/Webhook 模式 |
| Discord | `DiscordAdapter` | `discord.py`，WebSocket 模式 |
| QQ | `QQAdapter` | QQ 机器人，WebSocket 模式 |
| MQTT | `MQTTAdapter` | IoT 设备，MQTT 协议 |
| WebSocket | `WebSocketAdapter` | 原生 WebSocket，双向通信 |
| SIP | `SIPAdapter` | 语音通话，SIP 协议 |
| 移动设备 | `MobilePairingAdapter` | QR 码配对，WebSocket 长连接 |

## 4. 渠道管理器

### 4.1 ChannelManager

```python
class ChannelManager:
    """
    渠道管理器 - 单例
    
    职责:
    - 管理所有渠道适配器的生命周期
    - 路由消息到正确的适配器
    - 监控适配器健康状态
    """
    
    def __init__(self):
        self.adapters: Dict[str, ChannelAdapter] = {}
        self._running = False
    
    async def register_adapter(self, channel_type: str, adapter: ChannelAdapter):
        """注册渠道适配器"""
        self.adapters[channel_type] = adapter
        adapter.set_message_handler(self._handle_message)
        
        if self._running:
            await adapter.connect()
    
    async def start(self):
        """启动所有适配器"""
        self._running = True
        
        for channel_type, adapter in self.adapters.items():
            if adapter.enabled:
                try:
                    await adapter.connect()
                    logger.info(f"渠道 {channel_type} 已连接")
                except Exception as e:
                    logger.error(f"渠道 {channel_type} 连接失败: {e}")
    
    async def stop(self):
        """停止所有适配器"""
        self._running = False
        
        for channel_type, adapter in self.adapters.items():
            try:
                await adapter.disconnect()
            except Exception as e:
                logger.error(f"渠道 {channel_type} 断开失败: {e}")
    
    async def send_message(self, channel_type: str, message: ChannelMessage) -> bool:
        """发送消息到指定渠道"""
        adapter = self.adapters.get(channel_type)
        if not adapter:
            logger.error(f"渠道 {channel_type} 未注册")
            return False
        
        return await adapter.send_message(message)
    
    async def _handle_message(self, message: ChannelMessage):
        """处理接收到的消息"""
        # 路由到消息路由器
        from neurova.router import MessageRouter
        router = MessageRouter()
        await router.route_message(message)
    
    def get_health_status(self) -> Dict[str, bool]:
        """获取所有渠道健康状态"""
        status = {}
        for channel_type, adapter in self.adapters.items():
            status[channel_type] = adapter.enabled
        return status
```

### 4.2 渠道配置

```python
@dataclass
class ChannelConfig:
    """渠道配置"""
    channel_type: str  # feishu / dingtalk / wecom / ...
    enabled: bool = True
    app_id: str = ""
    app_secret: str = ""
    # Webhook 模式
    webhook_url: str = ""
    webhook_token: str = ""
    # Stream 模式（长连接）
    use_stream: bool = True
    # 加密
    encrypt_key: str = ""
    verification_token: str = ""
    # 自定义
    extra: Dict[str, Any] = field(default_factory=dict)
```

## 5. 消息路由器

### 5.1 路由规则引擎

```python
from typing import Callable, Dict, List, Optional, Pattern
import re

@dataclass
class RoutingRule:
    """路由规则"""
    id: str
    name: str
    pattern: str  # 正则表达式
    pattern_compiled: Pattern = None  # 编译后的正则
    
    # 匹配条件
    channel: Optional[MessageChannel] = None
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
    
    def match(self, message: ChannelMessage) -> List[str]:
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
    
    def _rule_matches(self, rule: RoutingRule, message: ChannelMessage) -> bool:
        """检查规则是否匹配消息"""
        # 频道过滤
        if rule.channel and message.channel_type != rule.channel.value:
            return False
        
        # 发送者过滤
        if rule.sender_id and message.sender_id != rule.sender_id:
            return False
        
        # 群组过滤
        if rule.group_id and message.chat_id != rule.group_id:
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
```

### 5.2 消息路由器

```python
class MessageRouter:
    """
    消息路由器
    
    负责消息的接收、分发、限流、重试
    """
    
    def __init__(self, config: RouterConfig = None):
        self.config = config or RouterConfig()
        self.rule_engine = RoutingRuleEngine()
        self.rate_limiter = RateLimiter()
        self.retry_manager = RetryManager()
        self.metrics = RouterMetrics()
    
    async def route_message(self, message: ChannelMessage) -> List[str]:
        """
        路由消息，返回目标 Agent 列表
        """
        # 记录开始时间
        start_time = time.time()
        
        # 限流检查
        if not self.rate_limiter.check(message.sender_id):
            message.metadata['error'] = "Rate limit exceeded"
            self.metrics.increment('rate_limited')
            return []
        
        # 匹配路由规则
        targets = self.rule_engine.match(message)
        
        # 记录路由结果
        self.metrics.record_routing(
            message_id=message.message_id,
            targets=targets,
            duration=time.time() - start_time
        )
        
        return targets
    
    async def dispatch_message(
        self,
        message: ChannelMessage,
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
        message: ChannelMessage,
        target: str
    ) -> bool:
        """发送消息到 Agent"""
        try:
            # 获取 Agent 通信端点
            from neurova.agent_core import Agent
            agent = Agent.get_instance(target)
            if not agent:
                raise ValueError(f"Agent not found: {target}")
            
            # 发送消息
            await agent.receive_message(message)
            
            return True
        except Exception as e:
            raise
```

## 6. 事件总线

### 6.1 事件发布/订阅

```python
from typing import Callable, Dict, List, Any
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

## 7. 限流和重试

### 7.1 限流器

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
```

### 7.2 重试管理器

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
        message: ChannelMessage,
        target: str,
        error: Exception
    ):
        """调度重试"""
        retry_key = f"{message.message_id}:{target}"
        
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
```

## 8. 配置示例

### 8.1 渠道配置

```yaml
# channels.yaml
channels:
  feishu:
    enabled: true
    app_id: "${FEISHU_APP_ID}"
    app_secret: "${FEISHU_APP_SECRET}"
    use_stream: true  # 推荐使用 Stream 模式
    encrypt_key: "${FEISHU_ENCRYPT_KEY}"
    verification_token: "${FEISHU_VERIFICATION_TOKEN}"
    
  dingtalk:
    enabled: true
    app_key: "${DINGTALK_APP_KEY}"
    app_secret: "${DINGTALK_APP_SECRET}"
    robot_code: "${DINGTALK_ROBOT_CODE}"
    use_stream: true
    
  wecom:
    enabled: true
    corp_id: "${WECOM_CORP_ID}"
    agent_id: "${WECOM_AGENT_ID}"
    token: "${WECOM_TOKEN}"
    encoding_aes_key: "${WECOM_ENCODING_AES_KEY}"
    use_websocket: true
    
  telegram:
    enabled: true
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    
  discord:
    enabled: true
    bot_token: "${DISCORD_BOT_TOKEN}"
    
  wechat:
    enabled: false
    app_id: "${WECHAT_APP_ID}"
    app_secret: "${WECHAT_APP_SECRET}"
    webhook_url: "http://0.0.0.0:8080/webhook"
    
  mqtt:
    enabled: false
    broker: "mqtt://localhost:1883"
    username: "${MQTT_USERNAME}"
    password: "${MQTT_PASSWORD}"
```

### 8.2 路由配置

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
      channel: "feishu"
    
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

## 9. 监控指标

### 9.1 关键指标

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
        self.channel_distribution: Dict[str, int] = defaultdict(int)
    
    def record_routing(
        self,
        message_id: str,
        targets: List[str],
        duration: float,
        channel: str = ""
    ):
        """记录路由"""
        self.total_messages += 1
        self.routed_messages += len(targets)
        self.routing_latencies.append(duration)
        
        for target in targets:
            self.target_distribution[target] += 1
        
        if channel:
            self.channel_distribution[channel] += 1
    
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
            'target_distribution': dict(self.target_distribution),
            'channel_distribution': dict(self.channel_distribution)
        }
```

## 10. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v4.0 | 2026-06-07 | 更新为 14 种渠道支持，添加飞书/钉钉/企业微信适配器 |
| v2.0 | 2026-05-05 | 初始版本，支持 5 种渠道 |

---

**最后更新**: 2026-06-07  
**维护者**: Neurova Team  
**版本**: 4.0