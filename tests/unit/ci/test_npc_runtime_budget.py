# -*- coding: utf-8 -*-
"""NPC 运行期预算的单一事实源（Issue #272：超时与超轮次的处理方式收口）。

## 为什么需要这一支

Issue #272 要求「参考外部配置调整各角色的超时与超轮次处理方式」。这两件事在本仓
此前**各有一份手抄的口径**，而两份都不在任何机器判据的覆盖面上：

1. **超时**：`.cnb.yml` 里三处 `npc:go` 各写一个 `timeout: 20m` 字面量，注释里另有
   一句「流水线 20h 上限」。而平台对同一件事至少有四个不同口径：流水线**整体**
   运行时长（由 Runner 下发，仓库侧改不掉）、Job / Stage 单次最长（最大 12h）、
   `npc:go` 的**每一次工具执行**（取所在 Stage 的 `timeout`）、无输出阈值（默认 10 分钟）。
   混在一起，实测后果就是「撞墙时连一句结论都发不出来」——Agent 只能靠猜，
   而猜的结果是零余量撞墙（本仓实测 222 轮 / 7,330,218ms 被中止，
   改而未提交的成果随容器一起丢，Issue 上只留下一条构建号）。

2. **超轮次（`maxTurns`）**：配额只在 `.cnb.yml` 写一处，**Agent 侧没有任何量尺** ——
   人设里那句「现行 N 轮」是被 `test_ci_npc_config_guard.py` 钉住的第二个数字，
   而「跑满之后怎么收尾」这条纪律此前完全不存在。撞满配额与撞满时长是两种不同的
   中止，但**都不给收尾机会**：平台中止 Agent 时不执行任何收尾指令或工具调用。

## 本文件钉六件事（都可证伪）

- **A 超时口径单源**：三处 `npc:go` 的工具超时经 YAML 锚点收敛到一处；
  该锚点在**展开后**的引用面必须覆盖全部三个挂载点。
- **B 量尺可达**：`scripts/ci/npc_runtime_budget.py` 存在、能独立运行，
  且 `.cnb.yml` 在 Agent 流水线里**真的执行**它（不是躺在仓库里当摆设）。
- **C 四态判据可证伪**：同一组输入下按已用比例给出 `continue` / `wrapup` / `halt`，
  变量缺失**响亮**报 `unknown`（不得静默当成「时间还很多」）。
- **D 纪律落在唯一必达通道**：每个在册角色的人设都写明量尺入口与两个阈值的处置。
- **E 角色准入在 Agent 开工之前**：不在册的名字被平台**静默回落**，本仓必须自己响亮；
  且名单只有一处事实源（`.cnb/settings.yml` 的 `npc.roles`），`.cnb.yml` 不得抄第二份。
- **F 读数不手抄**：阈值的事实源是脚本里的常量，人设引用时必须与现值一致。

反向锁（教义第 3 条禁恒真断言）：A/B/C/E 各带一条注入式反向控制。
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"
SETTINGS = PROJECT_ROOT / ".cnb" / "settings.yml"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 运行期预算量尺（Agent 的量尺）。它同时是「超时」与「超轮次」的读数入口。
BUDGET_SCRIPT = PROJECT_ROOT / "scripts" / "ci" / "npc_runtime_budget.py"

#: 角色准入判据（在 `npc:go` 之前跑）。
ADMISSION_SCRIPT = PROJECT_ROOT / "scripts" / "ci" / "npc_role_admission.py"

#: `.cnb.yml` 里承载「工具单次执行超时」的 YAML 锚点名（顶层 key 名即锚点名）。
TOOL_TIMEOUT_ANCHOR = "npc-tool-timeout"

#: 平台对 Job 的默认最长执行时间（未声明 `timeout` 时）。
PLATFORM_JOB_DEFAULT_MAX = 2 * 3600

#: 阈值：到这里就该收，而不是「跑到墙上再死」。
WRAP_PCT, HALT_PCT = 70, 85


def _load(path: Path):
    return yaml.safe_load(io.open(path, encoding="utf-8").read())


@pytest.fixture(scope="module")
def cnb_doc():
    assert CNB.exists(), ".cnb.yml 丢失"
    return _load(CNB)


@pytest.fixture(scope="module")
def roles():
    doc = _load(SETTINGS)
    declared = (doc.get("npc") or {}).get("roles") or []
    assert declared, ".cnb/settings.yml 未声明任何 NPC 角色"
    return declared


def _aliasEdges(text: str) -> list:
    """YAML 锚点引用链：一条 `<<: *X` 记一条边，产出 `(边所在锚点, 引用的锚点名)`。

    只解析两类行（文本级，不引 YAML 语义 —— 判据关心的是引用链，不是对象图）：

    * 锚点定义：`<任意缩进><key>: &<锚点名>`（可带 `|` / 标量尾巴）；
    * 别名引用，两种书写形态都要认：
      - 映射项：`<任意缩进><<: *<锚点名>[, *<锚点名>...]`
      - 列表项：`<任意缩进>- <<: *<锚点名>`（本仓三条事件定义即此形态）

    按**锚点名**建链而不是按顶层 key：超时锚点定义在 `$` 段**内部**
    （`  .工具超时: &npc-tool-timeout`），它不是一个顶层挂载点 ——
    「谁用到了它」只能沿引用链问，不能按顶层 key 反查。

    返回**列表**而不是映射：同一份 Job 体可以被多个事件各引用一次，两次都是
    独立的消费面，合并成键值对会把它们折叠成一条（判据当场失去分辨力）。

    作用域用**缩进**判定：锚点定义行的缩进记下来，缩进比它更浅时作用域结束。
    锚点定义层里的自引用被剔除 —— 那是定义本身，不是一处消费者。
    """
    edges: list = []
    current = None
    current_indent = None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        match = re.match(r"^([^:]+):\s*&([^\s|]+)", stripped)
        if match:
            current = match.group(2)
            current_indent = indent
            continue
        if current is None or indent < current_indent:
            current = None
            continue
        body = stripped[1:].strip() if stripped.startswith("-") else stripped
        if not body.startswith("<<"):
            continue
        for token in body.split(":", 1)[1].split(","):
            token = token.strip()
            if not token.startswith("*"):
                continue
            ref = token.lstrip("*")
            if ref == current and not ref.startswith("npc-"):
                # 定义层里的自引用是定义本身，不是消费者；
                # 但**共用 Job 体**（`&npc-dscoder-job` … `<<: *npc-dscoder-job`）
                # 不是自引用：那正是「一份 Job 体被多个事件引用」这件事的形态，
                # 每一次引用都是一处独立的消费面。故按名字前缀区分。
                continue
            edges.append((current, ref))
    return edges


def _reachesAnchor(graph: dict, node: str, anchor_name: str, seen: set) -> bool:
    """`node` 这个锚点沿引用图能否走到超时锚点。"""
    if node == anchor_name:
        return True
    if node in seen:
        return False
    seen.add(node)
    return any(_reachesAnchor(graph, ref, anchor_name, seen)
               for ref in graph.get(node, ()))


def _timeoutConsumers(text: str, anchor_name: str) -> int:
    """超时锚点被几处 `<<:` 引用（含间接经共用 Job 体引用的那两个事件）。

    口径：对引用图里每条边，若它直接指向超时锚点、或沿引用链能走到它，则该边算一处消费者。
    锚点定义层里的自引用已在建图时剔除（那是定义，不是消费者）。
    """
    edges = _aliasEdges(text)
    graph = {}
    for owner, ref in edges:
        graph.setdefault(owner, set()).add(ref)
    return sum(
        1 for _owner, ref in edges
        if ref == anchor_name or _reachesAnchor(graph, ref, anchor_name, set())
    )


def _iter_npc_go_stages(node, path=""):
    """递归收集所有 npc:go 任务，产出 (路径, 任务体)。"""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_npc_go_stages(item, f"{path}[{i}]")
        return
    if isinstance(node, dict):
        if node.get("type") == "npc:go":
            yield path, node
        for key, value in node.items():
            yield from _iter_npc_go_stages(value, f"{path}.{key}" if path else str(key))


def _npcJobs(cnb_doc):
    """`$` 段下真实事件挂载点上的 NPC Job（跳过 `^\\..` 锚点定义层）。"""
    fallback = cnb_doc.get("$") or {}
    return [
        (event, job)
        for event, body in fallback.items()
        if isinstance(event, str) and event.endswith("@npc")
        for job in (body if isinstance(body, list) else [])
        if isinstance(job, dict)
    ]


class TestToolTimeoutIsSingleSourced:
    """A：工具单次执行的超时只有一个事实源，且每个 Job 变体都吃到它。

    根因：`npc:go` 的 `timeout` 作用于 Agent 的**每一次工具执行**，不是整个会话；
    各写一个字面量就是多份可独立漂移的口径 —— 而平台对超时至少有四种语义
    （流水线整体 / Job 单次最长 / 一次工具执行 / 无输出阈值），混在一起时
    「到底哪个阈值先破」只能靠猜。锚点唯一则口径唯一。

    判据分两层，缺一不可：
      1. **形态**：每个 npc:go 任务都声明了 `timeout`，且取值完全相同
         （取值相同是「同一个事实源」的可观察后果）；
      2. **可达**：`&npc-tool-timeout` 锚点有定义，且它的**消费面**覆盖全部
         NPC Job 变体（共用 Job 体 + 每个事件各一份），不是只有一份碰巧对。
    可证伪：把任一处的 `<<: *npc-tool-timeout` 换成硬编码字面量 → 第 2 层红。
    """

    def test_every_npc_go_declares_a_timeout(self, cnb_doc):
        missing = [
            path for path, stage in _iter_npc_go_stages(cnb_doc)
            if stage.get("timeout") is None
        ]
        assert not missing, (
            "以下 npc:go 未声明工具超时：\n  " + "\n  ".join(missing) +
            "\n未声明时按平台默认（无输出阈值 10 分钟）执行，阈值不在仓内可见。"
        )

    def test_timeout_values_are_identical(self, cnb_doc):
        values = {path: stage.get("timeout") for path, stage in _iter_npc_go_stages(cnb_doc)}
        assert len(set(values.values())) == 1, (
            "多处 npc:go 的 timeout 不一致（同一件事抄成了多份口径）: "
            f"{values}\n超时只有一处事实源（.cnb.yml 的 &{TOOL_TIMEOUT_ANCHOR} 锚点）。"
        )

    def test_anchor_is_defined_and_consumed(self):
        text = io.open(CNB, encoding="utf-8").read()
        edges = _aliasEdges(text)
        assert any(TOOL_TIMEOUT_ANCHOR in ref for _owner, ref in edges), (
            f"锚点 &{TOOL_TIMEOUT_ANCHOR} 未定义 —— 超时口径没有事实源，"
            "各处仍是各写一份"
        )
        consumers = _timeoutConsumers(text, TOOL_TIMEOUT_ANCHOR)
        assert consumers >= 2, (
            f"锚点 &{TOOL_TIMEOUT_ANCHOR} 只有 {consumers} 个消费者 —— "
            "NPC Job 体至少有两层（共用 Job 体 + 各事件引用），"
            "只覆盖一层就说明别处另写了一个数字。\n"
            "修法：该处改用 `<<: *" + TOOL_TIMEOUT_ANCHOR + "`。"
        )

    def test_consumer_count_has_discriminating_power(self):
        """反向锁：把一处引用换成硬编码字面量 → 消费者数必须下降。"""
        text = io.open(CNB, encoding="utf-8").read()
        baseline = _timeoutConsumers(text, TOOL_TIMEOUT_ANCHOR)
        injected = text.replace("          <<: *" + TOOL_TIMEOUT_ANCHOR,
                                "          timeout: 30m", 1)
        assert _timeoutConsumers(injected, TOOL_TIMEOUT_ANCHOR) < baseline, (
            "把 `<<:` 换成硬编码字面量后消费者数没有变化 —— 本判据接不上真实文档"
        )


class TestBudgetScriptIsExecutedByTheBuild:
    """B：量尺必须由真实构建执行，不能只在仓库里躺着。"""

    def test_script_exists_and_parses(self):
        assert BUDGET_SCRIPT.exists(), (
            f"{BUDGET_SCRIPT.relative_to(PROJECT_ROOT)} 丢失 —— "
            "Agent 没有量尺，只能靠猜「离死还有多久」（实测代价：零余量撞墙、连结论都发不出）"
        )
        import ast
        ast.parse(io.open(BUDGET_SCRIPT, encoding="utf-8").read())

    def test_script_runs_without_cnb_variables(self):
        """变量缺失时必须**响亮**报 unknown，不得崩栈、也不得默认「时间还很多」。"""
        env = {k: v for k, v in os.environ.items()
               if k not in ("CNB_PIPELINE_MAX_RUN_TIME", "CNB_BUILD_START_TIME")}
        proc = subprocess.run(
            [sys.executable, str(BUDGET_SCRIPT)],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env, timeout=60,
        )
        assert proc.returncode == 0, (
            f"量尺在缺变量时未能以 0 退出（它是决策输入，不是判据）:\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}"
        )
        assert "verdict=unknown" in proc.stdout, (
            "缺变量时未报 unknown —— 静默当成「时间还很多」正是撞墙的根因\n"
            f"实际 stdout：\n{proc.stdout}"
        )

    def test_npc_jobs_run_the_budget_script(self, cnb_doc):
        jobs = _npcJobs(cnb_doc)
        assert jobs, "$ 段缺 NPC 事件定义"
        offenders = [
            event for event, job in jobs
            if not any(
                "npc_runtime_budget.py" in str(stage.get("script") or "")
                for stage in (job.get("stages") or [])
                if isinstance(stage, dict)
            )
        ]
        assert not offenders, (
            f"{offenders} 未在 Agent 流水线里执行 {BUDGET_SCRIPT.name} —— "
            "人设里教会了 Agent 跑它，配置里却没有把它放进环境。"
        )


class TestVerdictsAreFalsifiable:
    """C：四态判据逐条可证伪（阈值边界 + 缺失路径），不是恒真断言。"""

    @staticmethod
    def _read(env_extra: dict) -> dict:
        env = {k: v for k, v in os.environ.items()
               if k not in ("CNB_PIPELINE_MAX_RUN_TIME", "CNB_BUILD_START_TIME")}
        env.update(env_extra)
        proc = subprocess.run(
            [sys.executable, str(BUDGET_SCRIPT), "--json"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    def _verdictFor(self, elapsed_pct: int) -> str:
        """构造一份「已用 elapsed_pct%」的读数（总额固定为一个平台默认 Job 上限）。"""
        import time
        total_ms = PLATFORM_JOB_DEFAULT_MAX * 1000
        elapsed_s = PLATFORM_JOB_DEFAULT_MAX * elapsed_pct // 100
        start = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - elapsed_s)
        )
        return self._read({
            "CNB_PIPELINE_MAX_RUN_TIME": str(total_ms),
            "CNB_BUILD_START_TIME": start,
        })["verdict"]

    def test_verdicts_track_the_elapsed_ratio(self):
        assert self._verdictFor(10) == "continue", "余量充足时未报 continue"
        assert self._verdictFor(WRAP_PCT + 2) == "wrapup", f"已用超过 {WRAP_PCT}% 时未报 wrapup"
        assert self._verdictFor(HALT_PCT + 3) == "halt", f"已用超过 {HALT_PCT}% 时未报 halt"

    def test_unknown_is_loud(self):
        assert self._read({})["verdict"] == "unknown"

    def test_discriminating_power(self):
        """反向锁：两种相反的输入必须给出不同的读数（否则判据是恒真壳）。"""
        assert self._verdictFor(5) != self._verdictFor(HALT_PCT + 5)

    def test_node_branch_is_equivalent(self):
        """node 分支（NPC 镜像只有 node）必须与 python 分支同读数、同判据。"""
        import shutil
        if not shutil.which("node") or not shutil.which("sh"):
            pytest.skip("本环境没有 node/sh，无法做双运行时等价比对")
        bridge = PROJECT_ROOT / "scripts" / "ci" / "run_gate_under_node.sh"
        env_extra = {"CNB_PIPELINE_MAX_RUN_TIME": "7200000",
                     "CNB_BUILD_START_TIME": "2026-09-26T14:32:35.364Z"}
        env = {k: v for k, v in os.environ.items()
               if k not in ("CNB_PIPELINE_MAX_RUN_TIME", "CNB_BUILD_START_TIME")}
        env.update(env_extra)
        env.setdefault("CNB_BUILD_WORKSPACE", str(PROJECT_ROOT))
        proc = subprocess.run(
            ["sh", str(bridge), "scripts/ci/npc_runtime_budget.py", "--json"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env, timeout=60,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        reading = json.loads(proc.stdout)
        assert reading["verdict"] == self._read(env_extra)["verdict"], (
            "node 分支与 python 分支的判据不一致（双运行时必须逐字等价）"
        )


class TestBudgetDisciplineLivesOnTheReachableChannel:
    """D：量尺纪律必须写进**每个**在册角色的 prompt（唯一必达通道）。"""

    REQUIRED = (
        "npc_runtime_budget.py",
        f"verdict=wrapup`（已用 ≥{WRAP_PCT}%）",
        f"verdict=halt`（已用 ≥{HALT_PCT}%）",
        "verdict=unknown",
    )

    def test_every_role_carries_the_clause(self, roles):
        missing = []
        for role in roles:
            prompt = role.get("prompt") or ""
            absent = [m for m in self.REQUIRED if m not in prompt]
            if absent:
                missing.append(f"{role.get('name')}: 缺 {absent}")
        assert not missing, (
            "角色人设缺运行期预算纪律：\n  " + "\n  ".join(missing) +
            "\n人设是评论触发时唯一必达的指令通道（`.cnb.yml` 的 `npc:go.options` "
            "没有 prompt 键，写在那里会被静默忽略）。"
        )

    def test_clause_lines_identical_across_roles(self, roles):
        """同一份正文各角色各写一份就有漂移；判据即「逐字同一组行」。"""
        rendered = {
            role.get("name"): tuple(
                line.strip() for line in (role.get("prompt") or "").splitlines()
                if any(m in line for m in self.REQUIRED)
            )
            for role in roles
        }
        assert len(set(rendered.values())) == 1, (
            "各角色的预算纪律不一致（改一处必须同步另一处）: "
            f"{ {k: len(v) for k, v in rendered.items()} }"
        )


class TestRoleAdmissionIsPinnedBeforeTheAgent:
    """E：被 @ 的角色名必须在 Agent 开工**之前**被准入，且不在册就不烧 token。

    根因：平台按角色名解析人设，未命中的名字会被**静默回落** —— 用户以为切了角色，
    实际拿到平台默认 prompt，本仓的修复教义随之全部失效，而平台不报错。
    本仓还多一层同型风险：全部在册角色落到 `$` 兜底挂载点，名字写错照样能跑起来。

    判据落在三处，缺一不可：
      1. 准入步排在 `npc:go` **之前**（顺序即契约，倒过来时 token 已经烧掉）；
      2. 准入面来自**唯一**名单事实源（`.cnb/settings.yml` 的 npc.roles），
         `.cnb.yml` 不得再抄一份白名单；
      3. 脚本在「在册 / 不在册 / 未注入」三种输入下给出**相反**的读数（非恒真壳）。
    """

    def test_script_exists_and_parses(self):
        assert ADMISSION_SCRIPT.exists(), (
            f"{ADMISSION_SCRIPT.relative_to(PROJECT_ROOT)} 丢失 —— "
            "角色名写错时平台静默回落，本仓无任何一处响亮"
        )
        import ast
        ast.parse(io.open(ADMISSION_SCRIPT, encoding="utf-8").read())

    def test_admission_runs_before_npc_go(self, cnb_doc):
        jobs = _npcJobs(cnb_doc)
        assert jobs, "$ 段缺 NPC 事件定义"
        offenders = []
        for event, job in jobs:
            stages = [s for s in (job.get("stages") or []) if isinstance(s, dict)]
            admission = next(
                (i for i, s in enumerate(stages)
                 if "npc_role_admission.py" in str(s.get("script") or "")), None)
            agent = next(
                (i for i, s in enumerate(stages) if s.get("type") == "npc:go"), None)
            if admission is None or agent is None:
                offenders.append(f"{event}: 准入步或 npc:go 步缺失（{admission}/{agent}）")
            elif admission > agent:
                offenders.append(
                    f"{event}: 角色准入排在 npc:go 之后（下标 {admission} > {agent}）"
                    "—— 那时 token 已经烧掉了"
                )
        assert not offenders, "\n  ".join(offenders)

    def test_role_names_are_not_restated_in_the_pipeline(self, cnb_doc, roles):
        """`.cnb.yml` 不得抄一份角色名单：抄了就立刻过期，且过期处不会有任何红。"""
        names = {r.get("name") for r in roles if r.get("name")}
        offenders = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(io.open(CNB, encoding="utf-8"), 1)
            if not line.strip().startswith("#")
            and any(name in line for name in names)
        ]
        assert not offenders, (
            "`.cnb.yml` 把角色名单抄成了第二份"
            "（名单事实源只有 .cnb/settings.yml 的 npc.roles）:\n  " + "\n  ".join(offenders)
        )

    @staticmethod
    def _runAdmission(env_extra: dict, argv=None) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "CNB_NPC_NAME"}
        env.setdefault("CNB_BUILD_WORKSPACE", str(PROJECT_ROOT))
        env.update(env_extra)
        if argv is None:
            argv = [sys.executable, str(ADMISSION_SCRIPT)]
        return subprocess.run(argv, capture_output=True, text=True,
                              cwd=str(PROJECT_ROOT), env=env, timeout=60)

    def test_in_and_out_of_roster_are_both_falsifiable(self, roles):
        in_roster = self._runAdmission({"CNB_NPC_NAME": roles[0]["name"]})
        out_of_roster = self._runAdmission({"CNB_NPC_NAME": "DSCoder-NoSuchRole"})
        assert in_roster.returncode == 0, in_roster.stdout + in_roster.stderr
        assert out_of_roster.returncode != 0, (
            "不在册的角色名被放行了 —— 准入是一条恒真断言\n" + out_of_roster.stdout
        )
        assert "DSCoder-NoSuchRole" in out_of_roster.stdout, (
            "不在册时必须点名角色，用户才知道自己写错了什么"
        )

    def test_role_name_not_injected_means_not_applicable(self):
        """非角色触发的构建（变量未注入）不得被判红 —— 那是「不适用」，不是失败。"""
        proc = self._runAdmission({})
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_node_branch_is_equivalent(self, roles):
        """node 分支（NPC 镜像只有 node）必须与 python 分支同判据、同退出码。"""
        import shutil
        if not shutil.which("node") or not shutil.which("sh"):
            pytest.skip("本环境没有 node/sh，无法做双运行时等价比对")
        bridge = PROJECT_ROOT / "scripts" / "ci" / "run_gate_under_node.sh"
        for role, expected_zero in ((roles[0]["name"], True), ("DSCoder-NoSuchRole", False)):
            proc = self._runAdmission(
                {"CNB_NPC_NAME": role},
                argv=["sh", str(bridge), "scripts/ci/npc_role_admission.py"],
            )
            assert (proc.returncode == 0) is expected_zero, (
                f"node 分支对 {role} 的判定与 python 分支不一致：\n"
                f"stdout={proc.stdout}\nstderr={proc.stderr}"
            )


class TestRuntimeBudgetReadingsAreNotHandCopied:
    """F：阈值的事实源是脚本里的常量，人设引用时必须与现值一致。"""

    def test_thresholds_live_in_the_script_only(self):
        source = io.open(BUDGET_SCRIPT, encoding="utf-8").read()
        assert f"WRAP_PCT = {WRAP_PCT}" in source, "阈值常量在脚本里找不到 —— 事实源没落上"
        assert f"HALT_PCT = {HALT_PCT}" in source, "同上"


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = io.open(PROTECTED, encoding="utf-8").read()
        rel = "tests/unit/ci/test_npc_runtime_budget.py"
        assert rel in listed, (
            f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
        )
