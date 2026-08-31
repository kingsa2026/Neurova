# 插件系统和 CLI 接口设计

> **状态**: 已实现（对照代码核实） · 版本: v1.0.0-beta1
> **说明**: 本文档描述的功能已在 `neurova/` 对应模块实现，详见 [功能模块矩阵](../0-index/README.md)


## 1. 概述

### 1.1 设计目标
- 热插拔插件系统
- 完善的插件生命周期管理
- 强大的 CLI 接口
- 支持远程插件仓库
- 插件依赖管理
- 插件版本控制

### 1.2 插件分类

```
插件系统
├── 功能插件
│   ├── LLM 提供商插件 (OpenAI, Anthropic, etc.)
│   ├── 消息渠道插件 (WeChat, Telegram, etc.)
│   ├── 存储插件 (SQLite, Redis, etc.)
│   └── 工具插件 (Search, Calculator, etc.)
│
├── 扩展插件
│   ├── 监控插件
│   ├── 日志插件
│   ├── 认证插件
│   └── 授权插件
│
└── 主题插件
    ├── UI 主题
    └── 语言包
```

## 2. 插件数据模型

### 2.1 语义化版本 (SemVer)

```python
from neurova.plugins.plugin_manifest import SemVersion, VersionConstraint

# 语义化版本解析
version = SemVersion("1.2.3")
print(version.major, version.minor, version.patch)  # 1 2 3

# 版本比较
v1 = SemVersion("1.2.3")
v2 = SemVersion("1.3.0")
print(v1 < v2)  # True

# 版本约束
constraint = VersionConstraint(">=1.0.0,<2.0.0")
print(constraint.satisfies(SemVersion("1.5.0")))  # True
print(constraint.satisfies(SemVersion("2.0.0")))  # False

# 兼容版本约束
constraint = VersionConstraint("^1.2.3")  # 等价于 >=1.2.3,<2.0.0
print(constraint.satisfies(SemVersion("1.9.9")))  # True

# 近似版本约束
constraint = VersionConstraint("~1.2.3")  # 等价于 >=1.2.3,<1.3.0
print(constraint.satisfies(SemVersion("1.2.9")))  # True
print(constraint.satisfies(SemVersion("1.3.0")))  # False
```

### 2.2 插件类型和状态

```python
from neurova.plugins.plugin_manifest import PluginType, PluginState, PluginPermission

# 插件类型
class PluginType(str, Enum):
    CORE = "core"           # 核心插件
    SKILL = "skill"         # 技能插件
    CHANNEL = "channel"     # 渠道插件
    TOOL = "tool"           # 工具插件
    THEME = "theme"         # 主题插件
    FUNCTIONAL = "functional"  # 功能插件
    EXTENSION = "extension"    # 扩展插件

# 插件状态
class PluginState(str, Enum):
    INSTALLED = "installed"   # 已安装
    ENABLED = "enabled"       # 已启用
    DISABLED = "disabled"     # 已禁用
    LOADED = "loaded"         # 已加载
    ERROR = "error"           # 错误
    UPDATING = "updating"     # 更新中

# 插件权限
class PluginPermission(str, Enum):
    READ_EVENTS = "read:events"      # 读取事件
    EMIT_EVENTS = "emit:events"      # 发送事件
    HTTP_REQUEST = "http:request"    # HTTP 请求
    READ_FILES = "read:files"        # 读取文件
    WRITE_FILES = "write:files"      # 写入文件
    EXECUTE_COMMANDS = "execute:commands"  # 执行命令
    NETWORK_ACCESS = "network:access"    # 网络访问
    ADMIN = "admin"                    # 管理员权限
```

### 2.3 插件清单 (PluginManifest)

