# Neurova 消息渠道集成系统文档

> **更新日期**: 2026-05-07  
> **状态**: 核心架构、API、Web管理页面已完成

---

## 1. 核心架构

### 1.1 设计目标

解决跨渠道上下文丢失问题：
> "就像我给你发短信约吃火锅，你回好，然后我打电话问你几点去，你却问'啥火锅？'"

**核心方案**:
1. **统一消息模型** - 所有渠道消息标准化
2. **用户身份映射** - 同一用户在不同渠道的身份关联
3. **跨会话路由** - 基于全局用户 ID 的消息路由
4. **Agent 隔离** - 每个 Agent 独立的记忆和上下文
5. **内存会话管理** - 会话上下文在内存中管理，支持跨渠道切换

### 1.2 核心组件

```
┌─────────────────────────────────────────────────────────────┐
│                    跨渠道消息路由器                           │
│                   (CrossChannelRouter)                       │
├──────────────┬──────────────┬──────────────┬────────────────┤
│  用户身份管理器  │   会话管理器   │  渠道适配器    │  消息处理器     │
│ (UserIdentity  │ (Session     │ (Channel     │ (Message       │
│  Manager)      │  Manager)    │  Adapter)    │  Handler)      │
└──────────────┴──────────────┴──────────────┴────────────────┘
         ↓              ↓              ↓              ↓
     身份关联       会话保持       消息标准化      Agent调用
     跨渠道识别     上下文加载     发送/接收      回复生成
```

### 1.3 系统层次

```
┌─────────────────────────────────────────────────┐
│                 Web 管理界面                      │
│          channels-ui.html + stats.html            │
├─────────────────────────────────────────────────┤
│               REST API (Flask)                   │
│           neurova_server.py                        │
│  /api/channels/*  /api/chat  /api/memories       │
├─────────────────────────────────────────────────┤
│              渠道管理层                           │
│           channels/manager.py                    │
├──────────┬──────────┬──────────┬────────────────┤
│ 飞书适配器│ 钉钉适配器│ 微信适配器│ Telegram适配器  │
│ feishu.py│dingtalk.py│wechat.py │ telegram.py    │
├──────────┴──────────┴──────────┴────────────────┤
│              核心数据模型                         │
│            channels/__init__.py                  │
└─────────────────────────────────────────────────┘
```

---

## 2. 已实现的渠道适配器

### 2.1 飞书 (Feishu)

**文件**: `neurova/channels/feishu.py`

**配置项**:
| 配置项 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| app_id | string | ✅ | - | 应用 App ID |
| app_secret | string | ✅ | - | 应用 App Secret |
| region | string | ❌ | cn | 地区 (cn/sg) |
| bot_prefix | string | ❌ | @Kai | 机器人前缀 |
| show_tool_messages | bool | ❌ | true | 显示工具消息 |
| show_thinking | bool | ❌ | true | 显示思考过程 |
| encrypt_key | string | ❌ | - | 事件加密密钥 |
| verification_token | string | ❌ | - | 验证 Token |
| media_directory | string | ❌ | - | 媒体文件目录 |
| private_chat_strategy | string | ❌ | open | 私聊策略 (open/closed/whitelist) |
| group_chat_strategy | string | ❌ | open | 群聊策略 |
| require_mention | bool | ❌ | true | 需要@提及 |
| whitelist_users | list | ❌ | [] | 白名单用户 |

**API**: 
- 国内: `https://open.feishu.cn/open-apis`
- 国际: `https://open.larksuite.com/open-apis`

---

### 2.2 钉钉 (DingTalk)

**文件**: `neurova/channels/dingtalk.py`

**配置项**:
| 配置项 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| client_id | string | ✅ | - | 应用 Client ID |
| client_secret | string | ✅ | - | 应用 Client Secret |
| robot_code | string | ❌ | - | 机器人 Code |
| bot_prefix | string | ❌ | @bot | 机器人前缀 |
| show_tool_messages | bool | ❌ | true | 显示工具消息 |
| show_thinking | bool | ❌ | true | 显示思考过程 |
| message_type | string | ❌ | markdown | 消息类型 |
| cron_message_type | string | ❌ | markdown | 定时消息类型 |
| reply_at_sender | bool | ❌ | true | 回复时@发送者 |
| private_chat_strategy | string | ❌ | open | 私聊策略 |
| group_chat_strategy | string | ❌ | open | 群聊策略 |
| require_mention | bool | ❌ | true | 需要@提及 |
| whitelist_users | list | ❌ | [] | 白名单用户 |

---

### 2.3 企业微信 (WeChat)

