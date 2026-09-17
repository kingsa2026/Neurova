# console 第一批拆分验收（2026-09-17）

## 范围与 baseline

- 原文件：`E:/项目/Neurova/neurova/api/endpoints/console.py`，2217 行；开始时该文件 git diff 为空。
- 原文备份：`E:/AppData/Local/Temp/console-first-split-sphdnxo6/console.py`。
- 原文 SHA256：`be66c1a5d7d0638e6d102ad43672a186725f8e00fc34e52702ff29ac62f8c07e`。
- 仅移动原 1863–1931 文件四路由、1937–2011 调试三路由、2110–2192 标注模型及五路由。
- 消费方搜索：源码、tests、前端；包括 `_safe_filename`、`FileResponse`、上传目录、模型、路由注册和 `inspect.getsource`。搜索清单保存在上述临时目录 `consumers.txt` / `inspect-consumers.txt`。
- 既有模块源码 inspect 测试涉及 session repository 和未移动聊天函数，不需要修改。

## 实现

- 新增 `console_files.py`、`console_system.py`、`console_annotations.py`；旧位置 include_router，保留全路由顺序。
- `console` 显式导入旧函数名，文件/调试函数内通过 `from . import console as api` 读取旧 patch 缝；无 exec/globals/sys.modules 代理。
- `_CONSOLE_UPLOAD_DIR` 与 mkdir、`_safe_filename`、`_tail_text_file`、`CommandRequest`、manager 留在 console。
- 标注模型在叶子定义、旧模块 reexport，显式保留 `__module__ = neurova.api.endpoints.console`，没有字符串前向注解。
- 调试命令通过 `bind_command_endpoint(CommandRequest)` 在 console 原注册位置一次性绑定模型，返回实际端点，无请求期包装。保留签名 body 模型身份、Depends 的实际 callable 身份与 admin 闭包语义。其 Python `__qualname__` 带工厂局部作用域；HTTP name/unique_id 不变。
- 59 个留存函数/类 AST 与原文一致；12 个移动函数在去除 `api.` 限定和函数内 console 导入后 AST 与原文逐一一致。聊天/SSE/会话/反馈/WS/push/tasks 未改。

## 守卫与红绿证据

新增 `E:/项目/Neurova/tests/unit/api/test_console_split_contract.py`，快照 `console_split_routes.json`。

全 router 37 条（含 WS）原文快照冻结顺序、path、methods、name、unique_id、operation_id、依赖树及闭包、参数/默认值/注解/模型 schema、response_model 和返回注解。

| 阶段 | 实际结果 |
| --- | --- |
| 原文运行新增测试 | 13 passed，3 failed（仅叶子不存在，结构红灯） |
| files 域 | 14 passed，2 deselected（尚未移动域） |
| debug 域 | 15 passed，1 deselected |
| 三域完成 | 16 passed |
| 原有 `tests/unit/api/test_console*.py`，不含新增守卫 | 68 passed |
| console 消费方隔离回归（480 项） | **471 passed，4 skipped，5 xfailed** |
| 同回归独立加载备份原文（排除三个新结构测试） | **468 passed，4 skipped，5 xfailed，3 deselected** |
| 三个叶子各自 fresh process 先导入再导入 console | 全部成功，均 37 routes |
| git diff --check | 通过 |

新增行为测试上传只使用 tmp_path；验证 UUID、文件名、目录、FileResponse 原路径 patch；调试日志/psutil/子进程全部 mock；标注库 mock。匿名 get_current_user 替身拒绝 401、普通用户通过真实 require_admin 闭包拒绝 403，含三条 debug 与 push admin 路由；不创建真实账号或网络鉴权。