```python
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from neurova.plugins.plugin_manifest import SemVersion, PluginType, PluginPermission

@dataclass
class PluginManifest:
    """插件清单数据结构"""
    plugin_id: str                    # 插件 ID
    name: str                         # 插件名称
    version: SemVersion               # 版本号
    description: str = ""             # 描述
    author: str = ""                  # 作者
    plugin_type: PluginType = PluginType.FUNCTIONAL  # 插件类型
    
    # 依赖
    dependencies: Dict[str, str] = None      # 依赖插件及版本约束
    optional_dependencies: Dict[str, str] = None  # 可选依赖
    neurova_min_version: str = ""      # 最低框架版本
    
    # 入口
    entry_point: str = ""              # 入口模块
    module_class: str = ""             # 入口类
    
    # 权限
    required_permissions: List[PluginPermission] = None
    
    # 配置
    config_schema: Dict[str, Any] = None
    default_config: Dict[str, Any] = None
    
    # API 端点
    api_endpoints: List[Dict[str, str]] = None
    
    # 前端资源
    frontend_resources: List[str] = None
    
    # 标签和元数据
    tags: List[str] = None
    homepage: str = ""
    license: str = ""
```

## 3. 插件管理器

### 3.1 核心实现

```python
from neurova.plugins.plugin_manager import PluginManager, get_plugin_manager

# 获取全局插件管理器
manager = get_plugin_manager("~/.neurova/plugins")

# 发现插件
plugins = manager.discover_plugins()
print(f"发现 {len(plugins)} 个插件")

# 安装插件
success = manager.install_plugin("/path/to/plugin")
if success:
    print("插件安装成功")

# 启用插件
success = manager.enable_plugin("my-plugin")
if success:
    print("插件已启用")

# 加载插件（启用后才能加载）
success = manager.load_plugin("my-plugin")
if success:
    print("插件已加载")

# 获取插件实例
plugin_instance = manager.get_module("my-plugin")
if plugin_instance:
    # 调用插件方法
    plugin_instance.do_something()

# 列出所有插件
plugins = manager.list_plugins()
for plugin in plugins:
    print(f"{plugin.name} v{plugin.version} - {'启用' if plugin.enabled else '禁用'}")

# 禁用插件
manager.disable_plugin("my-plugin")

# 卸载插件
manager.uninstall_plugin("my-plugin")
```

### 3.2 依赖解析

```python
# 拓扑排序确定加载顺序
load_order = manager.resolve_load_order()
print("加载顺序:", load_order)

# 批量操作
manager.enable_all()   # 启用所有插件
manager.load_all()     # 加载所有已启用的插件
manager.disable_all()  # 禁用所有插件
manager.unload_all()   # 卸载所有插件
```

### 3.3 插件生命周期管理

```python
from neurova.plugins.plugin_lifecycle import (
    LifecycleEvent, LifecycleHook, PluginLifecycleManager,
    get_lifecycle_manager, register_lifecycle_hook
)

# 获取生命周期管理器
lifecycle = get_lifecycle_manager()

# 注册生命周期钩子
hook = register_lifecycle_hook(
    event=LifecycleEvent.BEFORE_ENABLE,
    callback=lambda plugin_name: print(f"即将启用插件: {plugin_name}"),
    plugin_name="my-plugin",
    priority=10,
    description="启用前检查"
)

# 注册事件监听器
def on_plugin_enabled(plugin_name, **kwargs):
    print(f"插件已启用: {plugin_name}")

lifecycle.add_event_listener(LifecycleEvent.AFTER_ENABLE, on_plugin_enabled)

# 执行生命周期事件（自动触发钩子和监听器）
lifecycle.execute_lifecycle(LifecycleEvent.AFTER_ENABLE, "my-plugin")
```

### 3.4 插件基类

```python
from neurova.plugins.base_plugin import BasePlugin, APIEndpoint
from neurova.plugins.plugin_manifest import PluginManifest, PluginType, PluginPermission

class MyPlugin(BasePlugin):
    """示例插件"""
    
    # 插件元数据
    plugin_type = PluginType.FUNCTIONAL
    api_endpoints = [
        APIEndpoint(
            method="GET",
            path="/api/my-plugin/status",
            handler_name="get_status",
            description="获取插件状态",
            tags=["status"]
        )
    ]
    required_permissions = [PluginPermission.READ_EVENTS]
    
    def __init__(self, manifest: PluginManifest):
        super().__init__(manifest)
        self._data = {}
    
    async def on_initialize(self) -> None:
        """初始化回调"""
        self.log_info("插件初始化")
        # 加载配置
        config = self.manifest.default_config
        self._data = config.get("data", {})
    
    async def on_start(self) -> None:
        """启动回调"""
        self.log_info("插件启动")
        # 注册事件监听器
        self.subscribe("message.received", self._on_message)
    
    async def on_stop(self) -> None:
        """停止回调"""
        self.log_info("插件停止")
    
    async def on_destroy(self) -> None:
        """销毁回调"""
        self.log_info("插件销毁")
        self._data.clear()
    
    def _on_message(self, data):
        """处理消息事件"""
        self.log_info(f"收到消息: {data}")
        # 发布自定义事件
        self.publish_event("my_plugin.processed", {"result": "ok"})
    
    def get_status(self):
        """API 端点处理函数"""
        return {"status": "running", "data_count": len(self._data)}
```