**文件**: `neurova/channels/wechat.py`

**配置项**:
| 配置项 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| corpid | string | ✅ | 企业 ID |
| corpsecret | string | ✅ | 应用密钥 |
| agentid | string | ❌ | 应用 ID |
| kf_mode | bool | ❌ | 微信客服模式 |
| open_kfid | string | ❌ | 客服账号 ID (客服模式) |
| token | string | ❌ | 回调 Token |
| encoding_aes_key | string | ❌ | 回调密钥 |

**支持模式**:
- 应用消息 (向员工/部门发送)
- 微信客服 (48小时内可回复)

---

### 2.4 Telegram

**文件**: `neurova/channels/telegram.py`

**配置项**:
| 配置项 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| bot_token | string | ✅ | - | Bot Token |
| bot_prefix | string | ❌ | kingsa | 机器人前缀 |
| show_tool_messages | bool | ❌ | true | 显示工具消息 |
| show_thinking | bool |  | true | 显示思考过程 |
| http_proxy | string | ❌ | - | HTTP 代理地址 |
| http_proxy_auth | string | ❌ | - | 代理认证 (user:password) |
| show_typing | bool | ❌ | false | 显示正在输入 |
| private_chat_strategy | string | ❌ | open | 私聊策略 |
| group_chat_strategy | string | ❌ | open | 群聊策略 |
| require_mention | bool | ❌ | false | 需要@提及 |
| whitelist_users | list | ❌ | [] | 白名单用户 |

---

### 2.5 微信 (WeChat)

**文件**: `neurova/channels/wechat.py`

**支持两种模式**:
1. **企业微信** (wecom)
2. **微信个人账号** (iLink协议)

#### 企业微信模式配置项:
| 配置项 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| mode | string | ✅ | 运行模式 (wecom) |
| bot_id | string | ✅ | Bot ID |
| corpsecret | string | ✅ | 应用密钥 |
| media_directory | string | ❌ | 媒体文件目录 |
| welcome_message | string | ❌ | 欢迎消息 |
| group_share_session | bool | ❌ | 群聊共享会话 |
| private_chat_strategy | string |  | 私聊策略 (open/closed/whitelist) |
| group_chat_strategy | string | ❌ | 群聊策略 (open/closed/whitelist) |
| require_mention | bool | ❌ | 需要@提及 |
| whitelist_users | list | ❌ | 白名单用户 |

#### 微信个人账号 (iLink) 配置项:
| 配置项 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| mode | string | ✅ | ilink | 运行模式 (ilink) |
| bot_token | string | ❌ | - | Bot Token (首次扫码后自动生成) |
| token_file | string | ❌ | ~/.qwenpaw/weixin_bot_token | Token 文件路径 |
| media_directory | string | ❌ | - | 媒体文件目录 |
| message_merge | bool | ❌ | false | 消息合并 (避免超出平台限制) |
| private_chat_strategy | string | ❌ | open | 私聊策略 |
| group_chat_strategy | string | ❌ | open | 群聊策略 |
| require_mention | bool | ❌ | false | 需要@提及 |
| whitelist_users | list |  | [] | 白名单用户 |

**iLink 协议说明**:
- 首次启动若未配置 Bot Token，系统将打印二维码链接，请扫码登录
- Token 将自动保存到本地文件供后续使用
- iLink 平台限制: 每条用户消息对应的 context_token 最多只能回复 10 条消息

---

### 2.6 QQ频道 (QQ)

**文件**: `neurova/channels/qq.py`

**配置项**:
| 配置项 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| app_id | string | ✅ | - | 应用ID (App ID) |
| token | string | ✅ | - | Bot Token |
| secret | string | ✅ | - | 应用密钥 |
| bot_prefix | string | ❌ | kingsa | 机器人前缀 |
| show_tool_messages | bool | ❌ | true | 显示工具消息 |
| show_thinking | bool | ❌ | true | 显示思考过程 |
| guild_id | string | ❌ | - | 频道ID |
| channel_ids | string | ❌ | - | 子频道ID列表 (逗号分隔) |
| media_directory | string | ❌ | - | 媒体文件目录 |
| message_merge | bool | ❌ | false | 消息合并 |
| group_share_session | bool | ❌ | true | 群聊共享会话 |
| welcome_message | string | ❌ | - | 欢迎消息 |
| private_chat_strategy | string | ❌ | open | 私聊策略 |
| group_chat_strategy | string | ❌ | open | 群聊策略 |
| require_mention | bool | ❌ | false | 需要@提及 |
| whitelist_users | list | ❌ | [] | 白名单用户 |

