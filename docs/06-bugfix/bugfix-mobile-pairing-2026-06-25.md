# 移动配对 API 阻断性 BUG 修复报告

**修复日期**: 2026-06-25
**修复方法**: TDD 红绿灯 + bug-hunt 5 阶段 + zoom-out + improve-codebase-architecture
**修复文件**: `neurova/api/endpoints/mobile_pairing.py`
**删除文件**: `neurova/channels/mobile_pairing.py`（死代码）
**测试文件**: `tests/unit/api/test_mobile_pairing_p0.py`（12 个测试）

---

## 一、修复的 BUG

### BE-MOB-001: WS URL 硬编码 ws://localhost:8000/mobile/ws

**严重程度**: P0（阻断性）
**类型**: 功能失效

**问题**:
- `api/endpoints/mobile_pairing.py` 第 267、292、379 行硬编码 `ws://localhost:8000/mobile/ws`
- 实际服务端口是 9527，且生产环境 host 未知
- 手机扫码后连接的 WS URL 指向不存在的 8000 端口

**根因**:
- 开发时硬编码本地调试地址，未考虑部署环境
- 违反"配置外置"原则

**修复**:
- 新增 `_build_ws_url(request, code=None, token=None)` 辅助函数
- 从 `Request.headers["host"]` 推导实际 host:port
- 根据 `Request.url.scheme` 推导 ws/wss 协议（HTTPS → wss）
- 修改 3 个端点（generate_pairing、get_pairing_qrcode、confirm_pairing）接收 `Request` 参数并调用 `_build_ws_url`

**验证**:
- `test_ws_url_should_derive_from_host_header` ✅
- `test_ws_url_should_use_https_when_request_is_https` ✅
- `test_ws_url_for_token_endpoint` ✅
- `test_generate_pairing_returns_correct_ws_url`（集成测试）✅

---

### BE-MOB-002: JWT 鉴权占位 _get_current_user_id 永远返回 default-user

**严重程度**: P0（安全漏洞 + 功能失效）
**类型**: 认证绕过

**问题**:
- `api/endpoints/mobile_pairing.py` 第 151-160 行的 `_get_current_user_id` 函数
- 注释写"从 JWT Token 提取 user_id"，实现却永远返回 `"default-user"`
- 所有用户的配对数据都被归到 `default-user` 名下，无用户隔离
- 任何带 Authorization 头的请求都被视为同一用户

**根因**:
- 占位实现未完成，遗留到生产
- `auth.py` 已有完整的 `verify_access_token` 和 `get_current_user`，但未复用

**修复**:
- 将 `_get_current_user_id` 改为 `async` 函数
- 复用 `neurova.api.auth.verify_access_token` 进行真正的 JWT 解析
- 从 payload 中提取 `sub`（用户标识）
- 无效 token 抛出 401

**验证**:
- `test_get_current_user_id_should_extract_from_jwt` ✅（真实 JWT 返回正确 user_id）
- `test_get_current_user_id_should_reject_invalid_token` ✅（无效 token 抛 401）
- `test_get_current_user_id_should_reject_missing_credentials` ✅（无凭证抛 401）

---

### BE-MOB-003: WS_SECRET 默认弱密钥

**严重程度**: P0（安全漏洞）
**类型**: 弱密钥

**问题**:
- `api/endpoints/mobile_pairing.py` 第 106 行：`_WS_SECRET = config.get("NEUROVA_WS_SECRET", "neurova-ws-secret-key-2026")`
- 默认密钥 `"neurova-ws-secret-key-2026"` 是公开的弱密钥
- 攻击者可伪造 WS Token 连接任意用户的 WebSocket

**根因**:
- 开发便利性优先于安全性
- 缺少生产环境强制配置校验

**修复**:
- 新增 `_get_ws_secret()` 函数，分层处理：
  1. 优先读取 `NEUROVA_WS_SECRET` 环境变量
  2. 生产环境（`NEUROVA_ENV=production`）未配置时 **fail-fast**（抛出 HTTPException 500）
  3. 开发环境允许使用弱默认密钥（并打印警告日志）
- `_generate_ws_token` 和 `_verify_ws_token` 改用 `_get_ws_secret()` 而非模块级常量

