
# Neutesting - Neurova 官方测试框架

<div align="center">

**Neurova × Testing Framework**

</div>

---

## 📖 概述

**Neutesting** 是为 Neurova 项目设计的现代化、完整的测试框架体系。它建立了从单元测试到端到端测试的完整测试金字塔。

## ✨ 特性

- 🎯 **四层测试体系** - 单元、集成、E2E、性能四层完整覆盖
- ⚡ **快速执行** - 优化的测试组织和执行
- 📊 **性能监控** - 内置性能基准测试
- 🔄 **CI/CD 集成** - 完整的自动化工作流
- 📝 **详细文档** - 完整的使用指南
- ✅ **高通过率** - 418/419 测试通过 (99.8%)

## 🏗️ 架构

```
Neutesting 测试金字塔
    ┌─────────────────┐
    │   端到端测试层   │ ← 用户场景完整验证
    ├─────────────────┤
    │   集成测试层     │ ← 模块间交互验证
    ├─────────────────┤
    │   单元测试层     │ ← 组件功能验证
    └─────────────────┘
           ↓
    ┌─────────────────┐
    │  性能基准测试   │ ← 性能监控
    └─────────────────┘
```

## 📊 测试覆盖率

| 模块 | 测试数 | 状态 |
|------|--------|------|
| core | 68 | ✅ |
| memory | 165 | ✅ |
| security | 41 | ✅ |
| admin | 56 | ✅ |
| api | 12 | ✅ |
| auth | 12 | ✅ |
| projects | 19 | ✅ |
| channels | 11 | ✅ |
| execution | 9 | ✅ |
| skills | 9 | ✅ |
| cognitive | 9 | ✅ |
| llm | 7 | ✅ |
| **总计** | **419** | **✅ 418 通过** |

## 🐛 已修复的 Bug

- MemoryStorage 死锁问题 (非重入锁)
- MemoryManager API 不匹配 (stats vs get_stats)
- MemoryManager relate 方法调用错误
- MemoryManager recall_graph 方法调用错误
- EmotionAnalyzer 类型不匹配 (tuple vs dict)
- EmotionAnalyzer 缺失 get_emotion_distribution 方法

## 📂 目录结构

```
tests/
├── unit/              # 单元测试层 (419 测试)
│   ├── core/         # 核心模块
│   ├── memory/       # Memory 模块 (165 测试)
│   ├── security/     # 安全模块
│   ├── admin/       # 管理模块
│   ├── api/         # API 模块
│   ├── auth/        # 认证模块
│   ├── projects/     # 项目模块
│   ├── channels/     # 通道模块
│   ├── execution/    # 执行模块
│   ├── skills/      # 技能模块
│   ├── cognitive/    # 认知模块
│   └── llm/         # LLM 模块
├── integration/       # 集成测试层
├── e2e/             # 端到端测试层
└── performance/      # 性能测试层
```

## 🚀 快速开始

### 安装依赖

```bash
pip install pytest pytest-cov
```

### 运行测试

```bash
# 运行所有 Neutesting 完整测试套件
python tests/run_all_tests.py

# 或使用 pytest
pytest tests/unit/ -v
```

## 🎯 测试层说明

### 1. 单元测试层 (tests/unit/)

测试单个组件的功能，快速反馈。

### 2. 集成测试层 (tests/integration/)

测试模块间的协作和数据流。

### 3. 端到端测试层 (tests/e2e/)

测试完整的用户工作流。

### 4. 性能测试层 (tests/performance/)

测试性能基准和性能回归。

## 🔧 配置

- [pytest.ini](../pytest.ini) - pytest 配置文件
- [.github/workflows/ci.yml](../.github/workflows/ci.yml) - CI/CD 工作流

## 📚 文档

- [README.md](README.md) - 详细使用文档
- [NEUTESTING.md](NEUTESTING.md) - 本文档

## 📄 许可证

与 Neurova 项目使用相同的许可证。

---

**Neutesting** - 为 Neurova 保驾护航 🛡️
