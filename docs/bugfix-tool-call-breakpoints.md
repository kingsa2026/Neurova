# Bug 报告:Agent 工具调用断点修复

**Bug ID**: TOOL-CALL-BREAKPOINTS-V1+V2+V3
**调查日期**: 2026-07-02
**调查方法**: bug-hunt 五阶段 + TDD RED-GREEN + zoom-out 架构深化 + improve-codebase-architecture
**症状**: 工具触发但执行错误 / 聊天对话触发工具失败
**状态**: 已修复(12 个断点,19 个测试 GREEN)

---

## 0. 复现 & 成功标准

**复现**: 用户报告 agent 在聊天中触发工具,但工具执行错误;且聊天对话触发工具失败。

**成功标准**:
1. Skill 工具(MemorySkill/WebSearchSkill/FileOperationSkill 等)能进入 LLM tools 列表
2. tool message 含 name 字段,OpenAI 兼容 API 不再 400
3. _tools_supported 一次性 400 后不再永久禁用
4. LLM 拿到对话历史,工具参数指代清晰
5. SkillRegistry 异常时 fallback 到 ToolRouter
6. 合成工具能注册到 SkillRegistry
7. 流式分支不抛 TypeError
8. `_resolve_skill_tool` 能正确解包类 B 的 `Dict[str, Tuple[Skill, Path]]` 元组(V2-7)
9. `_build_tools_from_skills` 死代码已删除(V2-8)

---

## 1. 定位 — 层表 + 命名假设

| 层 | 文件:行 | 假设 |
|---|---|---|
| API | console.py:134 | 强制 history_for_agent = [] |
| API | chat.py:133,225 | 强制 {"history": []} |
| API | console.py:445 | WebSocket metadata={"history": []} |
| Loop | openai_loop.py:80 | _tools_supported 永久 False |
| Loop | base.py:149,174,192 | tool message 缺 name 字段 |
| Loop | base.py:102 | SkillRegistry 异常不 fallback |
| Skill | skill_system.py:293 | SkillRegistry 无 skills property |
| Skill | skill_system.py:301 | SkillRegistry 无 register_skill 方法 |
| ToolRouter | tool_router.py:200 | isinstance(skills, dict) 不匹配 list |
| ToolRouter | tool_router.py:200 | dict 值是元组不解包 |
| Pipeline | chat_pipeline.py:647 | register_skill(manifest, path) 不存在 |
| Pipeline | chat_pipeline.py:890 | 流式 predict_step 缺 await |

---

## 2. 全链路埋点

使用 `[TOOLBUG]` 前缀的日志(已在 base.py:81-86 注入),输出:

```
INFO [TOOLBUG] skill_registry=True (type=SkillRegistry), tool_router=True (type=ToolRouter), tool_name=weather
WARNING SkillRegistry 执行 weather 抛异常,尝试 ToolRouter fallback: skill bug
INFO Tool executed via ToolRouter: weather
```

确认 SkillRegistry → ToolRouter fallback 链路在 V2-4 修复后能工作。

---

## 3. 根因 — 分层因果链

### 第一批(V1)— 工具执行错误

```
工具触发 → base.py 构造 tool message 缺 name 字段
  → DeepSeek/通义/智谱/Kimi strict 模式 400
  → openai_loop.py 一次性 400 后 _tools_supported = False
  → 后续所有 chat 都不注入 tools,工具调用静默失效
  → SkillRegistry 异常直接进 except,不 fallback ToolRouter
  → 工具触发但执行错误
```

叠加效应:console.py 强制传空历史 → LLM 缺对话上下文 → 工具参数指代不清("搜一下他"不知道"他"是谁)。

### 第二批(V2)— Skill 工具不可见 + 合成工具不可注册

