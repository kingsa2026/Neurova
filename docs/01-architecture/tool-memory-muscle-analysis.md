# Neurova 工具调用模式与肌肉记忆形成机制分析

> 纯机制分析（不含 OpenManus 对比）｜ 2026-08-29 ｜ 全部结论经代码逐行核实

## 一、工具调用全景：四条路径与肌肉记忆的位置

Neurova 的工具调用有四条独立路径，肌肉记忆位于**最前端**（LLM 介入之前）：

```
用户输入
   │
   ▼
┌─ pre_llm_checks（chat_pipeline:408，LLM 调用之前）─────────────┐
│  check_tool_memory(user_input)                                  │
│    ① 肌肉记忆匹配（match_by_query）→ 动态阈值决策：              │
│       auto_execute（≥阈值）→ _auto_execute_tool 直接执行，       │
│          结果写入 ctx.auto_execute_result，                      │
│          且 llm_call 阶段把该工具从工具列表移除（chat_pipeline:922）│
│       suggest（≥阈值*0.7）→ 结果进提示，LLM 决定                  │
│       do_not_execute → 继续                                      │
│    ② 降级：关键词匹配（tool_stats 成功率加权）                    │
│    ③ 技能获取检查 / NL 合成（另两条前置路径）                     │
└──────────────────────────────────────────────────────────────────┘
   │
   ▼ LLM 调用（llm_call 步骤）
   ├─ 路径A: native function calling（openai_loop → handle_tool_calls
   │         → SkillRegistry → ToolRouter → MCP）
   ├─ 路径B: 文本模式（execute_text_tool_calls，正则解析回复）
   ├─ 路径C: ToolEngine（execute_with_safeguards，带 safeguards 管线）
   └─ 路径D: 蜂群 SwarmManager
   │
   ▼ 每次执行后（反馈回流）
   ToolExecutionManager 的 MemoryRecordingStep（tool_pipeline:115-140）
   → tool_memory.record_tool_usage() → muscle_memory.record_usage()
```

关键特征：**肌肉记忆是"条件反射层"**——在 LLM 看到输入之前就完成"识别→决策→执行"，命中 auto_execute 时该输入根本不会到达 LLM 的工具列表（被移除）。这是 Neurova 区别于常规 Agent 框架的设计。

## 二、肌肉记忆本体解剖

### 2.1 数据结构（muscle_memory.py:37-53）

```
MuscleMemoryItem {
  id, tool_name,
  query_fingerprint,      # 查询关键词指纹（_extract_keywords）
  vector_fingerprint,     # 向量指纹（hash 近似，非真 embedding）
  parameters,             # 成功时使用的参数快照
  result_summary,
  level: L1/L2/L3,        # 三级层级
  success_count / failure_count / consecutive_successes,
  last_used               # 遗忘的时间基准
}
```

### 2.2 三级层级与升降级

| 层级 | 语义 | 匹配阈值 | 遗忘策略 |
|---|---|---|---|
| L1 | 条件反射级（毫秒） | conf > 0.7 | 30 天未用 → L2 |
| L2 | 热路径缓存 | conf > 0.5 | 30 天未用 → L3 |
| L3 | 需检索 | conf > 0.3 | 90 天未用 → **删除** |

- **固化（升级）**：`consecutive_successes >= 2` → L3→L2→L1（`_PROMOTE_THRESHOLD = 2`）
- **失败**：`consecutive_successes = 0`（连续成功清零，重新积累）
- **遗忘**：`check_forgotten()` 从 L3→L1 扫描降级/删除（含防级联降级的扫描顺序注释）

### 2.3 置信度公式（_compute_confidence:270-302）

```
score = 0.6 × (指纹精确匹配)         # 或 0.4 × 关键词重叠率
      + 0.3 × (向量指纹相等)
      + 0.1 × (历史成功率)
```

### 2.4 决策阈值

- `dynamic_threshold = muscle_memory_threshold / sqrt(adaptive_multiplier)`，夹在 [0.3, 1.0]；基准 `muscle_memory_threshold` 是 **RSI 可优化参数**（RSI 调它系统行为才会变——注释明确记录了此前"死参数"修复）
- 工具生命周期联动：ARCHIVED/DEGRADED 状态的工具直接跳过肌肉记忆匹配

## 三、闭环生命周期（设计意图）

```
形成：工具执行 → MemoryRecordingStep → record_tool_usage
      → record_usage(query=用户输入) → 指纹命中已有条目则更新，否则新建 L3
固化：连续成功 ≥2 → 升级 L3→L2→L1（响应速度逐级提升）
消费：下一次相似输入 → match_by_query → auto_execute 直接执行（跳过 LLM 工具决策）
反馈：执行成功/失败 → record_tool_usage → 强化/清零
降级：失败 → consecutive_successes=0；生命周期 ARCHIVED → 清理条目
RSI：muscle_memory_threshold / muscle_memory_hits 参与 RSI 优化循环
```

这个设计意图是完整且自洽的——**问题在实现的若干断点**。

## 四、发现的问题（按严重度排序，全部经代码核实）

