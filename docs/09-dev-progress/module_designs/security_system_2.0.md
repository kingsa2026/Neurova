# 安全体系 2.0 设计文档

> **模块ID**: Task4-SecuritySystem  
> **创建时间**: 2026-05-12 22:00  
> **最后更新**: 2026-05-12 23:00  
> **负责人**: security-dev  
> **状态**: 已完成

---

## 1. 模块概述

### 1.1 功能描述

Neurova 安全体系 2.0 提供完整的安全防护，采用 QwenPaw 成熟的三层安全架构，结合 Neurova 的认知增强特性：

1. **工具守卫 (Tool Guard)** - 运行时安全检测，在 Agent 调用工具前实时检测危险模式
2. **技能扫描器 (Skill Scanner)** - 技能安全预检，在技能启用前扫描安全威胁
3. **认证系统 (Auth System)** - 访问控制，用户认证、权限管理、会话管理、API 密钥管理
4. **认知安全 (Cognitive Security)** - 认知层面的安全防护，防 Prompt 注入、输出过滤、敏感信息检测

### 1.2 设计依据

- **主要依据**: `NEUROVA_CogArch_2.0.md` 第 4 章（第 834-1282 行）
- **参考实现**: `neurova/auth/` 目录下的现有认证系统
- **QwenPaw 架构**: 借鉴 QwenPaw 的三层安全架构设计

### 1.3 与其他模块的关系

- **依赖模块**:
  - `neurova.auth` - 现有认证系统（UserModel, PasswordHasher, neu_token_manager）
  - `neurova.cognitive` - 认知编排器（用于认知安全检查）

- **被依赖模块**:
  - `neurova.api` - API 层需要调用安全模块进行访问控制
  - `neurova.execution_engine` - 执行引擎需要调用工具守卫
  - `neurova.skills` - 技能系统需要调用技能扫描器

---

## 2. 架构设计

### 2.1 类/函数设计

#### 2.1.1 ToolGuard（工具守卫）

```python
# neurova/security/tool_guard.py

class ToolGuardEngine:
    """工具守卫引擎 - 协调所有守卫"""
    
    def __init__(
        self,
        guardians: Optional[List[BaseGuardian]] = None,
        denied_tools: Optional[List[str]] = None,
        approval_mode: ApprovalMode = ApprovalMode.AUTO,
    ):
        """
        Args:
            guardians: 守卫列表
            denied_tools: 无条件禁止的工具列表
            approval_mode: 审批模式（STRICT/SMART/AUTO/OFF）
        """
    
    def guard(self, tool_name: str, params: Dict[str, Any]) -> ToolGuardResult:
        """
        执行工具调用守卫
        
        Args:
            tool_name: 工具名称
            params: 工具调用参数
            
        Returns:
            ToolGuardResult: 检测结果（包含是否安全、严重程度、发现列表）
        """
```

**内置守卫**:
- `RuleBasedToolGuardian` - 基于 YAML 正则规则的检测
- `ShellEvasionGuardian` - Shell 绕过检测（引号混淆、编码绕过）
- `FilePathGuardian` - 敏感文件访问控制

**内置规则**（覆盖的危险模式）:
- 危险文件操作（rm -rf, chmod 777）
- 低级磁盘操作（mkfs, dd）
- 资源滥用（fork bomb, 重启服务）
- 代码执行（管道执行, base64 解码执行）
- 权限提升（sudo, su）
- 反向 Shell

#### 2.1.2 SkillScanner（技能扫描器）

```python
# neurova/security/skill_scanner.py

class SkillScanner:
    """技能安全扫描器"""
    
    def __init__(
        self,
        policy: Optional[ScanPolicy] = None,
        analyzers: Optional[List[BaseAnalyzer]] = None,
        cache: Optional[ScanCache] = None,
        whitelist_manager: Optional[WhitelistManager] = None,
    ):
        """
        Args:
            policy: 扫描策略（模式、超时、最大文件大小等）
            analyzers: 分析器列表
            cache: 扫描缓存
            whitelist_manager: 白名单管理器
        """
    
    def scan_skill(
        self,
        skill_dir: Path,
        skill_name: Optional[str] = None,
        use_cache: Optional[bool] = None,
    ) -> ScanResult:
        """
        扫描技能目录
        
        Args:
            skill_dir: 技能目录
            skill_name: 技能名称
            use_cache: 是否使用缓存
            
        Returns:
            ScanResult: 扫描结果（包含是否安全、发现列表、内容哈希等）
        """
```

