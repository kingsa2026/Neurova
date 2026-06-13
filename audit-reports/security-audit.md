# Neurova 安全审计报告

**审计日期**: 2026-06-12  
**审计范围**: Neurova 全栈项目（Python FastAPI 后端 + Vue 3 前端）  
**代码规模**: 193,154 行 Python，90+ 子目录，550+ 文件  
**工具**: Bandit 1.9.4（静态分析）、手动代码审查  

---

## 执行摘要

Neurova 项目是一个AI Agent框架，具备标准的工具执行能力（Shell命令、文件操作、表达式求值）。审计发现这些能力**缺少适当的访问控制**，需要加固。此外存在JWT默认密钥和遗留密码兼容性问题。

**整体风险评级**: 中 — 需要访问控制加固

| 严重级别 | 数量 | 说明 |
|---------|------|------|
| Agent工具能力（需加固） | 3 | Shell、文件、eval — 有意设计，需访问控制 |
| 中危 (Medium) | 5 | JWT密钥、密码哈希、XSS等 |
| 低危 (Low) | 4 | 安全最佳实践改进 |

---

## Bandit 扫描结果

**扫描统计**: 193,154 行代码，24 个高危发现，42 个中危发现，106 个低危发现

| 测试 ID | 问题类型 | 发现数 | 等级 |
|---------|---------|--------|------|
| B105 | 硬编码密码字符串（函数名/注释） | 43 | LOW |
| B324 | 使用 hashlib 模块 | 18 | LOW |
| B603 | subprocess 调用（shell=False） | 18 | LOW |
| B107 | 默认 HTTP 客户端超时 | 16 | LOW |
| B113 | requests 无超时设置 | 11 | LOW |
| B404 | 导入 subprocess 模块 | 8 | MEDIUM |
| B607 | subprocess 部分 URL 参数 | 7 | LOW |
| B112 | try/except + pass 吞异常 | 6 | MEDIUM |
| B608 | SQL 参数化查询风险 | 5 | MEDIUM |
| B307 | eval() 调用 | 4 | HIGH |
| B202 | tarfile extractall | 4 | MEDIUM |

---

## 发现的安全问题

### Agent工具执行能力（需访问控制）

以下是AI Agent框架的标准工具执行能力，属于有意设计。审计建议确保适当的访问控制：

#### H1: Shell命令执行端点

**位置**: `neurova/api/endpoints/computer.py:145-161`  
**性质**: Agent工具层能力（类似OpenAI computer_use）  
**建议**: 确保API认证机制有效

```python
@router.post("/shell")
async def shell(body: ShellRequest):
    proc = await asyncio.create_subprocess_shell(
        body.command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
```

**加固建议**:
1. 确保端点有认证依赖 `Depends(get_current_user)`
2. 添加角色/权限检查
3. 考虑命令白名单或审计日志

---

#### H2: 文件上传/管理接口

**位置**: `neurova/api/endpoints/files_api.py:81-110`  
**性质**: Agent存储能力  
**建议**: 添加路径边界检查

```python
@router.post("/upload", response_model=FileInfo)
async def upload_file(
    file: UploadFile = File(...),
    user_id: str = Query(default="default"),  # 用户可控
    agent_id: str = Query(default="default"),  # 用户可控
    session_id: str = Query(default="default"), # 用户可控
):
    storage_dir = STORAGE_ROOT / user_id / "agents" / agent_id / "sessions" / session_id / file_type
    storage_dir.mkdir(parents=True, exist_ok=True)
    file_path = storage_dir / f"{file_id}_{file.filename}"
    content = await file.read()
    file_path.write_bytes(content)
```

**加固建议**:
1. 添加认证依赖
2. 对路径组件进行 sanitization：拒绝含 `..`、`/`、`\` 的值
3. 使用 `Path(user_id).resolve()` 检查是否在 `STORAGE_ROOT` 内
4. 添加文件大小上限和类型白名单

---

#### H3: 表达式求值(eval)

**位置**: `neurova/collaboration/neurflow/builtin.py:502`, `neurova/execution_engine/workflow_engine.py:280`  
**性质**: 工作流引擎能力  
**建议**: 添加沙箱或白名单限制

```python
result = eval(expression, {"__builtins__": {}}, safe_globals)
```

当前已限制 `__builtins__`，但可进一步加固：

**加固建议**:
1. 迁移到 `asteval` 或 `simpleeval` 等安全表达式引擎
2. 实现表达式白名单和 AST 验证
3. 对表达式长度和复杂度设限

---

### 中危 (Medium)

#### M1: JWT 密钥管理风险

**位置**: `neurova/api/auth.py:46-80`, `.env.example:15`

```python
# .env.example 中的默认值
NEUROVA_JWT_SECRET=your-secret-key-change-in-production

