# Phase 5 觉醒基石·并行开发计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 完成Neurova Phase 5核心基石搭建：统一应用入口、动态API路由、前端插件加载器、元认知系统、实时记忆流

**Architecture:** 采用并行开发策略，5个独立任务同时推进，每个任务有明确的输入输出和接口定义，最终集成

**Tech Stack:** Python 3.11+, Flask, SQLite, JavaScript ES6+, HTML5/CSS3

**开发策略:**
- 并行启动5个开发任务（Task 1-5）
- 每个任务独立开发、独立测试
- 最后集成测试

---

## Task 1: 统一应用入口 (neurova/app.py)

**负责人:** Agent-Alpha
**优先级:** P0（最关键）
**预计时间:** 30分钟

**目标:** 创建统一的应用入口，取代分散的启动方式

**Files:**
- Create: `neurova/app.py` - 统一应用入口
- Create: `neurova/config/default.py` - 默认配置
- Modify: `neurova/neurova_server.py` - 重构为使用app.py
- Test: `tests/test_app_entry.py`

### 架构设计

```
neurova/app.py
├── create_app(config=None) -> Flask app
│   ├── 加载配置（默认/环境变量/文件）
│   ├── 初始化核心模块（EventBus, StateManager, ConfigManager, Logger, ErrorHandler）
│   ├── 注册Blueprint（auth, agent, chat, memory, skill, channels）
│   ├── 注册插件Blueprint
│   ├── 注册中间件（CORS, Auth, Error Handler）
│   └── 返回完整配置的Flask app
├── run_app(app, host, port, debug) -> 启动服务器
└── get_app() -> 获取全局app实例（单例模式）
```

### Step 1: 创建默认配置文件

```python
# neurova/config/default.py
class DefaultConfig:
    """Neurova默认配置"""
    
    # 服务器配置
    HOST = '0.0.0.0'
    PORT = 9527
    DEBUG = False
    
    # 数据库配置
    MEMORY_DB_PATH = 'memory/data/yi_ling_memory.db'
    
    # 安全配置
    SECRET_KEY = None  # 从环境变量或持久化文件加载
    CORS_ORIGINS = '*'  # 生产环境应设置为具体域名
    
    # LLM配置
    LLM_PROVIDER = 'openai'
    LLM_MODEL = 'gpt-4'
    LLM_API_KEY = None
    
    # 日志配置
    LOG_LEVEL = 'INFO'
    LOG_FORMAT = 'json'
    
    @classmethod
    def from_env(cls):
        """从环境变量加载配置"""
        import os
        config = cls()
        config.HOST = os.getenv('NEUROVA_HOST', cls.HOST)
        config.PORT = int(os.getenv('NEUROVA_PORT', cls.PORT))
        config.DEBUG = os.getenv('NEUROVA_DEBUG', 'false').lower() == 'true'
        config.LOG_LEVEL = os.getenv('NEUROVA_LOG_LEVEL', cls.LOG_LEVEL)
        return config
```

### Step 2: 创建统一应用入口

```python
# neurova/app.py
"""Neurova统一应用入口

使用方式:
    from neurova.app import create_app, run_app
    
    # 创建应用
    app = create_app()
    
    # 启动应用
    run_app(app, host='0.0.0.0', port=9527, debug=True)
"""

from flask import Flask
from typing import Optional

from neurova.config.default import DefaultConfig
from neurova.core.event_bus import EventBus
from neurova.core.state_manager import StateManager
from neurova.core.config_manager import ConfigManager
from neurova.core.logger import LogManager
from neurova.core.error_handler import ErrorHandler
from neurova.core.module_lib import ModuleLib


def create_app(config: Optional[dict] = None) -> Flask:
    """创建并配置Neurova应用
    
    Args:
        config: 可选的配置字典，会覆盖默认配置
        
    Returns:
        配置完成的Flask应用实例
    """
    app = Flask(__name__)
    
    # 1. 加载配置
    _load_config(app, config)
    
    # 2. 初始化核心模块
    _init_core_modules(app)
    
    # 3. 注册Blueprint
    _register_blueprints(app)
    
    # 4. 注册中间件
    _register_middleware(app)
    
    # 5. 注册错误处理器
    _register_error_handlers(app)
    
    # 6. 初始化插件系统
    _init_plugins(app)
    
    return app


def _load_config(app: Flask, config: Optional[dict] = None):
    """加载配置"""
    # 加载默认配置
    default_config = DefaultConfig.from_env()
    
    for key in dir(default_config):
        if not key.startswith('_'):
            value = getattr(default_config, key)
            app.config[key] = value
    
    # 应用自定义配置（覆盖默认值）
    if config:
        app.config.update(config)


def _init_core_modules(app: Flask):
    """初始化核心模块"""
    # 事件总线
    app.event_bus = EventBus()
    
    # 状态管理器
    app.state_manager = StateManager()
    
    # 配置管理器
    app.config_manager = ConfigManager()
    
    # 日志管理器
    app.log_manager = LogManager(level=app.config.get('LOG_LEVEL', 'INFO'))
    
    # 错误处理器
    app.error_handler = ErrorHandler()
    
    # 模块库
    app.module_lib = ModuleLib(event_bus=app.event_bus)


def _register_blueprints(app: Flask):
    """注册所有Blueprint"""
    from neurova.api.auth import auth_bp
    from neurova.api.endpoints.agent import agent_bp
    from neurova.api.endpoints.chat import chat_bp
    from neurova.api.endpoints.memory import memory_bp
    from neurova.api.endpoints.skill import skill_bp
    from neurova.api.endpoints.channel import channel_bp
    
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(agent_bp, url_prefix='/api/agent')
    app.register_blueprint(chat_bp, url_prefix='/api/chat')
    app.register_blueprint(memory_bp, url_prefix='/api/memory')
    app.register_blueprint(skill_bp, url_prefix='/api/skills')
    app.register_blueprint(channel_bp, url_prefix='/api/channels')


def _register_middleware(app: Flask):
    """注册中间件"""
    from neurova.api.middleware import AuthMiddleware, CORS
    
    # CORS中间件
    CORS(app, origins=app.config.get('CORS_ORIGINS', '*'))
    
    # 认证中间件（跳过公开端点）
    app.before_request(AuthMiddleware(app.config.get('SECRET_KEY')).process_request)


def _register_error_handlers(app: Flask):
    """注册错误处理器"""
    @app.errorhandler(400)
    def bad_request(error):
        return {'success': False, 'error': 'Bad Request', 'code': 400}, 400
    
    @app.errorhandler(401)
    def unauthorized(error):
        return {'success': False, 'error': 'Unauthorized', 'code': 401}, 401
    
    @app.errorhandler(404)
    def not_found(error):
        return {'success': False, 'error': 'Not Found', 'code': 404}, 404
    
    @app.errorhandler(500)
    def internal_error(error):
        app.log_manager.error(f"Internal Server Error: {error}")
        return {'success': False, 'error': 'Internal Server Error', 'code': 500}, 500


def _init_plugins(app: Flask):
    """初始化插件系统"""
    from neurova.plugins.plugin_manager import PluginManager
    from pathlib import Path
    
    plugin_dir = Path(__file__).parent / 'plugins' / 'installed'
    
    if plugin_dir.exists():
        app.plugin_manager = PluginManager(plugin_dir=plugin_dir)
        # 插件会在app启动后异步加载
    else:
        app.plugin_manager = None


def run_app(app: Flask, host: str = None, port: int = None, debug: bool = None):
    """启动Neurova应用
    
    Args:
        app: Flask应用实例
        host: 服务器主机地址
        port: 服务器端口
        debug: 是否开启调试模式
    """
    host = host or app.config.get('HOST', '0.0.0.0')
    port = port or app.config.get('PORT', 9527)
    debug = debug if debug is not None else app.config.get('DEBUG', False)
    
    print(f"🚀 Neurova starting on http://{host}:{port}")
    print(f"   Debug mode: {debug}")
    
    app.run(host=host, port=port, debug=debug)


# 全局app实例（单例模式）
_app_instance = None

def get_app() -> Flask:
    """获取全局app实例（单例模式）"""
    global _app_instance
    if _app_instance is None:
        _app_instance = create_app()
    return _app_instance
```

### Step 3: 测试文件

