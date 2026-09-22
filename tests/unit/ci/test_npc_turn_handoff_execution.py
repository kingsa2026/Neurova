# -*- coding: utf-8 -*-
"""NPC 轮数触顶接力的**执行面**守卫（Issue #145）。

## 为什么需要这份守卫

配置面已经有一份守卫（`tests/unit/test_ci_npc_config_guard.py` 的
`TestTurnHandoffCeiling`）：它钉住「`.cnb.yml` 里有这笔接力」——
`endStages` 里存在 `cnb:apply`、`event` 与触发事件同名、标记经 `env` 传下来。

但那份配置**从来没有被执行过**：接力 Stage 的 `if` 读的标记是 Agent 自己
在最后一轮写出的文件，而写在哪里由人设文本约定。构建 cnb-2e8-1k341d9s1 的
实测形态正是这样：

    Master[agent][201] stop with error: Agent aborted: reached maxTurns limit (200)
    ✅ DebugDetection / End 通过
    ⏳ 轮数触顶接力：自动开启下一轮 → skipped

Agent 从未写出标记，于是 `if` 恒假、接力被跳过、成果随容器一起丢，
用户在 Issue 上只看到「流水线构建失败」。配置面守卫对此是完全绿的 ——
它只能证明"接力被声明过"，证明不了"接力会真的发生"。

## 本文件钉三件事（都可证伪）

- **A 落点词汇统一**：`$CNB_BUILD_WORKSPACE` 是接力判据的唯一落点，
  凡提到"标记写在哪"的人设文本必须用这个变量，不得退化成
  「工作区工作目录 / 构建目录 / workspace 目录」这类字面表述 ——
  后者会让 Agent 把它理解成 `$PWD`，在两者不同的构建里写错位置。
- **B 落点在构建里可达**：`scripts/ci/npc_turn_handoff_gate.py` 存在，
  且被 `.cnb.yml` 的 NPC 流水线真实执行（不是躺在仓库里当摆设）。
- **C 门禁留在受保护子集**：门禁脚本的判据要在 CI 上真的跑，否则 A/B 无人执行。

可证伪路径：
- 把 `.cnb.yml` 里跑门禁的那一步删掉 → B 红；
- 把人设里 `$CNB_BUILD_WORKSPACE/.npc-turn-handoff` 改写成「工作区工作目录」→ A 红；
- 从 `scripts/ci/protected_tests.txt` 摘掉本文件 → C 红。
"""
import ast
import io
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"
SETTINGS = PROJECT_ROOT / ".cnb" / "settings.yml"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 接力标记的文件名（与 `.cnb/settings.yml` 人设、`.cnb.yml` 收尾阶段同一事实源）
HANDOFF_MARKER_FILE = ".npc-turn-handoff"

#: 落点变量：标记必须写在 `$CNB_BUILD_WORKSPACE` 下，而不是「工作目录」这类字面表述。
HANDOFF_ROOT_VAR = "$CNB_BUILD_WORKSPACE"

#: 门的脚本（接力判据可达性自证）
GATE_SCRIPT = PROJECT_ROOT / "scripts" / "ci" / "npc_turn_handoff_gate.py"

#: 人设提到标记落点时的**正确**写法（逐字）
MARKER_PATH_IN_PERSONA = f"{HANDOFF_ROOT_VAR}/{HANDOFF_MARKER_FILE}"

#: 同一句话里绝不允许出现的模糊说法：它们会被读成 `$PWD`，而非工作区根。
VAGUE_ROOT_PHRASES = ("工作区工作目录", "构建目录", "workspace 目录", "工作目录下")


@pytest.fixture(scope="module")
def cnb_doc():
    assert CNB.exists(), ".cnb.yml 丢失"
    return yaml.safe_load(io.open(CNB, encoding="utf-8").read())


@pytest.fixture(scope="module")
def npc_personas():
    """NPC 角色名 → 人设正文（人设是给 Agent 的唯一必达通道）。"""
    doc = yaml.safe_load(io.open(SETTINGS, encoding="utf-8").read())
    roles = (doc.get("npc") or {}).get("roles") or []
    assert roles, ".cnb/settings.yml 未声明任何 NPC 角色"
    return {r.get("name"): (r.get("prompt") or "") for r in roles}


