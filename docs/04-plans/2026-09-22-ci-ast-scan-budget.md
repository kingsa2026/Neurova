# 立项：跨文件 AST 判据的解析预算收口（受保护子集偶发超时）

> 立项日期：2026-09-22
> **状态：已落地（2026-09-22）**——共享预算 `tests/ast_scan.py` + 守卫
> `tests/unit/test_ci_ast_scan_budget_guard.py`；
> 承接单：Issue #148（构建 `cnb-2p6-1k347lfg1` 实测超时）；上游：Issue #112 / #68 的同一层
> （AGENTS.md 修复教义第 2 条：禁止「跑不起来就算过」与「降级断言换绿」）
> 性质：CI 判据根因修复（非配置问题，`.cnb.yml` 未改）

---

## 1. 现状（2026-09-22 实测锚点）

构建 `cnb-2p6-1k347lfg1` 的 `unit-tests-py312` 流水线转红，唯一失败用例：

```
FAILED tests/unit/test_api_inventory_guard.py::TestSnapshotDiscipline::test_injected_stale_block_is_detected
       - Failed: Timeout (>30.0s) from pytest-timeout.
===== 1 failed, 2312 passed, 8 skipped in 697.50s (0:11:37) ======
```

同一提交上的 `unit-tests-py311`（`protected subset with coverage gate`）**是绿的**。
即：**同一份代码、同一条用例，311 绿、312 红**。

`git log -1` 为 `49b4a906`，因此不是「某次提交引入的缺陷」——是**判据与机器速度捆绑**。

## 2. 根因

受保护子集里有若干个「单源 / 收口点」判据，判据内容是「仓库里不得出现第二处实现」，
实现方式却是**把全仓每个 `.py` 都 `ast.parse` 一遍、再 `ast.walk` 一遍**：

实测解析成本 ≈ 1.4 ms/文件（本机 1000 文件 ≈ 1.4s、2000 文件 ≈ 2.9s），
词法遍历（`ast.walk` 的 deque + `iter_child_nodes`）再叠约 1.5 倍。
于是**代码总量被编码成了时间上界**：

| 命中点 | 判据 | 单跑实测 | 全量同批实测 |
|------|------|------|------|
| `tests/unit/api/test_route_mount_contract_guard.py` | 未挂载模块名单 | 5.0s ×4 | **43.1s / 30.8s → timeout** |
| `tests/unit/knowledge/test_write_boundary_closes_verification.py` | `attest()` 单源 | 8.4s | 逼近上界 |
| `tests/unit/evolution/rsi/test_rsi_observation_surface.py` | `record_metric` 写入方 | 5.6s | 逼近上界 |
| `tests/unit/core/test_dead_cache_module_removed.py` | 已删模块无引用 | 4.6s ×2 | 逼近上界 |
| `tests/unit/llm/test_capability_cache_single_source.py` | 能力缓存单源 | 5.1s ×2 | 逼近上界 |
| `tests/unit/evolution/rsi/test_rsi_rollback_evidence.py` | 回滚判据单源 | 4.9s | 逼近上界 |
| `tests/unit/cognitive_layers/memory_layer/test_temperature_single_source.py` | 温度算子单源 | 7.4/7.7/9.1s | 逼近上界 |
| `tests/unit/test_ci_thin_env_guards.py` | 注解地雷零命中 | 3.9s | 逼近上界 |
| `tests/unit/test_dev_path_and_runtime_dep_guards.py` | 禁 `rg` 硬依赖 | 4.0s | 逼近上界 |

「本机单跑绿、CI 全量红」的两个变量——**机器负载**与**同批文件数**——都不在判据的
控制范围内；而 312 上 `python 3.12` 的 `ast` 实现比 311 更慢，正好把最重的那个
命中点推过 30s。这正是 `AGENTS.md` 修复教义第 2 条点名的形态的近亲：
判据本身与代码行数、与机器快慢都无关，**墙钟上界不会因为它变松而更成立，只会把
真实的超时回归一并放行**（放宽阈值 = 「降级断言换绿」）。

