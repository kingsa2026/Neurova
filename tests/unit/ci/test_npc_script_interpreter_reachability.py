# -*- coding: utf-8 -*-
"""NPC 流水线脚本解释器的可达性守卫（Issue #151）。

## 一次真实事故（构建 cnb-du8-1k34cfhg1，2026-09-22）

`.cnb.yml` 的 NPC 流水线在 Agent 开工前插了一步「接力判据可达性自证」，
写法是 `python scripts/ci/npc_turn_handoff_gate.py`。该构建的读数逐字如下：

    Runner[10.235.0.29][docker] 2026-09-22 19:02:16 $ python scripts/ci/npc_turn_handoff_gate.py
    sh: 1: python: not found
    Finished, code: 127, duration: 0.1s

Stage status=error → 主链中断 → `npc:go` 那一步被 skipper 跳过。
用户在 Issue 上看到的是「CI/CD 流水线构建失败」，而真实死因是**请求的解释器
在镜像里不存在**：`cnbcool/default-npc:latest` 只有 node，没有 python。
同一条死链在 `issue.comment@npc` 与 `pull_request.comment@npc` 两处逐字重复。

## 这份守卫钉四件事（全部可证伪）

- **A. 解释器先证后用**：每条 NPC 事件的 Job 必须在跑脚本前先探测解释器
  （`command -v` 逐级降级），脚本只用探测结果执行，不写死 `python`。
  可证伪：把 Job 的探测段删掉 → 红。
- **B. 探测结果真给到了 $PATH**：`.cnb.yml` 里探出的 `$NPX` 要么落在 PATH 上、
  要么由脚本写全路径；只把 `NPX` 当普通变量记下来就 `.cnb.yml` 里再
  `source` 一遍，等于白探。可证伪：把 `NPX` 指向一个不在 PATH 的私有变量名 → 红。
- **C. 脚本自身是双运行时可用**：门禁脚本必须带 node 分支，且该分支与 Python
  分支**逐字等价**（同判据、同读数、同退出码）——镜像里只有 node 时，
  判据不能因为换了解释器而漂移。可证伪：删掉脚本里的 node 实现 → 红；
  只把 node 分支写成"永远打印绿灯" → 红（下面用真跑 + 逐字比对拦）。
- **D. 守卫自洽**：本文件必须在受保护子集里，否则 A/B/C 在 CI 上无人执行。

可证伪路径：

- 把某条 NPC 事件定义的探测段删掉 → A 红；
- 把 `NPX=python3` 改成 `PY=python3`（探了但不导出）→ B 红；
- 把门禁脚本的 `NODE_IMPLEMENTATION` 删掉 → C 红；
- 从 `scripts/ci/protected_tests.txt` 摘掉本文件 → D 红。
"""
import io
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 门禁脚本（解释器可达性的被依赖方）
GATE_SCRIPT = PROJECT_ROOT / "scripts" / "ci" / "npc_turn_handoff_gate.py"

#: 探测段的锚点（`.cnb.yml` 的 YAML 锚点名）与探测结果变量名
INTERPRETER_ANCHOR = "&npc-script-interpreter"
INTERPRETER_VAR = "NPX"

#: 探测段必须覆盖的解释器（顺序即优先级）
PROBED_INTERPRETERS = ("python3", "python", "node")

