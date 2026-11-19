
# Neutesting - Neurova 测试框架

## 🎯 关于 Neutesting

**Neutesting** 是 Neurova 项目的官方测试框架体系，提供完整的测试金字塔覆盖：

- ✅ **单元测试** - 组件级别的功能验证
- ✅ **集成测试** - 模块间协作的验证
- ✅ **端到端测试** - 完整用户场景的验证
- ✅ **性能基准测试** - 性能指标的监控和回归检测

本目录包含 Neutesting 的完整实现，专为 Neurova 项目设计。

## 📊 测试规模读数（核对基准 2026-11-19）

> 口径：测试文件数按 `find tests -name 'test_*.py' | wc -l` 计；测试函数数按
> `grep -rE '^\s*(async )?def test_' tests --include='*.py' | wc -l` 计。
> 不再维护"逐模块通过数"快照——那是会过期的读数，实时结果以当次 `pytest` 输出为准。

| 测试层 | 测试文件数 | 测试函数数 |
|--------|-----------|-----------|
| unit（单元测试） | 2684 | 23546 |
| integration（集成测试） | 58 | 568 |
| e2e（端到端测试） | 5 | 26 |
| performance（性能测试） | 10 | 72 |
| fixtures（共享测试数据） | 1 | 6 |
| 其他历史目录（api/core/llm/test_api/test_memory/test_channels 等） | 59 | 589 |
| **总计** | **2817** | **24807** |

## 🐛 已修复的 Bug

### Memory 模块 Bug 修复

1. **死锁修复** - `MemoryStorage.get_stats()`
   - 问题: 在 `with self._lock` 内部调用 `self.count()`，非重入锁导致死锁
   - 修复: 直接执行 SQL 查询，避免重复加锁

2. **API 不匹配修复** - `MemoryManager.stats()` / `get_full_stats()`
   - 问题: 调用不存在的 `store.stats()` 方法
   - 修复: 改为调用 `store.get_stats()`

3. **API 不匹配修复** - `MemoryManager.relate()`
   - 问题: 调用不存在的 `store.relate()` 方法
   - 修复: 改为调用 `store.add_relation()`

4. **API 不匹配修复** - `MemoryManager.recall_graph()`
   - 问题: 调用不存在的 `store.get_graph()` 方法
   - 修复: 改为调用 `store.get_related_memories_graph()`

5. **类型不匹配修复** - `MemoryManager.remember()` / `analyze_emotion()`
   - 问题: `emotion_scores` 期望 dict，但 `emo.analyze()` 返回 tuple
   - 修复: 添加类型检查和转换逻辑

6. **缺失方法添加** - `EmotionAnalyzer.get_emotion_distribution()`
   - 在 `EmotionAnalyzer`、`EmotionHubEngine` 两层添加该方法（原适配器层已退役，台账 §6-368）

### 其他模块 Bug 修复

- `ModuleSystem` API 重写 - 修正了 `Module`、`ModuleInfo`、`DependencyResolver` 的导入和使用
- `LogManager` - 添加 `set_default_level(LogLevel.DEBUG)` 确保日志级别测试正确
- `ConfigManager` - 修复单例模式下的状态隔离问题

## 📁 目录结构

```
tests/                          # Neutesting 根目录（pytest 配置在仓库根 pyproject.toml 的 [tool.pytest.ini_options]，核对基准 2026-11-19）
├── __init__.py              # 测试包初始化
├── conftest.py              # 全局 fixtures
├── README.md                # 测试说明
├── runners/                 # 测试运行器
│   └── comprehensive_test_runner.py
├── fixtures/                # 共享测试数据（知识库评测语料等 JSON）
│
├── unit/                    # Neutesting 单元测试层（2684 个测试文件 / 23546 个测试函数）
│   ├── agent/  api/  knowledge/  evolution/  core/  context/  memory/
│   ├── skills/  llm/  channels/  tools/  security/  neurflow/  cognitive_layers/
│   └── ...                  # 共 59 个模块子目录，不逐一罗列
│
├── integration/            # Neutesting 集成测试层（58 个测试文件）
│   ├── conftest.py         # 集成测试配置和fixtures
│   ├── test_agent_loop.py
│   ├── test_chat_closed_loop.py
│   ├── test_memory_system.py
│   └── ...
│
├── e2e/                   # Neutesting 端到端测试层（5 个测试文件）
│   ├── conftest.py         # E2E测试配置和fixtures
│   ├── test_backend_boot.py
│   ├── test_mock_chat_e2e.py
│   └── test_phase4_integration.py
│
└── performance/           # Neutesting 性能测试层（10 个测试文件）
    ├── knowledge/test_admissionThroughput.py
    ├── memory/test_memoryRecallBenchmark.py
    ├── memory/test_associativeRecallGate.py
    ├── memory/test_longTermMemoryBaselineGate.py
    ├── test_context_pool_load.py
    ├── test_perf_gate_contract.py
    └── ...
```

> 注：`tests/` 下另有 `api/`、`core/`、`llm/`、`test_api/`、`test_memory/`、
> `test_channels/`、`archive/`、`manual/` 等历史目录（合计 59 个测试文件），
> 按 `AGENTS.md` 的测试目录纪律逐步归位到上述标准层。

## 🚀 快速开始

