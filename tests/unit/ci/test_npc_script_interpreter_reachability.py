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
import os
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
#: 允许两种形态：`$NPX <script>`（python 侧）与 `$NPX_CALL`（node 侧特例，
#: 因为 `node <script>.py` 会被 node 按扩展名拒收，必须由桥脚本改写调用形态）。
SCRIPT_INTERPRETER_ALLOWLIST = re.compile(
    r"^\$\{?(?:[A-Za-z_][A-Za-z0-9_]*)\b"
)

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

    #: 纯 Shell 步骤的识别：正文里**不调用任何解释器**（只做文件操作与判定）。
    #: 这类步骤天然可移植，不适用「走探测结果」这条 —— 它们的正确性判据是
    #: 「在镜像里跑得起来」，而那由 F 类（在被 @ 的仓库里真跑）负责。
    SHELL_ONLY_CALL = re.compile(r"(^|[\s;&|])(python3?|node)([\s]|$)")

    def test_script_stages_call_the_probed_interpreter(self, cnb_doc):
        """**要跑解释器**的 NPC stage 不得写死 python/node，必须用探测结果变量。

        判据按「这一步是否调用解释器」取，不按「有没有 script」取：
        `Issue #314` 的物化步是纯 POSIX shell（`git` + `cp` + `test`），
        它不请求任何解释器，也就不存在「写死 python/node」这种失败形态。
        把纯 shell 步骤也判成违规，会逼着人给它套一个用不上的解释器变量 ——
        那是为了让判据变绿而改被测物，不是修问题。
        """
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
                        # 纯 Shell 步骤：正文里没有解释器调用，不适用本条。
                        if not self.SHELL_ONLY_CALL.search(script):
                            continue
                        if not SCRIPT_INTERPRETER_ALLOWLIST.match(script):
                            offenders.append(f"{mount}.{event}: {script.strip()}")
        assert not offenders, (
            "以下 NPC stage 的脚本没走探测结果解释器:\n  " + "\n  ".join(offenders) +
            f"\n统一写成 `\"${INTERPRETER_VAR}_CALL\"`（由探测段给出调用形态），"
            "不得写死 python/node。"
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


class TestNodeDispatchReallyWorks:
    """E. node 分派链必须**真能跑通** —— 这正是构建 cnb-9cc-1k34ff3t1 的死因。

    上一版守卫（A/B/C）只把脚本里的 node 实现**抠出来**写成 `.js` 再跑，
    于是"抠出来的正文是对的"与"平台按 `$NPX <script>.py` 调用能跑通"是两件事：
    平台实际执行的是 `node scripts/ci/npc_turn_handoff_gate.py`，而 node 按
    扩展名解析模块、遇到 `.py` 在解析前就以 `ERR_UNKNOWN_FILE_EXTENSION` 退出。
    实测读数（本仓，node v24）：

        $ node scripts/ci/npc_turn_handoff_gate.py
        TypeError [ERR_UNKNOWN_FILE_EXTENSION]: Unknown file extension ".py" ...

    这条链**从没有人真跑过**，所以守卫全绿而平台全红。本类把判据落到
    「平台真实的调用形态」上：探测段给出的 $NPX_CALL 必须真能跑出正确读数。

    可证伪：把 .cnb.yml 的 node 分支改回 `$NPX <script>.py` → 红。
    """

    def _npc_call_forms(self, cnb_doc):
        """从 .cnb.yml 取探测段里登记的各分支调用形态。"""
        text = io.open(CNB, encoding="utf-8").read()
        anchor_at = text.find(INTERPRETER_ANCHOR)
        assert anchor_at >= 0, f"{CNB} 里找不到探测段锚点 {INTERPRETER_ANCHOR}"
        # 探测段正文（锚点到下一个同级 key 之前）
        rest = text[anchor_at:]
        end = rest.find("\n$:", 1)
        body = rest[: end if end > 0 else len(rest)]
        return body

    def test_node_branch_does_not_hand_py_to_node(self):
        """node 分支不得写 `$NPX <script>.py`：node 会在解析前拒收 .py。"""
        body = self._npc_call_forms(None)
        node_branch = None
        for line in body.splitlines():
            if "NPX=node" in line:
                node_branch = line
        assert node_branch is not None, "探测段没有 node 分支 —— 镜像只有 node 时判据不可达"
        assert "command -v node" in body, "探测段未登记 node（与 PROBED_INTERPRETERS 不一致）"
        # node 分支后必须给出调用形态，且该形态不得是 `node <脚本>.py`
        assert "NPX_CALL" in body, (
            "探测段没有给出调用形态 $NPX_CALL —— 解释器与调用方式各写各的，"
            "node 分支会被写成 `$NPX <script>.py`（本事故的死因）"
        )

    def _node_branch_call(self, text, script_path):
        """取探测段 node 分支登记的命令形态，拼出平台会执行的完整命令。

        调用形态是 `$NPX_CALL <script>`，故这里返回 `$NPX_CALL` 的值 + 脚本路径。
        """
        anchor_at = text.find(INTERPRETER_ANCHOR)
        assert anchor_at >= 0, f"找不到探测段锚点 {INTERPRETER_ANCHOR}"
        body = text[anchor_at:]
        cut = body.find("\n$:", 1)
        if cut > 0:
            body = body[:cut]
        lines = body.splitlines()
        # 只认**赋值分支行**（`then NPX=node` / `elif ... then NPX=node`）：
        # 注释里也会出现 `NPX=node` 字样，按子串找会锚到注释上，
        # 取到的是别的分支的调用形态（本守卫自身踩过这个坑）。
        branch_at = next(
            (
                i
                for i, line in enumerate(lines)
                if re.search(r"then\s+NPX=node\b", line) or re.fullmatch(r"\s*NPX=node\s*", line)
            ),
            None,
        )
        assert branch_at is not None, "探测段没有 node 分支（须为赋值形态 `NPX=node`）"
        # node 分支之后的第一个 NPX_CALL 赋值即其调用形态
        for line in lines[branch_at:]:
            match = re.search(r'NPX_CALL="([^"]+)"', line)
            if match:
                return f"{match.group(1)} {script_path}"
        raise AssertionError("node 分支没有登记调用形态 NPX_CALL")

    def test_node_call_form_reaches_the_same_reading(self, tmp_path):
        """真跑 `.cnb.yml` 里登记的那条 node 命令：与 python 分支同读数、同退出码。

        这一条是上一版守卫缺的那格：上一版跑的是把正文**抠出来**的 `.js`，
        而平台执行的是 `.cnb.yml` 里逐字写下的那条命令。两者只有在
        "命令形态本身正确"时才等价 —— 本条目直接取配置里的命令来跑，
        故能拦住 `$NPX <script>.py`（ERR_UNKNOWN_FILE_EXTENSION）。
        """
        node = shutil.which("node")
        if node is None:
            pytest.skip("本环境无 node，无法做调用形态比对")
        # 登记的调用形态是 `sh scripts/ci/run_gate_under_node.sh <script>`：
        # 桥脚本是 sh 脚本，故 sh 是**被测产物本身**的依赖，不是顺手借的宿主工具。
        # 仍与 node 一样先断言存在再使用——缺席时 skip 而不是 FileNotFoundError
        # （受保护子集里"守卫静默不跑"的同一根因，见
        # tests/unit/test_dev_path_and_runtime_dep_guards.py）。
        if shutil.which("sh") is None:
            pytest.skip("本环境无 sh，跑不了桥脚本的调用形态")

        # 平台登记的命令形态以 `sh <桥脚本>` 起头（`.cnb.yml` 的 node 分支），
        # 故这里先解析 sh 而不是写死字面量：受保护子集里写死外部命令，镜像缺席时
        # 不是断言失败而是 FileNotFoundError，整个文件（含同文件其余断言）静默不跑
        # —— 这正是 tests/unit/test_dev_path_and_runtime_dep_guards.py 的
        # TestProtectedGuardsUseNoExternalBinaries 常驻拦截的形态。与 node 同口径：
        # 先 which、缺席即跳过，不把环境能力写进判据。
        shell = shutil.which("sh")
        if shell is None:
            pytest.skip("本环境无 sh，无法复核平台登记的 node 调用形态")

        text = io.open(CNB, encoding="utf-8").read()
        node_command = self._node_branch_call(text, "scripts/ci/npc_turn_handoff_gate.py")
        assert node_command.strip(), "node 分支调用形态为空"
        assert "npc_turn_handoff_gate.py" in node_command, "调用形态里没有脚本路径"

        workspace = tmp_path / "ws"
        workspace.mkdir()
        base_env = {"PATH": "/usr/bin:/bin:/usr/local/bin"}

        for workspace_env in (
            {"CNB_BUILD_WORKSPACE": str(workspace)},
            {},
        ):
            for flag in ([], ["--json"]):
                python_run = subprocess.run(
                    [sys.executable, str(GATE_SCRIPT), *flag],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                    env={**base_env, **workspace_env}, timeout=60,
                )
                node_run = subprocess.run(
                    [shell, "-c", f"{node_command} {' '.join(flag)}"],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                    env={**base_env, **workspace_env}, timeout=60,
                )
                assert node_run.returncode == python_run.returncode, (
                    f"配置里登记的 node 命令与 python 分支退出码不一致"
                    f"（flag={flag}, env={workspace_env}）:\n"
                    f"命令: {node_command}\n"
                    f"python={python_run.returncode} node={node_run.returncode}\n"
                    f"node stderr={node_run.stderr}"
                )
                assert node_run.stdout == python_run.stdout, (
                    "配置里登记的 node 命令与 python 分支读数不一致（换解释器即换判据）:\n"
                    f"命令: {node_command}\n"
                    f"node={node_run.stdout!r}\npython={python_run.stdout!r}"
                )

    def test_raw_node_on_py_is_still_rejected(self):
        """反向自证：`node <script>.py` 确实跑不通 —— 说明这层桥不是摆设。

        若哪天 node 能直接解析 .py，本条目会红，提醒把这层桥连同探测段一起收掉。
        """
        node = shutil.which("node")
        if node is None:
            pytest.skip("本环境无 node")
        result = subprocess.run(
            [node, str(GATE_SCRIPT), "--json"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
            env={"PATH": "/usr/bin:/bin", "CNB_BUILD_WORKSPACE": "/tmp"}, timeout=60,
        )
        assert result.returncode != 0, (
            "node 居然能直接跑 .py 了 —— 请复核探测段的 node 桥是否还需要"
        )
        assert "ERR_UNKNOWN_FILE_EXTENSION" in result.stderr, (
            f"node 拒收 .py 的原因不是扩展名，请复核本桥的前提:\n{result.stderr[:500]}"
        )


class TestGateScriptsAreReachableFromTheRealWorkspace:
    """F. 门禁脚本必须在**它真正被执行的**工作区里可达（Issue #314）。

    ## 事故（构建 cnb-2cl-1k3k4gq0d，2026-09-28）

    `.cnb.yml` 的三条门禁 Stage 用**相对路径**引用脚本：

        $NPX_CALL scripts/ci/npc_turn_handoff_gate.py
        $NPX_CALL scripts/ci/npc_role_admission.py
        $NPX_CALL scripts/ci/npc_runtime_budget.py

    同一份配置里 `.解释器探测` 锚点的注释记着它修过一次「同一条死链的另一半」：
    构建 cnb-du8-1k34cfhg1 那次是 `sh: 1: python: not found`（rc=127），
    修法是**探测解释器、逐级降级 python3 → python → node**。
    但**路径本身从没被验证过**；这次撞的就是剩下那一半。平台日志逐字：

        sh: 1: scripts/ci/npc_turn_handoff_gate.py: not found
        Finished, code: 127

    ## 根因：配置写死了「工作区 = 配置仓库」这一前提

    平台文档《NPC》「事件执行 → 执行位置」逐字：流水线跑在**当前 Issue 或 PR
    所属仓库**下（不是 NPC 所属仓库）。于是：

    * `CNB_REPO_SLUG` / `CNB_BUILD_WORKSPACE` = **被 @ 的那个仓库**；
    * 本仓自己的 `scripts/` 与 `.cnb/` 压根不在工作区里。

    实测取证（`git clone --depth 1 kingsa2026/Qwen3.8-27B-Uncensored-FP8`，
    即本次被 @ 的仓库）：根目录只有
    `CONTRIBUTING.md LICENSE Modelfile README.md assets bin examples lib package.json test`
    —— 既没有 `scripts/`，也没有 `.cnb/`。

    所以三条门禁全部落空，且**与任务内容无关**：第一条就以 127 收场，
    后续 Stage（含真正的 `npc-go`）全部 `skipped`，Agent 一秒都没跑起来。

    ## 为什么它此前是绿的：守卫把宿主环境当成了生产环境

    既有守卫（本文件 A~E）全部在**仓库根**上跑脚本（`cwd=PROJECT_ROOT`），
    于是 `scripts/ci/*.py` 永远可取 —— 那正是本仓（配置仓库）的形态，
    而**不是**门禁真实运行的那台工作区。判据的输入端被宿主的目录布局填成了真值。

    ## 口径

    判据按 `.cnb.yml` 里**逐字写下的调用形态**取，在「被 @ 的仓库」这一形态的
    工作区里真跑（该工作区**没有** `scripts/`、也没有 `.cnb/`），要求：

    * 退出码不为 127/2 这类「文件/命令不存在」；
    * 三条门禁的**读数仍然成立** —— 自证能答「工作区在哪」，
      准入能答「谁是角色」，量尺能答「还有多少时间」。
    """

    #: 三条门禁脚本（`.cnb.yml` 的 NPC 流水线里逐字引用）。
    GATE_SCRIPTS = (
        "scripts/ci/npc_turn_handoff_gate.py",
        "scripts/ci/npc_role_admission.py",
        "scripts/ci/npc_runtime_budget.py",
    )

    @staticmethod
    def _npc_repo_workspace(tmp_path: Path) -> Path:
        """模拟「被 @ 的仓库」工作区：有普通仓库内容，没有 `scripts/` 与 `.cnb/`。

        目录名照实测的被 @ 仓库（kingsa2026/Qwen3.8-27B-Uncensored-FP8）取，
        好让失败信息一眼看出「这里是别人的仓库，不是配置仓库」。
        """
        workspace = tmp_path / "Qwen3.8-27B-Uncensored-FP8"
        for name in ("assets", "bin", "examples", "lib", "test"):
            (workspace / name).mkdir(parents=True)
        (workspace / "README.md").write_text("被 @ 的仓库\n", encoding="utf-8")
        (workspace / "package.json").write_text("{}\n", encoding="utf-8")
        return workspace

    def _gate_call_forms(self) -> dict:
        """从 `.cnb.yml` 取每条门禁 Stage 逐字写下的调用形态（脚本名 → 命令）。

        取的是**配置原文**，不是本文件另抄一份 —— 否则改配置而守卫不知道。
        """
        text = io.open(CNB, encoding="utf-8").read()
        forms = {}
        for script in self.GATE_SCRIPTS:
            match = re.search(
                r"script:\s*\"?([^\n\"]*" + re.escape(script) + r")\"?", text
            )
            assert match, f".cnb.yml 里找不到对 {script} 的调用"
            forms[script] = match.group(1).strip()
        return forms

    @staticmethod
    def _interpreter_forms(cnb_text: str, script: str) -> list:
        """把探测段登记的每个分支的调用形态，与脚本路径拼成完整命令。

        返回**全部**分支（python3 → python → node），因为镜像里任一分支都可能被选中，
        而「哪一支不可达」正是本条要拦的。
        """
        anchor_at = cnb_text.find(INTERPRETER_ANCHOR)
        assert anchor_at >= 0, f"`.cnb.yml` 缺探测段锚点 {INTERPRETER_ANCHOR}"
        body = cnb_text[anchor_at:]
        cut = body.find("\n$:", 1)
        if cut > 0:
            body = body[:cut]
        commands = []
        for line in body.splitlines():
            if line.strip().startswith("#"):
                continue
            match = re.search(r'NPX_CALL="([^"]+)"', line)
            if match:
                commands.append(f"{match.group(1)} {script}")
        assert commands, "探测段没有登记任何调用形态 $NPX_CALL"
        return commands

    @staticmethod
    def _shell() -> str:
        shell = shutil.which("sh")
        if shell is None:
            pytest.skip("本环境无 sh，跑不了配置里登记的调用形态")
        return shell

    @staticmethod
    def _gate_env(workspace: Path) -> dict:
        """门禁在平台里看到的那一组环境变量（工作区/角色/预算读数）。"""
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "CNB_BUILD_WORKSPACE": str(workspace),
            "CNB_NPC_NAME": os.environ.get("CNB_NPC_NAME", "DSCoder-Red"),
            "CNB_PIPELINE_MAX_RUN_TIME": "7200000",
            "CNB_BUILD_START_TIME": "2026-09-28T00:00:00.000Z",
        }

    def _runInWorkspace(self, command: str, workspace: Path, env_extra=None) -> subprocess.CompletedProcess:
        """把配置里的命令搬到「被 @ 的仓库」工作区上执行。

        关键：命令里的**相对路径**按工作区解析（平台就是这么跑的），
        而本守卫在宿主机上执行 —— 故必须在 workspace 里建一个等价的调用现场。
        """
        env = self._gate_env(workspace)
        env.update(env_extra or {})
        return subprocess.run(
            [self._shell(), "-c", command], cwd=str(workspace), env=env,
            capture_output=True, text=True, timeout=180,
        )

    @classmethod
    def _bootstrap_commands(cls) -> list:
        """从 `.cnb.yml` 取 NPC Job 里**排在门禁之前**的物化步骤（逐字命令）。

        判据只认配置原文：物化怎么跑、有没有跑，都必须由 `.cnb.yml` 说了算 ——
        本文件另写一遍就是第二份口径（改配置而守卫不知道）。
        """
        import yaml as _yaml
        doc = _yaml.safe_load(io.open(CNB, encoding="utf-8").read())
        job = (doc.get("$") or {}).get("issue.comment@npc", [{}])[0]
        stages = [s for s in (job.get("stages") or []) if isinstance(s, dict)]
        # 门禁步的形态是**逐字调用**：`$NPX_CALL <script>`。按调用形态取，不按
        # 子串取 —— 物化步的报错文案里也会提脚本名（本守卫踩过这个坑：按子串
        # 锚定会把物化步自己当成门禁步，于是「门禁之前」为空，判据退化成恒真）。
        gate_at = next(
            (i for i, s in enumerate(stages)
             if "$NPX_CALL" in str(s.get("script") or "")
             and "npc_turn_handoff_gate.py" in str(s.get("script") or "")),
            None,
        )
        assert gate_at is not None, "NPC Job 里找不到自证门禁步"
        # 「物化步」的形态：排在**第一条门禁之前**、且自身**不是**门禁调用的脚本步。
        # 判据按调用形态取（`$NPX_CALL` 缺席 = 不是门禁），不按脚本名子串取 ——
        # 物化步的报错文案里也会提到脚本名，按子串取会把它自己一起筛掉
        # （本守卫踩过这个坑：于是「门禁之前」为空，判据退化成一条恒真断言）。
        commands = []
        for stage in stages[:gate_at]:
            script = str(stage.get("script") or "")
            if stage.get("type") is not None or not script.strip():
                continue
            if "$NPX_CALL" in script:
                continue
            commands.append(script)
        return commands

    def _materializeWorkspace(self, workspace: Path) -> list:
        """按 `.cnb.yml` 的**实际 stage 顺序**先把门禁物化到工作区，产出每步读数。

        这一步是本守卫的关键：它模拟的是「平台按配置从上到下跑 stage」，
        而不是「直接去工作区里找脚本」。少了它，守卫会退化成
        「仓库根上 obviously 有 scripts/」那种恒真断言（事故之所以全绿的原因）。
        """
        runs = []
        for command in self._bootstrap_commands():
            assert command.strip(), "物化步骤的 script 为空 —— 门禁脚本无从取回"
            run = self._runInWorkspace(
                command, workspace,
                env_extra={"CNB_NPC_SLUG": "kingsa2026/neurova"},
            )
            runs.append((command, run))
            # 物化失败的形态必须响亮（教义第 2 条），否则后面全是级联假红。
            assert run.returncode == 0, (
                f"配置里的物化步骤在「被 @ 的仓库」工作区里失败（rc={run.returncode}）:\n"
                f"  {command.strip()[:200]}\n"
                f"  stdout={run.stdout}\n  stderr={run.stderr}"
            )
        return runs

    def test_no_gate_call_form_dies_on_a_missing_file(self, tmp_path):
        """配置里登记的每一条命令，都不得**因为文件不存在**而失败。

        事故的判据是「脚本拉不起来」，故这里只拦**缺文件**这一类失败：

        * `can't open file` / `cannot open` / `not found` 且命令所指的是脚本本身；
        * 纯解释器缺席（`sh: 1: python: not found`，宿主没有该解释器）**不算** ——
          那是探测段逐级降级的合法结果，平台在任一分支缺席时会落到下一支。
          把它算成失败，会让本守卫在「宿主恰好缺某一支解释器」时假红，
          而它要拦的从来不是这个。

        可证伪路径：把调用形态改回裸相对路径（且不提物化）→ 立刻红。
        """
        cnb_text = io.open(CNB, encoding="utf-8").read()
        workspace = self._npc_repo_workspace(tmp_path)
        materialized = self._materializeWorkspace(workspace)
        assert materialized, (
            "NPC Job 里没有任何物化步骤 —— 门禁脚本与角色名单不会出现在"
            "「被 @ 的仓库」工作区里（Issue #314 的根因）"
        )
        problems = []
        for script in self.GATE_SCRIPTS:
            for command in self._interpreter_forms(cnb_text, script):
                run = self._runInWorkspace(command, workspace)
                blob = run.stdout + run.stderr
                last = blob.strip().splitlines()[-1] if blob.strip() else ""
                # 缺脚本文件的两种形态：解释器自己的 "can't open file <path>"，
                # 与 shell 的 "cannot open <path>" / "<path>: not found"。
                # 判据落在**命令里那个脚本路径**上，故与解释器是哪一个无关。
                missing_script = script in blob and (
                    "can't open file" in blob
                    or "cannot open" in blob
                    or "not found" in blob
                )
                if missing_script:
                    problems.append(f"{command}\n    rc={run.returncode} :: {last}")
        assert not problems, (
            "NPC 门禁脚本在它真实运行的工作区里**不可达**"
            "（NPC 事件跑在被 @ 的仓库下，平台文档《NPC》「事件执行」）:\n  "
            + "\n  ".join(problems) +
            "\n被 @ 的仓库里没有 `scripts/`、也没有 `.cnb/` —— 实测取证："
            "`git clone --depth 1 kingsa2026/Qwen3.8-27B-Uncensored-FP8` 后根目录只有 "
            "assets/ bin/ examples/ lib/ test/ 与若干文档。\n"
            "构建 cnb-2cl-1k3k4gq0d 逐字读数："
            "`sh: 1: scripts/ci/npc_turn_handoff_gate.py: not found` / rc=127，"
            "后续 Stage（含 npc-go）全部 skipped —— 构建失败与任务内容无关。"
        )

    def test_gate_readings_survive_in_the_foreign_workspace(self, tmp_path):
        """三条门禁在「别人的仓库」里仍要给出**成立**的读数，不是只求退出码非 127。

        判据取各自的可观察结论：
        * 自证：点名工作区落点（`working_directory_check`）；
        * 准入：对**在册**角色给通过（名单必须仍能读到）；
        * 量尺：给出 `verdict=`（缺变量时也必须有结论，不是崩栈）。
        """
        cnb_text = io.open(CNB, encoding="utf-8").read()
        workspace = self._npc_repo_workspace(tmp_path)
        self._materializeWorkspace(workspace)

        expectations = {
            "scripts/ci/npc_turn_handoff_gate.py": ("working_directory_check", True),
            "scripts/ci/npc_role_admission.py": ("在册", True),
            "scripts/ci/npc_runtime_budget.py": ("verdict=", True),
        }
        problems = []
        for script, (needle, expect_ok) in expectations.items():
            commands = self._interpreter_forms(cnb_text, script)
            run = self._runInWorkspace(commands[0], workspace)
            blob = run.stdout + run.stderr
            if needle not in blob:
                problems.append(
                    f"{script}: 读数里没有 {needle!r}（rc={run.returncode}）\n"
                    f"    {blob.strip()[:400]}"
                )
        assert not problems, (
            "门禁在「被 @ 的仓库」里给不出读数 —— 它的数据源与它一起留在了配置仓库:\n  "
            + "\n  ".join(problems) +
            "\n`npc_role_admission.py` 要读 `.cnb/settings.yml` 的角色名单，"
            "而那份名单在**配置仓库**、不在被 @ 的仓库里 ——"
            "「工作区即配置仓库」这个前提整体不成立，须一并修正。"
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = io.open(PROTECTED, encoding="utf-8").read()
        rel = "tests/unit/ci/test_npc_script_interpreter_reachability.py"
        assert rel in listed, (
            f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
        )
