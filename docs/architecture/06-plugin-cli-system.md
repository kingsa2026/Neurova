# 插件系统和 CLI 接口设计

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

### 2.1 插件元数据

```python
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from enum import Enum
from datetime import datetime
import json

class PluginStatus(Enum):
    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"
    UPDATING = "updating"

class PluginType(Enum):
    FUNCTIONAL = "functional"
    EXTENSION = "extension"
    THEME = "theme"

@dataclass
class PluginManifest:
    """插件清单"""
    # 基本信息
    id: str
    name: str
    description: str
    version: str
    author: str
    type: PluginType = PluginType.FUNCTIONAL
    
    # 依赖
    dependencies: List[str] = field(default_factory=list)
    min_framework_version: str = "1.0.0"
    max_framework_version: str = "2.0.0"
    
    # 入口
    main: str = ""  # 入口模块/类
    entry_point: Optional[Callable] = None
    
    # 配置
    config_schema: Dict[str, Any] = field(default_factory=dict)
    default_config: Dict[str, Any] = field(default_factory=dict)
    
    # 权限
    permissions: List[str] = field(default_factory=list)
    
    # 钩子
    hooks: Dict[str, str] = field(default_factory=dict)
    
    # 状态
    status: PluginStatus = PluginStatus.INSTALLED
    error: Optional[str] = None
    
    # 时间戳
    installed_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'version': self.version,
            'author': self.author,
            'type': self.type.value,
            'dependencies': self.dependencies,
            'min_framework_version': self.min_framework_version,
            'max_framework_version': self.max_framework_version,
            'main': self.main,
            'config_schema': self.config_schema,
            'default_config': self.default_config,
            'permissions': self.permissions,
            'hooks': self.hooks,
            'status': self.status.value,
            'error': self.error,
            'installed_at': self.installed_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'PluginManifest':
        """从字典创建"""
        return cls(
            id=data['id'],
            name=data['name'],
            description=data['description'],
            version=data['version'],
            author=data['author'],
            type=PluginType(data.get('type', 'functional')),
            dependencies=data.get('dependencies', []),
            min_framework_version=data.get('min_framework_version', '1.0.0'),
            max_framework_version=data.get('max_framework_version', '2.0.0'),
            main=data.get('main', ''),
            config_schema=data.get('config_schema', {}),
            default_config=data.get('default_config', {}),
            permissions=data.get('permissions', []),
            hooks=data.get('hooks', {}),
            status=PluginStatus(data.get('status', 'installed')),
            error=data.get('error')
        )

@dataclass
class PluginContext:
    """插件上下文"""
    plugin_id: str
    base_path: str
    config: Dict[str, Any]
    logger: Any
    data_dir: str
    cache_dir: str
    
    # 框架服务
    skill_manager: Optional[Any] = None
    memory_manager: Optional[Any] = None
    message_router: Optional[Any] = None
    agent_orchestrator: Optional[Any] = None
    
    def get_service(self, name: str) -> Any:
        """获取框架服务"""
        services = {
            'skill_manager': self.skill_manager,
            'memory_manager': self.memory_manager,
            'message_router': self.message_router,
            'agent_orchestrator': self.agent_orchestrator
        }
        return services.get(name)
```

## 3. 插件管理器

### 3.1 核心实现