```
SkillRegistry 双实现 API 不匹配:
  类 A(neurova/skill_system.py): _skills: Dict[str, Skill], register(skill), list_skills() → List[SkillInfo]
  类 B(neurova/skills/registry.py): skills: Dict[str, Tuple[Skill, Path]], register_skill(manifest, path)

但 orchestrator.py:731 / base.py:241 用类 B 的 .skills 访问类 A → AttributeError
但 tool_router.py:200 用 isinstance(skills, dict) 检查 list → False
但 chat_pipeline.py:647 用类 B 的 register_skill(manifest, path) → AttributeError

三重失败:
  1. orchestrator 路径:Skill 工具不进 LLM tools 列表
  2. tool_router 路径:Skill 工具第二条发现路径也断
  3. chat_pipeline 路径:合成工具永远无法注册到 registry

→ Skill 工具(MemorySkill/WebSearchSkill/FileOperationSkill)永远不暴露给 LLM
→ "聊天对话触发工具"失败的核心根因
```

### 流式分支 latent bug

```
chat_pipeline.py:890: gen = self.loop.predict_step(...stream=True)
  → predict_step 是 async def,返回 coroutine
  → async for event in gen: 对 coroutine 迭代
  → TypeError: 'coroutine' object is not async iterable
  → 当前 latent(因 chat.py /chat/stream 走非流式 fallback),但任何
    直接调用 agent.chat(stream=True) 的代码会触发
```

---

## 4. 手术式修复

### V1 修复(4 个断点)

