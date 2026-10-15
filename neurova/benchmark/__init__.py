"""Benchmark 包：本包对外的现役面只有两个子模块（`rag_eval` / `rag_dataset_gen`）。

这里**不再有实现**。原 `__init__.py` 里的 575 行（468 行实现：7 个类 + 进程级单例
`get_benchmark_framework()`）于票④第一包按用户裁定退役，判据见
`tests/unit/benchmark/test_benchmarkFacadeImplementationRetired.py`。

退役依据（不是"零消费者"一句话，而是比过之后的判定）：
- 生产面对 `BenchmarkFramework` 及其单例的取数实测为 **0**；全仓唯一取用是一枚判据里的构造
  （为钉 `_storage_dir` 的裸相对落点，随该档同批改判）。
- `neurova/api/endpoints/benchmark.py:106` 自己就记着："真实评测执行器（neurova/benchmark 框架
  + LLM 答题打分）未接线，本端点不投机实现"——端点的 `/suites` 用的是它自带的 `_SUITES` 常量，
  `/run`、`/runs` 走进程内 `_RUNS_STORE`，**从未** import 过本门面。前端 `BenchmarkPage.vue` 那
  三张请求打的也是这些，所以退役不动任何一条在跑的链路。
- 包内子模块也不回头取本文件的任何名字（实测 `neurova/benchmark/*.py` 无 `from .` / `from neurova.benchmark import`）。

跟着消失的两样，说清楚别让人以为无损：
① `_DEFAULT_SUITES` 那套硬编码题面（三段论一类）。它是玩具数据——现役数据集经
   `rag_eval.save_dataset` 由用户提供，把玩具题并进活路等于塞占位数据，故**不并**。
② 那份 SQLite 的评测运行历史持久面。现役端点用进程内字典，重启即失；要做真持久评测台账
   属**新能力**（`core/agent_run_ledger` 有先例可循），不在退役批里顺手造。

要恢复这段实现，从 git 历史取，别在门面里重写第二份。
"""