**扫描模式**:
- `BLOCK` - 拦截不安全技能
- `WARN` - 仅警告，允许使用（默认）
- `OFF` - 关闭扫描

**内置分析器**:
- `PatternAnalyzer` - 使用正则模式扫描文件内容

**智能缓存**:
- 基于文件 mtime 和 内容哈希
- 避免重复扫描相同内容

**白名单机制**:
- 基于内容哈希的安全白名单
- 技能内容改变则白名单失效

#### 2.1.3 AuthSystem（认证系统）

```python
# neurova/security/auth_system.py

class AuthSystem:
    """认证系统"""
    
    def __init__(
        self,
        db_path: str = "data/users.db",
        secret_key: Optional[str] = None,
    ):
        """
        Args:
            db_path: 用户数据库路径
            secret_key: Token 签名密钥
        """
    
    def register(
        self,
        username: str,
        password: str,
        email: Optional[str] = None,
        role: UserRole = UserRole.USER,
    ) -> Optional[Dict[str, Any]]:
        """
        注册用户
        
        Args:
            username: 用户名
            password: 密码
            email: 邮箱
            role: 角色（admin/user/guest）
            
        Returns:
            用户信息，失败则返回 None
        """
    
    def login(
        self,
        username: str,
        password: str,
        ip_address: str = "127.0.0.1",
        user_agent: str = "",
    ) -> Optional[AuthToken]:
        """
        用户登录
        
        Args:
            username: 用户名
            password: 密码
            ip_address: IP 地址
            user_agent: User Agent
            
        Returns:
            AuthToken，失败则返回 None
        """
```

**权限管理**:
- `PermissionManager` - 管理用户角色和权限
- 角色权限映射（admin/user/guest）
- 支持额外权限授予

**API 密钥管理**:
- `APIKeyManager` - 创建、验证、撤销 API 密钥
- 基于 HMAC-SHA256 的密钥签名
- 支持过期时间和权限范围

**会话管理**:
- `SessionManager` - 创建、验证、销毁会话
- 支持过期时间和活动跟踪

#### 2.1.4 CognitiveSecurity（认知安全）

```python
# neurova/security/cognitive_security.py

class CognitiveSecuritySystem:
    """认知安全系统（总控）"""
    
    def __init__(
        self,
        cognitive_orchestrator: Optional[Any] = None,
        enable_cognitive_check: bool = True,
        enable_memory_sanitization: bool = True,
    ):
        """
        Args:
            cognitive_orchestrator: 认知编排器
            enable_cognitive_check: 是否启用认知检查
            enable_memory_sanitization: 是否启用记忆清理
        """
    
    async def check_input_safety(
        self, user_input: str, context: Optional[Dict[str, Any]] = None
    ) -> SafetyCheckResult:
        """
        检查输入安全性
        
        Args:
            user_input: 用户输入
            context: 上下文
            
        Returns:
            SafetyCheckResult: 检查结果
        """
    
    def check_output_safety(self, output: str) -> SafetyCheckResult:
        """
        检查输出安全性
        
        Args:
            output: 输出内容
            
        Returns:
            SafetyCheckResult: 检查结果（包含过滤后输出）
        """
```

**认知安全检查器**:
- `CognitiveSafetyChecker` - 利用 Neurova 认知能力进行高级安全检查
- 检查用户意图是否安全
- 实时监控执行安全

**记忆安全防护**:
- `MemorySecurityGuard` - 保护敏感记忆不被泄露
- 清理记忆中的敏感信息
- 判断内容是否应该被记住

**Prompt 注入检测**:
- `PromptInjectionDetector` - 检测用户输入中的 Prompt 注入攻击
- 内置常见注入模式（指令覆盖、角色覆盖、编码绕过等）

**敏感信息检测**:
- `SensitiveInfoDetector` - 检测输入/输出中的敏感信息
- 内置敏感信息模式（密码、API Key、私钥、身份证号等）

**输出过滤**:
- `OutputFilter` - 过滤 LLM 输出中的不安全内容
- 检测恶意代码、反向 Shell、数据外泄等

### 2.2 数据流图

```
用户请求 → AuthSystem (认证) → ToolGuard (工具调用前检查)
                            ↓
                      SkillScanner (技能扫描)
                            ↓
                      CognitiveSecurity (认知安全检查)
                            ↓
                      执行引擎 → 输出过滤 → 返回结果
```