```python
import os
import sys
import importlib
import importlib.util
from pathlib import Path
import asyncio

class PluginManager:
    """
    插件管理器
    管理插件的加载、卸载、启用、禁用
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.plugins: Dict[str, PluginManifest] = {}
        self.plugin_instances: Dict[str, Any] = {}
        self.hooks: Dict[str, List[Callable]] = defaultdict(list)
        
        # 路径
        self.plugins_dir = Path(config.get('plugins_dir', 'plugins'))
        self.data_dir = Path(config.get('data_dir', 'data/plugins'))
        self.cache_dir = Path(config.get('cache_dir', 'cache/plugins'))
        
        # 创建目录
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 事件总线
        self.event_bus = EventBus()
        
        # 加载已安装的插件
        self._load_installed_plugins()
    
    def _load_installed_plugins(self):
        """加载已安装的插件"""
        for plugin_dir in self.plugins_dir.iterdir():
            if plugin_dir.is_dir():
                manifest_path = plugin_dir / 'manifest.json'
                if manifest_path.exists():
                    try:
                        with open(manifest_path, 'r') as f:
                            data = json.load(f)
                        manifest = PluginManifest.from_dict(data)
                        self.plugins[manifest.id] = manifest
                    except Exception as e:
                        logger.error(f"Failed to load plugin {plugin_dir}: {e}")
    
    def install_plugin(
        self,
        source: str,
        version: Optional[str] = None
    ) -> PluginManifest:
        """
        安装插件
        - source: 插件源 (路径、URL、仓库名)
        - version: 版本号
        """
        try:
            # 下载/复制插件
            plugin_path = self._download_plugin(source, version)
            
            # 读取清单
            manifest = self._read_manifest(plugin_path)
            
            # 检查依赖
            self._check_dependencies(manifest)
            
            # 安装依赖
            self._install_dependencies(manifest)
            
            # 保存清单
            self._save_manifest(manifest)
            
            # 添加到注册表
            self.plugins[manifest.id] = manifest
            
            # 发布事件
            self.event_bus.publish(Event(
                type='plugin.installed',
                data={'plugin_id': manifest.id}
            ))
            
            return manifest
            
        except Exception as e:
            raise PluginInstallError(f"Failed to install plugin: {e}")
    
    def uninstall_plugin(self, plugin_id: str) -> bool:
        """卸载插件"""
        if plugin_id not in self.plugins:
            return False
        
        manifest = self.plugins[plugin_id]
        
        # 先禁用
        if manifest.status == PluginStatus.ENABLED:
            self.disable_plugin(plugin_id)
        
        # 删除文件
        plugin_path = self.plugins_dir / plugin_id
        if plugin_path.exists():
            import shutil
            shutil.rmtree(plugin_path)
        
        # 从注册表移除
        del self.plugins[plugin_id]
        
        # 发布事件
        self.event_bus.publish(Event(
            type='plugin.uninstalled',
            data={'plugin_id': plugin_id}
        ))
        
        return True
    
    def enable_plugin(self, plugin_id: str) -> bool:
        """启用插件"""
        if plugin_id not in self.plugins:
            return False
        
        manifest = self.plugins[plugin_id]
        
        if manifest.status == PluginStatus.ENABLED:
            return True
        
        try:
            # 加载插件
            plugin_instance = self._load_plugin(manifest)
            
            # 初始化
            context = self._create_context(manifest)
            asyncio.create_task(plugin_instance.initialize(context))
            
            # 注册钩子
            self._register_hooks(manifest, plugin_instance)
            
            # 更新状态
            manifest.status = PluginStatus.ENABLED
            
            # 保存实例
            self.plugin_instances[plugin_id] = plugin_instance
            
            # 发布事件
            self.event_bus.publish(Event(
                type='plugin.enabled',
                data={'plugin_id': plugin_id}
            ))
            
            return True
            
        except Exception as e:
            manifest.error = str(e)
            manifest.status = PluginStatus.ERROR
            return False
    
    def disable_plugin(self, plugin_id: str) -> bool:
        """禁用插件"""
        if plugin_id not in self.plugins:
            return False
        
        manifest = self.plugins[plugin_id]
        
        if manifest.status != PluginStatus.ENABLED:
            return True
        
        try:
            # 获取实例
            plugin_instance = self.plugin_instances.get(plugin_id)
            
            if plugin_instance:
                # 关闭
                asyncio.create_task(plugin_instance.shutdown())
                
                # 注销钩子
                self._unregister_hooks(manifest)
                
                # 删除实例
                del self.plugin_instances[plugin_id]
            
            # 更新状态
            manifest.status = PluginStatus.DISABLED
            
            # 发布事件
            self.event_bus.publish(Event(
                type='plugin.disabled',
                data={'plugin_id': plugin_id}
            ))
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to disable plugin {plugin_id}: {e}")
            return False
    
    def _load_plugin(self, manifest: PluginManifest) -> Any:
        """加载插件模块"""
        plugin_path = self.plugins_dir / manifest.id
        
        # 添加入口
        sys.path.insert(0, str(plugin_path))
        
        try:
            # 导入模块
            module = importlib.import_module(manifest.main)
            
            # 获取入口类
            if hasattr(module, 'Plugin'):
                return module.Plugin()
            else:
                raise ValueError(f"Plugin class not found in {manifest.main}")
        
        finally:
            sys.path.remove(str(plugin_path))
    
    def _create_context(self, manifest: PluginManifest) -> PluginContext:
        """创建插件上下文"""
        return PluginContext(
            plugin_id=manifest.id,
            base_path=str(self.plugins_dir / manifest.id),
            config=manifest.default_config,
            logger=logging.getLogger(f'plugin.{manifest.id}'),
            data_dir=str(self.data_dir / manifest.id),
            cache_dir=str(self.cache_dir / manifest.id),
            skill_manager=self.get_service('skill_manager'),
            memory_manager=self.get_service('memory_manager'),
            message_router=self.get_service('message_router'),
            agent_orchestrator=self.get_service('agent_orchestrator')
        )
    
    def _register_hooks(self, manifest: PluginManifest, plugin: Any):
        """注册插件钩子"""
        for hook_name, method_name in manifest.hooks.items():
            if hasattr(plugin, method_name):
                method = getattr(plugin, method_name)
                self.hooks[hook_name].append(method)
    
    def _unregister_hooks(self, manifest: PluginManifest):
        """注销插件钩子"""
        for hook_name in manifest.hooks:
            if hook_name in self.hooks:
                # 移除该插件的所有钩子
                self.hooks[hook_name] = [
                    h for h in self.hooks[hook_name]
                    if getattr(h, '__self__', None) != self.plugin_instances.get(manifest.id)
                ]
    
    async def trigger_hook(
        self,
        hook_name: str,
        *args,
        **kwargs
    ) -> List[Any]:
        """触发钩子"""
        results = []
        for hook in self.hooks.get(hook_name, []):
            try:
                if asyncio.iscoroutinefunction(hook):
                    result = await hook(*args, **kwargs)
                else:
                    result = hook(*args, **kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"Hook {hook_name} failed: {e}")
        return results
    
    def list_plugins(
        self,
        status: Optional[PluginStatus] = None,
        type: Optional[PluginType] = None
    ) -> List[PluginManifest]:
        """列出插件"""
        plugins = list(self.plugins.values())
        
        if status:
            plugins = [p for p in plugins if p.status == status]
        
        if type:
            plugins = [p for p in plugins if p.type == type]
        
        return plugins
    
    def get_plugin(self, plugin_id: str) -> Optional[PluginManifest]:
        """获取插件信息"""
        return self.plugins.get(plugin_id)
    
    def _download_plugin(
        self,
        source: str,
        version: Optional[str]
    ) -> Path:
        """下载插件"""
        import shutil
        
        # 如果是本地路径
        if os.path.exists(source):
            plugin_path = Path(source)
            dest = self.plugins_dir / plugin_path.name
            shutil.copytree(plugin_path, dest)
            return dest
        
        # 如果是 URL
        if source.startswith('http'):
            return self._download_from_url(source, version)
        
        # 如果是仓库名
        return self._download_from_repo(source, version)
    
    def _download_from_url(
        self,
        url: str,
        version: Optional[str]
    ) -> Path:
        """从 URL 下载"""
        import requests
        import zipfile
        import tempfile
        
        # 下载
        response = requests.get(url)
        
        # 解压
        with tempfile.NamedTemporaryFile(suffix='.zip') as f:
            f.write(response.content)
            f.flush()
            
            with zipfile.ZipFile(f) as zip_file:
                plugin_id = url.split('/')[-1].replace('.zip', '')
                dest = self.plugins_dir / plugin_id
                zip_file.extractall(dest)
        
        return dest
    
    def _download_from_repo(
        self,
        name: str,
        version: Optional[str]
    ) -> Path:
        """从仓库下载"""
        # 从配置的仓库下载
        repo_url = self.config.get('plugin_repo', 'https://plugins.neurova.io')
        download_url = f"{repo_url}/plugins/{name}"
        
        if version:
            download_url += f"/{version}"
        
        return self._download_from_url(download_url, version)
    
    def _read_manifest(self, plugin_path: Path) -> PluginManifest:
        """读取插件清单"""
        manifest_path = plugin_path / 'manifest.json'
        
        if not manifest_path.exists():
            raise ValueError(f"Manifest not found: {manifest_path}")
        
        with open(manifest_path, 'r') as f:
            data = json.load(f)
        
        return PluginManifest.from_dict(data)
    
    def _check_dependencies(self, manifest: PluginManifest):
        """检查依赖"""
        for dep in manifest.dependencies:
            # 检查是否已安装
            if dep not in self.plugins:
                raise PluginDependencyError(f"Missing dependency: {dep}")
            
            # 检查版本
            dep_plugin = self.plugins[dep]
            # TODO: 版本检查逻辑
    
    def _install_dependencies(self, manifest: PluginManifest):
        """安装依赖"""
        for dep in manifest.dependencies:
            if dep not in self.plugins:
                # 安装依赖
                self.install_plugin(dep)
    
    def _save_manifest(self, manifest: PluginManifest):
        """保存清单"""
        plugin_path = self.plugins_dir / manifest.id
        plugin_path.mkdir(parents=True, exist_ok=True)
        
        manifest_path = plugin_path / 'manifest.json'
        with open(manifest_path, 'w') as f:
            json.dump(manifest.to_dict(), f, indent=2)
    
    def get_service(self, name: str) -> Any:
        """获取服务 (占位符)"""
        # 实际实现中需要从框架获取服务
        return None
```