#: 脚本任务里出现的解释器写法白名单：一律走探测结果，不写死解释器名。
SCRIPT_INTERPRETER_ALLOWLIST = re.compile(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?\s")

#: 纯 Shell 内建（不解析 $PATH 的 `command`）——探测段的证据形态
#: 探测行的证据形态：`command -v <解释器>`（if / elif 两种分支写法都认）
PROBE_PATTERN = re.compile(r"command\s+-v\s+([A-Za-z0-9_.-]+)")


@pytest.fixture(scope="module")
def cnb_doc():
    assert CNB.exists(), ".cnb.yml 丢失"
    return yaml.safe_load(io.open(CNB, encoding="utf-8").read())


def _npc_event_jobs(cnb_doc):
    """产出 (事件名, Job) —— 只取含 npc:go 的 NPC 事件流水线。"""
    for mount, body in cnb_doc.items():
        if not isinstance(body, dict):
            continue
        for event, event_body in body.items():
            if not isinstance(event, str) or not event.endswith("@npc"):
                continue
            for job in event_body if isinstance(event_body, list) else []:
                if not isinstance(job, dict):
                    continue
                if any(
                    isinstance(stage, dict) and stage.get("type") == "npc:go"
                    for stage in (job.get("stages") or [])
                ):
                    yield event, job


class TestInterpreterIsProbedBeforeUse:
    """A. 脚本任务的解释器必须先探测、再由探测结果调用。"""

    def test_every_npc_job_probes_interpreters(self, cnb_doc):
        problems = []
        seen = 0
        for event, job in _npc_event_jobs(cnb_doc):
            seen += 1
            probe = job.get("envScript") or ""
            if INTERPRETER_ANCHOR.strip("&") not in str(probe) and not job.get("envScript"):
                problems.append(f"{event}: Job 未声明 envScript 探测段")
                continue
            probed = {m.group(1) for m in PROBE_PATTERN.finditer(str(probe))}
            missing = [name for name in PROBED_INTERPRETERS if name not in probed]
            if missing:
                problems.append(
                    f"{event}: 探测段未覆盖 {missing}（只探部分解释器，"
                    "镜像里换一种就再次 127）"
                )
        assert seen, "未在 .cnb.yml 找到任何 npc:go 流水线 —— 本守卫空转"
        assert not problems, (
            "NPC 流水线的脚本解释器没有被探测（构建 cnb-du8-1k34cfhg1 的 127 死因）:\n  "
            + "\n  ".join(problems) +
            "\n`cnbcool/default-npc:latest` 只有 node，没有 python；"
            "写死 `python <script>` 会在镜像里以 `sh: 1: python: not found`（rc=127）"
            "中断主链，Agent 那一步被 skipper 跳过，而用户只看到「构建失败」。"
        )

    def test_script_stages_call_the_probed_interpreter(self, cnb_doc):
        """含脚本正文的 stage 不得写死 python/node，必须用探测结果变量。"""
        offenders = []
        for mount, body in cnb_doc.items():
            if not isinstance(body, dict):
                continue
            for event, event_body in body.items():
                if not isinstance(event, str) or not event.endswith("@npc"):
                    continue
                for job in event_body if isinstance(event_body, list) else []:
                    if not isinstance(job, dict):
                        continue
                    for stage in job.get("stages") or []:
                        script = str((stage or {}).get("script") or "")
                        if not script or INTERPRETER_ANCHOR.strip("&") in script:
                            continue
                        if not SCRIPT_INTERPRETER_ALLOWLIST.match(script):
                            offenders.append(f"{mount}.{event}: {script.strip()}")
        assert not offenders, (
            "以下 NPC stage 的脚本没走探测结果解释器:\n  " + "\n  ".join(offenders) +
            f"\n统一写成 `\"${INTERPRETER_VAR} scripts/...\"`，变量由 Job 的探测段给出。"
        )

    def test_probe_binds_a_path_reachable_variable(self, cnb_doc):
        """B. 探测结果必须落在 PATH 可达的名字上（改了名却没人认，等于没探）。"""
        text = io.open(CNB, encoding="utf-8").read()
        assert INTERPRETER_ANCHOR in text, (
            f"`.cnb.yml` 缺探测段锚点 {INTERPRETER_ANCHOR}"
        )
        # 赋值与 `then` 同行（`... then NPX=python3`），故用两次上下文锚定：
        # 取探测段正文，再在正文里抽 `NPX=<解释器>`。
        probe_body = "\n".join(
            line for line in text.splitlines()
            if line.strip().startswith(("if ", "elif ", "then ", "else", "fi"))
            or "NPX=" in line
        )
        assignments = re.findall(
            rf"{INTERPRETER_VAR}=([A-Za-z0-9_./-]+)", probe_body
        )
        assert set(assignments) <= set(PROBED_INTERPRETERS), (
            f"{INTERPRETER_VAR} 被指向未登记的解释器: {sorted(set(assignments) - set(PROBED_INTERPRETERS))}"
        )
        assert len(assignments) >= len(PROBED_INTERPRETERS), (
            f"{INTERPRETER_VAR} 的赋值分支不足（应覆盖 {PROBED_INTERPRETERS}）"
        )
        uses = re.findall(rf"\$\{{?{INTERPRETER_VAR}\}}?", text)
        assert uses, (
            f"探测出 {INTERPRETER_VAR} 却没有任何消费方 —— 探了不用就是把死配置换个形态"
        )


class TestGateScriptRunsOnBothInterpreters:
    """C. 门禁脚本必须双运行时可用，且两个分支逐字等价。"""

    def test_script_carries_a_node_implementation(self):
        text = io.open(GATE_SCRIPT, encoding="utf-8").read()
        assert "NODE_IMPLEMENTATION" in text, (
            "门禁脚本没有 node 实现 —— NPC 镜像里没有 python 时判据直接不可达"
        )
        assert "process.exit(main(" in text, "node 实现未把退出码交回给进程"
        assert "python3" in text and "node" in text, (
            "脚本未声明解释器降级顺序（python3 → python → node）"
        )

    def test_node_and_python_readings_are_identical(self, tmp_path):
        """真跑两个分支：同判据、同读数、同退出码（逐字比对）。"""
        node = shutil.which("node")
        if node is None:
            pytest.skip("本环境无 node，无法做双运行时等价比对")

        text = io.open(GATE_SCRIPT, encoding="utf-8").read()
        match = re.search(
            r'NODE_IMPLEMENTATION = r"""\n(.*?)\n"""', text, re.S
        )
        assert match, "取不到脚本里的 node 实现正文"
        node_script = tmp_path / "gate_node.js"
        node_script.write_text(match.group(1) + "\n", encoding="utf-8")

        workspace = tmp_path / "ws"
        workspace.mkdir()
        base_env = {"PATH": "/usr/bin:/bin:/usr/local/bin"}

        for workspace_env in (
            {"CNB_BUILD_WORKSPACE": str(workspace)},   # 落点可达
            {},                                        # 落点缺失（必须判红）
        ):
            for flag in ([], ["--json"]):
                python_run = subprocess.run(
                    [sys.executable, str(GATE_SCRIPT), *flag],
                    capture_output=True, text=True, cwd=str(tmp_path),
                    env={**base_env, **workspace_env}, timeout=60,
                )
                node_run = subprocess.run(
                    [node, str(node_script), *flag],
                    capture_output=True, text=True, cwd=str(tmp_path),
                    env={**base_env, **workspace_env}, timeout=60,
                )
                assert python_run.returncode == node_run.returncode, (
                    f"两个分支的退出码不一致（flag={flag} env={workspace_env}）:\n"
                    f"python={python_run.returncode} node={node_run.returncode}\n"
                    f"python stderr={python_run.stderr}\nnode stderr={node_run.stderr}"
                )
                assert python_run.stdout == node_run.stdout, (
                    "两个分支的读数不一致（换了解释器就换判据 = 判据不唯一）:\n"
                    f"python={python_run.stdout!r}\nnode={node_run.stdout!r}"
                )

    def test_missing_workspace_still_fails_loudly(self, tmp_path):
        """缺落点必须响亮判红：换 node 跑也不例外（不得降级成静默绿灯）。"""
        node = shutil.which("node")
        if node is None:
            pytest.skip("本环境无 node")
        text = io.open(GATE_SCRIPT, encoding="utf-8").read()
        match = re.search(r'NODE_IMPLEMENTATION = r"""\n(.*?)\n"""', text, re.S)
        node_script = tmp_path / "gate_node.js"
        node_script.write_text(match.group(1) + "\n", encoding="utf-8")
        result = subprocess.run(
            [node, str(node_script), "--json"],
            capture_output=True, text=True, cwd=str(tmp_path),
            env={"PATH": "/usr/bin:/bin"}, timeout=60,
        )
        assert result.returncode == 1, (
            f"缺 CNB_BUILD_WORKSPACE 时 node 分支没判红: rc={result.returncode}\n{result.stdout}"
        )
        assert "CNB_BUILD_WORKSPACE" in result.stdout


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = io.open(PROTECTED, encoding="utf-8").read()
        rel = "tests/unit/ci/test_npc_script_interpreter_reachability.py"
        assert rel in listed, (
            f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
        )