## 4. CLI 接口设计

### 4.1 CLI 架构

Neurova CLI 是一个交互式命令行客户端，通过 HTTP API 与 Neurova 服务器通信。

```python
from cli import NeurovaCLI

# 创建 CLI 实例
cli = NeurovaCLI(base_url="http://localhost:9527")

# 运行交互式客户端
cli.run()
```

### 4.2 CLI 命令

#### 系统命令

```bash
# 显示帮助
/help

# 清屏
/clear

# 退出
/exit
# 或按 Ctrl+C
```

#### Agent 管理命令

```bash
# 列出所有 Agent
/agent

# 创建新 Agent
/agent add

# 删除 Agent
/agent del

# 切换 Agent（方式1）
/agent switch 1

# 切换 Agent（方式2，快捷方式）
/agent 1
```

#### LLM 管理命令

```bash
# 列出所有 LLM 服务商
/llm

# 添加 LLM 服务商
/llm add

# 删除 LLM 服务商
/llm del

# 切换 LLM 服务商/模型（方式1）
/llm switch 1

# 切换 LLM 服务商/模型（方式2，快捷方式）
/llm 1
```

### 4.3 CLI 使用示例

```bash
# 启动 CLI 客户端
python cli.py

# 指定服务器 URL
python cli.py --url http://192.168.1.100:9527

# 交互式会话示例
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   ███╗   ██╗███████╗██╗   ██╗██████╗  ██████╗ ██╗   ██╗      ║
║   ████╗  ██║██╔════╝██║   ██║██╔══██╗██╔═══██╗██║   ██║      ║
║   ██╔██╗ ██║█████╗  ██║   ██║██████╔╝██║   ██║██║   ██║      ║
║   ██║╚██╗██║██╔══╝  ██║   ██║██╔══██╗██║   ██║╚██╗ ██╔╝      ║
║   ██║ ╚████║███████╗╚██████╔╝██║  ██║╚██████╔╝ ╚████╔╝       ║
║   ╚═╝  ╚═══╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝   ╚═══╝        ║
║                                                               ║
║            智能无限，协作无间 - CLI 聊天客户端                  ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝

[✓] 服务器连接成功: http://localhost:9527
[✓] 登录成功
[✓] 已选择 Agent: 默认助手 (ID: agent_001)

输入 /help 查看命令帮助，输入消息开始聊天，Ctrl+C 退出

[默认助手] > 你好
[思考中...]
[Neurova] 你好！有什么可以帮助你的吗？

[默认助手] > /agent
┌─────────────────────────────────────────────────────────────┐
│  Agent 列表                                                 │
├─────────────────────────────────────────────────────────────┤
│ ► 1. 默认助手               ID: agent_001      状态: running 模型: gpt-4
│   2. 代码助手               ID: agent_002      状态: running 模型: claude-3
└─────────────────────────────────────────────────────────────┘

提示: 输入序号切换 Agent，或使用 /agent switch <序号>
```

## 5. CLI 工具执行器

### 5.1 功能概述

CLIToolExecutor 提供安全的命令行执行能力，包括：
- 风险评估
- 命令白名单
- 输出脱敏
- 超时控制

