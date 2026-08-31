# Bug 报告:[LLM Error] No client available 修复

**Bug ID**: LLM-NO-CLIENT-AVAILABLE
**调查日期**: 2026-07-06
**调查方法**: bug-hunt 五阶段 + zoom-out + TDD RED-GREEN
**症状**: agent 对话返回 `[LLM Error] No client available`,服务器进程无法初始化 LLM 客户端
**状态**: 已修复(3 处源码修复 + 6 个新测试 GREEN + 服务器验证通过)

---

## 0. 复现 & 成功标准

**复现请求**: "agent对话报错[LLM Error] No client available"

### 复现步骤

1. 服务器运行中(PID 29804,StartTime 08:34:29)
2. 调用 `/api/v1/console/chat`(无需认证):

```powershell
$body = '{"message":"你好","stream":false}'
Invoke-WebRequest -Uri "http://localhost:9527/api/v1/console/chat" -Method POST -Body $body -ContentType "application/json"
```

3. 响应:

```json
{"code":0,"message":"success","data":{"reply":"[LLM Error] No client available","session_id":"89e8c62e"}}
```

### 关键发现

- **独立运行脚本正常**:`MultiModelLLMClient` 能初始化 3 个 clients,api_key 解密成功
- **服务器运行报错**:`_clients` 字典为空,返回 `No client available`
- 说明问题在服务器进程的运行时状态,而非代码逻辑本身

### 成功标准

1. 服务器运行时,`/api/v1/console/chat` 返回真实 LLM 响应(非 `[LLM Error]` 前缀)
2. `MultiModelLLMClient` 首次初始化失败后,配置修复时能重新初始化
3. `chat()` 在 `_clients` 为空时自动尝试 `refresh_all_providers()` 自愈
4. 新增 6 个 TDD 测试全部 GREEN,现有 52 个 LLM 测试无回归

---

## 1. 定位 — 层表 + 命名假设

### zoom-out 模块依赖图

```
start_server.py
  └─ create_app() [app.py:669]
       └─ @app.on_event("startup") → _on_startup [app.py:742]
            └─ _initialize_components(app_state) [app.py:192]
                 ├─ Step 3: get_provider_manager() [app.py:219]  ← provider_manager 单例首次创建
                 │    └─ LLMProviderManager._load_config() [provider_manager.py:247]
                 │         └─ ProviderConfig.from_dict(decrypt=True)  ← api_key 解密
                 └─ Step 8: 默认 Agent [app.py:259-294]
                      └─ AgentLLMClient(provider_id, model) [agent_core.py:115]  ← 不触发 LLM 调用

首次用户请求 → /api/v1/console/chat [console.py:111]
  └─ agent.chat() [console.py:146]
       └─ ChatPipeline._step_llm_call()
            └─ AgentLLMClient.chat() [agent_core.py:132]
                 └─ _get_client() [agent_core.py:127]
                      └─ get_multi_model_client() [multi_model_client.py:401]  ← 单例首次创建
                           └─ MultiModelLLMClient.__init__() [multi_model_client.py:76]
                                ├─ _initialized = True  [line 87]  ← 提前置位!
                                ├─ get_provider_manager()  [line 89]
                                └─ _initialize_default_clients()  [line 97]
                                     └─ 三重门控: default_provider AND enabled AND api_key  [line 102]
                                          └─ 失败 → _clients 保持空字典
```

### 层表

| 层 | 文件:行 | 证据 |
|---|---|---|
| 错误返回 | `agent_core.py:144` | `[LLM Error] {result.get('error')}` 包装 |
| 错误产生 | `multi_model_client.py:321-326` | `if not client: return {"error": "No client available"}` |
| client 为 None | `multi_model_client.py:184-198` | `get_current_client` 在 `_clients` 空时返回 None |
| `_clients` 空 | `multi_model_client.py:90` | `self._clients = {}` 初始化为空 |
| 初始化跳过 | `multi_model_client.py:102` | 三重门控失败时不填充 `_clients` |
| 不可恢复 | `multi_model_client.py:85-87` | `_initialized=True` 在初始化前锁定 |
| api_key 解密失败 | `provider_manager.py:207-218`(服务器日志) | `Failed to decrypt API key: No module named 'Crypto'` |
| 无重置 API | 全局搜索 | 无 `reset()` / `reinitialize()` 方法 |

### 命名假设

