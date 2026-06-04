# Skill 协议兼容层设计

## 1. 概述

### 1.1 设计目标
- 兼容主流 Skill 协议 (OpenClaw, Qwenpaw 等)
- 统一的 Skill 接口抽象
- 支持动态加载和卸载
- Skill 沙箱执行环境
- 完善的错误处理和日志
- 支持 Skill 组合和链式调用

### 1.2 Skill 分类

```
Skill 系统
├── 内置 Skill
│   ├── 搜索类 (search, web_search)
│   ├── 计算类 (calculator, code_executor)
│   ├── 文件类 (file_reader, file_writer)
│   └── 工具类 (translator, summarizer)
│
├── 外部 Skill
│   ├── OpenClaw 兼容 Skill
│   ├── Qwenpaw 兼容 Skill
│   └── 自定义 Skill
│
└── 复合 Skill
    ├── 链式 Skill (多 Skill 串联)
    └── 并行 Skill (多 Skill 并行)
```

## 2. Skill 数据模型

### 2.1 Skill 元数据

```python
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum
import json
from datetime import datetime

class SkillStatus(Enum):
    READY = "ready"
    LOADING = "loading"
    ERROR = "error"
    DISABLED = "disabled"

class SkillScope(Enum):
    GLOBAL = "global"  # 所有 Agent 可用
    AGENT = "agent"    # 仅特定 Agent 可用
    PRIVATE = "private" # 仅创建者可用

@dataclass
class SkillParameter:
    """Skill 参数定义"""
    name: str
    type: str  # str, int, float, bool, list, dict
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[Any]] = None  # 枚举值
    min: Optional[float] = None  # 数值最小值
    max: Optional[float] = None  # 数值最大值
    pattern: Optional[str] = None  # 字符串正则

@dataclass
class SkillMetadata:
    """Skill 元数据"""
    id: str
    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    status: SkillStatus = SkillStatus.READY
    scope: SkillScope = SkillScope.GLOBAL
    
    # 能力
    parameters: List[SkillParameter] = field(default_factory=list)
    returns: Dict[str, Any] = field(default_factory=dict)
    
    # 配置
    timeout: int = 30  # 执行超时 (秒)
    max_retries: int = 3
    rate_limit: int = 100  # 每分钟调用次数
    
    # 依赖
    dependencies: List[str] = field(default_factory=list)
    required_permissions: List[str] = field(default_factory=list)
    
    # 标签和分类
    tags: List[str] = field(default_factory=list)
    category: str = "general"
    
    # 文档
    documentation: str = ""
    examples: List[Dict] = field(default_factory=list)
    
    # 时间戳
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'version': self.version,
            'author': self.author,
            'status': self.status.value,
            'scope': self.scope.value,
            'parameters': [self._param_to_dict(p) for p in self.parameters],
            'returns': self.returns,
            'timeout': self.timeout,
            'max_retries': self.max_retries,
            'rate_limit': self.rate_limit,
            'dependencies': self.dependencies,
            'required_permissions': self.required_permissions,
            'tags': self.tags,
            'category': self.category,
            'documentation': self.documentation,
            'examples': self.examples,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
    
    def _param_to_dict(self, param: SkillParameter) -> Dict:
        """参数转字典"""
        return {
            'name': param.name,
            'type': param.type,
            'description': param.description,
            'required': param.required,
            'default': param.default,
            'enum': param.enum,
            'min': param.min,
            'max': param.max,
            'pattern': param.pattern
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SkillMetadata':
        """从字典创建"""
        return cls(
            id=data['id'],
            name=data['name'],
            description=data['description'],
            version=data.get('version', '1.0.0'),
            author=data.get('author', ''),
            status=SkillStatus(data.get('status', 'ready')),
            scope=SkillScope(data.get('scope', 'global')),
            parameters=[cls._dict_to_param(p) for p in data.get('parameters', [])],
            returns=data.get('returns', {}),
            timeout=data.get('timeout', 30),
            max_retries=data.get('max_retries', 3),
            rate_limit=data.get('rate_limit', 100),
            dependencies=data.get('dependencies', []),
            required_permissions=data.get('required_permissions', []),
            tags=data.get('tags', []),
            category=data.get('category', 'general'),
            documentation=data.get('documentation', ''),
            examples=data.get('examples', [])
        )
    
    @staticmethod
    def _dict_to_param(data: Dict) -> SkillParameter:
        """字典转参数"""
        return SkillParameter(
            name=data['name'],
            type=data['type'],
            description=data['description'],
            required=data.get('required', True),
            default=data.get('default'),
            enum=data.get('enum'),
            min=data.get('min'),
            max=data.get('max'),
            pattern=data.get('pattern')
        )

@dataclass
class SkillResult:
    """Skill 执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    tokens_used: int = 0
    
    def to_dict(self) -> Dict:
        return {
            'success': self.success,
            'data': self.data,
            'error': self.error,
            'error_code': self.error_code,
            'metadata': self.metadata,
            'execution_time': self.execution_time,
            'tokens_used': self.tokens_used
        }
```