```python
# tests/test_app_entry.py
"""测试统一应用入口"""
import pytest
from neurova.app import create_app, get_app


def test_create_app():
    """测试创建应用"""
    app = create_app()
    assert app is not None
    assert hasattr(app, 'event_bus')
    assert hasattr(app, 'state_manager')
    assert hasattr(app, 'config_manager')
    assert hasattr(app, 'log_manager')
    assert hasattr(app, 'error_handler')
    assert hasattr(app, 'module_lib')


def test_app_config():
    """测试应用配置"""
    app = create_app()
    assert 'HOST' in app.config
    assert 'PORT' in app.config
    assert 'DEBUG' in app.config
    assert app.config['PORT'] == 9527


def test_app_custom_config():
    """测试自定义配置"""
    custom_config = {'PORT': 8080, 'DEBUG': True}
    app = create_app(config=custom_config)
    assert app.config['PORT'] == 8080
    assert app.config['DEBUG'] is True


def test_get_app_singleton():
    """测试单例模式"""
    app1 = get_app()
    app2 = get_app()
    assert app1 is app2  # 应该是同一个实例


def test_app_blueprints():
    """测试Blueprint注册"""
    app = create_app()
    blueprints = list(app.blueprints.keys())
    assert 'auth' in blueprints or 'auth_bp' in blueprints
    assert 'agent' in blueprints or 'agent_bp' in blueprints


def test_health_endpoint():
    """测试健康检查端点"""
    app = create_app()
    with app.test_client() as client:
        response = client.get('/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'
```

---

## Task 2: 动态API路由器

**负责人:** Agent-Beta
**优先级:** P0
**预计时间:** 40分钟

**目标:** 实现插件自动注册API端点的路由器

**Files:**
- Create: `neurova/core/api_router.py` - 动态API路由器
- Create: `neurova/plugins/plugin_api_registry.py` - 插件API注册器
- Modify: `neurova/plugins/base_plugin.py` - 添加API注册方法
- Test: `tests/test_api_router.py`

### 架构设计

```
neurova/core/api_router.py
├── APIRouter 类
│   ├── register_endpoint(endpoint) -> 注册端点
│   ├── unregister_endpoint(name) -> 注销端点
│   ├── get_endpoints() -> 获取所有端点
│   ├── mount_to_flask(app) -> 挂载到Flask
│   └── get_openapi_spec() -> 生成OpenAPI规范
└── 端点定义
    └── APIEndpoint
        ├── name: str
        ├── path: str
        ├── methods: List[str]
        ├── handler: Callable
        ├── auth_required: bool
        ├── permissions: List[str]
        └── metadata: dict
```

### Step 1: 创建动态API路由器

```python
# neurova/core/api_router.py
"""动态API路由器

支持插件在运行时动态注册和注销API端点
"""

from typing import List, Dict, Callable, Optional
from dataclasses import dataclass, field
from functools import wraps


@dataclass
class APIEndpoint:
    """API端点定义"""
    name: str
    path: str
    methods: List[str]
    handler: Callable
    auth_required: bool = False
    permissions: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    plugin_id: Optional[str] = None  # 所属插件ID


class APIRouter:
    """动态API路由器"""
    
    def __init__(self):
        self._endpoints: Dict[str, APIEndpoint] = {}
        self._routes: Dict[str, Callable] = {}
    
    def register_endpoint(self, endpoint: APIEndpoint) -> bool:
        """注册API端点
        
        Args:
            endpoint: API端点定义
            
        Returns:
            是否注册成功
        """
        if endpoint.name in self._endpoints:
            return False  # 端点已存在
        
        self._endpoints[endpoint.name] = endpoint
        self._routes[endpoint.path] = endpoint.handler
        return True
    
    def unregister_endpoint(self, name: str) -> bool:
        """注销API端点
        
        Args:
            name: 端点名称
            
        Returns:
            是否注销成功
        """
        if name not in self._endpoints:
            return False
        
        endpoint = self._endpoints.pop(name)
        self._routes.pop(endpoint.path, None)
        return True
    
    def unregister_plugin_endpoints(self, plugin_id: str) -> int:
        """注销插件的所有端点
        
        Args:
            plugin_id: 插件ID
            
        Returns:
            注销的端点数量
        """
        removed = 0
        to_remove = [
            name for name, ep in self._endpoints.items()
            if ep.plugin_id == plugin_id
        ]
        for name in to_remove:
            if self.unregister_endpoint(name):
                removed += 1
        return removed
    
    def get_endpoint(self, name: str) -> Optional[APIEndpoint]:
        """获取端点定义"""
        return self._endpoints.get(name)
    
    def get_endpoints(self) -> List[APIEndpoint]:
        """获取所有端点"""
        return list(self._endpoints.values())
    
    def get_endpoints_by_plugin(self, plugin_id: str) -> List[APIEndpoint]:
        """获取插件的所有端点"""
        return [
            ep for ep in self._endpoints.values()
            if ep.plugin_id == plugin_id
        ]
    
    def mount_to_flask(self, app, url_prefix: str = '/api/plugins'):
        """将动态端点挂载到Flask应用
        
        Args:
            app: Flask应用实例
            url_prefix: URL前缀
        """
        from flask import Blueprint, request, jsonify
        
        # 创建动态路由Blueprint
        dynamic_bp = Blueprint('dynamic_api', __name__, url_prefix=url_prefix)
        
        # 为每个端点创建路由
        for endpoint in self._endpoints.values():
            self._create_route_for_endpoint(dynamic_bp, endpoint)
        
        app.register_blueprint(dynamic_bp)
    
    def _create_route_for_endpoint(self, bp, endpoint: APIEndpoint):
        """为端点创建Flask路由"""
        from flask import request, jsonify
        from functools import wraps
        
        def wrapped_handler(*args, **kwargs):
            # 认证检查
            if endpoint.auth_required:
                # TODO: 实现认证检查
                pass
            
            # 权限检查
            if endpoint.permissions:
                # TODO: 实现权限检查
                pass
            
            # 调用原始handler
            return endpoint.handler(*args, **kwargs)
        
        # 动态添加路由到Blueprint
        methods = endpoint.methods or ['GET']
        bp.add_url_rule(
            endpoint.path,
            endpoint.name,
            wrapped_handler,
            methods=methods
        )
    
    def get_openapi_spec(self) -> Dict:
        """生成OpenAPI规范"""
        paths = {}
        for endpoint in self._endpoints.values():
            if endpoint.path not in paths:
                paths[endpoint.path] = {}
            
            for method in endpoint.methods:
                paths[endpoint.path][method.lower()] = {
                    'summary': endpoint.metadata.get('summary', endpoint.name),
                    'description': endpoint.metadata.get('description', ''),
                    'operationId': endpoint.name,
                    'tags': endpoint.metadata.get('tags', ['plugins']),
                }
        
        return {
            'openapi': '3.0.0',
            'info': {
                'title': 'Neurova Plugin API',
                'version': '1.0.0'
            },
            'paths': paths
        }


# 全局路由器实例
api_router = APIRouter()
```

### Step 2: 创建插件API注册器

```python
# neurova/plugins/plugin_api_registry.py
"""插件API注册器

插件使用此类注册自己的API端点
"""

from typing import List, Callable, Optional
from neurova.core.api_router import APIEndpoint, api_router


class PluginAPIRegistry:
    """插件API注册器"""
    
    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id
        self._registered_endpoints: List[str] = []
    
    def register_route(
        self,
        path: str,
        methods: List[str] = None,
        handler: Callable = None,
        name: str = None,
        auth_required: bool = False,
        permissions: List[str] = None,
        metadata: dict = None
    ) -> bool:
        """注册API路由
        
        Args:
            path: URL路径（相对于插件前缀）
            methods: HTTP方法列表
            handler: 处理函数
            name: 端点名称（默认为handler函数名）
            auth_required: 是否需要认证
            permissions: 权限列表
            metadata: 元数据
            
        Returns:
            是否注册成功
        """
        if methods is None:
            methods = ['GET']
        
        # 生成端点名称
        endpoint_name = name or handler.__name__
        full_name = f"{self.plugin_id}_{endpoint_name}"
        
        endpoint = APIEndpoint(
            name=full_name,
            path=path,
            methods=methods,
            handler=handler,
            auth_required=auth_required,
            permissions=permissions or [],
            metadata=metadata or {},
            plugin_id=self.plugin_id
        )
        
        success = api_router.register_endpoint(endpoint)
        if success:
            self._registered_endpoints.append(full_name)
        
        return success
    
    def unregister_all(self) -> int:
        """注销所有已注册的端点
        
        Returns:
            注销的端点数量
        """
        removed = 0
        for name in self._registered_endpoints:
            if api_router.unregister_endpoint(name):
                removed += 1
        self._registered_endpoints.clear()
        return removed
    
    def get_registered_endpoints(self) -> List[str]:
        """获取已注册的端点名称"""
        return self._registered_endpoints.copy()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unregister_all()
```

### Step 3: 修改BasePlugin添加API注册支持

在 `neurova/plugins/base_plugin.py` 中添加：

```python
def register_api_route(self, path, methods=None, handler=None, **kwargs):
    """注册API路由（插件使用）"""
    if not hasattr(self, '_api_registry'):
        from neurova.plugins.plugin_api_registry import PluginAPIRegistry
        self._api_registry = PluginAPIRegistry(plugin_id=self.module_id)
    
    return self._api_registry.register_route(
        path=path,
        methods=methods,
        handler=handler,
        **kwargs
    )

def on_stop(self):
    """插件停止时清理API端点"""
    if hasattr(self, '_api_registry'):
        self._api_registry.unregister_all()
```

### Step 4: 测试文件

