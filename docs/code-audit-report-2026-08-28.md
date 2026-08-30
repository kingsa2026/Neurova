# Neurova 全量代码审计报告

- **审计日期**：2026-08-28
- **审计范围**：`neurova/`（665 个模块）、`tests/`、`scripts/`，共 **1458 个 Python 文件**
- **测试基线**：收集 **7846** 个用例，基线 **1215 failed / 345 errors / 6385 passed**
- **审计方法**：AST 全量语法扫描 → pyflakes 静态分析 → 全模块导入检查 → 完整单元测试套件 → 根因聚类

---

## 一、审计结论摘要

| 指标 | 审计前 | 审计后 |
|------|--------|--------|
| 语法错误 | 3 | **0** |
| 模块导入失败 | 11 | **2**（均为环境缺依赖） |
| 未定义名称（NameError 隐患） | 53 处 / 36 文件 | **0** |
| 生产代码 linter 错误 | — | **0** |
| 回归测试 | — | **+23（全部通过）** |

**核心结论**：项目最大的问题不是零散的逻辑错误，而是两类系统性缺陷——
1. **一批模块因语法/导入错误完全不可用**（发现时 `computer_use` 视觉模块、模型适配器、`memory/scripts` 均无法导入）；
2. **大量 `import` 被误写成 `pass`**，导致依赖可用性探测形同虚设。

> 关于 1215 个测试失败：经根因聚类，其中**绝大多数属于「测试债务」**（测试按规划中的 API 编写，实现从未跟上），
> 而非生产代码缺陷。详见第五节。

---

## 二、P0 — 致命缺陷（模块不可用 / 核心链路崩溃）

### 1. ToolCall 默认 ID 生成必然崩溃 ⭐ 影响最广

**文件**：`neurova/cognitive_layers/model_adapter/base.py:26`

```python
id: str = Field(default_factory=lambda: f"call_{id(self)}")   # 缺陷
```

**根因**：类体作用域**不参与闭包链**。lambda 定义在类体中，其闭包只捕获外层函数作用域与全局作用域，
`self` 只能在全局命名空间查找，必然 `NameError`。

**影响**：`ToolCall` 是工具调用的核心数据结构，贯穿全部 `parse_tool_call()` 实现。
任何未显式传入 `id` 的构造都会崩溃 —— 即整个 function calling 链路。

**修复**：改用 `uuid4`。

```python
id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")
```

---

### 2. 模型适配器注册表整体不可用

**文件**：`neurova/cognitive_layers/model_adapter/registry.py`

两处缺陷叠加，导致 `model_adapter.builtin` 完全无法导入，模型路由失效：

1. **pydantic v2 私有属性未声明** —— `GenericAdapter.__init__` 中 `self._clients = {}` 抛
   `ValueError: "GenericAdapter" object has no field "_clients"`。pydantic v2 中下划线开头的
   私有属性必须用 `PrivateAttr` 声明。
2. **`register_adapter_pattern()` 方法根本不存在** —— `builtin.py:636` 调用它注册 9 类模型适配器。

**修复**：
- 用 `PrivateAttr(default_factory=dict)` 声明 `_clients`；
- 补齐 `register_adapter_pattern(pattern, adapter_class, priority)`。由于 builtin 适配器
  继承 `BaseModelAdapter`（构造需具体 `model_name`），而注册发生在导入期，实现惰性包装器
  `_LazyPatternAdapter`，匹配到模型后再用真实 model_name 实例化并缓存。

**验证**：模型路由恢复正常（deepseek-chat、claude-3 均能正确匹配，未知模型回落 generic）。

---

### 3. 四处 `import` 被误写成 `pass` ⭐ 系统性缺陷

同一模式出现在 4 个文件：`try:` 块内的 `import X` 被替换为 `pass`，
导致**可用性标志恒为 `True`，而目标名字从未绑定**；部分还在 `except` 分支引用未导入的名字，造成二次崩溃。

| 文件 | 缺失的导入 | 后果 |
|------|-----------|------|
| `neurova/agent_core.py:84` | Agent Loop 探测 | `AGENT_LOOP_AVAILABLE` 恒为 True，`rebuild_loop()` 失去降级保护 |
| `neurova/channels/qclaw_service.py:18` | `requests` + `logging` | 请求全崩；`except` 分支也因 `logging` 未导入而崩 |
| `neurova/channels/sip.py:27` | `requests` | SIP 渠道请求全崩 |
| `neurova/channels/qqbot.py:32` | `httpx` + `logger` | HTTP 调用与日志全崩 |