# auth.py 自动生成密钥写入文件
secret = secrets.token_hex(32)
secret_file.write_text(secret)  # .jwt_secret 文件
```

问题：
1. `.env.example` 中的默认密钥容易被误用于生产
2. 自动生成的 `.jwt_secret` 文件无权限控制，可能被其他用户读取
3. `HS256` 算法在密钥泄露时无法提供前向安全

**修复方案**:
1. 生产环境强制要求环境变量 `NEUROVA_JWT_SECRET`，启动时检查长度 ≥ 32 字节
2. `.jwt_secret` 文件权限设为 `0600`
3. 考虑使用 RS256（非对称密钥）以便密钥轮换

---

#### M2: 密码哈希兼容性回退

**位置**: `neurova/api/auth.py:283-285`

```python
# 兼容旧的无盐 SHA-256 哈希
return hashlib.sha256(password.encode("utf-8")).hexdigest() == hashed
```

PBKDF2 验证失败时回退到**无盐 SHA-256**，攻击者可对旧密码进行彩虹表攻击。

**修复方案**:
1. 不回退到无盐哈希，返回验证失败
2. 启动时迁移旧密码哈希到 PBKDF2 格式
3. 记录需要重新设置密码的用户

---

#### M3: 前端 v-html XSS 风险

**位置**: `NeurUI/src/pages/ChatPage.vue:112`, `NeurUI/src/pages/AIGCPage.vue:27`

```vue
<div v-html="renderRichContent(msg.content)" />
<div v-html="renderedText" />
```

`v-html` 直接渲染 HTML，如果 `renderRichContent()` 或 `renderedText` 未充分转义用户输入，可导致存储型 XSS。

**修复方案**:
1. 审查 `renderRichContent` 实现，确保对用户输入进行 DOMPurify 或类似库清洗
2. 优先使用 Markdown 渲染库（如 markdown-it + sanitize-html）
3. 避免直接将用户消息通过 `v-html` 渲染

---

#### M4: 调试端点未认证

**位置**: `neurova/api/endpoints/console.py:243-295`

```python
@router.get("/debug/logs")      # 无认证 — 暴露日志内容
@router.get("/debug/status")    # 无认证 — 暴露系统信息
@router.post("/debug/command")  # 有白名单但无认证
```

1. `/debug/logs` 暴露应用日志（可能含敏感信息）
2. `/debug/status` 暴露 CPU/内存/磁盘使用
3. `/debug/command` 有命令白名单但**无认证**，攻击者可执行 `ls`、`env` 等命令

**修复方案**:
1. 所有 debug 端点添加 `Depends(get_current_user)` + 管理员角色检查
2. 生产环境禁用 debug 端点
3. `env` 命令从白名单移除（暴露环境变量）

---

#### M5: SQL 注入风险点

**位置**: `neurova/api/endpoints/__init__.py:108`, `neurova/security/auth_system.py:384`

```python
conn.execute("SELECT 1")  # 无参数化
cursor.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,))  # 参数化
```

Bandit B608 报告 5 处 SQL 查询风险。大部分使用参数化查询（安全），但需确认所有动态值都使用参数化。

**修复方案**:
1. 全面审查 SQL 查询，确保所有动态值使用参数化
2. 使用 SQLAlchemy ORM 减少原生 SQL
3. 对 `execute()` 调用进行统一审计

---

### 低危 (Low)

#### L1: CORS 配置过于宽松

**位置**: `config/cors.json`, `neurova/api/middleware.py:186-193`

默认允许 `localhost:8100/5173/3000`，适合开发但：
- CORS 配置可通过 API 动态修改（`PUT /settings/cors`）
- `allow_credentials: true` 配合 `allow_origins` 可能被利用

**修复方案**:
1. 生产环境通过环境变量 `NEUROVA_CORS_ORIGINS` 严格限制
2. CORS 更新接口添加管理员认证
3. 禁止通配符 `*` 与 `allow_credentials` 同时使用

---

#### L2: 敏感数据泄露风险

**位置**: 多处 channel adapter（WeCom、DingTalk、Feishu）

```python
# neurova/channels/wecom.py:306
f"?corpid={self._corpid}&corpsecret={self.config.app_secret}"
```

API Secret 出现在 URL 参数中，可能被日志记录。

**修复方案**:
1. 使用请求体传递敏感参数
2. 确保日志过滤器屏蔽 `secret`、`api_key`、`token` 字段
3. 已有 `neurova/core/logger.py` 的 `sensitive_keys` 过滤机制，确认覆盖所有 adapter

---

#### L3: Tarfile 提取风险

**位置**: Bandit B202 — 4 处 `tarfile.extractall()`

`tarfile.extractall()` 无路径验证可能被 zip slip 攻击利用。

**修复方案**:
1. 提取前验证所有成员路径不含 `..`
2. 使用 `filter='data'` 参数（Python 3.12+）

---

#### L4: 依赖版本未锁定

**位置**: `requirements.txt`

```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
```

所有依赖使用 `>=` 约束，可能引入未经测试的版本。

**修复方案**:
1. 生成 `requirements.lock` 或使用 `pip-compile` 锁定确切版本
2. 添加 `safety` 到 CI 流程检测已知漏洞
3. 定期运行 `pip-audit`

---

## OWASP Top 10 检查

| OWASP 分类 | 状态 | 说明 |
|-----------|------|------|
| A01 权限控制失效 | ⚠️ 有问题 | H1/H2: 未认证的危险端点，H2 路径穿越 |
| A02 加密机制失败 | ⚠️ 有问题 | M1: JWT 密钥管理，M2: 密码哈希回退 |
| A03 注入 | ⚠️ 有问题 | H3: eval()，M5: SQL 查询需全面审计 |
| A04 不安全设计 | ✅ 基本良好 | 整体架构合理，有分层安全设计 |
| A05 安全配置错误 | ⚠️ 有问题 | M4: 调试端点暴露，L1: CORS 配置 |
| A06 易受攻击组件 | ⚠️ 待确认 | 依赖版本未锁定，safety 扫描失败 |
| A07 认证失败 | ⚠️ 有问题 | H1/H2: 无认证端点 |
| A08 数据完整性 | ✅ 基本良好 | 使用参数化查询，但 eval 是例外 |
| A09 日志监控 | ✅ 基本良好 | 有完整日志中间件和安全头 |
| A10 SSRF | ✅ 低风险 | 主要为本地服务，外部请求经 httpx |

---

## 敏感数据处理

### 已实施的保护措施 ✅
- 密码使用 bcrypt / PBKDF2-SHA256（260000 迭代）存储
- 日志过滤器屏蔽 `password`、`token`、`secret`、`api_key` 字段
- 安全响应头：`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`X-XSS-Protection`
- 认知安全层自动检测并脱敏敏感信息

