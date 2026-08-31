# 剪映 & ComfyUI CLI操作集成说明

## 概述

为Neurova项目添加了剪映（Jianying/CapCut）和ComfyUI的CLI操作能力，作为现有外部操作CLI框架的扩展。

## 新增模块

### 1. `jianying_ops.py` - 剪映操作模块

**支持平台**: Windows, macOS

**支持软件**:
- 剪映专业版 (Jianying Pro)
- CapCut (剪映国际版)

**可用命令**:
- `launch(software_name, project_path)` - 启动剪映
- `close(software_name)` - 关闭剪映
- `status(software_name)` - 获取软件状态
- `list_installed()` - 列出已安装的版本
- `open_project(project_path, software_name)` - 打开项目文件
- `export_video(project_path, output_path, preset)` - 导出视频（实验性）
- `get_recent_projects(software_name)` - 获取最近项目列表

**使用示例**:
```python
from neurova.cli import JianyingOps

ops = JianyingOps(verbose=True)

# 启动剪映
ops.launch("jianying")

# 打开项目
ops.open_project(r"C:\Users\username\Documents\JianyingPro\Projects\my_project")

# 获取状态
status = ops.status("jianying")
print(status)

# 关闭剪映
ops.close("jianying")
```

### 2. `comfyui_ops.py` - ComfyUI操作模块

**支持平台**: Windows, macOS, Linux (跨平台)

**可用命令**:
- `launch(port, listen, extra_args)` - 启动ComfyUI服务
- `close()` - 关闭ComfyUI服务
- `status()` - 获取服务状态
- `open_webui(browser)` - 打开Web界面
- `install(install_path, python_cmd)` - 安装ComfyUI
- `update()` - 更新ComfyUI
- `set_path(path)` - 设置ComfyUI路径
- `get_path()` - 获取ComfyUI路径
- `set_port(port)` - 设置服务端口
- `queue_prompt(prompt)` - 提交工作流到队列
- `get_queue_status()` - 获取队列状态
- `interrupt()` - 中断当前任务

**使用示例**:
```python
from neurova.cli import ComfyUIOps

ops = ComfyUIOps(verbose=True)

# 设置ComfyUI路径
ops.set_comfyui_path(r"C:\ComfyUI")

# 启动服务
ops.launch(port=8188)

# 打开Web界面
ops.open_webui()

# 获取状态
status = ops.status()
print(status)

# 关闭服务
ops.close()
```

## 集成到ExternalOpsCLI

已更新 `ExternalOpsCLI` 类，包含剪映和ComfyUI操作：

```python
from neurova.cli import ExternalOpsCLI

cli = ExternalOpsCLI(verbose=True)

# 通过CLI执行剪映操作
status = cli.execute("jianying", "status", "jianying")
cli.execute("jianying", "launch", "jianying")

# 通过CLI执行ComfyUI操作
status = cli.execute("comfyui", "status")
cli.execute("comfyui", "launch", 8188)

# 通过属性访问
cli.jianying.launch("jianying")
cli.comfyui.launch(port=8188)

# 列出所有能力
capabilities = cli.list_capabilities()
print(capabilities)
```

## 测试验证

已创建测试脚本 `test_jianying_comfyui.py`，测试覆盖：

1. **剪映操作测试** - 测试所有剪映相关功能
   - ✓ 列出可用命令
   - ✓ 列出已安装软件
   - ✓ 获取软件状态
   - ✓ 获取最近项目

2. **ComfyUI操作测试** - 测试所有ComfyUI相关功能
   - ✓ 列出可用命令
   - ✓ 获取服务状态
   - ✓ 路径操作
   - ✓ 端口设置

3. **ExternalOpsCLI集成测试** - 测试与主框架的集成
   - ✓ 列出所有能力
   - ✓ 通过CLI执行剪映操作
   - ✓ 通过CLI执行ComfyUI操作
   - ✓ 属性访问

**测试结果**: 3/3 通过

## 文件清单

### 新增文件
- `neurova/cli/jianying_ops.py` - 剪映操作模块
- `neurova/cli/comfyui_ops.py` - ComfyUI操作模块
- `test_jianying_comfyui.py` - 功能测试脚本

### 修改文件
- `neurova/cli/__init__.py` - 添加模块导出
- `neurova/cli/external_ops.py` - 集成到主框架

## 功能特性

### 剪映操作
- ✅ 自动检测安装路径 (Windows/macOS)
- ✅ 启动/关闭软件
- ✅ 状态检查（安装状态、运行状态）
- ✅ 打开项目文件
- ✅ 获取最近项目列表
- ⚠️ 视频导出（实验性，需要剪映命令行支持）

### ComfyUI操作
- ✅ 自动检测Python环境
- ✅ 自动查找ComfyUI安装
- ✅ 启动/关闭服务
- ✅ 状态检查（安装状态、服务运行状态）
- ✅ 打开Web界面
- ✅ 安装ComfyUI（从GitHub克隆）
- ✅ 更新ComfyUI（git pull）
- ✅ 工作流队列操作（需要服务运行）
- ✅ 端口配置

## 依赖要求

### 剪映操作
- 剪映专业版 或 CapCut 已安装
- 支持 Windows 和 macOS

### ComfyUI操作
- Python 3.8+
- Git（用于安装和更新）
- ComfyUI 依赖（通过 pip 安装）

## 已知限制

1. **剪映视频导出** - 需要剪映提供命令行接口，当前版本可能不支持
2. **ComfyUI API操作** - `queue_prompt`, `get_queue_status`, `interrupt` 需要服务运行中
3. **平台支持** - 剪映主要支持Windows和macOS，ComfyUI支持全平台

## 后续改进方向

1. 添加剪映项目模板创建功能
2. 添加ComfyUI工作流管理（保存/加载/分享）
3. 添加批量视频处理功能
4. 添加ComfyUI模型管理功能
5. 添加更多视频编辑软件的CLI操作（如DaVinci Resolve、Adobe Premiere等）

## 作者

Neurova Development Team

## 日期

2026-05-14