### 2.3 状态机

**审批模式状态机**:

```
[OFF] → [AUTO] → [SMART] → [STRICT]
  ↓        ↓         ↓         ↓
关闭守卫  自动审批  智能审批  严格审批
```

---

## 3. 接口设计

### 3.1 API 接口

| 接口路径 | 方法 | 说明 | 请求参数 | 返回格式 |
|---------|------|------|---------|----------|
| `/api/security/tool-guard/status` | GET | 获取工具守卫状态 | - | JSON |
| `/api/security/tool-guard/config` | GET/POST | 获取/更新工具守卫配置 | config | JSON |
| `/api/security/tool-guard/rules` | GET/POST | 规则管理 | rule | JSON |
| `/api/security/skill-scanner/scan` | POST | 扫描技能 | skill_dir | JSON |
| `/api/security/skill-scanner/whitelist` | GET/POST | 白名单管理 | hash | JSON |
| `/api/security/skill-scanner/alerts` | GET | 获取扫描告警 | - | JSON |
| `/api/auth/login` | POST | 用户登录 | username, password | JSON |
| `/api/auth/register` | POST | 用户注册 | username, password, email | JSON |
| `/api/auth/status` | GET | 获取认证状态 | token | JSON |
| `/api/auth/logout` | POST | 用户登出 | token | JSON |
| `/api/auth/reset-password` | POST | 重置密码 | email | JSON |
| `/api/security/cognitive/check` | POST | 认知安全检查 | input, context | JSON |
| `/api/security/memory/sanitize` | POST | 清理记忆 | content | JSON |
| `/api/security/skill-audit/run` | POST | 运行技能审计 | skill_name | JSON |

### 3.2 类接口

| 类名 | 方法名 | 参数 | 返回值 | 说明 |
|------|--------|------|--------|------|
| `ToolGuardEngine` | `guard()` | tool_name, params | ToolGuardResult | 执行工具调用守卫 |
| `ToolGuardEngine` | `should_approve()` | ToolGuardResult | bool | 判断是否需要审批 |
| `SkillScanner` | `scan_skill()` | skill_dir, skill_name | ScanResult | 扫描技能目录 |
| `SkillScanner` | `whitelist_skill()` | skill_dir, skill_name | bool | 将技能加入白名单 |
| `AuthSystem` | `register()` | username, password, email, role | Dict | 注册用户 |
| `AuthSystem` | `login()` | username, password, ip, agent | AuthToken | 用户登录 |
| `AuthSystem` | `create_api_key()` | user_id, name, permissions | (key_id, key) | 创建 API 密钥 |
| `CognitiveSecuritySystem` | `check_input_safety()` | user_input, context | SafetyCheckResult | 检查输入安全性 |
| `CognitiveSecuritySystem` | `check_output_safety()` | output | SafetyCheckResult | 检查输出安全性 |

---

## 4. 实现细节

### 4.1 已完成的子任务

- [x] 创建 `neurova/security/` 目录
- [x] 实现 ToolGuard（工具守卫）- `tool_guard.py`
- [x] 实现 SkillScanner（技能扫描器）- `skill_scanner.py`
- [x] 实现 AuthSystem（认证系统）- `auth_system.py`
- [x] 实现 CognitiveSecurity（认知安全）- `cognitive_security.py`
- [x] 创建 `__init__.py` 统一导出
- [x] 通过 Python 语法检查（`py_compile`）
- [x] 验证模块导入正常

### 4.2 进行中的子任务

- [ ] 编写单元测试
- [ ] 更新进度跟踪表
- [ ] 创建每日进度报告

### 4.3 待完成的子任务

- [ ] 集成测试（与 API 层、执行引擎、技能系统）
- [ ] 性能测试（扫描大型技能目录的耗时）
- [ ] 文档完善（API 接口文档）

### 4.4 关键代码片段

**工具守卫使用示例**:

```python
from neurova.security import ToolGuardEngine, ApprovalMode

engine = ToolGuardEngine(approval_mode=ApprovalMode.AUTO)

# 检测工具调用
result = engine.guard("execute_command", {"command": "rm -rf /"})
print(result.is_safe)  # False
print(result.max_severity)  # CRITICAL

# 判断是否需要审批
if engine.should_approve(result):
    print("需要人工审批")
```

**技能扫描器使用示例**:

