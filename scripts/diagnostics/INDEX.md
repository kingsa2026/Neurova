# 临时定位 / 检查脚本索引（scripts/diagnostics/）

本目录统一收纳编程过程中产生的**临时定位脚本、检查脚本与一次性修复脚本**，
原先散落在项目根目录（多被 `.gitignore` 的 `/_*.py`、`check*.py`、`fix_*.py` 等规则忽略）。
移入本目录后这些脚本不再命中根目录忽略规则，可被版本控制与索引。

> 运行约定：标注「项目根运行」的脚本使用 cwd 相对路径（如 `neurova/`、`data/`、`audit-reports/`），
> 必须在仓库根目录下执行；探针类脚本已自动注入项目根到 `sys.path`，可在任意位置运行。

## 一、临时定位 / 探针（probes）

| 脚本 | 用途 | 运行方式 | 副作用 |
|------|------|----------|--------|
| `_probe.py` | 拉起后端(8099)并探测 `/api/v1/agents`、`/api/agents` 路由 | `python scripts/diagnostics/_probe.py` | 启动临时 uvicorn 线程 |
| `_agent_probe.py` | 拉起后端(9527)并探测 agents 路由 | `python scripts/diagnostics/_agent_probe.py` | 启动临时 uvicorn 线程 |
| `_trace_stack.py` | 最小 Agent 初始化 + 一次 chat，用于堆栈定位 | `python scripts/diagnostics/_trace_stack.py` | 创建 `./_smoke_workspace` |
| `_run_backend.py` | 仅启动本地后端(9527)，供手工调试单独拉起服务 | `python scripts/diagnostics/_run_backend.py` | 占用 9527 端口 |

## 二、检查脚本（checks）

| 脚本 | 用途 | 运行方式 |
|------|------|----------|
| `check_databases.py` | 列出主要 SQLite 库（`neurova_memory.db`/`neurflow.db`/`data/neurova_memory.db`）及表名 | 项目根运行 |
| `check_users_db.py` | 检查 `data/users.db` 表结构、用户列表与 admin 记录 | 项目根运行 |
| `_tmp_check_tracked.py` | 检查 `tests/unit/core` 下测试文件的 git 跟踪状态 | 项目根运行 |
| `analyze_issues.py` | 解析 `audit-reports/pylint-report-v4.json`，抽样打印 broad-exception-caught / wrong-import-position / undefined-variable | 项目根运行（需该报告存在） |

## 三、一次性修复 / 补丁脚本（one-off，已完成使命）

⚠️ 以下脚本会**改写 `neurova/` 源码**，对应问题早已修复，仅作留档，**请勿再次运行**。

| 脚本 | 用途 | 状态 |
|------|------|------|
| `fix_logging.py` | 将 logger 的 f-string 调用批量转为 `%` 惰性格式化 | 已应用 |
| `fix_logger_format.py` | 修复 Black 格式化导致的 logger 调用语法错误 | 已应用 |
| `fix_all_syntax.py` | 批量修复 logger 调用中的格式化语法错误 | 已应用 |
| `fix_syntax_errors.py` | 修复指定文件清单中的 logger 格式化语法错误 | 已应用 |
| `fix_fstring_percent.py` | 修复 Black 导致的 f-string 百分比语法错误 | 已应用 |
| `_tmp_patch_evo.py` | 补丁：`delete_agent` 清理 AgentConfigManager 配置 | 已应用 |

## 四、未纳入本目录的根目录脚本（说明）

以下脚本不属于「临时定位/检查」，保留原位：
- `check_and_start.py`：前后端一键启动工具（启动器，非临时诊断）。
- `create_admin_user.py`、`create_github_release.py`：运维/发布工具。
- `example_agent_with_tts.py`、`example_channel_tts.py`：示例代码。
- `quick_start.py`、`weather_xuchang.py`、`chat.py`：组件验证/小工具。
- `cli.py`、`install.py`、`start.py`、`start_server.py`：项目入口。

---
*本索引随脚本增删维护；新增临时脚本时请同步更新本文件。*
