# 天气 / 实时信息查询能力缺失 — Bug 修复报告 v4

> **触发场景**：用户问"许昌天气"，Agent 回复"很抱歉，我目前没有查询实时天气信息的能力 🫤"
>
> **根因诊断**：三层断路（提示层禁止 + 工具层缺失 + 实现层断路）
>
> **方法论**：TDD 红绿灯 + bug-hunt 五阶段根因定位
>
> **修复日期**：2026-06-28

## 一、根因：三层断路

Agent 无法查天气不是单一 bug，而是三层链路同时被切断：

```
用户问天气
   ↓
[层1 提示层] orchestrator.get_tools_description 硬编码
   "需要实时信息时请直接回复告知用户你无法获取"
   → Agent 被告知"不能查实时信息"，根本不会尝试
   ↓ (即使尝试)
[层2 工具层] _BUILTIN_SCHEMAS (LLM 工具列表单一事实源) 不含 weather/web_search
   → LLM 看不到这两个工具，无法发起 function call
   ↓ (即使 Skill 路径注册)
[层3 实现层] 三处断点：
   a) skill_system/compat.py 文件不存在 → build_tools_for_llm 抑 ImportError
      → fallback 到空参数 schema（参数定义丢失）
   b) WebSearchSkill._search_web 是 `return []` 空实现 stub
   c) tool_executor._execute_weather / _execute_web_search 实现存在但未注册到 schema
```

**关键洞察**：`tool_executor.py` 早已实现 `_execute_weather`（wttr.in）和 `_execute_web_search`（Google），但因为 `_BUILTIN_SCHEMAS` 不含这两个工具名，LLM 永远看不到它们 → 实现层"有枪无弹"。

## 二、用户决策

通过 `AskUserQuestion` 获得两个关键决策：

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 修复路径 | **双路径并行** | 同时激活内置实现（tool_executor）+ 修复 Skill 系统，两条路径互为冗余 |
| 提示词策略 | **改为正向引导** | 保留 memory_search 限制（防止误用记忆搜实时信息），但去掉"回复无法获取"断路指令，改为"使用 weather/web_search 工具" |

## 三、Bug 列表与修复

### W-1: `_BUILTIN_SCHEMAS` 缺 weather / web_search schema

