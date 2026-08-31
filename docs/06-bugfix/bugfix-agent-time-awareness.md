# Bugfix: Agent 时间感知失败(误用训练截止日期)

**Bug ID**: T-1
**报告时间**: 2026-06-28
**修复时间**: 2026-06-28
**状态**: 已修复
**严重度**: 中(用户体验受损,但非崩溃)

## 症状

用户问时间相关问题(如"现在几点"、"今天几号"),agent 回复:

> 抱歉,我刚刚尝试获取系统时间,但没能成功 😅
> 目前我没有可用的系统时间工具来直接读取当前时间。

或回答 2025 年 4 月(LLM 训练截止日期),而非真实当前时间(2026 年 6 月 28 日)。

## 根因(分层)

### 第一层:表面原因
LLM 不知道当前真实时间,只能依赖训练时的知识截止日期(GLM 系列约 2025 年 4 月)。

### 第二层:system prompt 未注入时间(首次修复尝试)
[context/orchestrator.py](../../neurova/context/orchestrator.py) 的 `build_system_prompt()` 构造系统提示时**没有注入当前时间**。

**首次修复**:在 `build_system_prompt()` 末尾追加当前时间上下文段(9/9 测试通过)。

### 第三层:build_system_prompt 未被实际调用(真正根因)
首次修复后用户仍报告"没有系统时间工具"。bug-hunt 调查发现:

- `build_system_prompt()` 是**工具方法**,实际 chat 流程**不调用它**
- [chat_pipeline.py:687](../../neurova/agent/chat_pipeline.py#L687) 的 `_step_retrieve_and_build_context()` 调用的是 `build_context()`
- `build_context()` (line 136-523) 在 line 171-180 **独立构造** `system_instructions`,只包含 soul/personality/constitution,**不含时间**
- 首次修复的 `build_system_prompt()` 在这条路径上根本没被调用 → LLM 看不到时间

### 第四层:降级路径也无时间
`build_context()` 的降级路径(line 506-511,当 `context_builder` 不可用时)只返回 `[system: soul, user: user_input]`,同样不含时间。

## 修复

### 修改文件

**[neurova/context/orchestrator.py](../../neurova/context/orchestrator.py)**:

1. **line 19**: 新增 `import datetime`
2. **line 177-180**: 在 `build_context()` 的 `system_instructions` 构造处追加当前时间:
   ```python
   # Bug T-1 修复:注入当前时间上下文
   system_instructions.append(self._build_current_time_section())
   ```
3. **line 506-512**: 降级路径用 `"\n\n".join(system_instructions)` 替代单独的 `self.soul`,确保时间也注入:
   ```python
   return [
       {"role": "system", "content": "\n\n".join(system_instructions)},
       {"role": "user", "content": user_input},
   ]
   ```
4. **line 529-553**: `build_system_prompt()` 也调用 `_build_current_time_section()`(保留,虽然不是主路径,但作为工具方法应保持一致)
5. **line 555-648**: 新增 `_build_current_time_section()` 和 `_get_local_timezone_name()` 方法

### 时间注入格式

```
## 当前时间
当前日期:2026年6月28日 星期日
当前时刻:19:56:19
时区:Asia/Shanghai (UTC+08:00)
提示:以上是系统注入的真实当前时间,请基于此时间回答用户的时间相关问题,不要使用训练数据中的截止日期。
```

### 设计要点

- **动态读取**:每次调用 `build_context` 都用 `datetime.datetime.now()` 读取当前时间,不是构造时刻快照
- **两条路径都注入**:`use_pool=True`(生产路径,走 context_pool)和 `use_pool=False`(降级路径)都注入时间
- **时区感知**:包含 IANA 时区名 + UTC 偏移,避免 LLM 误判时区
- **明确提示 LLM**:段末加"以上是系统注入的真实当前时间,请基于此时间回答用户的时间相关问题,不要使用训练数据中的截止日期"
- **不破坏既有 section**:soul / personality / constitution / behavior_rules / tools_desc 段均保留

### 验证

- `use_pool=True`(生产路径)验证:时间段作为 system message 注入,未被 draw() 丢弃(priority=100 + 关键词匹配"时间"得高分)
- `use_pool=False`(降级路径)验证:时间段拼接到 system message 中

## 测试

**新增测试文件**:[tests/unit/test_current_time_injection.py](../tests/unit/test_current_time_injection.py)

5 个测试类,12 个测试用例:

| 测试类 | 测试数 | 验证内容 |
|--------|--------|----------|
| TestCurrentTimeInjection | 4 | build_system_prompt 包含当前日期/星期/标签/非硬编码 2025 |
| TestTimeInjectionFormat | 3 | 时间 section 可识别/不破坏既有 section/无 tools_desc 也注入 |
| TestTimeInjectionWithTools | 1 | 时间注入与工具描述共存 |
| TestTimeInjectionDeterminism | 1 | 时间注入是动态的(每次调用反映当前时刻) |
| TestBuildContextTimeInjection | 3 | **build_context(实际路径)注入时间/section header/星期** |

测试结果:12/12 GREEN

## 回归

针对性回归 63/63 全部通过:
- test_current_time_injection.py (12)
- test_history_load_bugs.py (15)
- test_chat_dead_endpoints.py (11)
- test_sqlite_orphan_tables.py (10)
- test_weather_capability_bugs.py (13)
- test_tool_bugs_v3.py (2)

## 教训

1. **修复前先确认调用路径**:首次修复改了 `build_system_prompt()`,但实际 chat 流程调用 `build_context()`。应该先 Grep 确认方法是否被实际调用,而非假设。
2. **工具方法 vs 实际路径**:`build_system_prompt()` 看起来像系统提示构造器,但只是个工具方法。`build_context()` 才是实际路径。命名误导导致首次修复无效。
3. **降级路径也要修复**:`build_context()` 的降级路径(context_builder 不可用时)同样需要注入时间,否则在 context_builder 异常时仍会复现 bug。
4. **bug-hunt 五阶段流程有效**:用户第二次报告"没有系统时间工具"后,通过 Phase 1(top-down localization)Grep `build_system_prompt\(\)` 调用点,立刻发现实际路径是 `build_context()`。

## 相关文件

- [neurova/context/orchestrator.py](../../neurova/context/orchestrator.py) — 修复主文件
- [neurova/context/injector.py:412](../../neurova/context/injector.py#L412) — 已有一段时间注入(`%Y年%m月%d日 %H:%M`),但格式简单,且 injector 不是主路径
- [neurova/agent/chat_pipeline.py:687](../../neurova/agent/chat_pipeline.py#L687) — 实际调用 build_context 的入口
- [tests/unit/test_current_time_injection.py](../tests/unit/test_current_time_injection.py) — TDD 测试