这是历史遗留现象「Agent Loop 系统不可用警告」的真正根因 —— 并非「预期行为」。

---

### 4. computer_use 视觉三模块 dataclass 字段顺序错误

**文件**：`neurova/computer_use/vision.py`、`vision_basic.py`、`vision_lite.py`

```python
@dataclass
class UIElement:
    element_type: str      # 基类无默认值
    bbox: BoundingBox      # 无默认值

@dataclass
class IconElement(UIElement):
    element_type: str = "icon"   # 子类赋默认值
```

**根因**：dataclass 继承时字段按基类顺序排列。子类给 `element_type` 赋默认值后，
其后的 `bbox`（无默认值）违反「非默认字段不得跟在默认字段之后」，抛
`TypeError: non-default argument 'bbox' follows default argument`。

**修复**：将 `bbox` 前置为首个字段。已确认全部构造点均使用关键字参数，顺序调整无副作用。

---

### 5. `memory_layer` 星号导入在依赖缺失时崩溃

**文件**：`neurova/cognitive_layers/memory_layer/__init__.py`

`__all__` 无条件声明了 `MemoryFieldNetwork` 等可选模块（NeRF/torch 系列）的名字，
但这些名字的导入包在 `try/except ImportError` 中。依赖缺失时名字不绑定，
`from ... import *` 抛 `AttributeError`。

**修复**：`__all__ = [name for name in __all__ if name in globals()]`，按实际可用性裁剪。

---

### 6. 5 个 memory 脚本引用不存在的模块

**文件**：`neurova/memory/scripts/`（init_memories、save_kai_letter、save_kai_letter_3、
save_precious_memories、save_tonight_story）

```python
from memory.core.manager import MemoryManager   # 该模块根本不存在
```

`neurova/memory/core/` 下只有 `cache.py`。同时 `sys.path` 层级计算也少了一级。

**修复**：改为 `from neurova.cognitive_layers.memory_layer.manager import MemoryManager`，
并修正 `project_root` 层级。修复后又暴露 `mm.count()` 调用不存在的 API，一并改为
`mm.get_stats()["total_memories"]`。

---

## 三、P1 — 功能失效类缺陷

| # | 文件 | 缺陷 | 影响 |
|---|------|------|------|
| 1 | `memory_layer/conflict.py` | `_check_contradiction()` 在 `return` 之后残留 17 行引用 `content1`/`memory1`/`similarity` 等**不存在变量**的死代码 | 不可达代码；否定词冲突检测在主流程中已完整实现，残留块纯属历史遗留 |
| 2 | `memory_layer/proactive_recall.py:403` | `config.get("emotions", [])` 返回值**被丢弃**，下方使用未定义的 `target_emotion` | 情感触发回忆**整体失效**（必抛 NameError） |
| 3 | `api/endpoints/firewall.py:369` | 引用不存在的模块级变量 `_firewall_rules_store`，且 `'_firewall_rules_store' in dir()` 判断恒为 False | NameError 被 `except` 吞掉，`/stats` 统计**永远返回全 0** |
| 4 | `auth/verification_code.py:705` | `verification_code_model._conn.close()` 缺少下划线前缀 | 重置时 NameError，**数据库连接泄漏**且实例无法置空 |
| 5 | `language/models.py:308` | `"alternatives": selfalternatives` 应为 `self.alternatives` | 翻译结果 `to_dict()` 崩溃 |
| 6 | `agent_core.py` `_init_router()` | 缺失局部导入 `create_default_skills`（同函数其余两处均有） | Agent 初始化链路 NameError |
| 7 | `context/injector.py:44` | `_logging.getLogger(...)` 应为 `logging.getLogger(...)` | BaseModule 降级路径崩溃 |

防火墙 `/stats` 的修复顺带修正了原本 `blocked_ips` / `blocked_paths` 恒返回 0 的问题
—— 现在从真实数据源 `get_firewall().get_global_rules()` 读取。

---

## 四、P2 — 健壮性与类型解析缺陷

### 1. 53 处未定义名称（36 个文件）

按类别全部修复：