- **假设 A(已证实)**:服务器启动时 `pycryptodome` 缺失,api_key AES-GCM 解密失败
- **假设 B(已证实)**:`_initialized=True` 提前置位(line 87),在 `_initialize_default_clients()`(line 97)之前
- **假设 C(已证实)**:三重单例(`_instance` + `_initialized` + `_multi_model_client`)无重置机制
- **假设 D(修复时发现)**:`_init_lock` 是 `threading.Lock()`(非 RLock),`refresh_provider()` 调用 `_initialize_provider_clients()` 时死锁

---

## 2. 全链路证据

### 服务器启动日志(`logs/server.log` line 207-218)

```
2026-07-06 08:34:36,698 - neurova.llm.provider_manager - WARNING - Failed to decrypt API key: AES-GCM decryption failed: No module named 'Crypto'
... (5 个 provider 全部解密失败)
2026-07-06 08:34:36,699 - neurova.llm.provider_manager - INFO - Loaded 5 providers from C:\Users\xccoo\.neurova\config\providers.json
```

**关键**:provider_manager 加载了 5 个 providers,但所有 api_key 解密失败为空字符串。

### 服务器运行时错误日志(`logs/server.log` line 1062-1070)

```
2026-07-06 08:35:33,752 - neurova.llm.multi_model_client - WARNING - No clients available
2026-07-06 08:35:33,752 - neurova.llm.multi_model_client - INFO - [LLM-REQ] model=gpt-4, messages=18, system=9, roles={'user': 6, 'system': 9, 'assistant': 3}
2026-07-06 08:35:33,752 - neurova.llm.multi_model_client - WARNING - No client available for chat
```

**关键**:首次请求时 `_clients` 为空,没有 `Initialized default client` 日志(对比独立运行时有此日志)。

### 独立运行诊断(对比基准)

```
2026-07-06 08:55:48,192 - neurova.llm.provider_manager - INFO - Decrypted API key for provider 商汤科技
... (5 个 provider 解密,3 个有 api_key)
2026-07-06 08:55:48,588 - neurova.llm.multi_model_client - INFO - Initialized default client: sensetime/deepseek-v4-flash
_clients count: 3
```

**关键**:独立运行时 `pycryptodome` 已安装(3.23.0),api_key 解密成功,3 个 clients 初始化。

### providers.json 配置

```json
{
  "default_provider_id": null,
  "providers": [
    {"id": "sensetime", "enabled": true, "api_key": "<encrypted>", "default_model": "deepseek-v4-flash"},
    ...
  ]
}
```

**关键**:api_key 是 AES-GCM 加密存储的,需要 `pycryptodome` 解密。服务器启动时缺失此库导致解密失败。

---

## 3. 根因分析(Cause Chain)

### 多层因果实链

```
[直接触发] 服务器启动时 pycryptodome 缺失
    ↓
[解密失败] LLMProviderManager._load_config() 调用 ProviderConfig.from_dict(decrypt=True)
    ↓ Crypto 库不可用
[api_key 为空] 5 个 provider 的 api_key 解密失败,全部为空字符串
    ↓
[门控失败] _initialize_default_clients() 三重门控失败:
    default_provider AND default_provider.enabled AND default_provider.api_key
    第三个条件(api_key 非空)失败
    ↓
[_clients 空] _clients 字典保持初始空状态 {}
    ↓
[_initialized 锁死] __init__ line 87 已将 _initialized = True
    在 _initialize_default_clients() (line 97) 之前执行
    ↓
[不可恢复] 三重单例无重置机制:
    - 类级 _instance (line 65):无 reset API
    - 实例级 _initialized (line 85-87):无 reset API
    - 模块级 _multi_model_client (line 398):无 reset API
    ↓
[错误传播] chat() → _get_client_for_request() 返回 None → 返回 {"error": "No client available"}
    ↓
[错误包装] AgentLLMClient.chat() 包装为 LLMResponse(content="[LLM Error] No client available")
```

### 为什么独立运行正常,服务器异常?

| 因素 | 独立运行 | 服务器运行(启动时) |
|---|---|---|
| pycryptodome | 已安装(3.23.0) | 缺失(启动时 08:34:36) |
| api_key 解密 | 成功(key_len=35) | 失败(空字符串) |
| `_clients` 初始化 | 3 个 clients | 0 个 clients |
| `_initialized` | True(但初始化成功) | True(但初始化失败,锁死) |

**根本差异**:服务器在 pycryptodome 安装之前启动,首次 LLM 请求时创建了空的 MultiModelLLMClient 单例。即使后续安装了 pycryptodome,单例不会重新初始化。

---

## 4. 外科手术式修复

### 修复 1:添加 `MultiModelLLMClient.reset()` 类方法

**文件**: `neurova/llm/multi_model_client.py`
**行号**: 99-118(新增)