## 3. Skill 接口定义

### 3.1 Skill 抽象基类

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import asyncio

class SkillContext:
    """
    Skill 执行上下文
    提供运行环境、配置、日志等
    """
    
    def __init__(
        self,
        agent_id: str,
        skill_id: str,
        config: Dict[str, Any],
        logger: Any,
        memory_manager: Optional[Any] = None,
        message_router: Optional[Any] = None
    ):
        self.agent_id = agent_id
        self.skill_id = skill_id
        self.config = config
        self.logger = logger
        self.memory = memory_manager
        self.message_router = message_router
        self.state: Dict[str, Any] = {}
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """获取配置"""
        return self.config.get(key, default)
    
    def log(self, level: str, message: str, **kwargs):
        """记录日志"""
        log_entry = {
            'skill_id': self.skill_id,
            'agent_id': self.agent_id,
            'level': level,
            'message': message,
            **kwargs
        }
        getattr(self.logger, level.lower())(json.dumps(log_entry))
    
    async def store_state(self, key: str, value: Any):
        """存储状态"""
        self.state[key] = value
        if self.memory:
            await self.memory.save(f"skill_state:{self.skill_id}:{key}", value)
    
    async def load_state(self, key: str, default: Any = None) -> Any:
        """加载状态"""
        if key in self.state:
            return self.state[key]
        if self.memory:
            return await self.memory.load(f"skill_state:{self.skill_id}:{key}", default)
        return default