## 4. CLI 接口设计

### 4.1 CLI 架构

```python
import click
import asyncio
from typing import Optional

@click.group()
@click.version_option(version='1.0.0')
@click.option('--config', '-c', default='config.yaml', help='配置文件路径')
@click.pass_context
def cli(ctx, config, version):
    """neurova CLI - 智能体代理框架命令行工具"""
    ctx.ensure_object(dict)
    ctx.obj['config'] = config
    ctx.obj['version'] = version

# ========== Agent 管理 ==========

@cli.group()
def agent():
    """Agent 管理命令"""
    pass

@agent.command('list')
@click.option('--status', '-s', type=click.Choice(['idle', 'busy', 'offline']), help='按状态过滤')
@click.pass_context
def agent_list(ctx, status):
    """列出所有 Agent"""
    orchestrator = get_orchestrator(ctx.obj['config'])
    agents = orchestrator.list_agents(status=status)
    
    click.echo(f"Found {len(agents)} agents:")
    click.echo()
    
    for agent in agents:
        click.echo(f"  ID: {agent.config.id}")
        click.echo(f"  Name: {agent.config.name}")
        click.echo(f"  Status: {agent.status.value}")
        click.echo(f"  Role: {agent.config.role.value}")
        click.echo()

@agent.command('create')
@click.argument('name')
@click.option('--config', '-c', 'config_file', required=True, help='Agent 配置文件')
@click.pass_context
def agent_create(ctx, name, config_file):
    """创建新 Agent"""
    orchestrator = get_orchestrator(ctx.obj['config'])
    
    # 读取配置
    with open(config_file, 'r') as f:
        agent_config = yaml.safe_load(f)
    
    config = AgentConfig(
        name=name,
        **agent_config
    )
    
    agent = orchestrator.create_agent(config)
    click.echo(f"Agent created: {agent.config.id}")

@agent.command('destroy')
@click.argument('agent_id')
@click.option('--force', '-f', is_flag=True, help='强制删除')
@click.pass_context
def agent_destroy(ctx, agent_id, force):
    """删除 Agent"""
    orchestrator = get_orchestrator(ctx.obj['config'])
    
    if not force:
        click.confirm(f"Are you sure you want to delete agent {agent_id}?", abort=True)
    
    success = orchestrator.destroy_agent(agent_id)
    if success:
        click.echo(f"Agent {agent_id} destroyed")
    else:
        click.echo(f"Failed to destroy agent {agent_id}")

@agent.command('status')
@click.argument('agent_id')
@click.pass_context
def agent_status(ctx, agent_id):
    """查看 Agent 状态"""
    orchestrator = get_orchestrator(ctx.obj['config'])
    agent = orchestrator.get_agent(agent_id)
    
    if not agent:
        click.echo(f"Agent {agent_id} not found")
        return
    
    click.echo(f"Agent: {agent.config.name}")
    click.echo(f"  ID: {agent.config.id}")
    click.echo(f"  Status: {agent.status.value}")
    click.echo(f"  Current Tasks: {len(agent.current_tasks)}")
    click.echo(f"  Completed Tasks: {len(agent.completed_tasks)}")
    click.echo(f"  Success Rate: {agent.get_success_rate():.2%}")

# ========== Skill 管理 ==========

@cli.group()
def skill():
    """Skill 管理命令"""
    pass

@skill.command('list')
@click.option('--category', '-c', help='按分类过滤')
@click.option('--tag', '-t', multiple=True, help='按标签过滤')
@click.pass_context
def skill_list(ctx, category, tag):
    """列出所有 Skill"""
    manager = get_skill_manager(ctx.obj['config'])
    skills = manager.list_skills(category=category, tags=list(tag) if tag else None)
    
    click.echo(f"Found {len(skills)} skills:")
    click.echo()
    
    for skill in skills:
        click.echo(f"  {skill.id}")
        click.echo(f"    Name: {skill.name}")
        click.echo(f"    Description: {skill.description}")
        click.echo(f"    Category: {skill.category}")
        click.echo(f"    Tags: {', '.join(skill.tags)}")
        click.echo()

@skill.command('info')
@click.argument('skill_id')
@click.pass_context
def skill_info(ctx, skill_id):
    """查看 Skill 详情"""
    manager = get_skill_manager(ctx.obj['config'])
    skill = manager.get_skill(skill_id)
    
    if not skill:
        click.echo(f"Skill {skill_id} not found")
        return
    
    click.echo(f"Skill: {skill.name}")
    click.echo(f"  ID: {skill.id}")
    click.echo(f"  Version: {skill.version}")
    click.echo(f"  Author: {skill.author}")
    click.echo(f"  Description: {skill.description}")
    click.echo()
    click.echo("Parameters:")
    for param in skill.parameters:
        required = " (required)" if param.required else ""
        click.echo(f"  - {param.name} ({param.type}){required}")
        click.echo(f"    {param.description}")
        if param.default is not None:
            click.echo(f"    Default: {param.default}")
    click.echo()

@skill.command('execute')
@click.argument('skill_id')
@click.option('--param', '-p', multiple=True, help='参数 (格式：key=value)')
@click.pass_context
def skill_execute(ctx, skill_id, param):
    """执行 Skill"""
    manager = get_skill_manager(ctx.obj['config'])
    
    # 解析参数
    params = {}
    for p in param:
        key, value = p.split('=', 1)
        params[key] = value
    
    # 执行
    result = asyncio.run(manager.execute_skill(
        skill_id=skill_id,
        agent_id='cli',
        params=params
    ))
    
    if result.success:
        click.echo("Success!")
        click.echo(json.dumps(result.data, indent=2))
    else:
        click.echo(f"Failed: {result.error}", err=True)

# ========== 插件管理 ==========

@cli.group()
def plugin():
    """插件管理命令"""
    pass

@plugin.command('list')
@click.option('--status', '-s', type=click.Choice(['installed', 'enabled', 'disabled', 'error']), help='按状态过滤')
@click.pass_context
def plugin_list(ctx, status):
    """列出所有插件"""
    manager = get_plugin_manager(ctx.obj['config'])
    plugins = manager.list_plugins(status=PluginStatus(status) if status else None)
    
    click.echo(f"Found {len(plugins)} plugins:")
    click.echo()
    
    for plugin in plugins:
        status_icon = {
            PluginStatus.ENABLED: "✓",
            PluginStatus.DISABLED: "✗",
            PluginStatus.ERROR: "!",
            PluginStatus.INSTALLED: "○"
        }[plugin.status]
        
        click.echo(f"  [{status_icon}] {plugin.id} v{plugin.version}")
        click.echo(f"      {plugin.name}")
        click.echo(f"      {plugin.description}")
        click.echo()

@plugin.command('install')
@click.argument('source')
@click.option('--version', '-v', help='版本号')
@click.pass_context
def plugin_install(ctx, source, version):
    """安装插件"""
    manager = get_plugin_manager(ctx.obj['config'])
    
    click.echo(f"Installing plugin from {source}...")
    
    try:
        manifest = manager.install_plugin(source, version)
        click.echo(f"Plugin installed: {manifest.id} v{manifest.version}")
    except Exception as e:
        click.echo(f"Failed to install: {e}", err=True)

@plugin.command('uninstall')
@click.argument('plugin_id')
@click.option('--force', '-f', is_flag=True, help='强制卸载')
@click.pass_context
def plugin_uninstall(ctx, plugin_id, force):
    """卸载插件"""
    manager = get_plugin_manager(ctx.obj['config'])
    
    if not force:
        click.confirm(f"Are you sure you want to uninstall {plugin_id}?", abort=True)
    
    success = manager.uninstall_plugin(plugin_id)
    if success:
        click.echo(f"Plugin {plugin_id} uninstalled")
    else:
        click.echo(f"Plugin {plugin_id} not found", err=True)

@plugin.command('enable')
@click.argument('plugin_id')
@click.pass_context
def plugin_enable(ctx, plugin_id):
    """启用插件"""
    manager = get_plugin_manager(ctx.obj['config'])
    
    success = manager.enable_plugin(plugin_id)
    if success:
        click.echo(f"Plugin {plugin_id} enabled")
    else:
        click.echo(f"Failed to enable plugin {plugin_id}", err=True)

@plugin.command('disable')
@click.argument('plugin_id')
@click.pass_context
def plugin_disable(ctx, plugin_id):
    """禁用插件"""
    manager = get_plugin_manager(ctx.obj['config'])
    
    success = manager.disable_plugin(plugin_id)
    if success:
        click.echo(f"Plugin {plugin_id} disabled")
    else:
        click.echo(f"Failed to disable plugin {plugin_id}", err=True)

# ========== 系统命令 ==========

@cli.command()
@click.pass_context
def start(ctx):
    """启动 neurova 服务"""
    config = load_config(ctx.obj['config'])
    
    # 初始化框架
    framework = neurovaFramework(config)
    framework.start()
    
    click.echo("neurova started successfully")
    click.echo(f"Web UI: http://localhost:{config.get('web_port', 8080)}")
    click.echo("Press Ctrl+C to stop")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\nShutting down...")
        framework.stop()

@cli.command('stop')
@click.pass_context
def stop(ctx):
    """停止 neurova 服务"""
    # 发送停止信号
    import signal
    os.kill(os.getpid(), signal.SIGTERM)
    click.echo("neurova stopped")

@cli.command('status')
@click.pass_context
def system_status(ctx):
    """查看系统状态"""
    config = load_config(ctx.obj['config'])
    
    click.echo("neurova Status")
    click.echo("=" * 40)
    
    # Agent 状态
    orchestrator = get_orchestrator(config)
    agents = orchestrator.list_agents()
    click.echo(f"Agents: {len(agents)}")
    click.echo(f"  - Online: {len([a for a in agents if a.status != AgentStatus.OFFLINE])}")
    click.echo(f"  - Offline: {len([a for a in agents if a.status == AgentStatus.OFFLINE])}")
    
    # Skill 状态
    manager = get_skill_manager(config)
    skills = manager.list_skills()
    click.echo(f"Skills: {len(skills)}")
    
    # 插件状态
    plugin_mgr = get_plugin_manager(config)
    plugins = plugin_mgr.list_plugins(status=PluginStatus.ENABLED)
    click.echo(f"Plugins Enabled: {len(plugins)}")
    
    # 内存使用
    import psutil
    process = psutil.Process()
    memory = process.memory_info().rss / 1024 / 1024
    click.echo(f"Memory Usage: {memory:.2f} MB")

@cli.command('config')
@click.option('--show', is_flag=True, help='显示当前配置')
@click.option('--validate', is_flag=True, help='验证配置')
@click.pass_context
def config_cmd(ctx, show, validate):
    """配置管理"""
    config_path = ctx.obj['config']
    
    if show:
        with open(config_path, 'r') as f:
            click.echo(f.read())
    
    if validate:
        try:
            config = load_config(config_path)
            click.echo("Configuration is valid")
        except Exception as e:
            click.echo(f"Configuration error: {e}", err=True)

# ========== 工具命令 ==========

@cli.command('logs')
@click.option('--follow', '-f', is_flag=True, help='跟踪日志')
@click.option('--lines', '-n', default=100, help='显示行数')
@click.pass_context
def logs(ctx, follow, lines):
    """查看日志"""
    log_file = get_log_file(ctx.obj['config'])
    
    if not os.path.exists(log_file):
        click.echo("No log file found", err=True)
        return
    
    if follow:
        # 跟踪模式
        with open(log_file, 'r') as f:
            # 移动到文件末尾
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    click.echo(line, nl=False)
                else:
                    time.sleep(0.1)
    else:
        # 显示最后 N 行
        with open(log_file, 'r') as f:
            all_lines = f.readlines()
            for line in all_lines[-lines:]:
                click.echo(line, nl=False)

def get_orchestrator(config):
    """获取 Agent 编排器"""
    # 实现略
    pass

def get_skill_manager(config):
    """获取 Skill 管理器"""
    # 实现略
    pass

def get_plugin_manager(config):
    """获取插件管理器"""
    # 实现略
    pass

def load_config(config_path):
    """加载配置"""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def get_log_file(config):
    """获取日志文件路径"""
    return config.get('logging', {}).get('file', 'logs/neurova.log')

if __name__ == '__main__':
    cli()
```