```python
# tests/test_api_router.py
"""测试动态API路由器"""
import pytest
from neurova.core.api_router import APIRouter, APIEndpoint
from neurova.plugins.plugin_api_registry import PluginAPIRegistry


def test_register_endpoint():
    """测试注册端点"""
    router = APIRouter()
    
    def handler():
        return {'status': 'ok'}
    
    endpoint = APIEndpoint(
        name='test_endpoint',
        path='/test',
        methods=['GET'],
        handler=handler
    )
    
    assert router.register_endpoint(endpoint) is True
    assert router.get_endpoint('test_endpoint') == endpoint


def test_unregister_endpoint():
    """测试注销端点"""
    router = APIRouter()
    
    endpoint = APIEndpoint(
        name='test',
        path='/test',
        methods=['GET'],
        handler=lambda: {}
    )
    
    router.register_endpoint(endpoint)
    assert router.unregister_endpoint('test') is True
    assert router.get_endpoint('test') is None


def test_plugin_api_registry():
    """测试插件API注册器"""
    registry = PluginAPIRegistry(plugin_id='test_plugin')
    
    def handler():
        return {'data': 'test'}
    
    assert registry.register_route(
        path='/test',
        methods=['GET'],
        handler=handler
    ) is True
    
    assert 'test_plugin_handler' in registry.get_registered_endpoints()
    assert registry.unregister_all() == 1


def test_unregister_plugin_endpoints():
    """测试注销插件所有端点"""
    router = APIRouter()
    
    for i in range(3):
        endpoint = APIEndpoint(
            name=f'plugin_ep_{i}',
            path=f'/test/{i}',
            methods=['GET'],
            handler=lambda: {},
            plugin_id='test_plugin'
        )
        router.register_endpoint(endpoint)
    
    removed = router.unregister_plugin_endpoints('test_plugin')
    assert removed == 3
    assert len(router.get_endpoints()) == 0
```

---

## Task 3: 前端插件加载器

**负责人:** Agent-Gamma
**优先级:** P1
**预计时间:** 35分钟

**目标:** 实现前端插件动态加载和卸载机制

**Files:**
- Create: `static/js/plugin-loader.js` - 前端插件加载器
- Create: `static/plugins/` - 前端插件目录
- Create: `static/plugins/weather-plugin.js` - 示例插件
- Test: 在浏览器中测试插件加载

### 架构设计

```
static/js/plugin-loader.js
├── PluginLoader 类
│   ├── loadPlugin(pluginUrl) -> 加载插件
│   ├── unloadPlugin(pluginId) -> 卸载插件
│   ├── getPlugin(pluginId) -> 获取插件
│   ├── listPlugins() -> 列出所有插件
│   └── executeHook(hookName, ...args) -> 执行插件钩子
└── 插件接口
    └── Plugin
        ├── id: string
        ├── name: string
        ├── version: string
        ├── init() -> 初始化
        ├── destroy() -> 清理
        ├── hooks: { [hookName]: Function }
        └── metadata: object
```

### Step 1: 创建前端插件加载器

```javascript
// static/js/plugin-loader.js
/**
 * Neurova前端插件加载器
 * 
 * 功能：
 * - 动态加载/卸载插件
 * - 插件生命周期管理
 * - 钩子系统
 * - 插件间通信
 */

(function() {
    'use strict';

    var PluginLoader = function(options) {
        this.options = options || {};
        this.plugins = {};
        this.hooks = {};
        this.eventBus = window.NeurovaUI ? window.NeurovaUI.eventBus : null;
    };

    /**
     * 加载插件
     * @param {string} pluginUrl - 插件JS文件URL
     * @param {object} config - 插件配置
     * @returns {Promise} 加载完成的插件
     */
    PluginLoader.prototype.loadPlugin = function(pluginUrl, config) {
        var self = this;
        
        return new Promise(function(resolve, reject) {
            // 动态加载JS文件
            var script = document.createElement('script');
            script.src = pluginUrl;
            script.async = true;
            
            script.onload = function() {
                try {
                    // 假设插件导出了 Plugin 类或对象
                    var PluginClass = window[pluginUrl.split('/').pop().replace('.js', '')];
                    if (!PluginClass) {
                        reject(new Error('Plugin not found after loading: ' + pluginUrl));
                        return;
                    }
                    
                    // 实例化插件
                    var plugin = new PluginClass(config);
                    
                    // 验证插件接口
                    self._validatePlugin(plugin);
                    
                    // 初始化插件
                    if (plugin.init) {
                        plugin.init();
                    }
                    
                    // 注册插件
                    self.plugins[plugin.id] = plugin;
                    
                    // 注册插件钩子
                    if (plugin.hooks) {
                        self._registerHooks(plugin.id, plugin.hooks);
                    }
                    
                    // 触发插件加载完成事件
                    self._emitEvent('plugin:loaded', {
                        pluginId: plugin.id,
                        pluginName: plugin.name,
                        version: plugin.version
                    });
                    
                    resolve(plugin);
                } catch (error) {
                    reject(error);
                }
            };
            
            script.onerror = function() {
                reject(new Error('Failed to load plugin: ' + pluginUrl));
            };
            
            document.head.appendChild(script);
        });
    };

    /**
     * 卸载插件
     * @param {string} pluginId - 插件ID
     * @returns {boolean} 是否卸载成功
     */
    PluginLoader.prototype.unloadPlugin = function(pluginId) {
        var plugin = this.plugins[pluginId];
        if (!plugin) {
            return false;
        }
        
        try {
            // 调用插件销毁方法
            if (plugin.destroy) {
                plugin.destroy();
            }
            
            // 注销插件钩子
            this._unregisterHooks(pluginId);
            
            // 删除插件引用
            delete this.plugins[pluginId];
            
            // 触发插件卸载事件
            this._emitEvent('plugin:unloaded', {
                pluginId: pluginId
            });
            
            return true;
        } catch (error) {
            console.error('Error unloading plugin:', error);
            return false;
        }
    };

    /**
     * 获取插件
     * @param {string} pluginId - 插件ID
     * @returns {object|null} 插件对象
     */
    PluginLoader.prototype.getPlugin = function(pluginId) {
        return this.plugins[pluginId] || null;
    };

    /**
     * 列出所有插件
     * @returns {Array} 插件列表
     */
    PluginLoader.prototype.listPlugins = function() {
        var self = this;
        return Object.keys(this.plugins).map(function(id) {
            var plugin = self.plugins[id];
            return {
                id: plugin.id,
                name: plugin.name,
                version: plugin.version,
                metadata: plugin.metadata || {}
            };
        });
    };

    /**
     * 执行插件钩子
     * @param {string} hookName - 钩子名称
     * @param {...*} args - 传递给钩子的参数
     * @returns {Array} 所有钩子执行结果
     */
    PluginLoader.prototype.executeHook = function(hookName) {
        var args = Array.prototype.slice.call(arguments, 1);
        var results = [];
        
        if (!this.hooks[hookName]) {
            return results;
        }
        
        for (var i = 0; i < this.hooks[hookName].length; i++) {
            var hook = this.hooks[hookName][i];
            try {
                var result = hook.callback.apply(null, args);
                results.push({
                    pluginId: hook.pluginId,
                    result: result
                });
            } catch (error) {
                console.error('Error executing hook:', hookName, error);
            }
        }
        
        return results;
    };

    /**
     * 验证插件接口
     * @private
     */
    PluginLoader.prototype._validatePlugin = function(plugin) {
        if (!plugin.id || typeof plugin.id !== 'string') {
            throw new Error('Plugin must have an id');
        }
        if (!plugin.name || typeof plugin.name !== 'string') {
            throw new Error('Plugin must have a name');
        }
    };

    /**
     * 注册插件钩子
     * @private
     */
    PluginLoader.prototype._registerHooks = function(pluginId, hooks) {
        var self = this;
        Object.keys(hooks).forEach(function(hookName) {
            if (!self.hooks[hookName]) {
                self.hooks[hookName] = [];
            }
            self.hooks[hookName].push({
                pluginId: pluginId,
                callback: hooks[hookName]
            });
        });
    };

    /**
     * 注销插件钩子
     * @private
     */
    PluginLoader.prototype._unregisterHooks = function(pluginId) {
        var self = this;
        Object.keys(this.hooks).forEach(function(hookName) {
            self.hooks[hookName] = self.hooks[hookName].filter(function(hook) {
                return hook.pluginId !== pluginId;
            });
        });
    };

    /**
     * 触发事件
     * @private
     */
    PluginLoader.prototype._emitEvent = function(eventName, data) {
        if (this.eventBus) {
            this.eventBus.emit(eventName, data);
        }
        // 也触发window事件
        window.dispatchEvent(new CustomEvent('neurova:plugin:' + eventName, {
            detail: data
        }));
    };

    // 导出到全局
    window.NeurovaPluginLoader = PluginLoader;

})();
```

### Step 2: 创建示例插件

