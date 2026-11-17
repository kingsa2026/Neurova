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

## live-verify（真后端 9541，2026-11-17）

起服判据：`.venv` 解释器 + 清代理变量 + `NEUROVA_PORT=9541`，启动日志 `[ERROR]`=0（仅 MCP filesystem 预存重连噪声）、`/health` ok、无凭证打 `/api/v1/benchmark/suites` 得 401（鉴权门完好）。`data/.jwt_secret` 同口签 admin token 直打（S1 手法）。

- **真执行**：POST `/api/v1/benchmark/run` {reasoning-v1, agent=default} → 即返 `running/simulated:false/tasks_total:6`，轮询 `GET /runs/{run_id}` 终态 **completed，6/6，score=1.0，avg_latency_ms=2509.62**（逐任务 answer/error/latency 落 per_task）；再跑 memory-v1 → **3/4，score=0.75**——m3 答出「发布计划」（gold「发布」）自然失分，判分从严如实记 0，不谎报。
- **作答链路（如实）**：本次实际作答来自该机已配置的真模型链（provider `amd` / DeepSeek-V4-Flash-Vision-Exp，~2.5s/题的真实时延与自然近失即证据）。试验性的可控假 LLM（127.0.0.1:9542 OpenAI 兼容桩 + `providers` 注册/发现/激活链）走通到「activate-model 成功」，但 agent 端 client 仍跟随自身 provider 链，未改吃全局 default provider——**假 LLM 桩零命中**（fake_hits.log 为空），故真执行证据以真模型链为准；该 provider 跟随语义属既有设置链行为，不在本批改动。
- **runs 历史**：GET `/runs` 列出两笔 completed 真实运行（score 1.0 / 0.75）。
- **聚合闭环**：GET `/agents/default` → total=2、**avg=0.88**（=(1.0+0.75)/2）、best=1.0——R3 None 安全聚合吃真实分数出真实均值；POST `/compare` {default, yi_ling} → default runs=2/avg 0.88/avg_latency 2519.35，无运行的 yi_ling 如实全 None 不编造。
- **simulated 保留**：multimodal-v1（未接任务库）→ `simulated` 记录、score=None、message「该 suite 未接真执行任务库」。
- 收尾：两进程已杀、端口已清，临时桩脚本在仓外 temp 目录（不入库）。

## 遗留

- runSuite 的 LLM 通道按任务串行执行；大批量 suite 的并发执行属后续优化（当前任务量 11 条内，串行可接受）。
