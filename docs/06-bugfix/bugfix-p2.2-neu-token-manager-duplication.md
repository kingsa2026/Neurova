# BUG 跟踪: P2.2 NEUTokenManager 架构重复

> **创建时间**: 2026-06-25
> **创建人**: Agent (TDD + bug-hunt + zoom-out + improve-codebase-architecture)
> **模块**: neurova/security, neurova/auth

---

## 🐛 BUG 基本信息

| 字段 | 内容 |
|------|------|
| **BUG ID** | P2.2-NEUTokenManager-Duplication |
| **标题** | 存在两个 NEUTokenManager 实现，其中一个为死代码 |
| **严重程度** | 🟠 High |
| **优先级** | P2 |
| **状态** | ✅ 已修复 |
| **发现时间** | 2026-06-25 |
| **发现人** | P2.2 架构审计 |
| **负责人** | Agent |
| **影响模块** | neurova/security/neu_token_manager.py, neurova/auth.py (已删除) |
| **影响功能** | 令牌管理、API Key 管理、JWT 签名/验证 |

---

## 📝 BUG 详细描述

### 复现步骤

1. 在项目中搜索 `NEUTokenManager` 类定义
2. 发现两个实现:
   - `neurova/auth.py` (449 行) — HMAC-SHA256 签名, refresh token, 黑名单
   - `neurova/security/neu_token_manager.py` (228 行) — API Key 管理, 简单令牌
3. 尝试 `from neurova.auth import NEUTokenManager` → ImportError
4. 检查 `neurova.auth` 模块路径 → 指向 `neurova/auth/__init__.py` (包), 而非 `neurova/auth.py` (文件)

### 预期行为

项目中应只有一个 `NEUTokenManager` 实现，所有令牌管理功能集中在一个深模块中。

### 实际行为

存在两个 `NEUTokenManager` 实现:
- `neurova/auth.py` 中的实现包含完整的安全特性 (JWT 签名、refresh token、黑名单、线程安全)，但**永远无法被导入** — Python 包优先于同名模块，`neurova/auth/` 目录遮蔽了 `neurova/auth.py` 文件
- `neurova/security/neu_token_manager.py` 中的实现只包含简单令牌和 API Key 管理，缺少 JWT 签名等安全特性

### 错误信息

```
>>> from neurova.auth import NEUTokenManager
ImportError: cannot import name 'NEUTokenManager' from 'neurova.auth'

>>> import neurova.auth
>>> neurova.auth.__file__
'E:\\项目\\Neurova\\neurova\\auth\\__init__.py'  # 包, 而非 auth.py
```

---

## 🔍 根本原因分析

### 根因链 (bug-hunt Phase 4)

```
1. 历史原因: neurova/auth.py 先于 neurova/auth/ 包存在
   ↓
2. 创建 neurova/auth/ 包后, Python 模块查找机制优先匹配包 (auth/__init__.py)
   ↓
3. neurova/auth.py 变成死代码 — 永远无法通过 import 语句访问
   ↓
4. 开发者未察觉 auth.py 已不可达, 继续在其中添加安全特性 (JWT, refresh, 黑名单)
   ↓
5. 另一开发者在 neurova/security/neu_token_manager.py 创建了第二个 NEUTokenManager
   ↓
6. 两个实现功能不重叠:
   - auth.py 独有: generate_tokens, refresh_tokens, is_token_blacklisted,
                  revoke_token_by_jti, cleanup_expired, _sign_jwt_token,
                  _verify_jwt_token, HMAC-SHA256 签名
   - security/ 独有: generate_token, generate_api_key, validate_api_key,
                     revoke_api_key, list_api_keys, cleanup_expired_tokens
   ↓
7. api/app.py 实际依赖 security/neu_token_manager.py (行 249):
   from neurova.security.neu_token_manager import NEUTokenManager
   ↓
8. auth.py 中的安全特性 (JWT 签名等) 完全不可用 — 代码资产流失
```

### zoom-out 视角

调用链分析:
- `api/app.py:249` → `from neurova.security.neu_token_manager import NEUTokenManager` ✅ 可达
- `from neurova.auth import NEUTokenManager` ❌ 永远 ImportError (包遮蔽)
- `auth.py` 只能通过 `importlib.util.spec_from_file_location` 直接加载 (非正常用法)

结论: `neurova/auth.py` 是**完全的死代码**, 其中的安全特性从未被生产代码使用。

---

## 🔧 修复方案

### 方案描述

采用 **合并 + 删除** 策略 (improve-codebase-architecture 深模块原则):

1. **TDD 红**: 先写 33 个测试定义统一接口 (覆盖两个实现的所有功能)
2. **TDD 绿**: 将 auth.py 的安全特性合并到 security/neu_token_manager.py
3. **删除死代码**: 删除 neurova/auth.py
4. **修复受影响测试**: 更新 test_auth_comprehensive.py 中引用已删除 auth.py 的测试

### 修改的文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `neurova/security/neu_token_manager.py` | 重写 | 从 228 行扩展到 554 行, 合并两个实现的所有功能 |
| `neurova/auth.py` | 删除 | 死代码, 被同名包遮蔽, 永远无法导入 |
| `tests/unit/security/test_unified_neu_token_manager.py` | 新建 | 33 个 TDD 测试, 覆盖统一接口 |
| `tests/unit/security/test_auth_comprehensive.py` | 修改 | 删除引用已删除 auth.py 的 2 个测试类 (14 个 ERROR) |
| `scripts/verify_auth_duplication.py` | 创建后删除 | bug-hunt Phase 4 临时仪表化脚本, 已清理 |