```javascript
// static/plugins/weather-plugin.js
/**
 * 天气插件示例
 * 
 * 演示如何创建一个Neurova前端插件
 */

(function() {
    'use strict';

    var WeatherPlugin = function(config) {
        this.id = 'weather-plugin';
        this.name = '天气插件';
        this.version = '1.0.0';
        this.config = config || {};
        this.container = null;
    };

    /**
     * 初始化插件
     */
    WeatherPlugin.prototype.init = function() {
        console.log('[WeatherPlugin] Initializing...');
        
        // 创建UI容器
        this.container = document.createElement('div');
        this.container.id = 'weather-plugin-container';
        this.container.className = 'weather-plugin';
        this.container.innerHTML = `
            <div class="weather-widget">
                <h3>天气查询</h3>
                <input type="text" id="weather-city" placeholder="输入城市名称" />
                <button id="weather-query">查询</button>
                <div id="weather-result"></div>
            </div>
        `;
        
        // 添加到页面
        var target = this.config.target || document.body;
        if (typeof target === 'string') {
            target = document.querySelector(target);
        }
        if (target) {
            target.appendChild(this.container);
        }
        
        // 绑定事件
        this._bindEvents();
    };

    /**
     * 销毁插件
     */
    WeatherPlugin.prototype.destroy = function() {
        console.log('[WeatherPlugin] Destroying...');
        
        if (this.container && this.container.parentNode) {
            this.container.parentNode.removeChild(this.container);
        }
        this.container = null;
    };

    /**
     * 插件钩子
     */
    WeatherPlugin.prototype.hooks = {
        'page:loaded': function(pageId) {
            console.log('[WeatherPlugin] Page loaded:', pageId);
        },
        'user:action': function(action, data) {
            console.log('[WeatherPlugin] User action:', action, data);
        }
    };

    /**
     * 元数据
     */
    WeatherPlugin.prototype.metadata = {
        author: 'Neurova Team',
        description: '天气查询插件示例',
        icon: 'cloud-sun',
        category: 'utility'
    };

    /**
     * 绑定事件
     * @private
     */
    WeatherPlugin.prototype._bindEvents = function() {
        var self = this;
        var button = document.getElementById('weather-query');
        var input = document.getElementById('weather-city');
        
        if (button && input) {
            button.addEventListener('click', function() {
                self._queryWeather(input.value);
            });
            
            input.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    self._queryWeather(input.value);
                }
            });
        }
    };

    /**
     * 查询天气
     * @private
     */
    WeatherPlugin.prototype._queryWeather = function(city) {
        var resultDiv = document.getElementById('weather-result');
        if (!city) {
            resultDiv.innerHTML = '<p style="color: #EF4444">请输入城市名称</p>';
            return;
        }
        
        resultDiv.innerHTML = '<p>正在查询...</p>';
        
        // 调用后端API
        fetch('/api/plugins/weather/current?city=' + encodeURIComponent(city))
            .then(function(response) { return response.json(); })
            .then(function(data) {
                if (data.success) {
                    resultDiv.innerHTML = '\n                        <div class="weather-result">\n                            <h4>' + self._escapeHtml(data.city) + '</h4>\n                            <p>温度: ' + self._escapeHtml(data.temperature) + '</p>\n                            <p>天气: ' + self._escapeHtml(data.description) + '</p>\n                            <p>湿度: ' + self._escapeHtml(data.humidity) + '</p>\n                        </div>\n                    ';
                } else {
                    resultDiv.innerHTML = '<p style="color: #EF4444">' + self._escapeHtml(data.error) + '</p>';
                }
            })
            .catch(function(error) {
                resultDiv.innerHTML = '<p style="color: #EF4444">查询失败: ' + self._escapeHtml(error.message) + '</p>';
            });
    };

    /**
     * HTML转义
     * @private
     */
    WeatherPlugin.prototype._escapeHtml = function(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    };

    // 导出到全局
    window.WeatherPlugin = WeatherPlugin;

})();
```

### Step 3: 测试文件

创建测试页面 `static/test-plugins.html`:

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>插件加载器测试</title>
    <script src="js/plugin-loader.js"></script>
</head>
<body>
    <h1>插件加载器测试</h1>
    
    <button id="load-plugin">加载天气插件</button>
    <button id="unload-plugin">卸载天气插件</button>
    <button id="list-plugins">列出所有插件</button>
    
    <div id="plugin-container"></div>
    <div id="plugin-list"></div>
    
    <script>
        // 创建插件加载器
        var loader = new NeurovaPluginLoader();
        
        // 加载插件
        document.getElementById('load-plugin').addEventListener('click', function() {
            loader.loadPlugin('/plugins/weather-plugin.js', {
                target: '#plugin-container'
            })
            .then(function(plugin) {
                console.log('插件加载成功:', plugin.name);
                alert('插件加载成功: ' + plugin.name);
            })
            .catch(function(error) {
                console.error('插件加载失败:', error);
                alert('插件加载失败: ' + error.message);
            });
        });
        
        // 卸载插件
        document.getElementById('unload-plugin').addEventListener('click', function() {
            var success = loader.unloadPlugin('weather-plugin');
            if (success) {
                alert('插件卸载成功');
            } else {
                alert('插件卸载失败');
            }
        });
        
        // 列出所有插件
        document.getElementById('list-plugins').addEventListener('click', function() {
            var plugins = loader.listPlugins();
            var listDiv = document.getElementById('plugin-list');
            listDiv.innerHTML = '<h3>已加载插件 (' + plugins.length + ')</h3><ul>' +
                plugins.map(function(p) {
                    return '<li>' + p.name + ' v' + p.version + '</li>';
                }).join('') +
                '</ul>';
        });
    </script>
</body>
</html>
```

---

## Task 4: 元认知系统

**负责人:** Agent-Delta
**优先级:** P1
**预计时间:** 45分钟

**目标:** 实现忆灵的自我监控、自我反思、自我优化能力

**Files:**
- Create: `neurova/memory/core/meta_cognition.py` - 元认知系统
- Create: `neurova/memory/core/self_reflection.py` - 自我反思模块
- Create: `neurova/memory/core/self_optimization.py` - 自我优化模块
- Test: `tests/test_meta_cognition.py`

### 架构设计

```
neurova/memory/core/meta_cognition.py
├── MetaCognition 类（元认知管理器）
│   ├── monitor() -> 监控记忆系统健康度
│   ├── reflect() -> 执行自我反思
│   ├── optimize() -> 执行自我优化
│   ├── get_health_report() -> 获取健康报告
│   └── get_reflection_report() -> 获取反思报告
├── SelfReflection 类（自我反思）
│   ├── analyze_memory_patterns() -> 分析记忆模式
│   ├── detect_anomalies() -> 检测异常
│   └── generate_insights() -> 生成洞察
└── SelfOptimization 类（自我优化）
    ├── optimize_temperature() -> 优化温度参数
    ├── prune_memories() -> 修剪低价值记忆
    └── restructure_associations() -> 重构关联
```

### Step 1: 创建元认知系统

```python
# neurova/memory/core/meta_cognition.py
"""元认知系统

忆灵的自我监控、自我反思、自我优化能力
让忆灵能够"思考自己的思考"
"""

