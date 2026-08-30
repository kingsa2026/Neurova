# Neurova 重启脚本使用说明

## 快速开始

### 一键重启前后端
```batch
restart_neurova.bat
```

### 仅重启后端
```batch
restart_neurova.bat --backend
# 或
restart_neurova.bat -b
```

### 仅重启前端
```batch
restart_neurova.bat --frontend
# 或
restart_neurova.bat -f
```

### 仅检查服务状态
```batch
restart_neurova.bat --check
```

## 脚本特性

### 1. 智能进程管理
- 自动检测并终止占用端口的进程
- 等待端口释放后再启动新服务
- 支持最大重试次数防止无限等待

### 2. 详细状态显示
- 实时显示服务运行状态
- 显示进程PID便于调试
- 彩色输出（如果终端支持）

### 3. 错误处理
- 端口释放超时警告
- 后端启动超时检测
- 前端依赖自动安装

### 4. 用户友好
- 清晰的操作步骤提示
- 完成后的访问地址汇总
- 常见问题提示

## 端口配置

默认端口配置：
- **后端**: 9527 (FastAPI)
- **前端**: 8100 (Vite Dev Server)

如需修改端口，编辑脚本开头的配置：
```batch
set BACKEND_PORT=9527
set FRONTEND_PORT=8100
```

## 修复的问题

运行此脚本可以修复以下问题：

### 1. Sandbox API 404 错误
- **问题**: `GET /api/v1/sandbox` 返回 404
- **原因**: FastAPI 路由注册顺序错误
- **修复**: 已调整 `sandbox.py` 中的路由顺序
- **状态**: ✅ 已修复

### 2. i18n 缺少 market.install 键
- **问题**: `[intlify] Not found 'market.install' key in 'zh' locale messages`
- **原因**: 所有语言文件缺少 `market` 对象
- **修复**: 已为所有11种语言添加 `market` 对象
- **状态**: ✅ 已修复

### 3. Auth 401 错误
- **问题**: `GET /api/v1/auth/me` 返回 401
- **原因**: 前端检查 `'id' in data` 但后端返回 `user_id`
- **修复**: 已修复前端数据检查逻辑
- **状态**: ✅ 已修复

## 故障排除

### 1. 端口被占用但进程无法终止
```batch
# 手动查看占用端口的进程
netstat -ano | findstr :9527
netstat -ano | findstr :8100

# 手动终止进程（替换 <PID>）
taskkill /F /PID <PID>
```

### 2. 后端启动失败
- 检查日志文件: `logs/server.log`
- 确认Python环境: `.venv\Scripts\python.exe`
- 手动启动测试: `.venv\Scripts\python.exe start.py --backend`

### 3. 前端启动失败
- 进入前端目录: `cd NeurUI`
- 安装依赖: `npm install`
- 手动启动: `npm run dev`
- 检查Node.js版本: `node --version` (需要 >= 18)

### 4. 浏览器无法访问
- 确认服务已启动: `restart_neurova.bat --check`
- 检查防火墙设置
- 尝试直接访问: `http://localhost:8100`

## 日志文件

- **后端日志**: `logs/server.log`
- **前端日志**: 控制台输出（Vite开发服务器）

## 开发模式

### 启动前后端 + 自动打开浏览器
```batch
start.bat --chat
```

### 启动后端 + CLI聊天
```batch
start.bat --cli
```

### 检查服务状态
```batch
start.bat --check
```

## 生产模式

### 生产环境部署
```batch
start.bat --prod
```

生产模式特点：
- 仅启动后端服务
- 服务静态文件（从 `NeurUI/dist` 复制）
- 不启动Vite开发服务器

## 脚本对比

| 脚本 | 用途 | 特点 |
|------|------|------|
| `restart_neurova.bat` | 快速重启 | 杀死现有进程，重新启动 |
| `start.bat` | 智能启动 | 检查端口，避免重复启动 |
| `start.py` | 功能最全 | 支持所有启动模式和选项 |

## 技术细节

### 进程管理
1. 使用 `netstat -ano` 查找占用端口的进程
2. 使用 `taskkill /F /PID` 强制终止进程
3. 等待端口释放（最多10秒）
4. 启动新进程

### 服务启动
- **后端**: `python start.py --backend --skip-install`
- **前端**: `cd NeurUI && npm run dev`
- **窗口**: 使用 `start` 命令在新窗口中运行

### 依赖检查
- 后端: 检查Python虚拟环境
- 前端: 检查 `node_modules` 目录

## 更新日志

### v2.0 (2026-06-10)
- 修复批处理延迟变量扩展语法
- 添加详细的服务状态检查
- 改进错误处理和超时管理
- 添加用户友好的提示信息
- 支持 `--check` 模式

### v1.0 (初始版本)
- 基本的前后端重启功能
- 支持 `--backend` 和 `--frontend` 参数

## 支持

如遇问题，请检查：
1. 日志文件: `logs/server.log`
2. 服务状态: `restart_neurova.bat --check`
3. 端口占用: `netstat -ano | findstr :9527`