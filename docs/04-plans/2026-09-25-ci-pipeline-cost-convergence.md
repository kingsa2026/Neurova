# 处置：CI 流水线耗时收口（11 个检查为什么慢，以及慢在哪）

> 立项日期：2026-09-25
> **状态：已落地（2026-09-25）**
> 承接单：Issue #223（用户提问「为什么每次 cnb/pull_request 的 11 个检查时间这么长？
> 是不是有什么冲突或者死循环？」）
> 性质：CI 配置耗时收口（非代码缺陷修复，仓内 Python 代码未改一行）
> 常驻判据：`tests/unit/test_ci_pipeline_speed_guard.py`（四条结论逐条可证伪）

---

## 1. 先回答"是不是死循环"

**不是死循环，也不是配置冲突。** 三条事实：

1. **每条流水线都是独立门禁，并发执行**——`.cnb.yml` 顶部早写明"同一事件下的多条
   流水线并发执行，各自独立上报"。墙钟 ≈ 单条最长的那条，**不是 11 条相加**。
2. **"长"来自可量化的事**：每条都从零装一遍依赖（容器间无共享）、同一片全仓
   代码被扫多遍、同一份子集被 py3.11/py3.12 各完整跑一遍（**这是刻意的**，
   GitHub matrix 同款，放行标准，不在本次收口范围）。
3. **同一个事件下的多条流水线之间没有依赖原语**，也就没有"互相等待"这种死锁形态。

## 2. 收口了什么（Issue #223 第 1~4 条）

| # | 改动 | 现状→处置 | 两侧 |
|---|------|-----------|------|
| 1 | OSV 离线漏洞库缓存 | 缓存落在 `~/.cache/osv-scalibr`，但没有任何流水线声明它 → **每次构建重下 206MB（实测 47s+）** → 挂卷 / `actions/cache` 跨构建复用 | `.cnb.yml` / `ci.yml` |
| 2 | 语法巡检与 lint 合并 | pyflakes 与 ruff **都在读同一片全仓 AST**，拆两条 = 多一次容器启动 + 多一遍全仓遍历 → 并成一条 `static-gate`，两条命令逐字不动 | `.cnb.yml` / `ci.yml` |
| 3 | 重复依赖安装走锁 | 三条流水线用无锁的 `-r requirements-ci.txt` **各解析一遍整棵依赖树** → 统一装 `requirements-ci.lock` | `.cnb.yml` / `ci.yml` |
| 4 | 不自举 pip | 10 条流水线里 10 处 `pip install --upgrade pip` → **每次构建一次 PyPI 网络往返**，与"这次提交是否合格"无关 → 一律去掉 | `.cnb.yml` / `ci.yml` |

流水线条数因此 **11 → 10**（`lint` 并入 `static-gate`），GitHub 侧 `job` 数同样 11 → 10。

## 3. 刻意**没有**动的三件事（以及为什么）

1. **`unit-tests` 的 py3.11/py3.12 双跑**：这是两侧一致的放行标准（GitHub matrix
   同款），砍掉会改变"什么样的改动能被放行"。若要收敛，正确做法是**先改放行标准**
   （同时改两侧配置与 `tests/unit/test_ci_parity_guard.py` 的 `EXPECTED_MAP`），
   而不是在耗时压力下悄悄减一条。
2. **e2e 的 `requirements.txt --no-deps` + 显式点名**：薄环境是它的设计目的
   （冒烟只需最小 import 面），改胖会让它退化成慢门禁。本次只去掉自举 pip。
3. **`pip` 缓存卷**：`/root/.cache/pip` 早就在挂，装依赖的"重复"体现在
   **解析依赖树**与**下载**两件事上；第 3 条治的是前者，缓存治的是后者。

## 4. 常驻判据（可证伪路径逐条列出）

`tests/unit/test_ci_pipeline_speed_guard.py` 把上面四条钉成结构判据
（口径是"哪一步做什么"，不是秒数——秒数会随机器漂移，属
`tests/unit/test_ci_wallclock_assertion_ledger.py` 管的另一件事）：

| 结论 | 回退即转红的路径 |
|------|------------------|
| 1 卷 | 从 `dependency-audit` 删掉 `/root/.cache/osv-scalibr` 卷 |
| 1 同源 | 把卷改成另一个目录名（扫描器读的还是自己的目录，卷只是白挂） |
| 2 合并 | 把 ruff 挪回独立的 `lint` 流水线 / job |
| 3 锁 | 任一条流水线回填 `-r requirements-ci.txt` |
| 4 不自举 | 任意 job 里写回 `pip install --upgrade pip ...` |

其中"卷落点"取自 `scripts/ci/osv_audit.py` 的 `OSV_DB_CACHE`（离线库落点的唯一
事实源），不写死第二份口径（教义第 6 条）。

## 5. 与 `AGENTS.md` §0 的关系

本次改的是 `.cnb.yml`，而**流水线配置随分支走**：本 PR 的分支合并后必须立即删除，
否则该分支每次产生构建都会重新加载它自己那一份配置。台账口径见
[`docs/06-bugfix/npc分支归档台账.md`](../06-bugfix/npc分支归档台账.md)，
判定与复算入口在 `scripts/ci/npc_branch_cleanup.py`。