**API**: `https://api.sgroup.qq.com`

---

### 2.7 Discord

**文件**: `neurova/channels/discord.py`

**配置项**:
| 配置项 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| bot_token | string | ✅ | - | Bot Token |
| bot_prefix | string | ❌ | kingsa | 机器人前缀 |
| show_tool_messages | bool | ❌ | true | 显示工具消息 |
| show_thinking | bool | ❌ | true | 显示思考过程 |
| http_proxy | string |  | - | HTTP Proxy |
| http_proxy_auth | string | ❌ | - | HTTP Proxy Auth (user:password) |
| receive_bot_messages | bool | ❌ | false | 接收机器人消息 |
| private_chat_strategy | string |  | open | 私聊策略 |
| group_chat_strategy | string | ❌ | open | 群聊策略 |
| require_mention | bool | ❌ | false | 需要@提及 |
| whitelist_users | list | ❌ | [] | 白名单用户 |

**API**: `https://discord.com/api/v10`

---

### 2.8 SIP 语音通话

**文件**: `neurova/channels/sip.py`

**支持两种模式**:
1. **Dev 模式** (pyVoIP) - 本地处理 SIP/RTP
2. **Production 模式** (LiveKit SIP Server) - 使用外部 SIP 服务器

**配置项**:
| 配置项 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| bot_prefix | string | ❌ | @bot | 机器人前缀 |
| show_tool_messages | bool | ❌ | true | 显示工具消息 |
| show_thinking | bool | ❌ | true | 显示思考过程 |
| sip_mode | string | ❌ | dev | SIP 模式 (dev/production) |
| sip_server | string | ❌ | - | SIP 服务器 (留空使用内置) |
| sip_username | string | ✅ | kingsa | SIP 用户名 |
| sip_password | string | ✅ | - | SIP 密码 |
| sip_port | number | ❌ | 5061 | SIP 端口 |
| transport_protocol | string | ❌ | UDP | 传输协议 (UDP/TCP/TLS) |
| dashscope_api_key | string |  | - | DashScope API Key |
| tts_provider | string | ❌ | aliyun | TTS 提供商 |
| tts_voice | string | ❌ | longxiaochun | TTS 语音 |
| stt_provider | string | ❌ | aliyun | STT 提供商 |
| language | string | ❌ | zh-CN | 语言 |
| welcome_message | string | ❌ | 你好，我是QwenPaw | 欢迎语 |

**语音处理**:
- **TTS (文本转语音)**: 使用 DashScope API 将 Agent 回复转换为语音
- **STT (语音转文本)**: 使用 DashScope API 将用户语音转换为文本

**依赖安装**:
```bash
pip install pyvoip
```

---

## 3. 核心数据模型

### 3.1 统一消息 (UnifiedMessage)

```python
@dataclass
class UnifiedMessage:
    message_id: str              # 全局唯一消息 ID
    channel: MessageChannel      # 来源渠道
    chat_id: str                 # 会话 ID
    user_id: str                 # 发送者 ID
    agent_id: str                # 目标 Agent ID
    content: str                 # 消息内容
    content_type: ContentType    # 内容类型
    timestamp: datetime          # 时间戳
    global_user_id: str          # 全局用户 ID (跨渠道统一)
    session_id: str              # 全局会话 ID
    raw_message: Any             # 原始消息对象
    metadata: Dict               # 渠道特有元数据
```

### 3.2 用户身份映射 (UserIdentity)

```python
@dataclass
class UserIdentity:
    global_user_id: str          # 全局唯一用户 ID
    feishu_open_id: str          # 飞书 open_id
    feishu_union_id: str         # 飞书 union_id
    feishu_user_id: str          # 飞书 user_id
    dingtalk_user_id: str        # 钉钉 user_id
    wechat_openid: str           # 微信 openid
    wechat_external_userid: str  # 企业微信 external_userid
    telegram_user_id: str        # Telegram user_id
    telegram_username: str       # Telegram username
    qq_openid: str               # QQ openid
    discord_user_id: str         # Discord user_id
    display_name: str            # 显示名称
```

### 3.3 会话上下文 (SessionContext)

```python
@dataclass
class SessionContext:
    session_id: str              # 全局会话 ID
    agent_id: str                # Agent ID
    global_user_id: str          # 全局用户 ID
    channel: MessageChannel      # 当前活跃渠道
    active_channels: List        # 所有活跃渠道
    conversation_history: List   # 对话历史
    memory_keys: List            # 关联的记忆键
```

---

## 4. 跨渠道消息流程