class Skill(ABC):
    """
    Skill 抽象基类
    所有 Skill 必须继承此类
    """
    
    def __init__(self):
        self.metadata = self.define_metadata()
        self.context: Optional[SkillContext] = None
        self._initialized = False
    
    @abstractmethod
    def define_metadata(self) -> SkillMetadata:
        """定义 Skill 元数据"""
        pass
    
    @abstractmethod
    async def execute(self, context: SkillContext, params: Dict[str, Any]) -> SkillResult:
        """
        执行 Skill
        - context: 执行上下文
        - params: 参数
        - return: 执行结果
        """
        pass
    
    async def initialize(self, context: SkillContext):
        """初始化 Skill"""
        self.context = context
        self._initialized = True
    
    async def shutdown(self):
        """关闭 Skill"""
        self._initialized = False
    
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证参数
        返回 (是否有效，错误信息)
        """
        for param_def in self.metadata.parameters:
            # 检查必填参数
            if param_def.required and param_def.name not in params:
                return False, f"Missing required parameter: {param_def.name}"
            
            # 检查参数类型
            if param_def.name in params:
                value = params[param_def.name]
                if not self._check_type(value, param_def.type):
                    return False, f"Invalid type for {param_def.name}: expected {param_def.type}"
                
                # 检查枚举值
                if param_def.enum and value not in param_def.enum:
                    return False, f"Value {value} not in allowed values: {param_def.enum}"
                
                # 检查数值范围
                if param_def.type in ['int', 'float']:
                    if param_def.min is not None and value < param_def.min:
                        return False, f"Value {value} is less than minimum {param_def.min}"
                    if param_def.max is not None and value > param_def.max:
                        return False, f"Value {value} is greater than maximum {param_def.max}"
        
        return True, None
    
    def _check_type(self, value: Any, type_name: str) -> bool:
        """检查参数类型"""
        type_map = {
            'str': str,
            'int': int,
            'float': (int, float),
            'bool': bool,
            'list': list,
            'dict': dict
        }
        
        expected_type = type_map.get(type_name)
        if not expected_type:
            return True  # 未知类型，跳过检查
        
        return isinstance(value, expected_type)

class SkillManager:
    """
    Skill 管理器
    负责加载、卸载、执行 Skill
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.skills: Dict[str, Skill] = {}
        self.skill_registry: Dict[str, SkillMetadata] = {}
        self.context_factory = SkillContextFactory()
        self.metrics = SkillMetrics()
        
        # 沙箱配置
        self.sandbox_config = config.get('sandbox', {
            'enabled': True,
            'network_access': False,
            'file_access': False,
            'max_memory_mb': 256,
            'max_cpu_percent: 50
        })
    
    def load_skill(self, skill_path: str) -> SkillMetadata:
        """
        加载 Skill
        - skill_path: Skill 路径 (文件或模块名)
        """
        try:
            # 动态导入
            skill_class = self._import_skill(skill_path)
            
            # 创建实例
            skill = skill_class()
            
            # 验证
            if not isinstance(skill, Skill):
                raise ValueError(f"Invalid skill type: {type(skill)}")
            
            # 注册
            self.skills[skill.metadata.id] = skill
            self.skill_registry[skill.metadata.id] = skill.metadata
            
            # 初始化
            context = self.context_factory.create_context(skill.metadata.id)
            asyncio.create_task(skill.initialize(context))
            
            return skill.metadata
            
        except Exception as e:
            raise SkillLoadError(f"Failed to load skill {skill_path}: {e}")
    
    def unload_skill(self, skill_id: str) -> bool:
        """卸载 Skill"""
        if skill_id not in self.skills:
            return False
        
        skill = self.skills[skill_id]
        
        # 关闭
        asyncio.create_task(skill.shutdown())
        
        # 移除
        del self.skills[skill_id]
        del self.skill_registry[skill_id]
        
        return True
    
    async def execute_skill(
        self,
        skill_id: str,
        agent_id: str,
        params: Dict[str, Any]
    ) -> SkillResult:
        """
        执行 Skill
        """
        if skill_id not in self.skills:
            return SkillResult(
                success=False,
                error=f"Skill not found: {skill_id}",
                error_code="SKILL_NOT_FOUND"
            )
        
        skill = self.skills[skill_id]
        
        # 检查状态
        if skill.metadata.status != SkillStatus.READY:
            return SkillResult(
                success=False,
                error=f"Skill not ready: {skill.metadata.status.value}",
                error_code="SKILL_NOT_READY"
            )
        
        # 验证参数
        valid, error = skill.validate_params(params)
        if not valid:
            return SkillResult(
                success=False,
                error=error,
                error_code="INVALID_PARAMS"
            )
        
        # 创建上下文
        context = self.context_factory.create_context(
            skill_id=skill_id,
            agent_id=agent_id
        )
        
        # 执行 (带超时和重试)
        start_time = time.time()
        
        try:
            result = await asyncio.wait_for(
                skill.execute(context, params),
                timeout=skill.metadata.timeout
            )
            
            # 记录指标
            execution_time = time.time() - start_time
            self.metrics.record_execution(skill_id, execution_time, result.success)
            
            return result
            
        except asyncio.TimeoutError:
            return SkillResult(
                success=False,
                error=f"Skill execution timeout ({skill.metadata.timeout}s)",
                error_code="TIMEOUT"
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                error_code="EXECUTION_ERROR"
            )
    
    def _import_skill(self, skill_path: str) -> type:
        """导入 Skill 类"""
        import importlib
        
        # 从文件加载
        if skill_path.endswith('.py'):
            spec = importlib.util.spec_from_file_location("skill_module", skill_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.Skill
        
        # 从模块加载
        module = importlib.import_module(skill_path)
        return module.Skill
    
    def list_skills(
        self,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> List[SkillMetadata]:
        """列出可用的 Skill"""
        skills = list(self.skill_registry.values())
        
        if category:
            skills = [s for s in skills if s.category == category]
        
        if tags:
            skills = [s for s in skills if any(tag in s.tags for tag in tags)]
        
        return skills
    
    def get_skill(self, skill_id: str) -> Optional[SkillMetadata]:
        """获取 Skill 信息"""
        return self.skill_registry.get(skill_id)
```

### 3.2 Skill 上下文工厂

```python
class SkillContextFactory:
    """Skill 上下文工厂"""
    
    def __init__(self):
        self.logger = logging.getLogger('skill')
        self.memory_manager = None
        self.message_router = None
        self.config = {}
    
    def create_context(
        self,
        skill_id: str,
        agent_id: str = ""
    ) -> SkillContext:
        """创建 Skill 上下文"""
        return SkillContext(
            agent_id=agent_id,
            skill_id=skill_id,
            config=self.config,
            logger=self.logger,
            memory_manager=self.memory_manager,
            message_router=self.message_router
        )
```

## 4. 内置 Skill 实现

### 4.1 搜索 Skill

```python
class SearchSkill(Skill):
    """
    搜索 Skill
    支持多种搜索引擎
    """
    
    def define_metadata(self) -> SkillMetadata:
        return SkillMetadata(
            id="search",
            name="Web Search",
            description="Search the web for information",
            version="1.0.0",
            author="Neurova",
            category="search",
            tags=["search", "web", "information"],
            parameters=[
                SkillParameter(
                    name="query",
                    type="str",
                    description="Search query",
                    required=True
                ),
                SkillParameter(
                    name="engine",
                    type="str",
                    description="Search engine (google, bing, baidu)",
                    required=False,
                    default="google",
                    enum=["google", "bing", "baidu"]
                ),
                SkillParameter(
                    name="num_results",
                    type="int",
                    description="Number of results",
                    required=False,
                    default=10,
                    min=1,
                    max=100
                )
            ],
            returns={
                "type": "list",
                "description": "List of search results",
                "schema": {
                    "title": "str",
                    "url": "str",
                    "snippet": "str"
                }
            },
            timeout=30,
            examples=[
                {
                    "description": "Search for Python tutorials",
                    "params": {
                        "query": "Python tutorial",
                        "num_results": 5
                    }
                }
            ]
        )
    
    async def execute(self, context: SkillContext, params: Dict[str, Any]) -> SkillResult:
        """执行搜索"""
        query = params['query']
        engine = params.get('engine', 'google')
        num_results = params.get('num_results', 10)
        
        try:
            context.log('info', f"Searching for: {query}", engine=engine)
            
            # 调用搜索引擎 API
            results = await self._search(engine, query, num_results)
            
            return SkillResult(
                success=True,
                data=results,
                metadata={
                    'engine': engine,
                    'query': query,
                    'count': len(results)
                }
            )
            
        except Exception as e:
            context.log('error', f"Search failed: {e}")
            return SkillResult(
                success=False,
                error=str(e),
                error_code="SEARCH_ERROR"
            )
    
    async def _search(self, engine: str, query: str, num_results: int) -> List[Dict]:
        """执行搜索"""
        # 实现搜索逻辑
        # 这里使用伪代码
        if engine == 'google':
            return await self._google_search(query, num_results)
        elif engine == 'bing':
            return await self._bing_search(query, num_results)
        elif engine == 'baidu':
            return await self._baidu_search(query, num_results)
        else:
            raise ValueError(f"Unknown search engine: {engine}")
    
    async def _google_search(self, query: str, num_results: int) -> List[Dict]:
        """Google 搜索"""
        # 调用 Google Custom Search API
        pass
```

### 4.2 计算器 Skill

```python
class CalculatorSkill(Skill):
    """
    计算器 Skill
    支持数学表达式计算
    """
    
    def define_metadata(self) -> SkillMetadata:
        return SkillMetadata(
            id="calculator",
            name="Calculator",
            description="Evaluate mathematical expressions",
            version="1.0.0",
            author="Neurova",
            category="utility",
            tags=["math", "calculator", "computation"],
            parameters=[
                SkillParameter(
                    name="expression",
                    type="str",
                    description="Mathematical expression",
                    required=True,
                    pattern=r"^[\d+\-*/().\s]+$"
                )
            ],
            returns={
                "type": "float",
                "description": "Calculation result"
            },
            examples=[
                {
                    "description": "Calculate 2 + 2",
                    "params": {
                        "expression": "2 + 2"
                    }
                }
            ]
        )
    
    async def execute(self, context: SkillContext, params: Dict[str, Any]) -> SkillResult:
        """执行计算"""
        expression = params['expression']
        
        try:
            # 安全计算
            result = self._safe_eval(expression)
            
            return SkillResult(
                success=True,
                data=result,
                metadata={
                    'expression': expression
                }
            )
            
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Invalid expression: {e}",
                error_code="CALCULATION_ERROR"
            )
    
    def _safe_eval(self, expression: str) -> float:
        """安全计算表达式"""
        import ast
        import operator
        
        # 定义允许的操作符
        operators = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.USub: operator.neg
        }
        
        def eval_node(node):
            if isinstance(node, ast.Num):
                return node.n
            elif isinstance(node, ast.BinOp):
                left = eval_node(node.left)
                right = eval_node(node.right)
                return operators[type(node.op)](left, right)
            elif isinstance(node, ast.UnaryOp):
                operand = eval_node(node.operand)
                return operators[type(node.op)](operand)
            else:
                raise ValueError(f"Unsupported operation: {node}")
        
        tree = ast.parse(expression, mode='eval')
        return eval_node(tree.body)