```python
from neurova.tool_layers.cli_tool import CLIToolExecutor

# 创建执行器
executor = CLIToolExecutor()

# 评估命令风险
risk = executor.assess_risk("rm -rf /")
print(risk)
# {
#     "level": "critical",
#     "score": 0.95,
#     "reasons": ["Pattern: rm\\s+-rf\\s+/", "Dangerous character: /"],
#     "allowed": False
# }

# 安全命令执行
result = executor.execute_sync("ls -la", timeout=10.0)
print(result)
# {
#     "success": True,
#     "output": "total 123...",
#     "error": "",
#     "return_code": 0,
#     "risk": {"level": "low", "score": 0.0, ...}
# }

# 创建 CLI 工具模板
tool = executor.create_cli_tool(
    name="git_status",
    command="git -C {repo_path} status",
    parameters={
        "repo_path": {
            "type": "string",
            "required": True,
            "description": "Git 仓库路径"
        }
    },
    description="获取 Git 仓库状态"
)

# 执行 CLI 工具
result = executor.execute_cli_tool("git_status", {"repo_path": "/path/to/repo"})
```

### 5.2 风险评估

```python
# 风险级别
# - critical: 极高风险（rm -rf /, dd, mkfs 等）
# - high: 高风险（sudo rm, eval, exec 等）
# - medium: 中等风险（cat /etc/passwd, find / 等）
# - low: 低风险（ls, echo, cat 等）

# 白名单命令
allowed_commands = [
    'ls', 'echo', 'cat', 'grep', 'find', 'wc', 'head', 'tail',
    'sort', 'uniq', 'awk', 'sed', 'tr', 'cut', 'paste',
    'mkdir', 'rmdir', 'touch', 'cp', 'mv', 'ln',
    'ps', 'top', 'df', 'du', 'free', 'uptime',
    'git', 'python', 'pip', 'node', 'npm',
    'docker', 'kubectl', 'make', 'cmake'
]
```

### 5.3 输出脱敏

```python
# 敏感信息模式（自动脱敏）
sensitive_patterns = [
    (r'password\s*[=:]\s*\S+', "password=***"),
    (r'api_key\s*[=:]\s*\S+', "api_key=***"),
    (r'secret\s*[=:]\s*\S+', "secret=***"),
    (r'token\s*[=:]\s*\S+', "token=***"),
    (r'key\s*[=:]\s*[A-Za-z0-9+/=]{20,}', "key=***"),
    (r'[A-Za-z0-9+/=]{40,}', "***"),  # Base64 编码的长字符串
]
```

## 6. 配置示例

### 6.1 插件清单示例

```json
{
  "plugin_id": "my-plugin",
  "name": "My Plugin",
  "description": "A sample plugin for Neurova",
  "version": "1.0.0",
  "author": "Your Name",
  "plugin_type": "functional",
  "dependencies": {},
  "optional_dependencies": {},
  "neurova_min_version": "4.0.0",
  "entry_point": "main.py",
  "module_class": "MyPlugin",
  "required_permissions": [
    "read:events",
    "emit:events"
  ],
  "config_schema": {
    "type": "object",
    "properties": {
      "api_key": {
        "type": "string",
        "description": "API Key"
      }
    }
  },
  "default_config": {
    "api_key": ""
  },
  "api_endpoints": [
    {
      "method": "GET",
      "path": "/api/my-plugin/status",
      "handler": "get_status"
    }
  ],
  "frontend_resources": [
    "dist/index.js",
    "dist/index.css"
  ],
  "tags": ["sample", "demo"],
  "homepage": "https://github.com/yourname/my-plugin",
  "license": "MIT"
}
```

### 6.2 插件目录结构

```
my-plugin/
├── manifest.json          # 插件清单
├── main.py                # 入口模块
├── requirements.txt       # Python 依赖
├── README.md              # 插件文档
├── dist/                  # 前端资源
│   ├── index.js
│   └── index.css
└── tests/                 # 测试文件
    └── test_plugin.py
```

### 6.3 插件入口模块