### P-A【闭环断裂】遗忘机制是死代码

`check_forgotten()`（muscle_memory.py:414）全仓库**无任何调用方**——没有调度器、没有启动钩子、没有定时任务。后果：**记忆只升不降**，L1 永远不遗忘，与"肌肉记忆需要遗忘旧习惯"的设计意图相反；90 天删除永不发生，存储单调增长。

### P-B【闭环断裂】失败降级路径双重字段错误

`agent_core._record_tool_failure_lesson`（agent_core.py:1470-1478）：
- `muscle.items.items()` —— MuscleMemory **没有 `items` 属性**（存储是 `_l1/_l2/_l3` 三个 dict），`hasattr(muscle, "items")` 恒 False → 循环体永不执行
- 即使到了条目，字段名写的是 `item.consecutive_success` —— 实际是 `consecutive_successes`（复数）

双重错误导致"工具失败 → 降级肌肉记忆"的路径**静默失效**（且外层 except 吞掉）。真实效果：失败的肌肉记忆条目不会被降级，下一次同指纹输入照样 auto_execute。

### P-C【回声室效应】命中即记成功

`check_tool_memory` 命中肌肉记忆路径时立即 `record_tool_usage(success=True)`（tool_memory_integration.py:226-234）——**匹配命中本身就记一次成功**。若后续 auto_execute 失败，同一输入会被记"1 成功 + 1 失败"；若成功则"2 成功"。净效果：**越常命中的条目成功率统计越虚高**，置信度公式的 0.1×成功率项被系统性推高——自我强化回路，缺独立校验。

### P-D【阈值语义重叠】两道决策门不一致

`check_tool_memory` 用 `dynamic_threshold`（基准 0.8，RSI 可调）决策 auto_execute；但 `_auto_execute_tool` 又硬编码 `confidence < 0.7` 转 suggest（chat_pipeline.py:452）。两道门语义重叠且 RSI 只能动第一道——RSI 把阈值调到 0.7 以下时，第二道 0.7 硬门仍在，闭环再次出现"调参不生效"的死区（与注释里已修复的"死参数"问题同型）。

### P-E【危险设计+死代码】execute_from_memory 用缓存冒充执行

`tool_executor.py:453-459`：`check_tool_memory(tool_name)`——**把工具名当用户输入传给语义匹配**；且 confidence > 0.8 时直接 `return memory_result.get("result", {})`——**返回记忆中的历史结果而不实际执行工具**。双重问题：(a) 语义错位（工具名≠查询）；(b) `MuscleMemoryItem` 根本没有 `result` 字段 → 永远返回空 dict 冒充执行结果。所幸该方法**无调用方**（实际使用的是 `execute_from_memory_async`，那个是真实执行 ✓）——但留在代码里是隐患。

### P-F【死代码】生命周期清理无触发

`_cleanup_deprecated_tools`（ARCHIVED/DEGRADED 工具的条目清理）同样无调用方——工具下线后其肌肉记忆残留，仍可能被匹配命中。

### P-G【参数双源】阈值基准不一致

`agent_core:323` 的 `muscle_memory_threshold = 0.85`（类属性）与 RSI `system_performance:32` 的默认 0.8 并存；ToolMemoryIntegration 初始化时也未显式传入该参数——三处来源，实际生效值取决于初始化链路，RSI 调参可能调不到实际生效的那份。

## 五、强点（值得保留的设计）

1. **三级层级**本身是优雅的：匹配代价与使用频率挂钩（L1 毫秒级全扫、L3 用关键词索引剪枝）
2. **指纹 + 参数快照**：条目存的不是"工具好用"而是"这类输入用这些参数成功过"——可复现
3. **动态阈值接 RSI**：工具权重 multiplier 调整自动执行激进度，方向正确
4. **生命周期联动**：工具 ARCHIVED 后跳过匹配的守卫（_should_demote_from_muscle_memory）设计正确
5. **并发纪律**：全程 RLock，Bug 15 之类的锁内排序修复有历史沉淀

## 六、修复建议（优先级）

| 优先级 | 项 | 动作 |
|---|---|---|
| 1 | P-B | 修 `_record_tool_failure_lesson`：遍历 `_l1/_l2/_l3`，字段改 `consecutive_successes`；失败路径写红测试 |
| 1 | P-C | 命中时不记 success（只记 hit 统计）；成功/失败由**真实执行结果**单独记录 |
| 2 | P-A | check_forgotten 接入调度（agent 启动后定时/每 N 次请求触发一次） |
| 2 | P-D | 移除 `_auto_execute_tool` 的 0.7 硬门，统一走 dynamic_threshold |
| 3 | P-E | 删除死方法 execute_from_memory（同步版） |
| 3 | P-F | _cleanup_deprecated_tools 接入 tool_lifecycle 变更钩子 |
| 3 | P-G | 阈值单源化：ToolMemoryIntegration 显式从 config 取，RSI 只改一处 |

按既定纪律：每项先红后绿。P-B/P-C 是闭环正确性问题（影响每一次工具执行的学习质量），建议合并为一个批次先做。