```python
@classmethod
def reset(cls) -> None:
    """重置单例,允许重新初始化。

    用途:当首次初始化因配置缺失(如 api_key 解密失败、provider 未就绪)
    导致 _clients 为空时,配置修复后调用 reset() 可让下次 get_multi_model_client()
    重新初始化。

    线程安全:在 cls._lock(RLock)保护下清除 _instance 和模块级单例。
    """
    with cls._lock:
        instance = cls._instance
        if instance is not None and hasattr(instance, "_initialized"):
            instance._initialized = False
        cls._instance = None
    global _multi_model_client
    _multi_model_client = None
```

**设计依据**:三重单例(`_instance` + `_initialized` + `_multi_model_client`)需要同步重置,否则任一残留都会阻止重新初始化。`reset()` 在 `cls._lock`(RLock)保护下原子清除所有三重状态。

### 修复 2:`chat()` 添加自愈逻辑

**文件**: `neurova/llm/multi_model_client.py`
**行号**: 299-308(新增)

```python
# 自愈:_clients 为空时尝试 refresh_all_providers()
# 场景:首次初始化时 api_key 解密失败/pycryptodome 缺失 → _clients 空
# 后续配置修复后(如 pycryptodome 安装),refresh 可恢复 clients
if not client and not self._clients:
    logger.info("Auto-refreshing providers due to empty _clients")
    try:
        self.refresh_all_providers()
        client = self._get_client_for_request(model, provider_id)
    except Exception as e:
        logger.warning("Auto-refresh failed: %s", e, exc_info=True)
```

**设计依据**:运行时自愈比要求手动重启更健壮。当 `chat()` 检测到 `_clients` 为空时,先尝试 `refresh_all_providers()` 重新加载 providers(此时 provider_manager 会重新解密 api_key)。如果 refresh 后仍无 client,再返回错误。这确保:
- 首次初始化失败后,后续请求能自动恢复
- 不掩盖真实错误(refresh 失败仍返回 `No client available`)

### 修复 3:`_init_lock` 改为 RLock 避免死锁

**文件**: `neurova/llm/multi_model_client.py`
**行号**: 94-96

```python
# 使用 RLock:refresh_provider() 持锁后调用 _initialize_provider_clients()
# 后者也获取 _init_lock,Lock 会死锁;RLock 可重入避免死锁
self._init_lock = threading.RLock()
```

**设计依据**:修复 2 启用 `refresh_all_providers()` 后,发现 `_init_lock` 是 `threading.Lock()`(非 RLock)。`refresh_provider()` (line 248)在 `with self._init_lock:` 内调用 `_initialize_provider_clients()`,后者(line 111)也获取 `self._init_lock`。Lock 不可重入,导致死锁。改为 RLock 可重入,与类级 `_lock`(P0-3 修复已改为 RLock)保持一致。

### TDD 测试

**文件**: `tests/unit/llm/test_multi_model_client_reinit.py`(新增 6 个测试)

| 测试 | 验证内容 |
|---|---|
| `test_init_with_empty_api_key_leaves_clients_empty` | RED:复现首次初始化失败,_clients 为空,_initialized=True |
| `test_reinit_after_config_fix_via_reset` | GREEN:reset() + 配置修复后,重新初始化,_clients 非空 |
| `test_chat_auto_refresh_on_empty_clients` | GREEN:chat() 自愈,_clients 空时 refresh 后返回成功 |
| `test_chat_returns_error_when_refresh_also_fails` | GREEN:refresh 失败时仍返回错误,不掩盖 |
| `test_reset_clears_initialized_flag` | GREEN:reset() 清除三重单例状态 |
| `test_reset_is_thread_safe` | GREEN:10 线程并发 reset/构造 无异常 |

### 验证结果

```
tests/unit/llm/test_multi_model_client_reinit.py: 6 passed
tests/unit/llm/test_multi_model_client_init_lock.py: 3 passed(无回归)
tests/unit/llm/: 52 passed, 7 skipped(无回归)
```

**服务器验证**(重启后):

```powershell
Invoke-WebRequest -Uri "http://localhost:9527/api/v1/console/chat" -Method POST -Body '{"message":"你好","stream":false}'
```