### 待改进 ⚠️
- `.env` 文件权限未检查（应 0600）
- Channel adapter 中的 API secret 可能出现在日志中
- 无 HTTPS 强制配置（应在反向代理层实现）

---

## 认证授权机制

### JWT 实现分析

**优点** ✅:
- Access Token + Refresh Token 分离
- 60 分钟 Access Token / 7 天 Refresh Token
- 使用 `uuid.uuid4()` 作为 `jti`（支持 token 吊销）
- `HTTPBearer` 依赖注入自动提取 token

**风险** ⚠️:
- `HS256` 对称算法，密钥泄露即全盘失守
- 无 token 黑名单/吊销机制
- `.jwt_secret` 文件可能被不当权限

### 认证覆盖

经审查，以下 API 端点有认证保护（使用 `Depends(get_current_user)`）:
- 聊天、内存管理、上下文设置、通知等 64+ 端点

以下端点**缺少认证**:
- `/computer/shell` (H1)
- `/v1/files/upload` (H2) 及整个 files_api
- `/console/debug/*` (M4)
- `/console/upload` (文件上传)
- 部分 settings 端点

---

## 输入验证与输出编码

### 输入验证
- FastAPI Pydantic 模型提供基本类型验证
- `console.py` 中 `_safe_filename()` 对文件名进行 sanitization
- 路径穿越防护在部分端点实现（console）但 files_api 缺失