- **缺失 `typing` 导入**（`Optional`/`Dict`/`Any`/`List`/`Tuple`/`Union`）：
  `context_pool.py`、`collaboration/neurflow/execution_engine.py`、`agent/protocols/agent_adapter.py`、
  `meta_cognition_layer/models.py`、`meta_cognition_layer/growth_log.py`、
  `emotion_context_layer/emotion_conduction.py`、4 个 `llm/providers/*_provider.py`
- **缺失标准库导入**：`time`（`plan_orchestrator.py`、`lm_studio_provider.py`）、
  `secrets`（`secret_store_clean.py`）、`asyncio`（`benchmark/__init__.py`）、
  `hmac`（`channels/dingtalk.py`、`channels/qq.py`）
- **可选依赖标注**：`numpy`（`asr/funasr_engine.py`）、`aiohttp`（`api/openplatform/events.py`）
  改用 `TYPE_CHECKING` + 字符串注解，避免依赖缺失时崩溃

> 说明：这类缺陷在运行时**不一定**立即可见（部分因 `from __future__ import annotations`
> 延迟求值），但一旦被 Pydantic / FastAPI 的 `get_type_hints()` 触发，就会在启动期崩溃。

### 2. 字符串注解引用的名字从未导入

`storage.py` / `sleep.py`（`IsolationContext`）、`task_decomposer.py`（`SkillChain`）、
`auto_skill_improver.py`（`OptimizedPrompt`）、`agent_core.py`（`SkillManifestProvider`）、
3 个 `agent/loops/*.py`（`Agent`）—— 统一补齐 `TYPE_CHECKING` 条件导入。

### 3. logger.py 非法日志级别导致业务中断

`_should_log()` 中 `level_order.index(level)`，当调用方传入非 `LogLevel` 值（如字符串）
时抛 `ValueError`，进而中断业务调用。改为捕获后降级为「放行」。

### 4. 3 个语法错误

| 文件 | 缺陷 |
|------|------|
| `scripts/verify_cli_commands.py:107` | `results.append((...)` 缺失右括号 |
| `scripts/diagnose_post_issue.py:79` | f-string 未闭合引号 |
| `tests/comprehensive_test_runner.py:126` | f-string 括号与引号不匹配 |

---

## 五、P3 — 架构缺陷：ADR 0011 技能系统迁移未完成

`neurova/skill_system/`（包）与 `neurova/skill_system.py`（同名单文件，被包遮蔽）并存，
`SkillEvent` / `SkillRegistry` 只能通过包的 `__getattr__` 反射加载。ADR 0011 要求统一收敛到
`neurova.skills` 门面，但：

- `neurova/skills/events.py` 模块**缺失**；
- `agent_core.py` 仍从 `neurova.skill_system` 直接导入 `create_default_skills`（3 处）与 `SkillEvent`。

**修复**：新建 `neurova/skills/events.py` 门面模块；`agent_core.py` 改为
`from neurova.skills.events import SkillEvent, SkillRegistry`、
`from neurova.skills import create_default_skills`。

对应测试 `tests/unit/agent/test_agent_core_skill_imports.py` 由 3 失败 → **5 全通过**。

---

## 六、测试套件失败根因分析

基线 **1215 failed / 345 errors**。按根因聚类后，**主体是测试债务，不是生产代码缺陷**。

### 典型模式

**模式 A：测试按规划中（未实现的）API 编写**

最大失败源 `tests/unit/agent/test_p0_p1_refactor.py`（25 个失败）：
断言 `ToolExecutor._parse_params` 存在，但该方法在全代码库中**从未实现**
—— 参数解析实际内联在各调用点（`execute_text_tool_calls` 中的 `json.loads` 等）。

**模式 B：测试未适配 async 接口**

```python
assert pipeline._step_save_session(...) == 's1'
# 实际得到 <coroutine object ...>，测试未 await
```

**模式 C：测试期望的方法/属性与实现命名不一致**

- `test_agent_config.py`：期望 `base_path` / `agents_file` / `models_file`，
  实现中为 `_config_dir` / `_agents_file` / `_models_file`
- `test_logger.py`：期望 `LogEntry.to_json`，实现中不存在
- `test_constitution.py`：未按 `ConstitutionRule` 的必填参数构造
- `test_performance.py`：传 `MemoryCache(max_size=...)`，实现中无该参数

**模式 D：测试用错事件总线 API**