from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class MetaCognition:
    """元认知管理器
    
    负责协调自我监控、反思和优化
    """
    
    def __init__(self, memory_manager, config=None):
        """初始化元认知系统
        
        Args:
            memory_manager: MemoryManager实例
            config: 配置字典
        """
        self.memory_manager = memory_manager
        self.config = config or {}
        
        # 子模块
        from neurova.memory.core.self_reflection import SelfReflection
        from neurova.memory.core.self_optimization import SelfOptimization
        
        self.reflection = SelfReflection(memory_manager)
        self.optimization = SelfOptimization(memory_manager)
        
        # 监控数据
        self._monitor_history = []
        self._last_monitor_time = None
        
        # 默认配置
        self.default_config = {
            'monitor_interval': 3600,  # 监控间隔（秒）
            'reflect_interval': 86400,  # 反思间隔（秒）
            'optimize_interval': 172800,  # 优化间隔（秒）
            'health_threshold': 0.6,  # 健康度阈值
            'max_monitor_history': 100,  # 最大监控历史条数
        }
        self.config = {**self.default_config, **self.config}
    
    def monitor(self) -> Dict:
        """执行系统监控
        
        Returns:
            监控报告
        """
        try:
            # 收集监控数据
            health_report = self._collect_health_metrics()
            
            # 记录监控历史
            self._monitor_history.append({
                'timestamp': datetime.now().isoformat(),
                'health_score': health_report['health_score'],
                'metrics': health_report
            })
            
            # 保留最近N条记录
            if len(self._monitor_history) > self.config['max_monitor_history']:
                self._monitor_history = self._monitor_history[-self.config['max_monitor_history']:]
            
            self._last_monitor_time = datetime.now()
            
            logger.info(f"MetaCognition monitor completed. Health: {health_report['health_score']:.2f}")
            
            return health_report
            
        except Exception as e:
            logger.error(f"MetaCognition monitor failed: {e}")
            return {'error': str(e), 'health_score': 0.0}
    
    def reflect(self) -> Dict:
        """执行自我反思
        
        Returns:
            反思报告
        """
        try:
            # 分析记忆模式
            pattern_analysis = self.reflection.analyze_memory_patterns()
            
            # 检测异常
            anomalies = self.reflection.detect_anomalies()
            
            # 生成洞察
            insights = self.reflection.generate_insights()
            
            # 生成反思报告
            report = {
                'timestamp': datetime.now().isoformat(),
                'pattern_analysis': pattern_analysis,
                'anomalies': anomalies,
                'insights': insights,
                'reflection_score': self._calculate_reflection_score(pattern_analysis, anomalies)
            }
            
            logger.info(f"MetaCognition reflection completed. Score: {report['reflection_score']:.2f}")
            
            return report
            
        except Exception as e:
            logger.error(f"MetaCognition reflection failed: {e}")
            return {'error': str(e), 'reflection_score': 0.0}
    
    def optimize(self) -> Dict:
        """执行自我优化
        
        Returns:
            优化报告
        """
        try:
            # 优化温度参数
            temp_optimization = self.optimization.optimize_temperature()
            
            # 修剪低价值记忆
            pruning_result = self.optimization.prune_memories()
            
            # 重构关联
            restructuring_result = self.optimization.restructure_associations()
            
            # 生成优化报告
            report = {
                'timestamp': datetime.now().isoformat(),
                'temperature_optimization': temp_optimization,
                'pruning': pruning_result,
                'restructuring': restructuring_result,
                'optimization_score': self._calculate_optimization_score(
                    temp_optimization, pruning_result, restructuring_result
                )
            }
            
            logger.info(f"MetaCognition optimization completed. Score: {report['optimization_score']:.2f}")
            
            return report
            
        except Exception as e:
            logger.error(f"MetaCognition optimization failed: {e}")
            return {'error': str(e), 'optimization_score': 0.0}
    
    def get_health_report(self) -> Dict:
        """获取系统健康报告
        
        Returns:
            健康报告
        """
        if not self._last_monitor_time:
            return self.monitor()
        
        # 返回最新的监控数据
        return self._monitor_history[-1] if self._monitor_history else {}
    
    def get_reflection_report(self) -> Dict:
        """获取反思报告"""
        return self.reflect()
    
    def _collect_health_metrics(self) -> Dict:
        """收集健康指标"""
        # 获取记忆统计
        stats = self.memory_manager.stats()
        
        # 计算健康度
        total_memories = stats.get('total', 0)
        crystallized = stats.get('crystallized', 0)
        avg_temp = stats.get('avg_temperature', 0)
        
        # 健康度计算（简化版）
        health_score = 0.0
        if total_memories > 0:
            # 固化记忆比例
            crystallized_ratio = crystallized / total_memories
            # 平均温度
            temp_ratio = avg_temp / 100.0
            # 健康度 = 固化比例 * 0.3 + 温度比例 * 0.3 + 总数因子 * 0.4
            total_factor = min(total_memories / 100, 1.0)
            health_score = (crystallized_ratio * 0.3 + temp_ratio * 0.3 + total_factor * 0.4)
        
        return {
            'health_score': health_score,
            'total_memories': total_memories,
            'crystallized_memories': crystallized,
            'avg_temperature': avg_temp,
            'memory_categories': stats.get('categories', {}),
            'is_healthy': health_score >= self.config['health_threshold']
        }
    
    def _calculate_reflection_score(self, pattern_analysis, anomalies) -> float:
        """计算反思得分"""
        # 基于模式完整性和异常数量计算
        base_score = 0.5
        if pattern_analysis.get('patterns_found', 0) > 0:
            base_score += 0.2
        if len(anomalies) == 0:
            base_score += 0.3
        return min(base_score, 1.0)
    
    def _calculate_optimization_score(self, temp_opt, pruning, restructuring) -> float:
        """计算优化得分"""
        # 基于优化效果计算
        scores = []
        if temp_opt.get('optimized', False):
            scores.append(0.8)
        if pruning.get('pruned', 0) > 0:
            scores.append(0.7)
        if restructuring.get('restructured', 0) > 0:
            scores.append(0.9)
        
        return sum(scores) / len(scores) if scores else 0.5
    
    def should_monitor(self) -> bool:
        """是否应该执行监控"""
        if not self._last_monitor_time:
            return True
        
        elapsed = (datetime.now() - self._last_monitor_time).total_seconds()
        return elapsed >= self.config['monitor_interval']
    
    def should_reflect(self) -> bool:
        """是否应该执行反思"""
        if not self._last_reflect_time:
            return True
        
        elapsed = (datetime.now() - self._last_reflect_time).total_seconds()
        return elapsed >= self.config['reflect_interval']
    
    def should_optimize(self) -> bool:
        """是否应该执行优化"""
        if not self._last_optimize_time:
            return True
        
        elapsed = (datetime.now() - self._last_optimize_time).total_seconds()
        return elapsed >= self.config['optimize_interval']
```

### Step 2: 创建自我反思模块

```python
# neurova/memory/core/self_reflection.py
"""自我反思模块

分析记忆模式、检测异常、生成洞察
"""

from typing import Dict, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class SelfReflection:
    """自我反思"""
    
    def __init__(self, memory_manager):
        self.memory_manager = memory_manager
    
    def analyze_memory_patterns(self) -> Dict:
        """分析记忆模式
        
        Returns:
            模式分析报告
        """
        patterns = {
            'patterns_found': 0,
            'emotion_patterns': {},
            'time_patterns': {},
            'category_patterns': {},
            'insights': []
        }
        
        try:
            # 获取所有记忆
            # 这里使用简化的实现，实际应该查询数据库
            stats = self.memory_manager.stats()
            
            # 分析情感模式
            patterns['emotion_patterns'] = self._analyze_emotion_distribution()
            
            # 分析时间模式
            patterns['time_patterns'] = self._analyze_time_distribution()
            
            # 分析分类模式
            patterns['category_patterns'] = self._analyze_category_distribution()
            
            # 计算发现的模式数
            patterns['patterns_found'] = (
                len(patterns['emotion_patterns']) +
                len(patterns['time_patterns']) +
                len(patterns['category_patterns'])
            )
            
            # 生成洞察
            patterns['insights'] = self._generate_pattern_insights(patterns)
            
        except Exception as e:
            logger.error(f"Pattern analysis failed: {e}")
        
        return patterns
    
    def detect_anomalies(self) -> List[Dict]:
        """检测异常
        
        Returns:
            异常列表
        """
        anomalies = []
        
        try:
            stats = self.memory_manager.stats()
            total = stats.get('total', 0)
            
            # 检测异常1: 记忆数量突增
            if total > 1000:
                anomalies.append({
                    'type': 'memory_spike',
                    'severity': 'warning',
                    'message': f'记忆数量过多: {total}',
                    'suggestion': '考虑执行记忆压缩或归档'
                })
            
            # 检测异常2: 平均温度过低
            avg_temp = stats.get('avg_temperature', 0)
            if avg_temp < 20:
                anomalies.append({
                    'type': 'low_temperature',
                    'severity': 'warning',
                    'message': f'平均温度过低: {avg_temp}',
                    'suggestion': '检查温度衰减配置'
                })
            
            # 检测异常3: 没有固化记忆
            crystallized = stats.get('crystallized', 0)
            if total > 10 and crystallized == 0:
                anomalies.append({
                    'type': 'no_crystallized',
                    'severity': 'info',
                    'message': '没有固化记忆',
                    'suggestion': '考虑将重要记忆固化'
                })
            
        except Exception as e:
            logger.error(f"Anomaly detection failed: {e}")
            anomalies.append({
                'type': 'detection_error',
                'severity': 'error',
                'message': str(e)
            })
        
        return anomalies
    
    def generate_insights(self) -> List[Dict]:
        """生成洞察
        
        Returns:
            洞察列表
        """
        insights = []
        
        try:
            stats = self.memory_manager.stats()
            
            # 洞察1: 记忆健康度
            if stats.get('avg_temperature', 0) > 70:
                insights.append({
                    'type': 'positive',
                    'message': '记忆健康状况良好',
                    'confidence': 0.9
                })
            
            # 洞察2: 情感分布
            if stats.get('total', 0) > 0:
                insights.append({
                    'type': 'neutral',
                    'message': f'共有{stats["total"]}条记忆，其中{stats.get("crystallized", 0)}条已固化',
                    'confidence': 1.0
                })
            
        except Exception as e:
            logger.error(f"Insight generation failed: {e}")
        
        return insights
    
    def _analyze_emotion_distribution(self) -> Dict:
        """分析情感分布"""
        # 简化实现
        return {'joy': 0.4, 'neutral': 0.3, 'love': 0.3}
    
    def _analyze_time_distribution(self) -> Dict:
        """分析时间分布"""
        # 简化实现
        return {'recent': 0.6, 'old': 0.4}
    
    def _analyze_category_distribution(self) -> Dict:
        """分析分类分布"""
        # 简化实现
        return {'conversation': 0.5, 'fact': 0.3, 'emotional': 0.2}
    
    def _generate_pattern_insights(self, patterns) -> List[str]:
        """生成模式洞察"""
        insights = []
        
        if patterns['emotion_patterns'].get('joy', 0) > 0.5:
            insights.append('积极情感记忆占主导')
        
        if patterns['time_patterns'].get('recent', 0) > 0.7:
            insights.append('近期记忆较多，建议执行归档')
        
        return insights