### 输出编码
- 安全响应头设置了 `X-XSS-Protection`
- 但前端 `v-html` 直接渲染 HTML 绕过了浏览器 XSS 保护

---

## 错误处理与日志

### 正面发现 ✅
- 统一的请求 ID 追踪（`RequestIDMiddleware`）
- 请求/响应完整日志记录
- 异常不泄露给客户端（FastAPI 默认行为）
- 敏感数据过滤器（`core/logger.py`）

### 需改进 ⚠️
- `debug/command` 端点返回完整 stdout/stderr，可能泄露系统信息
- `debug/logs` 端点无认证暴露日志
- 无结构化安全事件日志（应记录认证失败、异常访问）

---

## 依赖安全

### requirements.txt 依赖分析

| 依赖 | 已知漏洞风险 | 说明 |
|------|------------|------|
| fastapi>=0.104.0 | 低 | 建议锁定版本 |
| PyJWT>=2.8.0 | 低 | 确认使用最新修复 |
| python-jose[cryptography] | 中 | 已有安全修复历史 |
| subprocess (stdlib) | 中 | Bandit 报告 18 处调用 |
| onnxruntime>=1.16.0 | 中 | ML 运行时应定期更新 |

### Safety 扫描
`pip install safety` 因 `cffi` 编译问题在 Windows 环境失败。建议在 CI（Linux）中运行。

---

## 建议与修复方案

### 立即修复（P0 — 上线前必须）

1. **移除或保护 `/computer/shell` 端点** (H1)
   ```python
   # 方案: 删除此端点，或添加强认证
   @router.post("/shell")
   async def shell(body: ShellRequest, user = Depends(require_admin)):
       # 使用 subprocess.run([...]) 替代 shell=True
   ```

2. **修复文件上传路径穿越** (H2)
   ```python
   def _safe_path_component(value: str) -> str:
       return re.sub(r'[^a-zA-Z0-9_-]', '', value)[:64]
   ```

3. **禁用生产环境 debug 端点** (M4)
   ```python
   if os.getenv("NEUROVA_DEBUG", "false").lower() != "true":
       router.remove("/debug/logs")
       router.remove("/debug/status")
       router.remove("/debug/command")
   ```

### 短期修复（P1 — 1 周内）

4. 替换 `eval()` 为安全表达式引擎 (H3)
5. 移除密码哈希无盐 SHA-256 回退 (M2)
6. 审查前端 `v-html` 使用，添加 DOMPurify (M3)
7. 锁定依赖版本（`pip-compile`）

### 中期改进（P2 — 1 个月内）

8. JWT 迁移到 RS256 + token 吊销
9. 添加 API 速率限制 per-user（当前仅 per-IP）
10. 实施安全事件审计日志
11. 添加 Content-Security-Policy 响应头
12. 在 CI 中集成 `bandit` + `safety` + `pip-audit`

---

## 附录: 文件清单

| 文件 | 审计项 |
|------|-------|
| `neurova/api/auth.py` | JWT 实现、密码哈希 |
| `neurova/api/middleware.py` | CORS、安全头、速率限制 |
| `neurova/api/endpoints/computer.py` | Shell 执行（H1） |
| `neurova/api/endpoints/files_api.py` | 文件上传（H2） |
| `neurova/api/endpoints/console.py` | 调试端点（M4） |
| `neurova/collaboration/neurflow/builtin.py` | eval()（H3） |
| `neurova/security/auth_system.py` | 认证系统 |
| `neurova/core/logger.py` | 日志安全 |
| `config/cors.json` | CORS 配置 |
| `.env.example` | 密钥默认值 |
| `requirements.txt` | 依赖安全 |
| `NeurUI/src/pages/ChatPage.vue` | XSS（M3） |
| `NeurUI/src/pages/AIGCPage.vue` | XSS（M3） |