**设计决策**:
- 选择 fail-fast 而非静默生成随机密钥 —— 因为多实例部署时随机密钥会导致 token 验证失败
- 遵循 bug-hunt "不绕过错误根本原因"原则：生产环境弱密钥是安全漏洞，宁可拒绝服务也不使用

**验证**:
- `test_ws_secret_should_not_use_weak_default_in_production` ✅（生产环境抛 500）
- `test_ws_secret_should_allow_weak_default_in_development` ✅（开发环境允许）
- `test_ws_secret_should_use_env_var_when_configured` ✅（环境变量优先）

---

### BE-MOB-004: 双实现未互通

**严重程度**: P0（代码混乱 + 维护风险）
**类型**: 死代码 / 重复实现

**问题**:
- `channels/mobile_pairing.py`（300 行）和 `api/endpoints/mobile_pairing.py`（530 行）是两个独立实现
- `channels/mobile_pairing.py` 定义了 `MobilePairingManager` 类，但无任何业务代码导入
- 仅 pylint 报告引用（静态分析），运行时完全孤立
- 两个实现的数据结构不互通（`PairingSession` vs `_pairing_codes` dict）

**根因**:
- 开发时创建了两套实现，未统一
- `channels/` 版本被 `api/endpoints/` 版本取代后未清理

**zoom-out 分析**:
- `api/endpoints/mobile_pairing.py` 是实际生效的实现（注册到 `/v1/mobile`）
- `channels/mobile_pairing.py` 是孤立的死代码

**improve-codebase-architecture 删除测试**:
- 假设删除 `channels/mobile_pairing.py` → 复杂度是否增加？否 → 它是死代码
- 假设删除 `api/endpoints/mobile_pairing.py` → 复杂度是否增加？是（路由消失）→ 它是真实实现

**修复**:
- 删除 `neurova/channels/mobile_pairing.py`（300 行死代码）
- 保留 `neurova/api/endpoints/mobile_pairing.py` 作为唯一实现

**验证**:
- `test_channels_mobile_pairing_should_be_removed_or_unified` ✅
- `test_no_business_code_imports_channels_mobile_pairing` ✅

---

## 二、修改文件清单

### 修改的文件（1 个）

| 文件 | 修改内容 |
|------|---------|
| `neurova/api/endpoints/mobile_pairing.py` | 4 个 BUG 全部修复 |

**具体修改**:
1. 新增 `from fastapi import Request` 导入
2. 新增 `_WEAK_DEFAULT_WS_SECRET` 常量
3. 新增 `_get_ws_secret()` 函数（生产环境强制配置）
4. 新增 `_build_ws_url(request, code, token)` 函数（从 Host header 推导）
5. 修改 `_generate_ws_token` / `_verify_ws_token` 使用 `_get_ws_secret()`
6. 修改 `_get_current_user_id` 为 async，复用 `verify_access_token`
7. 修改 `generate_pairing` 端点接收 `Request` 参数
8. 修改 `get_pairing_qrcode` 端点接收 `Request` 参数
9. 修改 `confirm_pairing` 端点接收 `Request` 参数

### 删除的文件（1 个）

| 文件 | 原因 |
|------|------|
| `neurova/channels/mobile_pairing.py` | 死代码（300 行），通不过删除测试 |

### 新增的文件（1 个）

| 文件 | 内容 |
|------|------|
| `tests/unit/api/test_mobile_pairing_p0.py` | 12 个测试（4 个 BUG 的复现 + 集成测试） |

---

## 三、测试结果

### 新增测试（12 个，全部通过）