```

### Step 3: 创建自我优化模块

```python
# neurova/memory/core/self_optimization.py
"""自我优化模块

优化温度参数、修剪低价值记忆、重构关联
"""

from typing import Dict
import logging

logger = logging.getLogger(__name__)


class SelfOptimization:
    """自我优化"""
    
    def __init__(self, memory_manager):
        self.memory_manager = memory_manager
    
    def optimize_temperature(self) -> Dict:
        """优化温度参数
        
        Returns:
            优化结果
        """
        result = {
            'optimized': False,
            'changes': [],
            'reason': ''
        }
        
        try:
            stats = self.memory_manager.stats()
            avg_temp = stats.get('avg_temperature', 0)
            
            # 如果平均温度过低，调整衰减率
            if avg_temp < 30:
                result['changes'].append({
                    'parameter': 'decay_rate',
                    'action': 'decrease',
                    'reason': '平均温度过低，减缓衰减'
                })
                result['optimized'] = True
            
            # 如果平均温度过高，调整升温倍率
            elif avg_temp > 80:
                result['changes'].append({
                    'parameter': 'heat_multiplier',
                    'action': 'decrease',
                    'reason': '平均温度过高，降低升温速度'
                })
                result['optimized'] = True
            
            result['reason'] = f'当前平均温度: {avg_temp}'
            
        except Exception as e:
            logger.error(f"Temperature optimization failed: {e}")
            result['reason'] = str(e)
        
        return result
    
    def prune_memories(self) -> Dict:
        """修剪低价值记忆
        
        Returns:
            修剪结果
        """
        result = {
            'pruned': 0,
            'archived': 0,
            'reason': ''
        }
        
        try:
            # 这里应该查询数据库，找出低温记忆并归档
            # 简化实现
            stats = self.memory_manager.stats()
            total = stats.get('total', 0)
            
            if total > 500:
                # 假设修剪10%的记忆
                result['pruned'] = int(total * 0.1)
                result['archived'] = result['pruned']
            
        except Exception as e:
            logger.error(f"Memory pruning failed: {e}")
        
        return result
    
    def restructure_associations(self) -> Dict:
        """重构关联
        
        Returns:
            重构结果
        """
        result = {
            'restructured': 0,
            'new_associations': 0,
            'removed_associations': 0,
            'reason': ''
        }
        
        try:
            # 这里应该分析记忆关联，移除弱关联，添加新关联
            # 简化实现
            result['restructured'] = 5
            result['new_associations'] = 3
            result['removed_associations'] = 2
            
        except Exception as e:
            logger.error(f"Association restructuring failed: {e}")
        
        return result
```

### Step 4: 测试文件

```python
# tests/test_meta_cognition.py
"""测试元认知系统"""
import pytest
from neurova.memory.core.meta_cognition import MetaCognition


def test_meta_cognition_init():
    """测试初始化"""
    # 需要mock memory_manager
    class MockMemoryManager:
        def stats(self):
            return {'total': 4, 'crystallized': 3, 'important': 4, 'avg_temperature': 87.5}
    
    meta = MetaCognition(MockMemoryManager())
    assert meta is not None
    assert meta.config['monitor_interval'] == 3600


def test_monitor():
    """测试监控"""
    class MockMemoryManager:
        def stats(self):
            return {'total': 10, 'crystallized': 5, 'avg_temperature': 60}
    
    meta = MetaCognition(MockMemoryManager())
    report = meta.monitor()
    
    assert 'health_score' in report
    assert 'total_memories' in report
    assert report['total_memories'] == 10


def test_reflect():
    """测试反思"""
    class MockMemoryManager:
        def stats(self):
            return {'total': 10, 'crystallized': 5, 'avg_temperature': 60}
    
    meta = MetaCognition(MockMemoryManager())
    report = meta.reflect()
    
    assert 'pattern_analysis' in report
    assert 'anomalies' in report
    assert 'insights' in report


def test_optimize():
    """测试优化"""
    class MockMemoryManager:
        def stats(self):
            return {'total': 10, 'crystallized': 5, 'avg_temperature': 60}
    
    meta = MetaCognition(MockMemoryManager())
    report = meta.optimize()
    
    assert 'temperature_optimization' in report
    assert 'pruning' in report
    assert 'restructuring' in report


def test_should_monitor():
    """测试是否应该监控"""
    class MockMemoryManager:
        def stats(self):
            return {'total': 10}
    
    meta = MetaCognition(MockMemoryManager())
    assert meta.should_monitor() is True  # 首次应该监控
```

---

## Task 5: 实时记忆流

**负责人:** Agent-Epsilon
**优先级:** P1
**预计时间:** 35分钟

**目标:** 实现实时记忆流可视化，让冯先生能看见忆灵的记忆过程

**Files:**
- Create: `neurova/memory/core/memory_stream.py` - 实时记忆流引擎
- Create: `static/js/pages/memory-stream.js` - 前端记忆流展示
- Create: `static/pages/memory-stream.html` - 记忆流页面
- Modify: `neurova/memory/core/manager.py` - 集成记忆流
- Test: `tests/test_memory_stream.py`

### 架构设计

```
neurova/memory/core/memory_stream.py
├── MemoryStream 类
│   ├── record_event(event) -> 记录事件
│   ├── get_stream(limit) -> 获取事件流
│   ├── clear() -> 清空事件流
│   └── export() -> 导出事件流
├── MemoryEvent 类（记忆事件）
│   ├── type: str (new/recall/temperature_change/conflict/consolidate)
│   ├── memory_id: str
│   ├── content: str
│   ├── metadata: dict
│   └── timestamp: datetime
└── 前端展示
    └── memory-stream.js/html
        ├── 实时事件列表
        ├── 事件类型图标
        ├── 时间戳显示
        ├── 记忆内容预览
        └── 自动刷新
```

### Step 1: 创建实时记忆流引擎

```python
# neurova/memory/core/memory_stream.py
"""实时记忆流引擎

记录记忆系统的所有操作，支持实时查看和导出
"""

from typing import List, Dict, Optional
from datetime import datetime
from collections import deque
import json
import logging

logger = logging.getLogger(__name__)


class MemoryEvent:
    """记忆事件"""
    
    def __init__(self, event_type: str, memory_id: str = None, content: str = None, metadata: dict = None):
        self.id = f"evt_{datetime.now().timestamp() * 1000:.0f}"
        self.type = event_type
        self.memory_id = memory_id
        self.content = content
        self.metadata = metadata or {}
        self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'type': self.type,
            'memory_id': self.memory_id,
            'content': self.content,
            'metadata': self.metadata,
            'timestamp': self.timestamp.isoformat()
        }
    
    def __repr__(self):
        return f"MemoryEvent(type='{self.type}', content='{self.content[:50]}...')"