```

### 4.3 文件操作 Skill

```python
class FileReaderSkill(Skill):
    """
    文件读取 Skill
    """
    
    def define_metadata(self) -> SkillMetadata:
        return SkillMetadata(
            id="file_reader",
            name="File Reader",
            description="Read content from files",
            version="1.0.0",
            author="Neurova",
            category="file",
            tags=["file", "read", "io"],
            parameters=[
                SkillParameter(
                    name="file_path",
                    type="str",
                    description="Path to the file",
                    required=True
                ),
                SkillParameter(
                    name="encoding",
                    type="str",
                    description="File encoding",
                    required=False,
                    default="utf-8"
                ),
                SkillParameter(
                    name="max_size",
                    type="int",
                    description="Maximum file size in bytes",
                    required=False,
                    default=1024*1024,  # 1MB
                    min=1
                )
            ],
            returns={
                "type": "str",
                "description": "File content"
            }
        )
    
    async def execute(self, context: SkillContext, params: Dict[str, Any]) -> SkillResult:
        """读取文件"""
        file_path = params['file_path']
        encoding = params.get('encoding', 'utf-8')
        max_size = params.get('max_size', 1024*1024)
        
        try:
            # 安全检查
            if not self._is_safe_path(file_path):
                return SkillResult(
                    success=False,
                    error="Access denied: path outside allowed directories",
                    error_code="ACCESS_DENIED"
                )
            
            # 检查文件大小
            file_size = os.path.getsize(file_path)
            if file_size > max_size:
                return SkillResult(
                    success=False,
                    error=f"File too large: {file_size} > {max_size}",
                    error_code="FILE_TOO_LARGE"
                )
            
            # 读取文件
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
            
            return SkillResult(
                success=True,
                data=content,
                metadata={
                    'file_path': file_path,
                    'size': file_size
                }
            )
            
        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                error_code="FILE_READ_ERROR"
            )
    
    def _is_safe_path(self, file_path: str) -> bool:
        """检查路径是否安全"""
        import os
        
        # 解析绝对路径
        abs_path = os.path.abspath(file_path)
        
        # 检查是否在允许的目录内
        allowed_dirs = self.context.get_config('allowed_directories', [])
        for allowed_dir in allowed_dirs:
            if abs_path.startswith(os.path.abspath(allowed_dir)):
                return True
        
        return False