过程中的两项自身错误均已修正并重跑，不隐去失败证据：
1. files 初次机械替换误将 datetime.datetime 双重限定，出现 1 failed/13 passed，修正限定后绿。
2. 新结构测试最初字符串查找 exec( 误匹配 create_subprocess_exec，改用 AST 检查真正的 exec/globals 名称调用；未修改已有测试。

## 回归隔离与原文对照

临时运行器：`E:/AppData/Local/Temp/console-first-split-sphdnxo6/run_regression.py`。

- 动态搜集 tests 中实际 `endpoints.console` / `endpoints import console` / `/console/` 消费文件；排除 manual/archive/runners/llm/e2e 目录，不重跑前批 external_api 专项。
- 通过临时 pytest plugin 将旧测试上传路径重定向每用例 tmp_path，mock 日志/psutil/调试子进程；未修改已有测试。
- 第一次回归 468 passed/3 failed/4 skipped/5 xfailed。3 个 no_double_write 测试是运行器全局 NEUROVA_SESSIONS_DIR 覆盖旧 fixture 的 Path("sessions") 替身，引起预期路径无文件。独立加载原文得到同样 3 个失败（465 passed）。
- 只修临时运行器：已有 isolated_sessions_dir fixture 时不设置环境目录。之后拆分版与原文对照均无失败，未触碰生产聊天逻辑或放宽断言。
- 原文对照通过临时 MetaPathFinder 从备份加载原模块；未 stash/checkout/覆盖共享 console.py。原文模式仅 deselect 新增结构测试，既有 skip/xfail 均原样保留。
- 最终日志：`regression-green.log`、`regression-original-green.log`；此前失败日志 `red.log`、`regression.log`、`regression-original.log` 留在临时目录。

## 复验命令（Git Bash）

```bash
"E:/项目/Neurova/.venv/Scripts/python.exe" -m pytest "E:/项目/Neurova/tests/unit/api/test_console_split_contract.py" -q --tb=short
"E:/项目/Neurova/.venv/Scripts/python.exe" "E:/AppData/Local/Temp/console-first-split-sphdnxo6/run_regression.py"
CONSOLE_BASELINE=1 "E:/项目/Neurova/.venv/Scripts/python.exe" "E:/AppData/Local/Temp/console-first-split-sphdnxo6/run_regression.py"
git -C "E:/项目/Neurova" diff --check -- neurova/api/endpoints/console.py
```

文件清单：临时目录 `regression-files.txt`。快照在原文件未移动时生成并跑绿，拆分后未刷新预期。

## 主控独立验收

- 前批平台客户端回归进入本批前再次执行：634 passed（20.57s）。
- 独立审查发现 `*_debug*.py` 忽略规则命中新模块，普通 Git 收集将漏文件。未修改 ignore 规则，改名为 `console_system.py`，原 HTTP 路径和旧 console 导出保持不变。
- 改名先更新结构守卫：1 failed / 15 passed；实际改名和调整导入后：16 passed（1.92s）。
- 后续 Git 可见性检查确认 `*_diag*.py` 也会忽略 diagnostics 命名，最终统一为 `console_system.py`。所有新产物经 `git check-ignore` 确认均未被忽略，旧 debug/diagnostics 文件均不存在，未修改 `.gitignore` 或强制暂存。
- 最终命名下主控独立复跑：守卫 16 passed（2.14s），隔离运行器 471 passed、4 skipped、5 xfailed（12.87s），两命令退出码均为 0；19 条既有弃用警告未屏蔽。
- 独立 AST 审查确认归一化调用时 `api` 依赖后，原 73 个顶层函数/类未出现业务逻辑变化。

## LOC 与限制

- console：2217 → 2009，减少 208 行。
- 叶子：files 82、debug 91、annotations 95，共 268 行。
- 生产总行数 2217 → 2277，净 +60；这是结构拆分而非 bug fix。新增去向：叶子模块导入/路由声明/分隔 29 行、旧模块 include/reexports 19 行、运行时旧全局访问 import 7 行、模型 module 身份 2 行、一次性模型绑定工厂及返回 3 行。
- 测试 192 行、冻结 JSON 2811 行，单独计，不属于生产 LOC。
- 未执行完整 tests/、端到端真实服务/网络/LLM/真实调试命令；现有 skip/xfail 不宣称修复。原有 AnnotationStore 单测在 tmp_path 使用 SQLite，不操作用户库；新增标注端点守卫完全 mock store。
- 临时备份及运行器可能被系统清理；正式测试和冻结快照保留仓库内。模块 reload 不在本批契约内；一次性绑定不是可重复插件注册 API。
- 没有提交/推送，没有修改已有测试文件，也没有主动修改范围外业务代码。