## 3. 处置：解析单源到一处，判据与代码总量脱钩

`AGENTS.md` 第 6 条：不新造平行体系。故不逐个「给用例加豁免」，而是把跨文件 AST
扫描的取数收口到 `tests/ast_scan.py`：

1. **文本预筛（充分条件，不是放宽）**：谓词是 `X.<name>` 时，连 `<name>` 都不含的
   文件不可能命中。实测 `neurova/` 1014 文件里含 `attest` 的只有 4 个——
   解析量从「代码总量」降到「命中面」（**0.06s vs 6.5s**）。
   预筛口径由守卫反向锁住（注入真实命中必须被报出）。
2. **整进程复用**：语法树、节点元组、文件文本都按「路径 + mtime + 大小」缓存
   （改文件即失效，不留会静默漏报的陈旧缓存）。同批 N 个守卫扫同一子树只编译一次。
3. **不物化 150 万节点的元组**：`nodeScan()` 返回迭代器——即便全命中缓存，
   `tuple()` 重建 150 万个 `(path, node)` 对也要 2s（实测）。
4. **惰性求值而非豁免墙钟**：`semantic` 判据（如注解地雷，必须读每个文件的注解）
   无法预筛缩面者，走 `sourceRefsUnder(hints=...)` 的同一份读盘/编译缓存，
   不为它放宽时限。

## 4. 验收判据（逐条可复算）

1. **无预筛的全仓 `rglob + ast.parse` 归零**（受保护子集内），由
   `tests/unit/test_ci_ast_scan_budget_guard.py` 的棘轮（空集）常驻钉住；
2. **共享入口真实可用**：`callSites` / `importsOf` / `classDefsIn` / `nodeScan` /
   `sourceRefsUnder` / `relativeToRepo` 必须存在且能真报出命中（否则门禁空转）；
3. **预筛不漏报**：注入真实命中必须被报出；字符串/注释里的「提及」不算引用；
4. **受保护子集同批跑无 timeout**，最长用例 ≤ 6s（原最长 43.1s）；
5. 用例行为不变：受保护子集结果集合修复前后逐行一致（`2280 passed` 两侧相同，
   预存的 39 个 fixture 解析 ERROR 两侧相同）。

## 5. 落地结果（2026-09-22，Issue #148 销账）

| 命中点 | 修复前（最长用例） | 修复后 |
|------|------|------|
| `test_route_mount_contract_guard.py` | 5.0s ×4 → 全量 **43.1s timeout** | 1.5s |
| `test_write_boundary_closes_verification.py` | 8.4s | 0.14s |
| `test_rsi_observation_surface.py` | 5.6s | 0.09s |
| `test_dead_cache_module_removed.py` | 4.6s ×2 | 0.07s |
| `test_capability_cache_single_source.py` | 5.1s ×2 | 0.07s |
| `test_rsi_rollback_evidence.py` | 4.9s | 0.43s |
| `test_temperature_single_source.py` | 9.1s（文件合计 28.0s） | 3.5s（合计 5.3s） |
| `test_ci_thin_env_guards.py` | 3.9s | 1.6s |
| `test_dev_path_and_runtime_dep_guards.py` | 4.0s | 0.5s |

**受保护子集同批跑**：修复前最长 43.1s（2 处 timeout 转红）；修复后最长 5.4s，
末行 `2280 passed, 39 errors`（39 个 ERROR 为**预存**的 fixture 解析问题，
与本次变更无关——修复前后逐文件比对一致）。

## 6. 与 `.cnb.yml` 的关系

**未改 `.cnb.yml`**。`timeout: 30m` 是 stage 级预算，本次失败是 `pytest-timeout`
的**用例级** 30s 默认墙钟——放宽 stage 预算或给用例加豁免都只是把症状挪走
（教义第 1 条禁止 consumer-only guard）。根因在判据粒度，已在根因处修复。