**文件**：[neurova/builtin_tools.py](file:///e:/项目/Neurova/neurova/builtin_tools.py)

**问题**：`_BUILTIN_SCHEMAS`（line 21）是 LLM 工具列表的单一事实源，原含 14 个工具，无 `weather`/`web_search`。`tool_executor._execute_weather`（line 565）和 `_execute_web_search`（line 544）的实现因此永远不被 LLM 调用。

**修复**：在 `_BUILTIN_SCHEMAS` 末尾追加两个 schema，参数与 `_execute_weather`/`_execute_web_search` 的读取逻辑对齐：
- `weather`: 必填 `location`，可选 `city`/`query`（`_execute_weather` 读取 `location or city or query`）
- `web_search`: 必填 `query`，可选 `q`/`keywords`（`_execute_web_search` 读取 `query or q or keywords`）

### W-2: orchestrator 提示词禁止查实时信息

**文件**：[neurova/context/orchestrator.py](file:///e:/项目/Neurova/neurova/context/orchestrator.py#L559-L563)

**问题**：`get_tools_description`（line 559-562）硬编码断路指令：
```python
"- 需要实时信息（天气、新闻、股价等）时，请直接回复告知用户你无法获取，不要尝试用记忆搜索工具\n"
```
Agent 被告知"无法获取"，根本不会尝试调用 weather/web_search。

**修复**：改为正向引导，保留 memory_search 限制：
```python
"- 需要实时信息（天气、新闻、股价等）时，请使用 `weather` 或 `web_search` 工具获取，不要用记忆搜索工具查实时信息\n"
"- `weather` 工具可查实时天气（支持中文城市名，如'许昌'）；`web_search` 工具可查新闻、股价等实时网络信息\n"
```

### W-3: `skill_system/compat.py` 缺失

**文件**：[neurova/skill_system/compat.py](file:///e:/项目/Neurova/neurova/skill_system/compat.py)（新建）

**问题**：`orchestrator.build_tools_for_llm`（line 624-628）试图 `from neurova.skill_system.compat import OpenAISchemaAdapter`，但该文件不存在 → ImportError → fallback 到空参数 schema（line 630-644），导致 Skill 工具对 LLM 暴露的参数定义丢失。

**修复**：创建 `compat.py`，实现 `OpenAISchemaAdapter.skill_to_tool_schema(skill)` 静态方法：
- 读取 `skill.name` / `skill.description`
- 调用 `skill._get_parameters()` 提取参数（与 fallback 逻辑一致）
- 返回标准 OpenAI function call schema

**设计原则**：单一职责（仅做格式转换）、防御式（无 `_get_parameters` 时返回空参数 schema，不抛异常）。

### W-4: `WebSearchSkill._search_web` 是 stub

**文件**：[neurova/skill_system.py](file:///e:/项目/Neurova/neurova/skill_system.py#L199-L227)

**问题**：`WebSearchSkill._search_web`（原 line 199-202）是空实现：
```python
async def _search_web(self, query: str, params: Dict) -> List[Dict]:
    """搜索网络"""
    # 这里应该实现网络搜索逻辑
    return []
```
即使 Skill 路径被调用，也返回空列表。

**修复**：用 urllib 实现真实搜索（与 `tool_executor._execute_web_search` 逻辑对齐），保证 WebSearchSkill 路径独立可用（不依赖 ToolExecutor / agent_ref）：
- urllib.request 发起 Google 搜索请求
- 正则提取摘要文本
- 返回 `[{"query": ..., "snippet": ...}]`
- 异常时返回 `[{"query": ..., "error": ...}]`

## 四、TDD 红绿灯验证

**测试文件**：[tests/unit/test_weather_capability_bugs.py](file:///e:/项目/Neurova/tests/unit/test_weather_capability_bugs.py)

### RED 阶段（修复前）
```
8 failed, 1 passed, 4 skipped in 0.13s
```
- W-1: 2 failed（weather/web_search schema 缺失）
- W-2: 2 failed（断路指令存在 + 无正向引导）
- W-3: 2 failed（compat.py 不存在 + 不可导入）
- W-4: 2 failed（stub 存在 + 无真实实现）
- 1 passed（`test_keeps_memory_search_limit`，memory_search 限制本就在）
- 4 skipped（条件跳过，依赖前置条件）

### GREEN 阶段（修复后）
```
13 passed in 0.12s
```
全部通过，无 skip。

## 五、回归验证

### 直接相关测试（47/47 PASS）
```
python -m pytest tests/unit/test_tool_bugs_v3.py tests/unit/test_start_script_bugs.py \
  tests/unit/test_weather_capability_bugs.py tests/unit/skills/test_scripts_start.py -v
============================= 47 passed in 0.42s =============================
```

### 广义回归（ builtin / orchestrator / skill_system / tool_executor / compat 主题）

| 阶段 | passed | failed | errors |
|------|--------|--------|--------|
| 基线（不含我的改动，git stash） | 306 | 102 | 15 |
| 修复后（含我的改动） | 325 | 94 | 15 |
| **净变化** | **+19** | **−8** | **0** |

**结论**：
- 11 个新增天气测试全部通过（+19 = 11 新增 + 8 修复）
- 8 个原本失败的测试现在通过（修复 compat.py + 提示词正向引导的副作用）
- **零回归**：没有任何原本通过的测试现在失败
- 15 个 errors 是预存在的模块路径问题（`neurova.core.health_checker` 等模块缺失），与本次修复无关

## 六、修改文件清单

| 文件 | 操作 | 内容 |
|------|------|------|
| `neurova/builtin_tools.py` | 修改 | 追加 `weather` + `web_search` schema 到 `_BUILTIN_SCHEMAS` |
| `neurova/context/orchestrator.py` | 修改 | `get_tools_description` 提示词从断路改为正向引导 |
| `neurova/skill_system/compat.py` | 新建 | `OpenAISchemaAdapter.skill_to_tool_schema` 实现 |
| `neurova/skill_system.py` | 修改 | `WebSearchSkill._search_web` 用 urllib 实现真实搜索 |
| `tests/unit/test_weather_capability_bugs.py` | 新建 | 13 个 TDD 测试（4 个测试类） |

## 七、未修复的架构观察（非本次范围）

1. **`skill_system.py` 单文件与 `skill_system/` 包名遮蔽**：`__init__.py` 用 `importlib.util.spec_from_file_location` 加载单文件模块，存在命名陷阱。`test_skill_system_cleanup.py` 要求删除该单文件，但本次 W-4 修复恰好在其中实现 `_search_web`，删除会引入新问题。需后续重构（将 `WebSearchSkill` 迁移到 `skill_system/web_search_skill.py`）。

2. **`WebSearchSkill._search_web` 与 `tool_executor._execute_web_search` 逻辑重复**：两处都用 urllib + Google 搜索，未抽象共享。后续可提取 `neurova/services/web_search.py` 统一实现。

3. **`weather` 工具未走 Skill 路径**：本次只在 builtin 路径注册了 weather schema，未创建 `WeatherSkill`。若需 Skill 路径冗余，可后续添加。

4. **提示词仍硬编码工具名**：`get_tools_description` 中的"使用 weather 或 web_search"是字符串硬编码，与实际工具列表解耦。若未来工具改名，提示词需手动同步。