```
tests/unit/api/test_mobile_pairing_p0.py::TestWSUrlHardcoded::test_ws_url_should_derive_from_host_header PASSED
tests/unit/api/test_mobile_pairing_p0.py::TestWSUrlHardcoded::test_ws_url_should_use_https_when_request_is_https PASSED
tests/unit/api/test_mobile_pairing_p0.py::TestWSUrlHardcoded::test_ws_url_for_token_endpoint PASSED
tests/unit/api/test_mobile_pairing_p0.py::TestJWTAuthPlaceholder::test_get_current_user_id_should_extract_from_jwt PASSED
tests/unit/api/test_mobile_pairing_p0.py::TestJWTAuthPlaceholder::test_get_current_user_id_should_reject_invalid_token PASSED
tests/unit/api/test_mobile_pairing_p0.py::TestJWTAuthPlaceholder::test_get_current_user_id_should_reject_missing_credentials PASSED
tests/unit/api/test_mobile_pairing_p0.py::TestWSSecretWeakDefault::test_ws_secret_should_not_use_weak_default_in_production PASSED
tests/unit/api/test_mobile_pairing_p0.py::TestWSSecretWeakDefault::test_ws_secret_should_allow_weak_default_in_development PASSED
tests/unit/api/test_mobile_pairing_p0.py::TestWSSecretWeakDefault::test_ws_secret_should_use_env_var_when_configured PASSED
tests/unit/api/test_mobile_pairing_p0.py::TestDuplicateImplementation::test_channels_mobile_pairing_should_be_removed_or_unified PASSED
tests/unit/api/test_mobile_pairing_p0.py::TestDuplicateImplementation::test_no_business_code_imports_channels_mobile_pairing PASSED
tests/unit/api/test_mobile_pairing_p0.py::TestMobilePairingIntegration::test_generate_pairing_returns_correct_ws_url PASSED

======================= 12 passed, 30 warnings in 0.34s =======================
```

### 回归测试（47 个，全部通过）

```
tests/unit/api/test_mobile_pairing_p0.py (12 tests) — PASSED
tests/unit/api/test_api_auth.py — PASSED
tests/unit/api/test_auth_security_p0.py — PASSED
tests/unit/api/test_endpoint_registration.py — PASSED

====================== 47 passed, 174 warnings in 2.26s =======================
```

### 预先存在的失败（未引入新失败）

`tests/unit/api/` 和 `tests/unit/channels/` 中有 119 个预先存在的失败，均与本次修改无关：
- `test_communication_protocol_comprehensive.py` — 预先存在的 API 不匹配
- `test_context_pool_settings_api.py` — 预先存在的变量作用域问题
- `test_channels_models.py` — 预先存在的 schema 不匹配

---

## 四、TDD 红绿灯流程

### RED 阶段
- 编写 12 个测试覆盖 4 个 BUG
- 运行测试：10 个失败，2 个通过（边界场景）
- 失败原因：
  - `_build_ws_url` 不存在（AttributeError）
  - `_get_current_user_id` 是同步函数（TypeError）
  - `_get_ws_secret` 不存在（AttributeError）
  - `channels/mobile_pairing.py` 仍有独立实现（AssertionError）
  - `qr_code_url` 包含 `localhost:8000`（AssertionError）

### GREEN 阶段
- 逐个最小修复：
  1. 添加 `_build_ws_url` 函数 + 修改 3 个端点
  2. 修改 `_get_current_user_id` 为 async + 复用 JWT
  3. 添加 `_get_ws_secret` 函数 + 修改 token 生成/验证
  4. 删除 `channels/mobile_pairing.py`
- 运行测试：12/12 通过

### REFACTOR 阶段
- 运行回归测试：47/47 通过
- 确认未破坏任何现有测试
- 代码已最小化，无需进一步重构

---

## 五、部署指南

### 生产环境配置

修复后，生产环境必须配置以下环境变量：

```bash
# 必须配置（否则服务返回 500）
export NEUROVA_WS_SECRET="your-strong-secret-key-at-least-32-bytes-long"

# 标记为生产环境
export NEUROVA_ENV="production"
```

### 生成强密钥

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 验证配置

```bash
# 启动服务后，调用 generate_pairing 端点
# 如果返回 500，说明 NEUROVA_WS_SECRET 未配置
curl -X POST http://your-server:9527/v1/mobile/pairing/generate \
  -H "Authorization: Bearer <jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{"device_name": "test", "device_type": "mobile"}'
```

---

## 六、bug-hunt 5 阶段总结

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 0 — Reproduce | 4 个 BUG 均有文件:行号证据 | ✅ |
| Phase 1 — Localization | `api/endpoints/mobile_pairing.py` + `channels/mobile_pairing.py` | ✅ |
| Phase 2 — Instrumentation | 测试覆盖（替代日志插桩） | ✅ |
| Phase 3 — Root Cause | 4 个根因分析（见上文） | ✅ |
| Phase 4 — Surgical Fix | 最小修复（1 文件修改 + 1 文件删除） | ✅ |
| Phase 5 — Report | 本文档 | ✅ |

---

**修复完成时间**: 2026-06-25
**修复人**: AI Agent（TDD + bug-hunt + zoom-out + improve-codebase-architecture）
**文档版本**: 1.0