## 5. CLI 使用示例

### 5.1 使用示例

```bash
# 查看帮助
neurova --help

# 启动服务
neurova start

# 查看系统状态
neurova status

# 列出所有 Agent
neurova agent list

# 创建 Agent
neurova agent create assistant --config agents/assistant.yaml

# 查看 Agent 状态
neurova agent status agent_12345

# 列出所有 Skill
neurova skill list

# 查看 Skill 详情
neurova skill info search

# 执行 Skill
neurova skill execute search -p query="Python tutorial" -p num_results=5

# 列出插件
neurova plugin list

# 安装插件
neurova plugin install wechat-connector

# 启用插件
neurova plugin enable wechat-connector

# 查看日志
neurova logs -f -n 100

# 验证配置
neurova config --validate
```

## 6. 配置示例

### 6.1 CLI 配置

```yaml
# config.yaml
framework:
  name: "neurova"
  version: "1.0.0"

# 插件配置
plugins:
  plugins_dir: "plugins"
  data_dir: "data/plugins"
  cache_dir: "cache/plugins"
  plugin_repo: "https://plugins.neurova.io"

# 日志配置
logging:
  level: "INFO"
  file: "logs/neurova.log"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  max_size: 10485760  # 10MB
  backup_count: 5

# Web 配置
web:
  enabled: true
  host: "0.0.0.0"
  port: 8080

# API 配置
api:
  enabled: true
  host: "0.0.0.0"
  port: 8081
```

## 7. 插件开发模板

### 7.1 插件结构

```
my-plugin/
├── manifest.json
├── my_plugin/
│   ├── __init__.py
│   └── plugin.py
├── requirements.txt
└── README.md
```

### 7.2 manifest.json

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "description": "A sample plugin for neurova",
  "version": "1.0.0",
  "author": "Your Name",
  "type": "functional",
  "main": "my_plugin.plugin",
  "dependencies": [],
  "permissions": ["network", "file_read"],
  "hooks": {
    "on_message": "handle_message",
    "on_task": "handle_task"
  },
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
  }
}
```

### 7.3 plugin.py

```python
from neurova import Plugin, PluginContext

class Plugin:
    def __init__(self):
        self.context = None
    
    async def initialize(self, context: PluginContext):
        """初始化插件"""
        self.context = context
        self.context.log('info', 'Plugin initialized')
    
    async def shutdown(self):
        """关闭插件"""
        self.context.log('info', 'Plugin shutdown')
    
    async def handle_message(self, message):
        """处理消息钩子"""
        # 实现消息处理逻辑
        pass
    
    async def handle_task(self, task):
        """处理任务钩子"""
        # 实现任务处理逻辑
        pass
```