```
用户发送消息 (微信)
    ↓
[微信适配器] 解析原始消息 → UnifiedMessage
    ↓
[用户身份管理器] 识别/关联用户身份 → global_user_id
    ↓
[会话管理器] 获取/创建会话 (按 Agent 隔离) → session_id
    ↓
[消息路由器] 加载会话上下文 → 调用 Agent 处理
    ↓
Agent 生成回复
    ↓
[消息路由器] 发送响应到原渠道 (微信)
    ↓
───────── 用户切换渠道 ─────────
    ↓
[飞书适配器] 解析消息
    ↓
[用户身份管理器] 识别同一用户 → 相同 global_user_id
    ↓
[会话管理器] 获取相同会话 → 上下文保持!
    ↓
Agent 继续对话 (知道之前在微信聊了什么)
```

---

## 5. REST API 接口

### 5.1 渠道管理 API

**基础路径**: `/api/channels`

#### 获取渠道列表

```
GET /api/channels/
```

**响应**:
```json
{
    "success": true,
    "channels": [
        {
            "channel": "feishu",
            "enabled": true,
            "display_name": "飞书",
            "adapter_config": {...}
        }
    ],
    "total": 1
}
```

#### 获取渠道状态

```
GET /api/channels/<channel>
```

**参数**: `channel` - 渠道名称 (feishu, dingtalk, wechat, telegram)

#### 添加/更新渠道配置

```
POST /api/channels/<channel>
```

**请求体**:
```json
{
    "enabled": true,
    "config": {
        "app_id": "xxx",
        "app_secret": "xxx",
        "region": "cn",
        ...
    }
}
```

#### 部分更新渠道配置

```
PATCH /api/channels/<channel>/config
```

**请求体**:
```json
{
    "enabled": true,
    "bot_prefix": "@Kai",
    ...
}
```

#### 启用/禁用渠道

```
POST /api/channels/<channel>/enable
POST /api/channels/<channel>/disable
```

#### 移除渠道

```
DELETE /api/channels/<channel>
```

#### 获取渠道能力描述

```
GET /api/channels/capabilities
```

**用途**: 前端动态生成配置表单

**响应**:
```json
{
    "success": true,
    "capabilities": {
        "feishu": {
            "display_name": "飞书",
            "description": "飞书开放平台，支持国内和国际版本",
            "required_fields": ["app_id", "app_secret"],
            "optional_fields": [
                {"name": "region", "type": "select", "default": "cn", "options": ["cn", "sg"], "label": "地区"},
                {"name": "bot_prefix", "type": "text", "default": "@Kai", "label": "机器人前缀"},
                ...
            ],
            "webhook_url": "/api/channels/webhook/feishu"
        },
        ...
    }
}
```

### 5.2 用户身份管理 API

#### 关联用户身份

```
POST /api/channels/users/link
```

**请求体**:
```json
{
    "global_user_id": "user123",
    "channel": "feishu",
    "channel_user_id": "ou_xxx"
}
```

#### 获取用户会话

```
GET /api/channels/users/<global_user_id>/sessions?agent_id=Yiling
```

### 5.3 消息发送 API

```
POST /api/channels/<channel>/send
```

**请求体**:
```json
{
    "chat_id": "xxx",
    "content": "消息内容",
    "agent_id": "default"
}
```

### 5.4 Webhook 端点

```
POST /api/channels/webhook/<channel>?agent_id=Yiling
```

**用途**: 接收外部渠道的消息回调

### 5.5 其他 API

#### 健康检查

```
GET /health
```

#### 系统统计

```
GET /api/stats
```

#### 对话接口

```
POST /api/chat
```

**请求体**:
```json
{
    "message": "你好",
    "agent_id": "Yiling"
}
```

#### 添加记忆

```
POST /api/remember
```

**请求体**:
```json
{
    "content": "记忆内容",
    "category": "conversation",
    "is_important": false
}
```

#### 搜索记忆

```
GET /api/memories?query=关键词&limit=10
```

---

## 6. Web 管理界面

### 6.1 渠道管理页面

**文件**: `neurova/channels-ui.html`  
**访问**: `http://localhost:8000/channels-ui.html`

**功能**:
- 渠道列表展示 (支持全部/内置/自定义筛选)
- 渠道配置模态框 (动态生成表单)
- 开关控制渠道启用/禁用
- 保存配置到后端
- 测试连接功能
- Toast 提示反馈

**设计特点**:
- 深空主题，与 Neurova 整体风格统一
- 响应式布局，支持移动端
- 动态表单生成 (基于 capabilities API)
- 密码字段显示/隐藏切换
- 加载状态和空状态提示