`test_event_bus_comprehensive.py` 把 `Event` 对象传给 `publish(event_name: str, ...)`，
触发 `unhashable type: 'Event'`。

### 建议

测试债务的修复应作为**独立专项**推进，按「对齐测试到真实实现」处理，
而非反向改生产代码去迁就测试 —— 除非测试反映的是已确认的产品意图。

---

## 七、环境问题（非代码缺陷）

`numpy` 与 `onnxruntime` 未在环境中安装，导致 2 个模块无法导入：

- `neurova/cognitive_layers/memory_layer/memory_field.py`
- `neurova/embedding/onnx_embedding.py`

二者均已在 `requirements.txt` 中声明（`numpy>=1.24.0`、`onnxruntime>=1.16.0`），
属于**环境依赖未安装**，执行 `pip install -r requirements.txt` 即可解决。

> 附带发现：`memory_field.py` 硬依赖 `torch`，但 `torch` 未在 `requirements.txt` 中声明。
> 该模块已被 `memory_layer/__init__.py` 用 `try/except` 正确降级，暂不影响系统，
> 但依赖声明不完整，建议补入可选依赖组。

---

## 八、回归测试

新增 `tests/unit/test_audit_regressions.py`（**23 个测试，全部通过**），
按缺陷类别固化本次修复，每个测试类注释中记录根因：

- `TestToolCallDefaultId` — 默认 ID 不再崩溃且唯一
- `TestModelAdapterRegistry` — 内置适配器注册与模型路由
- `TestMemoryLayerExports` — `__all__` 与星号导入
- `TestSkillsEventsFacade` — ADR 0011 门面
- `TestOptionalDependencyGuards` — 可用性标志与实际导入状态一致
- `TestDeletedDeadCode` — 冲突检测主流程
- `TestProactiveRecallEmotionTrigger` / `TestFirewallStatsEndpoint` — 功能失效修复
- `TestSyntaxErrorsFixed` — 3 个语法错误文件可解析

---

## 九、修改文件清单（35 个生产文件 + 1 个新增测试）

**模型/Adapter**：`model_adapter/registry.py`、`model_adapter/base.py`、`model_adapter/builtin.py`（间接受益）
**视觉**：`computer_use/vision.py`、`vision_basic.py`、`vision_lite.py`
**核心**：`agent_core.py`、`context_pool.py`、`core/logger.py`、`core/plan_orchestrator.py`、`context/injector.py`
**记忆**：`memory_layer/__init__.py`、`conflict.py`、`proactive_recall.py`、`storage.py`、`sleep.py`
**脚本**：`memory/scripts/` × 5
**渠道**：`qclaw_service.py`、`dingtalk.py`、`qq.py`、`sip.py`、`qqbot.py`
**LLM**：`llm/providers/` × 6
**其他**：`benchmark/__init__.py`、`api/openplatform/events.py`、`api/endpoints/firewall.py`、
`auth/verification_code.py`、`language/models.py`、`asr/funasr_engine.py`、
`collaboration/neurflow/execution_engine.py`、`agent/protocols/agent_adapter.py`、
`meta_cognition_layer/models.py`、`meta_cognition_layer/growth_log.py`、
`emotion_context_layer/emotion_conduction.py`、`agent/loops/` × 3、
`skills/task_decomposer.py`、`skills/auto_skill_improver.py`
**新增**：`skills/events.py`
**修复脚本/测试**：`scripts/verify_cli_commands.py`、`scripts/diagnose_post_issue.py`、`tests/comprehensive_test_runner.py`

---

## 十、后续建议（按 ROI 排序）

1. **专项清理测试债务**（约 1200 个失败）—— 工作量最大但收益最直接：
   当前测试套件已失去「质量信号」作用，无法用于回归防护。
2. **统一两套技能系统**（ADR 0011）—— 消除 `skill_system` 包/单文件遮蔽的反射黑魔法。
3. **补齐 `torch` 可选依赖声明**，或为 `memory_field.py` 添加 `try/except` 降级。
4. **引入 CI 门禁**：本次发现的全部缺陷（语法错误、未定义名称、导入失败）
   均可通过 `pyflakes` + 全模块导入检查在 CI 中自动拦截，成本极低。
5. **Agent 类深度模块化**（已有既定规划）—— 2213 行 / 37 方法，变更风险持续偏高。
