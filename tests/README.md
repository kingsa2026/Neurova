# tests/ 目录约定

> 2026-09-16 根目录 ad-hoc 文件归位后建立。

## 分层结构

| 目录 | 定位 | pytest 收集 | 入库 |
|------|------|-------------|------|
| `unit/` | 单元测试（无外部依赖） | ✅ 是（`test_*.py`） | ✅ |
| `integration/` | 集成测试（跨模块/真实 IO/DB） | ✅ 是 | ✅ |
| `e2e/` | 端到端（后端启动、全链路） | ✅ 是 | ✅ |
| `performance/` | 性能与基准（含 LongMemEval 评测脚本） | ✅ 是（同 `test_*.py` 规则） | ✅ |
| `manual/` | **手工验证脚本**（需活后端 / 打印断言 / 硬编码路径） | ❌ 否 | ✅ |
| `runners/` | 测试运行器（`run_*.py`、`comprehensive_test_runner.py`） | ❌ 否 | 部分（见下） |
| `archive/` | 退役件（保留历史，不参与套件） | ❌ 否 | ✅ |
| `legacy 目录` | `test_api/` `test_channels/` `test_memory/` `test_storage/` `test_output/` `test_boundary/` `test_integration/` `admin/` `auth/` `knowledge/` … | 按 `test_*.py` 规则 | ✅ |

**收集规则**（`pyproject.toml`）：`python_files = ["test_*.py"]`，`--import-mode=importlib`。
根目录只保留 `__init__.py` 与 `conftest.py`（后者提供跨目录共享 fixture）。

## 为何 `runners/` 不叫 `scripts/`

> **踩坑记录（2026-09-16）**：曾命名为 `tests/scripts/`，其 `__init__.py` 使 `tests/scripts` 成为名为 `scripts` 的包，
> **遮蔽了项目根的生产包 `scripts/`**（含 `common.py`/`config.py`/`health_check.py`/`port_utils.py`），
> 导致 `tests/unit/skills/test_scripts_*.py` 的 `from scripts.common import ...` 全部 ImportError
> （收集数 16423 → 16299，5 errors）。
> 改名为 `runners/` 后收集数精确复原。
> **结论：tests 下新建目录名不得与项目顶层包名重名**（现有顶层包：`neurova`/`scripts`/`config`/`docs`/`data`/`models`/`logs`…）。

## `runners/` 入库状态

`run_*.py` 命中 `.gitignore` 的临时脚本规则（`run_*.py`），属**本地产物**、不入库；
`comprehensive_test_runner.py` 已入库。因此 `runners/` 中部分文件仅存在于本地工作区。

文档化命令的实际路径：`python tests/runners/run_all_tests.py`（本地存在时可用）。
`run_tests3.py` / `run_integration_tests.py` 用 `cwd=os.getcwd()`，需在项目根目录执行。

## `archive/` 台账

| 文件 | 归档日期 | 失效原因 |
|------|----------|----------|
| `channels_archive.py` | 2026-09-16 | 原位于 `tests/` 根目录、因文件名不匹配 `test_*.py` **从未被收集**。直跑为 **11 failed**：断言针对已变更的 `ChannelManager` 旧 API（`add_channel`/`remove_channel`/`set_channel_priority`/`mark_channel_success`/`update_channel_health`）。现行实现已由 `tests/unit/channels/`（61 个文件）覆盖。保留作历史参考，**不注入标准套件**；如需复活须先核对 `neurova.channels.ChannelManager` 现接口。 |

## 已知遗留（未处理，登记备查）

1. `runners/comprehensive_test_runner.py` 默认把报告写到 `tests/COMPREHENSIVE_TEST_REPORT.md`（`cwd` 相对）——会在 tests 根目录再生产物，后续可收敛到 `runners/` 内。
2. 各测试目录间仍存在同名测试文件（如 `test_api.py`/`test_manager.py` 多处重名，共 8+ 组），
   这是 `--import-mode=importlib` 变通仍必要的原因，**不要**改回 prepend 模式。
3. 遗留目录（`test_api/`、`test_channels/`、`test_memory/` 等）与新分层（`unit/`）职责重叠，属独立清理任务。