class MemoryStream:
    """实时记忆流
    
    记录记忆系统的所有操作，支持实时查看
    """
    
    # 事件类型常量
    EVENT_NEW = 'new'
    EVENT_RECALL = 'recall'
    EVENT_TEMPERATURE_CHANGE = 'temperature_change'
    EVENT_CONFLICT = 'conflict'
    EVENT_CONSOLIDATE = 'consolidate'
    EVENT_FORGET = 'forget'
    EVENT_COMPRESS = 'compress'
    EVENT_RELATE = 'relate'
    
    def __init__(self, max_events: int = 100):
        """初始化记忆流
        
        Args:
            max_events: 最大事件数量（超过后自动清理）
        """
        self._events = deque(maxlen=max_events)
        self._max_events = max_events
        self._subscribers = []
    
    def record_event(self, event: MemoryEvent):
        """记录事件
        
        Args:
            event: 记忆事件
        """
        self._events.append(event)
        
        # 通知订阅者
        for subscriber in self._subscribers:
            try:
                subscriber(event)
            except Exception as e:
                logger.error(f"MemoryStream subscriber error: {e}")
        
        logger.debug(f"MemoryStream recorded: {event.type} - {event.content[:50]}...")
    
    def record(self, event_type: str, **kwargs):
        """便捷方法：记录事件
        
        Args:
            event_type: 事件类型
            **kwargs: 事件参数
        """
        event = MemoryEvent(event_type=event_type, **kwargs)
        self.record_event(event)
        return event
    
    def get_stream(self, limit: int = 50, event_type: str = None) -> List[Dict]:
        """获取事件流
        
        Args:
            limit: 返回事件数量限制
            event_type: 过滤事件类型
            
        Returns:
            事件列表（字典格式）
        """
        events = list(self._events)
        
        # 按时间倒序
        events.reverse()
        
        # 过滤类型
        if event_type:
            events = [e for e in events if e.type == event_type]
        
        # 限制数量
        events = events[:limit]
        
        return [e.to_dict() for e in events]
    
    def clear(self):
        """清空事件流"""
        self._events.clear()
    
    def export(self, format: str = 'json') -> str:
        """导出事件流
        
        Args:
            format: 导出格式（json/csv）
            
        Returns:
            导出的字符串
        """
        events = [e.to_dict() for e in self._events]
        
        if format == 'json':
            return json.dumps(events, indent=2, ensure_ascii=False)
        elif format == 'csv':
            # 简化CSV实现
            lines = ['id,type,memory_id,content,timestamp']
            for e in events:
                lines.append(f"{e['id']},{e['type']},{e['memory_id']},\"{e['content']}\",{e['timestamp']}")
            return '\n'.join(lines)
        else:
            return json.dumps(events)
    
    def subscribe(self, callback):
        """订阅事件流
        
        Args:
            callback: 回调函数，接收MemoryEvent参数
        """
        self._subscribers.append(callback)
    
    def unsubscribe(self, callback):
        """取消订阅"""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
    
    def stats(self) -> Dict:
        """获取事件统计"""
        type_counts = {}
        for event in self._events:
            type_counts[event.type] = type_counts.get(event.type, 0) + 1
        
        return {
            'total_events': len(self._events),
            'max_events': self._max_events,
            'type_counts': type_counts,
            'subscribers': len(self._subscribers),
            'latest_event': self._events[-1].to_dict() if self._events else None
        }
    
    @property
    def event_types(self):
        """获取所有事件类型"""
        return {
            self.EVENT_NEW: '新记忆',
            self.EVENT_RECALL: '回忆',
            self.EVENT_TEMPERATURE_CHANGE: '温度变化',
            self.EVENT_CONFLICT: '冲突检测',
            self.EVENT_CONSOLIDATE: '巩固',
            self.EVENT_FORGET: '遗忘',
            self.EVENT_COMPRESS: '压缩',
            self.EVENT_RELATE: '关联'
        }
```

### Step 2: 修改MemoryManager集成记忆流

在 `neurova/memory/core/manager.py` 中添加：

```python
# 在 __init__ 中添加
from neurova.memory.core.memory_stream import MemoryStream
self.memory_stream = MemoryStream()

# 在 remember 方法中添加
def remember(self, content, **kwargs):
    # ... 原有代码 ...
    
    # 记录到记忆流
    self.memory_stream.record(
        event_type=MemoryStream.EVENT_NEW,
        memory_id=memory_id,
        content=content,
        metadata={'category': kwargs.get('category', 'conversation')}
    )
    
    return memory_id

# 在 recall 方法中添加
def recall(self, query, **kwargs):
    # ... 原有代码 ...
    
    # 记录到记忆流
    self.memory_stream.record(
        event_type=MemoryStream.EVENT_RECALL,
        content=query,
        metadata={'results_count': len(results)}
    )
    
    return results
```

### Step 3: 创建前端记忆流展示

```javascript
// static/js/pages/memory-stream.js
/**
 * 实时记忆流展示页面
 */