### 6.2 统计页面

**文件**: `neurova/stats.html`  
**访问**: `http://localhost:8000/stats.html`

**功能**:
- Token 消耗统计
- 调用次数统计
- 趋势图表展示
- 环形图分布

---

## 7. Neurova Server

### 7.1 启动服务

```bash
python neurova/neurova_server.py
```

指定端口和 Agent：
```bash
python neurova/neurova_server.py --port 8080 --agent-id Yiling
```

调试模式：
```bash
python neurova/neurova_server.py --debug
```

禁用模块：
```bash
python neurova/neurova_server.py --no-memory --no-channels
```

### 7.2 服务器特性

- 整合所有 API 接口 (渠道、对话、记忆、统计)
- CORS 支持 (跨域请求)
- 静态文件服务 (HTML 页面)
- 配置持久化 (channels.json)
- 异常处理和日志记录

---

## 8. 文件结构

```
neurova/
├── channels/
│   ├── __init__.py           # 核心数据模型和基类
│   ├── feishu.py             # 飞书适配器
│   ├── dingtalk.py           # 钉钉适配器
│   ├── wechat.py             # 企业微信适配器
│   ├── telegram.py           # Telegram 适配器
│   ├── manager.py            # 渠道管理器
│   └── api.py                # 渠道 REST API
├── channels-ui.html          # 渠道管理 Web 页面
├── stats.html                # 统计页面
├── neurova_server.py           # Neurova Server 入口
├── server.py                 # 原始 HTTP 服务器 (保留)
└── memory/
    └── scripts/
        └── test_channels_api.py  # 渠道 API 测试脚本

docs/architecture/
└── channels.md               # 本文档

data/
└── channels.json             # 渠道配置持久化文件
```

---

## 9. 使用示例

### 9.1 程序化使用

```python
from neurova.channels.manager import ChannelManager
from neurova.channels import MessageChannel, ChannelConfig

# 1. 初始化渠道管理器
manager = ChannelManager(default_agent_id="Yiling")

# 2. 添加飞书渠道
feishu_config = ChannelConfig(
    channel=MessageChannel.FEISHU,
    enabled=True,
    config={
        "app_id": "cli_a94e05359b391cc0",
        "app_secret": "xxx",
        "bot_prefix": "@Kai",
        "region": "cn",
        "private_chat_strategy": "open",
        "group_chat_strategy": "open",
        "require_mention": True,
    }
)
manager.add_channel(feishu_config)

# 3. 关联用户身份 (微信 ↔ 飞书)
manager.link_user_identities(
    global_user_id="user123",
    channel=MessageChannel.FEISHU,
    channel_user_id="ou_xxx"
)

# 4. 处理消息
manager.process_incoming_message(raw_data, MessageChannel.FEISHU)

# 5. 发送消息
manager.send_message(MessageChannel.FEISHU, "chat_id", "你好!")
```

### 9.2 curl 测试

```bash
# 获取渠道列表
curl http://localhost:8000/api/channels/

# 配置飞书渠道
curl -X POST http://localhost:8000/api/channels/feishu \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "config": {
      "app_id": "cli_xxx",
      "app_secret": "xxx",
      "region": "cn",
      "bot_prefix": "@Kai"
    }
  }'

# 获取渠道能力
curl http://localhost:8000/api/channels/capabilities

# 关联用户身份
curl -X POST http://localhost:8000/api/channels/users/link \
  -H "Content-Type: application/json" \
  -d '{
    "global_user_id": "user123",
    "channel": "feishu",
    "channel_user_id": "ou_xxx"
  }'
```

---

## 10. 待扩展渠道

| 渠道 | 优先级 | 说明 |
|------|--------|------|
| QQ 频道 | 第二批 | 年轻用户群体 |
| Discord | 第二批 | 国际社区 |
| 微信客服 | 第三批 | 客户服务场景 |
| 短信 (Twilio) | 第三批 | 通知场景 |
| OneBot | 第三批 | 统一标准 |

---

## 11. 注意事项

1. **配置持久化**: 渠道配置保存在 `data/channels.json`，重启后自动加载
2. **内存会话**: 会话上下文在内存中管理，服务重启后会丢失
3. **跨渠道身份**: 需要手动关联同一用户在不同渠道的身份，或使用全局用户 ID
4. **Webhook 配置**: 各平台需要在开发者后台配置 Webhook URL 指向 `/api/channels/webhook/<channel>`
5. **安全**: 敏感配置 (secret, token) 建议通过环境变量传递，不要硬编码

---

*文档完成，消息渠道集成系统已实现核心功能*