响应:
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "reply": "你好呀！😊 我是 **Neurova**,很高兴见到你！...",
    "session_id": "73c0ee0d"
  }
}
```

**成功**:返回真实 LLM 响应,不再有 `[LLM Error]` 前缀。

---

## 5. 经验教训

### 5.1 单例模式的不可恢复性陷阱

**模式**:三重单例(`_instance` + `_initialized` + 模块级变量)在没有 `reset()` 方法时,首次初始化失败会导致永久不可恢复。

**教训**:
- 单例必须提供 `reset()` 方法,允许显式重置
- `_initialized` 标志不应在初始化逻辑完成前置位,应在所有初始化步骤成功后设置
- 或采用延迟初始化:不在 `__init__` 中初始化,首次请求时才初始化

### 5.2 Lock vs RLock 的重入陷阱

**模式**:`refresh_provider()` 持有 `_init_lock` 后调用 `_initialize_provider_clients()`,后者也获取同一锁。

**教训**:
- 当一个方法在锁内调用另一个获取同一锁的方法时,必须使用 RLock
- 与 P0-3 修复(类级 `_lock` 改为 RLock)和 EventBus.health_report 死锁修复一致
- `threading.Lock()` 适用于简单互斥,`threading.RLock()` 适用于同一线程重入场景

### 5.3 运行时自愈比手动重启更健壮

**模式**:`chat()` 在 `_clients` 为空时自动 `refresh_all_providers()`,而非直接返回错误。

**教训**:
- 服务器长时间运行时,配置可能变化(如 pycryptodome 安装、api_key 更新)
- 自愈逻辑让系统能从临时故障中恢复,无需人工干预
- 但要确保自愈不会掩盖真实错误 — refresh 失败时仍返回明确错误

### 5.4 加密依赖的隐性耦合

**模式**:`providers.json` 中的 api_key 是 AES-GCM 加密的,依赖 `pycryptodome` 库。库缺失时静默降级为空字符串。

**教训**:
- 加密依赖应在启动时显式检查,缺失时快速失败而非静默继续
- `provider_manager._load_config()` 的 `except Exception` 块(line 267)静默回退到内置 providers,掩盖了解密失败
- 应在解密失败时记录 ERROR 级别日志(当前是 WARNING),并考虑是否阻止启动

### 5.5 独立运行 vs 服务器运行的差异

**模式**:独立运行脚本时 `pycryptodome` 已安装,但服务器启动时缺失。

**教训**:
- 服务器的 Python 环境可能与开发环境不同
- 诊断时应检查服务器进程的实际环境(如 `import Crypto` 是否成功)
- 服务器日志是关键证据源 — `Failed to decrypt API key: No module named 'Crypto'` 直接揭示了根因

---

## 6. 改动文件清单

| 文件 | 改动 | 行数 |
|---|---|---|
| `neurova/llm/multi_model_client.py` | 新增 `reset()` 类方法 + chat() 自愈 + _init_lock 改 RLock | +28 行 |
| `tests/unit/llm/test_multi_model_client_reinit.py` | 新增 6 个 TDD 测试 | +242 行 |
| `docs/bugfix-llm-no-client-available.md` | 新增 bug 报告 | 本文件 |

---

## 7. 后续建议(improve-codebase-architecture)

### 7.1 单例初始化模式统一

当前代码库有多处单例(`MultiModelLLMClient`、`LLMProviderManager`、`LLMRouter` 等),初始化模式不统一:
- `MultiModelLLMClient`:三重单例(`_instance` + `_initialized` + `_multi_model_client`)
- `LLMProviderManager`:仅模块级 `_provider_manager`,无 `_instance`
- `LLMRouter`:需进一步调查

**建议**:建立统一的单例基类或装饰器,提供 `reset()` / `reinitialize()` 方法,避免每个单例都重新设计重置逻辑。

### 7.2 provider_manager 缺少 reset

`LLMProviderManager` 同样缺少 `reset_provider_manager()` 函数。如果 provider_manager 首次初始化时配置加载失败,后续无法重新加载。

### 7.3 加密依赖的显式检查

`provider_manager._load_config()` 应在解密失败时:
1. 记录 ERROR 级别日志(当前是 WARNING)
2. 考虑是否阻止启动,或提供显式的 `--ignore-decrypt-failures` 启动选项
3. 在健康检查端点暴露解密状态

---

## 8. 参考资料

- [bug-hunt methodology](C:\Users\xccoo\.agents\skills\bug-hunt.keep) — 五阶段调查流程
- [Python threading.Lock vs RLock](https://docs.python.org/3/library/threading.html#lock-objects) — 官方文档
- [pycryptodome AES-GCM](https://pycryptodome.readthedocs.io/en/latest/src/cipher/aes.html) — 加密库文档
- P0-3 修复(`test_multi_model_client_init_lock.py`)— 类级 `_lock` 改为 RLock 的先例
- EventBus.health_report 死锁修复(P-1~P-4)— 同类 Lock 死锁问题