class TestHandoffRootIsTheWorkspaceVariable:
    """A. 标记落点必须用 `$CNB_BUILD_WORKSPACE` 表达，不得退化成字面目录名。"""

    def test_personas_state_the_marker_path_with_the_workspace_variable(self, npc_personas):
        missing = [name for name, prompt in npc_personas.items() if MARKER_PATH_IN_PERSONA not in prompt]
        assert not missing, (
            f"NPC 人设未把标记落点写成 {MARKER_PATH_IN_PERSONA}: {missing}\n"
            "收尾阶段读的是 `$CNB_BUILD_WORKSPACE/"
            f"{HANDOFF_MARKER_FILE}`；写法一旦含糊（如「工作区工作目录」），"
            "Agent 会把它当成 $PWD，在两者不同的构建里写到收尾读不到的位置，"
            "接力整条失效（构建 cnb-2e8-1k341d9s1 的跳过形态）。"
        )

    def test_personas_do_not_use_vague_directory_phrases(self, npc_personas):
        offenders = []
        for name, prompt in npc_personas.items():
            for line in prompt.splitlines():
                if HANDOFF_MARKER_FILE not in line:
                    continue
                for phrase in VAGUE_ROOT_PHRASES:
                    if phrase in line:
                        offenders.append(f"{name}: 「{phrase}」出现在 {line.strip()}")
        assert not offenders, (
            "标记落点用了会被读成 $PWD 的模糊表述:\n  " + "\n  ".join(offenders) +
            f"\n统一写成 {MARKER_PATH_IN_PERSONA}（单一事实源）。"
        )

    def test_cnb_comment_only_cites_the_variable_form(self, cnb_doc):
        """`.cnb.yml` 里提到标记落点时，同样只准用变量形态。"""
        text = io.open(CNB, encoding="utf-8").read()
        bad = [
            f"{lineno}: {line.strip()}"
            for lineno, line in enumerate(text.splitlines(), 1)
            if HANDOFF_MARKER_FILE in line and HANDOFF_ROOT_VAR not in line
        ]
        assert not bad, (
            "`.cnb.yml` 提到接力标记时未点明落点变量:\n  " + "\n  ".join(bad) +
            f"\n落点只有一处：{MARKER_PATH_IN_PERSONA}。"
        )


class TestGateScriptIsExecutedByTheBuild:
    """B. 落点可达性必须由真实构建自证，不能只在仓库里躺着。"""

    def test_gate_script_exists_and_is_a_python_program(self):
        assert GATE_SCRIPT.exists(), (
            "scripts/ci/npc_turn_handoff_gate.py 丢失 —— 接力判据的可达性无人自证"
        )
        ast.parse(io.open(GATE_SCRIPT, encoding="utf-8").read())

    def test_npc_pipeline_runs_the_gate(self, cnb_doc):
        """每条 NPC 流水线都要跑门禁：门禁不跑，A 条判据在 CI 上就是空转。"""
        found = []

        def walk(node, job=None):
            """产出 (所在 Job, Stage)；job 为空时用当前 Stage 充当占位。

            复用式递归：`.cnb.yml` 里同一个 Job 下并列着多个 stage，
            「这个 Job 有没有跑门禁」要看**同级**的兄弟 stage，而不是 stage 自己。
            """
            if isinstance(node, list):
                for item in node:
                    walk(item, job)
                return
            if isinstance(node, dict):
                if node.get("type") == "npc:go":
                    found.append((job if job is not None else node, node))
                for value in node.values():
                    walk(value, job if job is not None else node)

        for key in ("issue.comment@npc", "pull_request.comment@npc"):
            walk((cnb_doc.get("$") or {}).get(key))
        assert found, "未在 .cnb.yml 找到 npc:go 流水线 —— 判据空转"
        missing = [
            job for job, _stage in found
            if not any(
                "npc_turn_handoff_gate.py" in str(stage.get("script", ""))
                for stage in (job.get("stages") or [])
                if isinstance(stage, dict)
            )
        ]
        assert not missing, (
            f"{len(missing)} 条 npc:go 流水线未执行 scripts/ci/npc_turn_handoff_gate.py\n"
            "该步在真实构建里断言 `$CNB_BUILD_WORKSPACE/.npc-turn-handoff` 可写可读，"
            "并反向自证 $PWD 是否等于 $CNB_BUILD_WORKSPACE——"
            "这是接手时唯一能回答「标记到底写在哪」的读数。"
        )

    def test_gate_is_registered_in_the_import_sweep_or_directly_runnable(self):
        """门禁必须能独立跑起来（不依赖仓库内其它模块的导入副作用）。"""
        r = subprocess.run(
            [sys.executable, str(GATE_SCRIPT), "--json"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
            env={"PATH": "/usr/bin:/bin", "CNB_BUILD_WORKSPACE": str(PROJECT_ROOT)},
            timeout=60,
        )
        assert r.returncode == 0, (
            f"门禁在 CNB_BUILD_WORKSPACE 可写时仍判红: rc={r.returncode}\n"
            f"stdout={r.stdout}\nstderr={r.stderr}"
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = io.open(PROTECTED, encoding="utf-8").read()
        rel = "tests/unit/ci/test_npc_turn_handoff_execution.py"
        assert rel in listed, (
            f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
        )