```

## 5. OpenClaw 兼容层

### 5.1 协议适配器

```python
class OpenClawAdapter:
    """
    OpenClaw 协议适配器
    实现 OpenClaw Skill 协议
    """
    
    def __init__(self, skill_manager: SkillManager):
        self.skill_manager = skill_manager
    
    async def handle_request(self, request: Dict) -> Dict:
        """处理 OpenClaw 请求"""
        action = request.get('action')
        
        if action == 'list_skills':
            return await self._list_skills(request)
        elif action == 'get_skill':
            return await self._get_skill(request)
        elif action == 'execute_skill':
            return await self._execute_skill(request)
        else:
            return {
                'success': False,
                'error': f'Unknown action: {action}'
            }
    
    async def _list_skills(self, request: Dict) -> Dict:
        """列出 Skills"""
        category = request.get('category')
        tags = request.get('tags')
        
        skills = self.skill_manager.list_skills(category, tags)
        
        return {
            'success': True,
            'data': {
                'skills': [s.to_dict() for s in skills],
                'count': len(skills)
            }
        }
    
    async def _get_skill(self, request: Dict) -> Dict:
        """获取 Skill 信息"""
        skill_id = request.get('skill_id')
        
        skill = self.skill_manager.get_skill(skill_id)
        
        if not skill:
            return {
                'success': False,
                'error': f'Skill not found: {skill_id}'
            }
        
        return {
            'success': True,
            'data': skill.to_dict()
        }
    
    async def _execute_skill(self, request: Dict) -> Dict:
        """执行 Skill"""
        skill_id = request.get('skill_id')
        agent_id = request.get('agent_id', 'default')
        params = request.get('params', {})
        
        result = await self.skill_manager.execute_skill(
            skill_id=skill_id,
            agent_id=agent_id,
            params=params
        )
        
        return {
            'success': result.success,
            'data': result.data,
            'error': result.error,
            'error_code': result.error_code,
            'metadata': result.metadata
        }
