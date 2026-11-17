# N3 · Benchmark 真评测执行器（2026-11-17）

> 会话说明（如实）：本能力由 N3 会话实现，但该会话两度卡在 needs_attention，
> 代码完成后未提交、未建台账。总控按验收流程接手：全量跑其测试（29 passed）、
> 复核 `suite_eval.py` 判分与诚实性（单任务异常计 0 分不中断、判据异常不掩盖、
> 空任务库 score=None 不编造、时延 clockFn 注入可测），代为入库本台账。

## 设计决策

| 决策 | 内容 |
|---|---|
| 模式 | 按审计 docstring 指引"按现役 rag_eval 那条路另立批次"——新建 `neurova/benchmark/suite_eval.py`（256 行），不在旧门面重写第二份 |
| 执行形态 | **后台线程 + 状态查询**：POST /run 即返 running，`GET /runs/{run_id}` 轮询终态——长 suite 不阻塞请求 |
| 事实源 | suite 任务库经 `registerSuiteTasks` 注册（reasoning/coding/memory/creative 四 suite 已接；multimodal-v1 **有意不接**——文本 LLM 通道无法诚实考多模态，走 simulated 路径） |
| 判分 | 每任务 `CheckFn`（exactAnswer/markersPresent）给 (passed, score, details)；聚合 tasks_total/tasks_correct/score/avg_latency_ms |
| 诚实性 | 单任务异常＝失败事实计 0 分记 error 不中断；判据异常记 checker_error 不掩盖；空任务库 score=None；无 LLM 通道 503 拒绝伪造 |
| simulated 语义 | 保留：显式 config.simulated=true 或 suite 未接任务库 → simulated 记录（score=None） |

## 落地面

- `neurova/benchmark/suite_eval.py`：SuiteTask/CheckFn/registerSuiteTasks/getSuiteTasks/suiteWired/runSuite
- `benchmark.py`：run_benchmark 分流（simulated/真执行）、`_rag_llm_fn`（被测 agent 的 LLM 通道单一事实源）、`_executeBenchmarkRun` 后台线程、`GET /runs/{run_id}` 进度/结果查询
- 测试：`tests/unit/benchmark/test_suite_eval.py`（执行器单测：全对/部分对/异常任务/空库）、`tests/unit/api/test_benchmark_run_real_execution.py`（端点集成：running→终态、simulated 保留、503）、`test_benchmark_api.py` 适配

## 验证

- 三测试文件 **29 passed**（suite_eval 190 行单测 + 端点集成 210 行 + 既有 api 适配）
- 聚合端点兼容：真实 score 落库后经 R3 的 None 安全聚合出真实均值（端到端断言在内）

## 遗留

- runSuite 的 LLM 通道按任务串行执行；大批量 suite 的并发执行属后续优化（当前任务量 11 条内，串行可接受）。