```python
# main.py
from neurova.plugins.base_plugin import BasePlugin, APIEndpoint
from neurova.plugins.plugin_manifest import PluginManifest, PluginType, PluginPermission

class MyPlugin(BasePlugin):
    """示例插件"""
    
    plugin_type = PluginType.FUNCTIONAL
    api_endpoints = [
        APIEndpoint(
            method="GET",
            path="/api/my-plugin/status",
            handler_name="get_status",
            description="获取插件状态"
        )
    ]
    required_permissions = [PluginPermission.READ_EVENTS]
    
    def __init__(self, manifest: PluginManifest):
        super().__init__(manifest)
        self._counter = 0
    
    async def on_initialize(self) -> None:
        """初始化"""
        self.log_info("插件初始化完成")
    
    async def on_start(self) -> None:
        """启动"""
        self.log_info("插件启动")
        self.subscribe("message.received", self._on_message)
    
    async def on_stop(self) -> None:
        """停止"""
        self.log_info("插件停止")
    
    async def on_destroy(self) -> None:
        """销毁"""
        self.log_info("插件销毁")
    
    def _on_message(self, data):
        """处理消息"""
        self._counter += 1
        self.publish_event("my_plugin.count", {"count": self._counter})
    
    def get_status(self):
        """API 端点"""
        return {"status": "running", "count": self._counter}
```

## 7. API 接口

### 7.1 插件管理 API

```http
# 列出所有插件
GET /api/v1/plugins

# 获取插件详情
GET /api/v1/plugins/{plugin_id}

# 安装插件
POST /api/v1/plugins/install
Content-Type: application/json
{
  "source": "/path/to/plugin",
  "version": "1.0.0"
}

# 卸载插件
DELETE /api/v1/plugins/{plugin_id}

# 启用插件
POST /api/v1/plugins/{plugin_id}/enable

# 禁用插件
POST /api/v1/plugins/{plugin_id}/disable

# 获取插件状态
GET /api/v1/plugins/status
```

### 7.2 CLI API

```http
# 聊天接口
POST /api/v1/chat
Content-Type: application/json
{
  "message": "你好",
  "agent_id": "agent_001"
}

# 列出 Agent
GET /api/v1/agents

# 创建 Agent
POST /api/v1/agents
Content-Type: application/json
{
  "name": "新助手",
  "description": "一个新助手",
  "enable_memory": true
}

# 列出 LLM 服务商
GET /api/v1/providers

# 切换模型
POST /api/v1/providers/activate-model
Content-Type: application/json
{
  "provider_id": "openai",
  "model_id": "gpt-4"
}
```

## 8. 最佳实践

### 8.1 插件开发

1. **遵循 SemVer 规范**：版本号应反映兼容性变化
2. **声明依赖**：明确列出必需和可选依赖
3. **最小权限原则**：只申请必需的权限
4. **错误处理**：在生命周期回调中妥善处理异常
5. **资源清理**：在 `on_destroy()` 中释放所有资源
6. **日志记录**：使用 `self.log_info/warning/error()` 记录日志

### 8.2 CLI 使用

1. **使用 `/help` 查看命令**：了解所有可用命令
2. **切换 Agent 前先列出**：使用 `/agent` 查看所有 Agent
3. **切换模型前先列出**：使用 `/llm` 查看所有服务商和模型
4. **使用快捷方式**：`/agent 1` 等同于 `/agent switch 1`

### 8.3 安全考虑

1. **插件签名**：验证插件来源和完整性
2. **权限控制**：限制插件可访问的资源
3. **沙箱执行**：在隔离环境中运行插件
4. **审计日志**：记录所有插件操作
5. **CLI 命令白名单**：只允许安全命令执行
6. **输出脱敏**：自动过滤敏感信息

## 9. 故障排除

### 9.1 常见问题

**插件无法加载**
- 检查 `manifest.json` 格式是否正确
- 确认 `entry_point` 指向的文件存在
- 检查依赖是否已安装
- 查看日志中的错误信息

**CLI 无法连接服务器**
- 确认服务器已启动（`python start.py`）
- 检查 URL 是否正确（默认 `http://localhost:9527`）
- 检查网络连接和防火墙设置

**命令执行被拒绝**
- 检查命令是否在白名单中
- 评估命令风险级别
- 使用更安全的替代命令

### 9.2 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查插件状态
manager = get_plugin_manager()
status = manager.get_status()
print(status)

# 检查生命周期钩子
lifecycle = get_lifecycle_manager()
hooks = lifecycle.list_hooks()
print(hooks)
```