```

## 6. Qwenpaw 兼容层

### 6.1 协议适配器

```python
class QwenpawAdapter:
    """
    Qwenpaw 协议适配器
    实现 Qwenpaw Skill 协议
    """
    
    def __init__(self, skill_manager: SkillManager):
        self.skill_manager = skill_manager
    
    async def handle_command(self, command: str, params: Dict) -> Dict:
        """处理 Qwenpaw 命令"""
        if command == 'skill.list':
            return await self._list_skills(params)
        elif command == 'skill.info':
            return await self._skill_info(params)
        elif command == 'skill.exec':
            return await self._execute_skill(params)
        else:
            return {
                'status': 'error',
                'message': f'Unknown command: {command}'
            }
    
    async def _list_skills(self, params: Dict) -> Dict:
        """列出 Skills"""
        skills = self.skill_manager.list_skills()
        
        return {
            'status': 'ok',
            'result': {
                'skills': [
                    {
                        'id': s.id,
                        'name': s.name,
                        'description': s.description,
                        'tags': s.tags
                    }
                    for s in skills
                ]
            }
        }
    
    async def _skill_info(self, params: Dict) -> Dict:
        """获取 Skill 信息"""
        skill_id = params.get('skill_id')
        
        skill = self.skill_manager.get_skill(skill_id)
        
        if not skill:
            return {
                'status': 'error',
                'message': f'Skill not found: {skill_id}'
            }
        
        return {
            'status': 'ok',
            'result': skill.to_dict()
        }
    
    async def _execute_skill(self, params: Dict) -> Dict:
        """执行 Skill"""
        skill_id = params.get('skill')
        agent_id = params.get('agent', 'default')
        arguments = params.get('arguments', {})
        
        result = await self.skill_manager.execute_skill(
            skill_id=skill_id,
            agent_id=agent_id,
            params=arguments
        )
        
        if result.success:
            return {
                'status': 'ok',
                'result': result.data,
                'execution_time': result.execution_time
            }
        else:
            return {
                'status': 'error',
                'message': result.error,
                'code': result.error_code
            }
```

## 7. Skill 沙箱

### 7.1 沙箱环境

```python
import multiprocessing
import signal