**B-5**: [neurova/agent/loops/base.py](file:///e:/项目/Neurova/neurova/agent/loops/base.py) — 3 处 tool message 添加 `"name": _tc_function_name` 字段(成功/未找到/异常分支)。

**B-4**: [neurova/agent/loops/base.py](file:///e:/项目/Neurova/neurova/agent/loops/base.py) — SkillRegistry 执行包裹 try/except,异常时 fallback 到 ToolRouter。

**B-2**: [neurova/api/endpoints/console.py](file:///e:/项目/Neurova/neurova/api/endpoints/console.py) — 删除 `history_for_agent = []`,不强制传空历史。

**B-10**: [neurova/agent/loops/openai_loop.py](file:///e:/项目/Neurova/neurova/agent/loops/openai_loop.py) — 每次 `predict_step` 开始时重置 `self._tools_supported = True`,改为 per-request 禁用。

### V2 修复(6 个断点)

**V2-1**: [neurova/skill_system.py](file:///e:/项目/Neurova/neurova/skill_system.py) — SkillRegistry 加 `skills` property 返回 `_skills` 字典。

**V2-2**: [neurova/tool_layers/tool_router.py](file:///e:/项目/Neurova/neurova/tool_layers/tool_router.py) — `_discover_skill_tools` 增加 `isinstance(skills, list)` 分支;dict 分支处理元组解包(类 B 的 `Dict[str, Tuple[Skill, Path]]`)。

**V2-3**: [neurova/api/endpoints/chat.py](file:///e:/项目/Neurova/neurova/api/endpoints/chat.py) — 两处 `call_metadata = body.metadata if "history" in body.metadata else {"history": []}` 改为 `body.metadata or {}`。

**V2-4**: [neurova/api/endpoints/console.py](file:///e:/项目/Neurova/neurova/api/endpoints/console.py) — WebSocket 路径删除 `metadata={"history": []}`。

**V2-5**: [neurova/skill_system.py](file:///e:/项目/Neurova/neurova/skill_system.py) — SkillRegistry 加 `register_skill(manifest, path=None)` 兼容方法,内部委托到 `register(skill)`。

**V2-6**: [neurova/agent/chat_pipeline.py](file:///e:/项目/Neurova/neurova/agent/chat_pipeline.py) — 流式分支 `gen = self.loop.predict_step(...)` 改为 `gen = await self.loop.predict_step(...)`。

### V3 修复(2 个断点)— zoom-out + TDD 垂直切片

**V2-7**: [neurova/tool_layers/tool_router.py](file:///e:/项目/Neurova/neurova/tool_layers/tool_router.py) — `_resolve_skill_tool` 在取到 `skill = skills[tool_name]` 后,若是元组/列表则解包取 `[0]`。根因:类 B `neurova/skills/registry.py` 的 `.skills` 返回 `Dict[str, Tuple[Skill, Path]]`,原代码直接拿元组导致后续 `getattr(元组, "description", "")` 返回空字符串,proxy schema 为空。

**V2-8**: [neurova/agent/loops/base.py](file:///e:/项目/Neurova/neurova/agent/loops/base.py) — 删除 `_build_tools_from_skills` 死代码方法(line 221-257)。根因:全代码库无任何调用点(ripgrep 验证),且方法内含与 V2-1 同根的 `.skills` bug。删除遵循 AGENTS.md 规则 "Surgical Changes — Every changed line should trace back to the request"。

---

## 5. 验证 — 测试结果

### V1 测试 — [tests/unit/test_tool_call_breakpoints.py](file:///e:/项目/Neurova/tests/unit/test_tool_call_breakpoints.py)

```
6 passed in 0.33s
- TestToolMessageNameField::test_success_tool_message_has_name ✅
- TestToolMessageNameField::test_error_tool_message_has_name ✅
- TestToolMessageNameField::test_not_found_tool_message_has_name ✅
- TestConsoleHistoryNotForceEmpty::test_console_no_history_in_metadata ✅
- TestToolsSupportedNotPermanent::test_tools_supported_resets_per_request ✅
- TestSkillExceptionFallback::test_skill_exception_falls_back_to_tool_router ✅
```

### V2 测试 — [tests/unit/test_tool_call_breakpoints_v2.py](file:///e:/项目/Neurova/tests/unit/test_tool_call_breakpoints_v2.py)

```
9 passed in 0.08s
- TestSkillRegistrySkillsProperty::test_skills_property_returns_dict ✅
- TestSkillRegistrySkillsProperty::test_skills_property_reflects_registered_skills ✅
- TestToolRouterListSkillsSupport::test_discover_skill_tools_handles_list ✅
- TestChatEndpointNotForceEmptyHistory::test_chat_endpoint_no_force_empty_history ✅
- TestConsoleWebSocketNotForceEmptyHistory::test_console_ws_no_force_empty_history ✅
- TestSkillRegistryRegisterSkillCompat::test_register_skill_method_exists ✅
- TestSkillRegistryRegisterSkillCompat::test_register_skill_does_not_raise_on_manifest ✅
- TestChatPipelineStreamAwait::test_stream_branch_has_await ✅
- TestChatPipelineRegisterSkillNoAttributeError::test_chat_pipeline_calls_register_skill_compatible ✅
```

### 联合回归

```
27 passed in 0.51s (V1 + V2 + 时间注入)
8 passed in 1.44s (test_history_load_bugs.py)
2/3 passed in test_tool_router_skill_discovery.py(1 个 ImportError 是预先存在,与本次无关)
8/12 passed in test_tool_router.py(4 个失败是预先存在的 MCP mock 问题)
```

**额外收获**: V2-2 修复了 1 个预先存在的失败
`test_discover_skill_tools_uses_list_skills_not_skills_attribute`(原 dict 值元组未解包导致 description 空)。

### V3 测试 — [tests/unit/test_tool_call_breakpoints_v3.py](file:///e:/项目/Neurova/tests/unit/test_tool_call_breakpoints_v3.py)

TDD 垂直切片执行:一次一个测试 → 一次一个实现(遵循 tdd skill 规范,反对水平切片)。

```
4 passed in 0.08s
- TestResolveSkillToolUnpacksTuple::test_resolve_skill_tool_unpacks_tuple_from_class_b ✅
  (类 B 的 Dict[str, Tuple[Skill, Path]] 元组解包验证)
- TestResolveSkillToolUnpacksTuple::test_resolve_skill_tool_handles_class_a_dict ✅
  (类 A 的 Dict[str, Skill] 对照组,确保不破坏原功能)
- TestBuildToolsFromSkillsDeadCodeRemoved::test_build_tools_from_skills_method_removed ✅
  (方法已从 BaseAgentLoop 删除)
- TestBuildToolsFromSkillsDeadCodeRemoved::test_no_callers_of_build_tools_from_skills ✅
  (ripgrep 确认 neurova/ 目录无任何调用点)
```

### 全量联合回归(2026-07-02 终态)

```
19 passed in 0.41s (V1 6 + V2 9 + V3 4)
+ 12 passed (时间注入测试)
+ 8 passed (history_load 测试)
= 39/39 GREEN
```

---

## 6. 教训

1. **SkillRegistry 双实现是设计债**: 类 A (`neurova/skill_system.py`) 和类 B (`neurova/skills/registry.py`) API 完全不同,但调用方混用,导致多处静默失败。建议长期统一为一个实现,或显式定义协议接口。

2. **静默 except 是 bug 温床**: orchestrator.py:760、base.py:199、chat_pipeline.py:571 都用 `except Exception` 吞掉异常,导致 AttributeError 不暴露。建议关键路径用 `except Exception as e: logger.exception(...)` 至少记录。

3. **API 不匹配应抛 TypeError,而非 AttributeError**: SkillRegistry 的兼容方法(register_skill)应明确接受 manifest+path,而非让调用方猜 API。

4. **流式分支单独测试**: 非流式 GREEN 不代表流式 GREEN。chat_pipeline.py:890 的 `await` 缺失在非流式路径不会暴露,但流式路径会立即崩。

5. **源码扫描测试需排除注释**: V2-3/V2-4 的源码扫描测试因修复说明注释中包含 `"history": []` 字符串而假阳性失败,后改用 `re.sub(r'#.*', '', src)` 去除注释再检查。

---

## 7. 后续建议(架构深化候选)

V1+V2+V3 已修复全部 12 个工具调用断点。剩余的架构债通过 improve-codebase-architecture skill 识别为 4 个深化候选,详见 HTML 架构报告:

→ [docs/architecture-review-tool-call.html](file:///e:/项目/Neurova/docs/architecture-review-tool-call.html)

### 已实现(2026-07-02 第二轮,tdd + zoom-out + improve-codebase-architecture)

| 候选 | 类型 | 状态 | 改动 |
|---|---|---|---|
| 3. 静默 except → logger.exception | Worth exploring | ✅ 已实现 | orchestrator.py:725/760 + chat_pipeline.py:571(3 处) |
| 2. ToolRouter 提取 `_unpack_skill` helper | Worth exploring | ✅ 已实现 | tool_router.py 新增 `_unpack_skill` 方法,2 处调用替换 |
| 1. 统一 SkillRegistry 双实现为 Protocol | Strong | ✅ 已实现 | skill_system.py 新增 `SkillRegistryProtocol`,__init__.py 导出 |
| 4. ChatPipeline 流式/非流式分支统一 | Speculative | ⏸️ 推迟 | 补齐 3 个流式分支测试覆盖,完整统一待测试完善后执行 |

### 候选 4 推迟理由

完整统一 stream/non-stream 分支被评估为 Speculative,推迟执行:
1. predict_step 接口变更影响所有调用方(高风险)
2. non-stream 分支有 reasoning 捕获 + auto-continue,stream 分支缺失
3. 强制统一可能引入新 latent bug
4. V2-6(await)已修复最紧迫的 bug,统一是 nice-to-have

已补齐流式分支测试覆盖(3 个测试),为未来统一铺路:
- `test_stream_branch_extracts_content_events` — 只提取 content 事件
- `test_stream_branch_done_event_fallback` — done.reply 兜底
- `test_stream_branch_empty_when_no_content_no_done_reply` — 空回复处理

### 测试结果

```
38 passed in 0.36s
- 候选 3: 3/3 GREEN (TestSilentExceptReplacedWithLoggerException)
- 候选 2: 6/6 GREEN (TestUnpackSkillHelper)
- 候选 1: 6/6 GREEN (TestSkillRegistryProtocol)
- 候选 4: 4/4 GREEN (TestStreamBranchCoverage + TestCandidate4DeferralDecision)
- V1+V2+V3 回归: 19/19 GREEN
```

---

## 8. 引用

- OpenAI 官方文档 — Tool message name 字段为可选,但 DeepSeek/通义/智谱/Kimi 在 strict 模式下要求必含 name(社区共识,GitHub issue 验证)
- Python 文档 — `@property` 装饰器用于暴露只读字段
- bug-hunt 方法论 — `C:\Users\xccoo\.agents\skills\bug-hunt.keep\SKILL.md`
- 项目 memory — `c:\Users\xccoo\.trae-cn\memory\projects\-e----Neurova\project_memory.md`(工具调用相关硬约束)