### 合并后的统一接口

```python
class NEUTokenManager:
    def __init__(self, secret_key=None, token_expiry_hours=24,
                 access_token_ttl=3600, refresh_token_ttl=604800, issuer="neurova"):
        # 简单令牌存储 + API Key 存储 + JWT 黑名单 + JWT 刷新令牌

    # 简单令牌 (向后兼容 security/ 原有 API)
    def generate_token(self, user_id, metadata=None) -> str
    def validate_token(self, token) -> Optional[Dict]  # 双模式: JWT 优先, 回退简单令牌
    def revoke_token(self, token) -> bool  # 双模式: JWT 优先, 回退简单令牌

    # JWT 签名令牌对 (从 auth.py 合并)
    def generate_tokens(self, user_id, extra_claims=None) -> Tuple[str, str, Dict]
    def refresh_tokens(self, refresh_token) -> Optional[Tuple[str, str, Dict]]

    # 黑名单 (从 auth.py 合并)
    def revoke_token_by_jti(self, jti, expires_at=0) -> bool
    def is_token_blacklisted(self, jti) -> bool

    # JWT 签名工具 (从 auth.py 合并)
    def _sign_jwt_token(self, payload) -> str  # HMAC-SHA256
    def _verify_jwt_token(self, token) -> Optional[Dict]

    # API Key 管理 (向后兼容 security/ 原有 API)
    def generate_api_key(self, user_id, name, scopes=None) -> str
    def validate_api_key(self, api_key) -> Optional[Dict]
    def revoke_api_key(self, api_key) -> bool
    def list_api_keys(self) -> List[Dict]

    # 清理 (合并两者)
    def cleanup_expired_tokens(self) -> int  # 简单令牌
    def cleanup_expired(self) -> int  # 黑名单 + 刷新令牌
```

### 向后兼容性

`api/app.py:249` 的 `NEUTokenManager()` 无参构造继续工作:
```python
from neurova.security.neu_token_manager import NEUTokenManager
app_state.token_manager = NEUTokenManager()  # ✅ 无参构造, 自动生成 secret_key
```

---

## ✅ 验证结果

### 修复后测试

- [x] 原复现步骤不再出现 BUG — `neurova/auth.py` 已删除, 不再有两个实现
- [x] 添加单元测试防止回归 — 33 个测试覆盖统一接口
- [x] 通过所有相关测试 — test_unified_neu_token_manager.py 33/33 PASSED
- [x] 向后兼容验证 — `NEUTokenManager()` 无参构造正常工作
- [x] 死代码清理验证 — `from neurova.auth import NEUTokenManager` 确认 ImportError

### 测试覆盖率

| 测试组 | 测试数 | 状态 |
|--------|--------|------|
| TestBackwardCompatibility | 3 | ✅ 全通过 |
| TestSimpleToken | 4 | ✅ 全通过 |
| TestJWTTokenPair | 6 | ✅ 全通过 |
| TestRefreshToken | 3 | ✅ 全通过 |
| TestBlacklist | 3 | ✅ 全通过 |
| TestAPIKeyManagement | 5 | ✅ 全通过 |
| TestCleanup | 4 | ✅ 全通过 |
| TestThreadSafety | 2 | ✅ 全通过 |
| TestDeadCodeRemoval | 3 | ✅ 全通过 |
| **合计** | **33** | **✅ 33/33 PASSED** |

### 已知预存问题 (不在本次修复范围)

`test_auth_comprehensive.py` 中保留的 `TestPasswordHasher` 和 `TestUserModel` 存在 19 个预存失败:
- `PasswordHasher.hash_password(password)` 被当作类方法调用, 但实际是实例方法 (需要 `self`)
- `PasswordHasher.needs_rehash` 属性不存在
- 这是独立的 PasswordHasher API 不匹配问题, 与 NEUTokenManager 重复无关

---

## 📚 经验教训

1. **Python 包遮蔽陷阱**: 同名包 (`auth/`) 会遮蔽同名模块 (`auth.py`), 导致模块变成死代码。创建包前应检查是否存在同名 `.py` 文件。

2. **死代码的安全风险**: auth.py 中的 JWT 签名、refresh token、黑名单等安全特性从未被使用 — 生产环境实际运行的是缺少这些安全特性的 security/ 实现。这类"安全特性看似存在实则不可达"的问题比显式缺失更危险。

3. **架构重复的检测**: 两个 NEUTokenManager 功能不重叠, 说明它们由不同开发者在不同时间独立创建, 缺乏全局视角。定期架构审计 (zoom-out) 可及早发现。

4. **TDD 合并策略**: 合并两个实现时, 先写覆盖两者所有功能的统一测试 (红), 再实现合并 (绿), 最后删除死代码 — 确保合并过程不丢失任何功能。

---

## 🔗 相关链接

- 统一测试: `tests/unit/security/test_unified_neu_token_manager.py`
- 合并后实现: `neurova/security/neu_token_manager.py`
- 受影响测试: `tests/unit/security/test_auth_comprehensive.py`
- api/app.py 依赖点: `neurova/api/app.py:249`

---

**最后更新**: 2026-06-25 | **更新人**: Agent