class SkillSandbox:
    """
    Skill 执行沙箱
    提供资源限制和隔离
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.max_memory = config.get('max_memory_mb', 256) * 1024 * 1024
        self.max_cpu = config.get('max_cpu_percent', 50)
        self.timeout = config.get('timeout', 30)
    
    async def execute(
        self,
        skill: Skill,
        context: SkillContext,
        params: Dict[str, Any]
    ) -> SkillResult:
        """在沙箱中执行 Skill"""
        if not self.config.get('enabled', True):
            # 沙箱禁用，直接执行
            return await skill.execute(context, params)
        
        # 在多进程中执行
        def target():
            # 设置资源限制
            self._set_resource_limits()
            
            # 执行
            return asyncio.run(skill.execute(context, params))
        
        process = multiprocessing.Process(target=target)
        process.start()
        process.join(timeout=self.timeout)
        
        if process.is_alive():
            # 超时，终止进程
            process.terminate()
            process.join()
            return SkillResult(
                success=False,
                error=f"Skill execution timeout ({self.timeout}s)",
                error_code="TIMEOUT"
            )
        
        return process.exitcode == 0
    
    def _set_resource_limits(self):
        """设置资源限制"""
        import resource
        
        # 内存限制
        resource.setrlimit(
            resource.RLIMIT_AS,
            (self.max_memory, self.max_memory)
        )
        
        # CPU 限制 (通过信号)
        signal.signal(signal.SIGXCPU, self._handle_cpu_limit)
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (self.timeout, self.timeout + 5)
        )
    
    def _handle_cpu_limit(self, signum, frame):
        """CPU 限制处理"""
        raise TimeoutError("CPU time limit exceeded")
```

## 8. Skill 组合

### 8.1 链式 Skill

```python
class ChainSkill(Skill):
    """
    链式 Skill
    多个 Skill 顺序执行，前一个的输出作为后一个的输入
    """
    
    def __init__(self, skills: List[Skill], connections: List[Dict]):
        """
        - skills: Skill 列表
        - connections: 连接配置
          [{"from": "skill1", "to": "skill2", "param_map": {"output": "input"}}]
        """
        self.skills = {s.metadata.id: s for s in skills}
        self.connections = connections
    
    def define_metadata(self) -> SkillMetadata:
        return SkillMetadata(
            id=f"chain_{uuid.uuid4().hex[:8]}",
            name="Chain Skill",
            description="Chain multiple skills together",
            version="1.0.0",
            category="composite"
        )
    
    async def execute(self, context: SkillContext, params: Dict[str, Any]) -> SkillResult:
        """执行链式 Skill"""
        current_data = params
        
        for connection in self.connections:
            from_skill_id = connection['from']
            to_skill_id = connection['to']
            param_map = connection.get('param_map', {})
            
            # 执行前一个 Skill
            from_skill = self.skills[from_skill_id]
            result = await from_skill.execute(context, current_data)
            
            if not result.success:
                return result
            
            # 映射参数
            current_data = self._map_params(result.data, param_map)
        
        return SkillResult(
            success=True,
            data=current_data
        )
    
    def _map_params(self, data: Any, param_map: Dict) -> Dict:
        """参数映射"""
        mapped = {}
        for src, dst in param_map.items():
            if isinstance(data, dict) and src in data:
                mapped[dst] = data[src]
            else:
                mapped[dst] = data
        return mapped
```

## 9. 监控和指标

### 9.1 Skill 指标

```python
class SkillMetrics:
    """Skill 指标收集"""
    
    def __init__(self):
        self.executions: Dict[str, int] = defaultdict(int)
        self.failures: Dict[str, int] = defaultdict(int)
        self.latencies: Dict[str, List[float]] = defaultdict(list)
        self.last_executed: Dict[str, datetime] = {}
    
    def record_execution(
        self,
        skill_id: str,
        execution_time: float,
        success: bool
    ):
        """记录执行"""
        self.executions[skill_id] += 1
        self.latencies[skill_id].append(execution_time)
        self.last_executed[skill_id] = datetime.now()
        
        if not success:
            self.failures[skill_id] += 1
        
        # 保持列表大小
        if len(self.latencies[skill_id]) > 1000:
            self.latencies[skill_id] = self.latencies[skill_id][-1000:]
    
    def get_stats(self, skill_id: str) -> Dict:
        """获取统计信息"""
        latencies = self.latencies.get(skill_id, [])
        
        return {
            'total_executions': self.executions.get(skill_id, 0),
            'total_failures': self.failures.get(skill_id, 0),
            'success_rate': 1 - (self.failures.get(skill_id, 0) / max(self.executions.get(skill_id, 1), 1)),
            'avg_latency': sum(latencies) / len(latencies) if latencies else 0,
            'p95_latency': sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 20 else 0,
            'last_executed': self.last_executed.get(skill_id)
        }
```

## 10. 配置示例

### 10.1 Skill 配置

```yaml
# skills.yaml
skills:
  # 内置 Skill
  - id: "search"
    enabled: true
    config:
      default_engine: "google"
      api_key: "${GOOGLE_SEARCH_API_KEY}"
  
  - id: "calculator"
    enabled: true
  
  - id: "file_reader"
    enabled: true
    config:
      allowed_directories:
        - "/app/data"
        - "/tmp"
      max_file_size: 10485760  # 10MB
  
  # 自定义 Skill
  - id: "custom_analyzer"
    path: "/app/skills/analyzer.py"
    enabled: true
    config:
      model_path: "/app/models/analyzer.pkl"
  
  # 外部 Skill
  - id: "openclaw_translator"
    source: "openclaw"
    remote_url: "http://openclaw.example.com/api"
    api_key: "${OPENCLAW_API_KEY}"

# 沙箱配置
sandbox:
  enabled: true
  max_memory_mb: 256
  max_cpu_percent: 50
  timeout: 30
  network_access: false
  file_access: false
```