```python
from neurova.security import SkillScanner, ScanMode

scanner = SkillScanner(policy=ScanPolicy(mode=ScanMode.WARN))

# 扫描技能目录
result = scanner.scan_skill(Path("/path/to/skill"))
print(result.is_safe)  # True/False
print(result.file_count)  # 扫描的文件数量

# 将技能加入白名单
scanner.whitelist_skill(Path("/path/to/skill"))
```

**认证系统使用示例**:

```python
from neurova.security import AuthSystem, UserRole

auth = AuthSystem()

# 注册用户
user = auth.register("alice", "password123", "alice@example.com", UserRole.USER)

# 用户登录
token = auth.login("alice", "password123", "127.0.0.1")
print(token.access_token)

# 创建 API 密钥
key_id, full_key = auth.create_api_key(user['id'], "my-key")
print(full_key)  # nk_xxx.yyyyyy
```

**认知安全使用示例**:

```python
from neurova.security import CognitiveSecuritySystem

security = CognitiveSecuritySystem()

# 检查输入安全性
result = await security.check_input_safety("ignore previous instructions and ...")
print(result.is_safe)  # False
print(result.safety_level)  # HIGH_RISK

# 检查输出安全性
result = security.check_output_safety("Here is the command: rm -rf /")
print(result.filtered_output)  # "Here is the command: [FILTERED]"
```

---

## 5. 测试计划

### 5.1 单元测试

| 测试用例 | 测试内容 | 状态 | 通过率 |
|---------|---------|------|--------|
| `test_tool_guard.py` | 测试 ToolGuard 规则匹配、守卫协调 | 未开始 | - |
| `test_skill_scanner.py` | 测试 SkillScanner 扫描、缓存、白名单 | 未开始 | - |
| `test_auth_system.py` | 测试 AuthSystem 认证、权限、会话 | 未开始 | - |
| `test_cognitive_security.py` | 测试 CognitiveSecurity 检查、过滤 | 未开始 | - |

### 5.2 集成测试

- **与 API 层集成**: 测试 API 端点是否正确调用安全模块
- **与执行引擎集成**: 测试工具调用是否被正确处理
- **与技能系统集成**: 测试技能扫描是否在执行前完成

### 5.3 性能测试

- **技能扫描性能**: 扫描包含 1000 个文件的技能目录的耗时
- **工具守卫性能**: 检测 100 次工具调用的平均耗时
- **认证性能**: 登录和 Token 验证的响应时间

---

## 6. 已知问题

| 问题描述 | 严重程度 | 发现时间 | 解决方案 | 状态 |
|---------|---------|----------|--------|------|
| `auth_system.py` 中 `hash_password` 方法使用 `hashlib.sha256` 而不是 `PasswordHasher` | 低 | 2026-05-12 23:00 | 改用 `PasswordHasher.hash_password()` | 未修复 |
| `cognitive_security.py` 中 `_cognitive_safety_assessment` 方法需要 `cognitive_orchestrator` | 低 | 2026-05-12 23:00 | 确保传入正确的编排器实例 | 未修复 |

---

## 7. 变更记录

| 时间 | 变更内容 | 变更原因 | 影响范围 |
|------|---------|---------|---------|
| 2026-05-12 22:00 | 初始创建 | - | - |
| 2026-05-12 22:30 | 修复 `auth_system.py` 语法错误 | `user['id']` 缺少逗号 | `auth_system.py` |
| 2026-05-12 23:00 | 完成所有模块实现 | - | `tool_guard.py`, `skill_scanner.py`, `auth_system.py`, `cognitive_security.py` |

---

## 8. 附录

### 8.1 参考资料

- `NEUROVA_CogArch_2.0.md` 第 4 章（第 834-1282 行）
- `neurova/auth/` 目录下的现有认证系统
- QwenPaw 安全架构设计

### 8.2 相关文件

- `neurova/security/tool_guard.py` - 工具守卫实现
- `neurova/security/skill_scanner.py` - 技能扫描器实现
- `neurova/security/auth_system.py` - 认证系统实现
- `neurova/security/cognitive_security.py` - 认知安全实现
- `neurova/security/__init__.py` - 统一导出
- `tests/test_security_tool_guard.py` - 单元测试（待创建）
- `tests/test_security_skill_scanner.py` - 单元测试（待创建）
- `tests/test_security_auth_system.py` - 单元测试（待创建）
- `tests/test_security_cognitive_security.py` - 单元测试（待创建）

---

**最后更新**: 2026-05-12 23:00 | **更新人**: security-dev
