# JWT 登录问题修复指南

## 问题描述
前端登录时出现 500 Internal Server Error，后端日志显示：
```
Login failed: No module named 'jwt'
```

## 根本原因
`neurova/api/auth.py` 第25行使用 `import jwt`（PyJWT 包），但 `requirements.txt` 中只包含了 `python-jose`（提供 `jose` 模块，不提供 `jwt` 模块）。

## 已完成的修复
✅ 已在 `requirements.txt` 中添加 `PyJWT>=2.8.0`

## 需要手动执行的步骤

### 1. 安装 PyJWT 包
在服务器上运行以下命令：
```bash
pip install PyJWT>=2.8.0
```

或者重新安装所有依赖：
```bash
pip install -r requirements.txt
```

### 2. 重启后端服务器
停止当前运行的服务器，然后重新启动：
```bash
# 如果使用 start_server.py
python start_server.py

# 或者直接使用 uvicorn
uvicorn neurova.api.app:create_app --host 0.0.0.0 --port 9527 --reload
```

### 3. 验证修复
运行测试脚本验证 JWT 是否正常工作：
```bash
python test_jwt_fix.py
```

预期输出：
```
✅ PyJWT 导入成功，版本: 2.x.x
✅ neurova.api.auth 模块导入成功
✅ Access token 创建成功
✅ Token 解码成功
✅ 登录端点模块导入成功
🎉 所有测试通过！JWT 修复成功。
```

### 4. 测试登录
使用以下凭据尝试登录：
- 用户名: `admin`
- 密码: `Admin23@`

## 技术细节
- PyJWT 提供 `jwt` 模块，用于 JWT Token 的生成和验证
- python-jose 提供 `jose` 模块，功能类似但 API 不同
- `neurova/api/auth.py` 使用 PyJWT 的 API，因此需要安装 PyJWT
- 两个包可以共存，不会冲突

## 如果问题仍然存在
1. 检查 Python 环境是否正确（虚拟环境）
2. 确认 PyJWT 已安装：`pip show PyJWT`
3. 检查服务器日志是否有其他错误
4. 确保服务器已重启（不是热重载）

## 相关文件
- `requirements.txt` - 已添加 PyJWT 依赖
- `neurova/api/auth.py` - JWT 认证模块
- `test_jwt_fix.py` - 验证脚本
- `fix_jwt_import.py` - 诊断脚本