(function() {
    'use strict';

    var currentStream = [];
    var autoRefreshInterval = null;
    var filterType = 'all';

    /**
     * 初始化记忆流页面
     */
    window.initMemoryStream = function() {
        console.log('[MemoryStream] Initializing...');
        
        loadMemoryStream();
        initFilterButtons();
        startAutoRefresh();
        
        // 返回destroy方法用于页面切换时清理
        return {
            destroy: function() {
                stopAutoRefresh();
            }
        };
    };

    /**
     * 加载记忆流数据
     */
    function loadMemoryStream() {
        fetch('/api/memory/stream?limit=50&type=' + filterType)
            .then(function(response) { return response.json(); })
            .then(function(data) {
                if (data.success) {
                    currentStream = data.events || [];
                    renderStream(currentStream);
                    updateStats(data.stats);
                } else {
                    showError('加载失败: ' + (data.error || '未知错误'));
                }
            })
            .catch(function(error) {
                console.error('Failed to load memory stream:', error);
                showError('网络错误');
            });
    }

    /**
     * 渲染事件流
     */
    function renderStream(events) {
        var container = document.querySelector('.stream-container');
        if (!container) return;
        
        if (events.length === 0) {
            container.innerHTML = '<div class="empty-state">暂无记忆流事件</div>';
            return;
        }
        
        var html = events.map(function(event) {
            return `
                <div class="stream-event" data-type="${event.type}">
                    <div class="event-header">
                        <span class="event-icon">${getEventIcon(event.type)}</span>
                        <span class="event-type">${getEventTypeName(event.type)}</span>
                        <span class="event-time">${formatTime(event.timestamp)}</span>
                    </div>
                    <div class="event-content">
                        ${escapeHtml(event.content || '')}
                    </div>
                    ${event.metadata ? '<div class="event-meta">' + formatMetadata(event.metadata) + '</div>' : ''}
                </div>
            `;
        }).join('');
        
        container.innerHTML = html;
        
        // 滚动到顶部（最新事件）
        container.scrollTop = 0;
    }

    /**
     * 初始化筛选按钮
     */
    function initFilterButtons() {
        var buttons = document.querySelectorAll('.stream-filter-btn');
        buttons.forEach(function(btn) {
            btn.addEventListener('click', function() {
                // 移除其他按钮的active状态
                buttons.forEach(function(b) { b.classList.remove('active'); });
                // 添加当前按钮的active状态
                btn.classList.add('active');
                
                filterType = btn.dataset.type || 'all';
                loadMemoryStream();
            });
        });
    }

    /**
     * 开始自动刷新
     */
    function startAutoRefresh() {
        stopAutoRefresh();
        autoRefreshInterval = setInterval(loadMemoryStream, 5000); // 每5秒刷新
    }

    /**
     * 停止自动刷新
     */
    function stopAutoRefresh() {
        if (autoRefreshInterval) {
            clearInterval(autoRefreshInterval);
            autoRefreshInterval = null;
        }
    }

    /**
     * 更新统计信息
     */
    function updateStats(stats) {
        var statsContainer = document.querySelector('.stream-stats');
        if (!statsContainer || !stats) return;
        
        statsContainer.innerHTML = `
            <div class="stat-item">
                <span class="stat-value">${stats.total_events || 0}</span>
                <span class="stat-label">总事件数</span>
            </div>
            ${Object.keys(stats.type_counts || {}).map(function(type) {
                return `
                    <div class="stat-item">
                        <span class="stat-value">${stats.type_counts[type]}</span>
                        <span class="stat-label">${getEventTypeName(type)}</span>
                    </div>
                `;
            }).join('')}
        `;
    }

    /**
     * 获取事件图标
     */
    function getEventIcon(type) {
        var icons = {
            'new': '✨',
            'recall': '🔍',
            'temperature_change': '🌡️',
            'conflict': '⚠️',
            'consolidate': '🌙',
            'forget': '🍂',
            'compress': '📦',
            'relate': '🔗'
        };
        return icons[type] || '📝';
    }

    /**
     * 获取事件类型名称
     */
    function getEventTypeName(type) {
        var names = {
            'new': '新记忆',
            'recall': '回忆',
            'temperature_change': '温度变化',
            'conflict': '冲突检测',
            'consolidate': '巩固',
            'forget': '遗忘',
            'compress': '压缩',
            'relate': '关联'
        };
        return names[type] || type;
    }

    /**
     * 格式化时间
     */
    function formatTime(timestamp) {
        if (!timestamp) return '';
        var date = new Date(timestamp);
        return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    /**
     * 格式化元数据
     */
    function formatMetadata(metadata) {
        if (!metadata) return '';
        return Object.keys(metadata).map(function(key) {
            return `<span class="meta-item">${key}: ${escapeHtml(String(metadata[key]))}</span>`;
        }).join('');
    }

    /**
     * HTML转义
     */
    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * 显示错误
     */
    function showError(message) {
        var container = document.querySelector('.stream-container');
        if (container) {
            container.innerHTML = '<div class="error-state">⚠️ ' + escapeHtml(message) + '</div>';
        }
    }

})();
```

### Step 4: 创建记忆流页面HTML

```html
<!-- static/pages/memory-stream.html -->
<div id="page-memory-stream" class="page">
    <!-- 页面头部 -->
    <div class="page-header">
        <h2 class="page-title">实时记忆流</h2>
        <p class="page-subtitle">查看忆灵的记忆过程：记住、回忆、升温、遗忘...</p>
    </div>

    <!-- 统计卡片 -->
    <div class="stream-stats stats-grid">
        <div class="stat-card">
            <div class="stat-value" id="stream-total">0</div>
            <div class="stat-label">总事件数</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="stream-new">0</div>
            <div class="stat-label">新记忆</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="stream-recall">0</div>
            <div class="stat-label">回忆</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="stream-temp">0</div>
            <div class="stat-label">温度变化</div>
        </div>
    </div>

    <!-- 筛选栏 -->
    <div class="card">
        <div class="card-header">
            <h3 class="card-title">筛选</h3>
        </div>
        <div class="card-body">
            <div class="filter-bar">
                <button class="stream-filter-btn active" data-type="all">全部</button>
                <button class="stream-filter-btn" data-type="new">新记忆</button>
                <button class="stream-filter-btn" data-type="recall">回忆</button>
                <button class="stream-filter-btn" data-type="temperature_change">温度变化</button>
                <button class="stream-filter-btn" data-type="conflict">冲突</button>
                <button class="stream-filter-btn" data-type="consolidate">巩固</button>
            </div>
        </div>
    </div>

    <!-- 事件流 -->
    <div class="card">
        <div class="card-header">
            <h3 class="card-title">记忆流</h3>
            <span class="auto-refresh-indicator">🔄 自动刷新 (5s)</span>
        </div>
        <div class="card-body">
            <div class="stream-container">
                <div class="empty-state">
                    <p>暂无记忆流事件</p>
                    <p class="hint">记忆系统操作将在这里实时显示</p>
                </div>
            </div>
        </div>
    </div>
</div>
```

### Step 5: 添加API端点

在 `neurova/api/endpoints/memory.py` 中添加：

```python
@memory_bp.route('/stream', methods=['GET'])
def get_memory_stream():
    """获取实时记忆流"""
    limit = int(request.args.get('limit', 50))
    event_type = request.args.get('type')
    
    # 获取memory_manager
    # ... 从app获取 ...
    
    stream = memory_manager.memory_stream
    events = stream.get_stream(limit=limit, event_type=event_type)
    stats = stream.stats()
    
    return jsonify({
        'success': True,
        'events': events,
        'stats': stats
    })
```

### Step 6: 测试文件

```python
# tests/test_memory_stream.py
"""测试实时记忆流"""
import pytest
from neurova.memory.core.memory_stream import MemoryStream, MemoryEvent


def test_memory_stream_record():
    """测试记录事件"""
    stream = MemoryStream()
    
    event = stream.record(
        event_type=MemoryStream.EVENT_NEW,
        content="测试记忆",
        metadata={'category': 'test'}
    )
    
    assert event.type == 'new'
    assert event.content == "测试记忆"


def test_memory_stream_get():
    """测试获取事件流"""
    stream = MemoryStream()
    
    for i in range(10):
        stream.record(event_type='new', content=f"记忆{i}")
    
    events = stream.get_stream(limit=5)
    assert len(events) == 5


def test_memory_stream_filter():
    """测试事件过滤"""
    stream = MemoryStream()
    
    stream.record(event_type='new', content="新记忆")
    stream.record(event_type='recall', content="回忆")
    stream.record(event_type='new', content="另一条新记忆")
    
    events = stream.get_stream(event_type='new')
    assert len(events) == 2


def test_memory_stream_stats():
    """测试事件统计"""
    stream = MemoryStream()
    
    stream.record(event_type='new', content="记忆1")
    stream.record(event_type='recall', content="回忆")
    stream.record(event_type='new', content="记忆2")
    
    stats = stream.stats()
    assert stats['total_events'] == 3
    assert stats['type_counts']['new'] == 2
    assert stats['type_counts']['recall'] == 1


def test_memory_stream_max_events():
    """测试最大事件数量限制"""
    stream = MemoryStream(max_events=5)
    
    for i in range(10):
        stream.record(event_type='new', content=f"记忆{i}")
    
    assert len(stream.get_stream()) == 5


def test_memory_stream_export():
    """测试导出事件流"""
    stream = MemoryStream()
    stream.record(event_type='new', content="测试")
    
    json_export = stream.export(format='json')
    assert '测试' in json_export
    assert 'new' in json_export
```

---

## 集成测试计划

所有5个任务完成后，执行以下集成测试：

### Test 1: 应用启动测试
```bash
cd neurova
python -c "from app import create_app; app = create_app(); print('✅ App created successfully')"
```

### Test 2: 插件API注册测试
```python
# 测试插件能否成功注册API端点
from neurova.app import create_app
from neurova.plugins.plugin_api_registry import PluginAPIRegistry

app = create_app()
registry = PluginAPIRegistry(plugin_id='test_plugin')
registry.register_route('/test', methods=['GET'], handler=lambda: {'status': 'ok'})

# 验证端点已注册
endpoints = app.api_router.get_endpoints()
assert len(endpoints) > 0
print('✅ Plugin API registration works')
```

### Test 3: 前端插件加载测试
```bash
# 在浏览器中打开测试页面
open http://localhost:9527/test-plugins.html
# 点击"加载天气插件"按钮，验证插件加载成功
```

### Test 4: 元认知监控测试
```python
from neurova.memory.core.meta_cognition import MetaCognition
from neurova.memory.core.manager import MemoryManager

mgr = MemoryManager(db_path='memory/data/yi_ling_memory.db')
meta = MetaCognition(mgr)

health = meta.monitor()
print(f"Health score: {health['health_score']:.2f}")
print(f"Is healthy: {health['is_healthy']}")

reflection = meta.reflect()
print(f"Reflection score: {reflection['reflection_score']:.2f}")

optimize = meta.optimize()
print(f"Optimization score: {optimize['optimization_score']:.2f}")
```

### Test 5: 实时记忆流测试
```python
from neurova.memory.core.memory_stream import MemoryStream

stream = MemoryStream()
stream.record(event_type='new', content='测试记忆')
stream.record(event_type='recall', content='回忆测试')

events = stream.get_stream(limit=10)
print(f"Events: {len(events)}")
for event in events:
    print(f"  {event['type']}: {event['content']}")

print(f"Stats: {stream.stats()}")
```

---

## 提交规范

每个任务完成后，单独提交：

```bash
# Task 1: 统一应用入口
git add neurova/app.py neurova/config/default.py tests/test_app_entry.py
git commit -m "feat: add unified application entry point (Task 1)

- Create create_app() function for centralized app initialization
- Add DefaultConfig class for configuration management
- Register all blueprints and middleware
- Implement singleton pattern with get_app()
- Add comprehensive tests"

# Task 2: 动态API路由器
git add neurova/core/api_router.py neurova/plugins/plugin_api_registry.py tests/test_api_router.py
git commit -m "feat: add dynamic API router for plugin endpoint registration (Task 2)

- Create APIRouter class for runtime endpoint management
- Add PluginAPIRegistry for plugin-specific API registration
- Support endpoint lifecycle management (register/unregister)
- Implement OpenAPI spec generation
- Add comprehensive tests"

# Task 3: 前端插件加载器
git add static/js/plugin-loader.js static/plugins/weather-plugin.js static/test-plugins.html
git commit -m "feat: add frontend plugin loader with dynamic loading (Task 3)

- Create PluginLoader class for dynamic plugin management
- Implement plugin lifecycle (init/destroy)
- Add hook system for plugin integration
- Create weather plugin as example
- Add test page for browser testing"

# Task 4: 元认知系统
git add neurova/memory/core/meta_cognition.py neurova/memory/core/self_reflection.py neurova/memory/core/self_optimization.py tests/test_meta_cognition.py
git commit -m "feat: add meta-cognition system for self-reflection (Task 4)

- Create MetaCognition manager for coordination
- Add SelfReflection for pattern analysis and anomaly detection
- Add SelfOptimization for temperature/pruning/association optimization
- Implement health monitoring and reporting
- Add comprehensive tests"

# Task 5: 实时记忆流
git add neurova/memory/core/memory_stream.py static/js/pages/memory-stream.js static/pages/memory-stream.html tests/test_memory_stream.py
git commit -m "feat: add real-time memory stream visualization (Task 5)

- Create MemoryStream engine for event recording
- Add MemoryEvent class for event representation
- Implement frontend visualization with auto-refresh
- Integrate with MemoryManager
- Add API endpoint for stream retrieval
- Add comprehensive tests"
```

---

## 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| Task 1与Task 2冲突（API路由） | 高 | 中 | Task 2使用独立的路由器，不修改现有Blueprint |
| Task 4依赖MemoryManager | 中 | 高 | 使用mock进行测试，实际集成时调整 |
| Task 5前端与现有UI冲突 | 低 | 低 | 使用独立的页面和CSS类名 |
| 并行开发合并冲突 | 中 | 中 | 每个任务使用不同的文件，减少冲突 |

---

## 完成标准

- [ ] 所有5个任务独立测试通过
- [ ] 集成测试全部通过
- [ ] 代码审查通过
- [ ] 文档更新完成
- [ ] 提交到版本控制

---

**并行开发策略说明:**
1. Task 1和Task 2可以同时进行（不同文件）
2. Task 3独立开发（前端）
3. Task 4和Task 5可以同时进行（不同文件）
4. 最后执行集成测试（所有任务完成后）

**预计总时间:** 45-60分钟（并行）