### 安装 Neutesting 依赖

```bash
pip install pytest pytest-cov
```

### 运行 Neutesting 测试套件

pytest 配置集中在仓库根 `pyproject.toml` 的 `[tool.pytest.ini_options]`（`tests/pytest.ini` 不存在）。

```bash
# 使用项目虚拟环境解释器直接跑 pytest（Windows）
.venv/Scripts/python.exe -m pytest tests/ -v

# Linux / macOS
.venv/bin/python -m pytest tests/ -v
```

### 运行 Neutesting 特定测试层

```bash
# 仅运行 Neutesting 单元测试层
pytest tests/unit/ -v

# 仅运行 Neutesting 集成测试层
pytest tests/integration/ -v

# 仅运行 Neutesting 端到端测试层
pytest tests/e2e/ -v

# 运行 Neutesting 性能基准测试（实际性能测试文件见上方目录树）
.venv/Scripts/python.exe -m pytest tests/performance/ -v
```

### 运行特定模块测试

```bash
# 仅运行 core 模块测试
pytest tests/unit/core/ -v

# 仅运行 memory 模块测试
pytest tests/unit/memory/ -v

# 仅运行 security 模块测试
pytest tests/unit/security/ -v
```

### 生成 Neutesting 覆盖率报告

```bash
# 生成覆盖率报告
pytest tests/unit/ --cov=neurova --cov-report=html --cov-report=term

# 查看HTML报告
open htmlcov/index.html  # macOS
# 或在浏览器中打开 htmlcov/index.html
```

## 🧪 Neutesting 测试类型说明

### 1. 单元测试层 (Unit Tests)

位置: `tests/unit/`

- 测试单个函数或类的独立功能
- 不依赖外部系统
- 执行快速，应该经常运行
- 目标: 验证每个组件在隔离状态下的正确性

### 2. 集成测试层 (Integration Tests)

位置: `tests/integration/`

- 测试多个组件一起工作的情况
- 验证模块间的接口和交互
- 测试数据在不同层之间的流动
- 目标: 确保组件集成后能正常协作

### 3. 端到端测试层 (End-to-End Tests)

位置: `tests/e2e/`

- 测试完整的用户场景
- 模拟真实用户操作流程
- 涉及整个系统栈
- 目标: 验证系统在实际使用场景下的完整性

### 4. 性能测试层 (Performance Benchmarks)

位置: `tests/performance/`

- 测试关键组件的性能指标
- 测量吞吐量和响应时间
- 检测性能回归
- 目标: 确保系统性能在可接受范围内

## 🔄 Neutesting CI/CD 集成

项目配置了 GitHub Actions 工作流 (`.github/workflows/ci.yml`)，在以下情况自动运行:

- 推送到 `main` / `master` 分支
- 创建 Pull Request
- 手动触发（`workflow_dispatch`）

Neutesting CI 流程（job 清单实测于 `.github/workflows/ci.yml`，核对基准 2026-11-19）:
1. static-gate — 语法/未定义名快速静态门（pyflakes + ruff）
2. deploy-config / architecture-gate — 部署配置一致性与架构门禁
3. import-and-regression / unit-tests / coverage / e2e — 导入巡检、单元、覆盖率与端到端测试
4. perf-gate — 性能门禁
5. frontend — 前端 vitest 与 vue-tsc
6. dependency-audit / experience-quality — 依赖审计与经验质量门

Python 版本：CI 各 job 实际使用 **3.11 与 3.12**（static-gate、import-and-regression 用 3.11；deploy-config、architecture-gate 用 3.12）。

## ✍️ 编写 Neutesting 测试

### 单元测试指南

1. 命名: `test_<module>_<functionality>.py`
2. 使用 `unittest.TestCase` 或 pytest
3. 保持测试独立，不依赖其他测试
4. 使用有意义的断言
5. 每个测试只验证一个功能点

示例:
```python
import unittest
from neurova.core.config import ConfigManager

class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.config = ConfigManager()

    def test_set_and_get(self):
        self.config.set("key", "value")
        self.assertEqual(self.config.get("key"), "value")
```

### 集成测试指南

1. 使用 pytest fixtures 进行测试环境设置
2. 测试组件间的真实交互
3. 验证数据流转的正确性
4. 测试错误处理和恢复机制

### 端到端测试指南

1. 模拟真实用户场景
2. 测试完整的功能流程
3. 验证系统各部分协同工作
4. 包含常见的用户操作路径

## 最佳实践

1. **测试覆盖率**: 保持核心功能的高测试覆盖率
2. **测试速度**: 单元测试应该快速，慢速测试标记为 `@pytest.mark.slow`
3. **测试独立性**: 每个测试应该可以独立运行
4. **清晰的断言**: 使用清晰的断言信息，便于调试
5. **定期运行**: 在开发过程中经常运行测试
6. **CI 前置**: 在提交代码前确保测试通过

## 故障排除

### 测试失败

1. 检查测试输出中的错误信息
2. 验证测试数据的正确性
3. 确保所有依赖都已正确安装

### 导入错误

确保项目根目录在 Python 路径中:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
```

## 更多资源

- [pytest 文档](https://docs.pytest.org/)
- [unittest 文档](https://docs.python.org/3/library/unittest.html)
- 项目主 README
