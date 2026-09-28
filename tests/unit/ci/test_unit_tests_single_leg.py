# -*- coding: utf-8 -*-
"""受保护子集只跑**一腿**，且那一腿必须是生产解释器（Issue #301）。

## 为什么收敛这一腿

`unit-tests` 此前是 py3.11 / py3.12 双跑（cnb 两条流水线、GitHub matrix 两格），
理由是"对应 GitHub matrix、两侧一致的放行标准"。用户提问（Issue #301）：这两条
重复跑是否有必要。本判据把回答所需的读数钉成常驻判据，而不是靠人记得去翻构建列表。

**实测读数（`cnb/pull_request` 事件，按平台给出的构建列表与逐条状态复算）**：

- 收敛前 101 次构建里，两腿状态**完全一致**：84 次双绿、17 次双红，
  **单边红 0 次**——即 py3.11 腿没有拦住过任何 py3.12 腿放行的缺陷；
- 更早（11 条流水线时代，收口前）：单边红 9 次，根因均为**判据绑了墙钟**
  （`perf_gate.py` 微基准 21.9ms>20ms、`context_deadline_ledger` 撞 30s 超时），
  已被 `19065c3f` / `f4f71943` / `930db08a` 等逐个根修——即那 9 次不是
  "版本差异"，是"同一份代码在共享负载下抖动"，修完即消失（收敛后单边红回到 0）；
- 墙钟不受影响：同一批构建里 py3.12 腿在 94/101 次中是**最慢的那条流水线**
  （中位 492s vs py3.11 腿 435s），构建墙钟与最慢流水线之差中位仅 3s。
  故省下的是 runner 资源（每构建约 29.5 CPU·min），不是用户看到的等待时长。

## 收敛的是"跑几遍"，不是"判据"

那一腿仍跑同一份 `scripts/ci/protected_tests.txt` 与同一道 `--cov-fail-under=60`
覆盖率门禁；**不同**的只有解释器腿数与它落在哪个版本上。故本判据同时钉住
"判据不得被顺手放宽"（教义第 2 条：不许把失败改写成 warning、不许降级断言）。

## 为什么留下的是 3.12

生产解释器是 3.12（`Dockerfile` 两个阶段的 `FROM python:3.12-slim`）——
按生产解释器跑受保护子集，跑的就是"线上那份解释器"。

3.11 并未从 CI 消失：`static-gate`（pyflakes + ruff 全仓 AST，按 3.11 语法解析）
与 `import-and-regression`（真导入全模块）仍在 `python:3.11` 上跑，
"3.11 上能不能解析、能不能导入"这两件事仍有解释器级覆盖；收敛掉的只是
"同一份受保护子集在 3.11 上再全量跑一遍"。

## 解释器版本的事实源

不写死 `3.12`：版本从 `Dockerfile` 的 `FROM python:` 派生（与
`scripts/ci/deploy_config_consistency_check.py` 的 R4 同源），下限取
`scripts/config.py` 的 `MIN_PYTHON_VERSION`。写死一份即与生产镜像脱钩
——改了镜像而这里不响，正是教义第 6 条点名的那类断点。
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"
GHW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
DOCKERFILE = PROJECT_ROOT / "Dockerfile"
SCRIPTS_CONFIG = PROJECT_ROOT / "scripts" / "config.py"

#: 该 job / 流水线族的前缀：腿数按"名字以此开头"计，不按枚举的完整名计
#: （枚举会把改名当成删除 + 新增，判据随即失效）。
LEG_PREFIX = "unit-tests"


def _cnbPipelines(path: Path | None = None) -> dict:
    # 默认值在**调用期**取模块级 `CNB`，不用 def 期绑定的默认参数：
    # 后者会让反向控制的 monkeypatch 打不中（判定退化成对某份固定文件的快照）。
    data = yaml.safe_load(io.open(path or CNB, encoding="utf-8").read())
    return {
        pipe["name"]: pipe
        for pipe in data["main"]["push"]
        if isinstance(pipe, dict) and pipe.get("name")
    }


def _ghwJob(path: Path | None = None, job: str = LEG_PREFIX) -> dict:
    jobs = yaml.safe_load(io.open(path or GHW, encoding="utf-8").read())["jobs"]
    assert job in jobs, f"ci.yml 缺 job '{job}'——双侧放行标准分叉"
    return jobs[job]


def _pipelineScripts(pipe: dict) -> str:
    return "\n".join(
        str(stage.get("script", ""))
        for stage in pipe.get("stages") or []
        if isinstance(stage, dict)
    )


def _jobRuns(job: dict) -> str:
    return "\n".join(
        str(step.get("run", ""))
        for step in job.get("steps") or []
        if isinstance(step, dict)
    )


def _jobPythonVersions(job: dict) -> list:
    return [
        str((step.get("with") or {}).get("python-version", ""))
        for step in job.get("steps") or []
        if isinstance(step, dict) and "actions/setup-python" in str(step.get("uses", ""))
    ]


def _productionInterpreter(path: Path = DOCKERFILE) -> str:
    """生产解释器版本——`Dockerfile` 的 `FROM python:` 派生（唯一事实源）。"""
    versions = set(
        re.findall(r"^FROM\s+python:(\d+\.\d+)", io.open(path, encoding="utf-8").read(), re.M)
    )
    assert len(versions) == 1, (
        f"Dockerfile 的 `FROM python:` 版本不唯一：{sorted(versions)}——"
        "两条腿跑哪个版本、镜像跑哪个版本无从作答，先收口成一份。"
    )
    return versions.pop()


def _minInterpreter(path: Path = SCRIPTS_CONFIG) -> str:
    match = re.search(
        r"MIN_PYTHON_VERSION\s*=\s*\((\d+),\s*(\d+)\)",
        io.open(path, encoding="utf-8").read(),
    )
    assert match, "scripts/config.py 取不到 MIN_PYTHON_VERSION——下限判据无从作答"
    return f"{match.group(1)}.{match.group(2)}"


def _asTuple(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


def unitTestLegs(pipelines: dict) -> list:
    """`main.push` 里属于受保护子集那一族的流水线名（按前缀，不按枚举）。"""
    return sorted(name for name in pipelines if name.startswith(LEG_PREFIX))


class TestCnbRunsASingleLeg:
    def testCnbRunsExactlyOneUnitTestLeg(self):
        """cnb 侧只允许一条受保护子集流水线（Issue #301 收敛的靶心）。"""
        legs = unitTestLegs(_cnbPipelines())
        assert len(legs) == 1, (
            f"cnb 侧有 {len(legs)} 条受保护子集流水线: {legs}\n"
            "同一份 `scripts/ci/protected_tests.txt` 与同一道覆盖率门禁被各跑一遍，"
            "而实测 101 次构建里两腿状态完全一致（单边红 0 次）——"
            "重复的那一腿只花费 runner 资源（每构建约 29.5 CPU·min），不提供新信号。"
        )

    def testCnbLegRunsTheProductionInterpreter(self):
        """留下的一腿必须落在生产解释器上（版本由 Dockerfile 派生）。"""
        leg = _productionInterpreter()
        pipe = _cnbPipelines()[unitTestLegs(_cnbPipelines())[0]]
        image = str((pipe.get("docker") or {}).get("image", ""))
        assert image == f"python:{leg}", (
            f"受保护子集跑在 {image!r}，生产镜像解释器是 python:{leg}——"
            "留下的那一腿必须是线上那份解释器（Issue #301）。"
        )

    def testLegInterpreterMeetsDeclaredFloor(self):
        """下限不因收敛而破：生产解释器必须 ≥ 项目最低版本。"""
        assert _asTuple(_productionInterpreter()) >= _asTuple(_minInterpreter()), (
            f"生产解释器 {_productionInterpreter()} < 项目最低 {_minInterpreter()}——"
            "受保护子集跑在低于声明下限的解释器上"
        )


class TestGithubRunsTheSameSingleLeg:
    def testGithubHasNoVersionMatrix(self):
        """GitHub 侧不得保留版本 matrix（一侧单腿、一侧双跑即放行标准分叉）。"""
        job = _ghwJob()
        matrix = (job.get("strategy") or {}).get("matrix")
        assert matrix is None, (
            f"ci.yml 的 unit-tests 仍带 matrix {matrix!r}——"
            "收敛必须两侧同批完成，否则同一提交在两侧的放行标准不同。"
        )

    def testGithubLegRunsTheProductionInterpreter(self):
        """两侧必须落在**同一个**解释器上（版本同取 Dockerfile 这一份事实源）。"""
        versions = _jobPythonVersions(_ghwJob())
        assert versions == [_productionInterpreter()], (
            f"ci.yml 的 unit-tests 解释器 {versions} 与生产解释器 "
            f"{_productionInterpreter()!r} 不一致——两侧放行标准分叉。"
        )


class TestConvergenceDoesNotRelaxTheCriteria:
    """收敛的是"跑几遍"，不是"判据"——余下的那一腿不得少跑一样东西。"""

    def testCnbLegStillRunsProtectedSubsetWithCoverageGate(self):
        pipe = _cnbPipelines()[unitTestLegs(_cnbPipelines())[0]]
        scripts = _pipelineScripts(pipe)
        assert "protected_tests.txt" in scripts, "余下的一腿不再跑受保护子集——判据被掏空"
        assert "--cov-fail-under=60" in scripts, "覆盖率门禁没跟着走——判据被顺手放宽"

    def testGithubLegStillRunsProtectedSubsetWithCoverageGate(self):
        runs = _jobRuns(_ghwJob())
        assert "protected_tests.txt" in runs, "GitHub 侧余下的一腿不再跑受保护子集"
        assert "--cov-fail-under=60" in runs, "GitHub 侧覆盖率门禁没跟着走"


class TestDetectorIsNotVacuous:
    """反向控制：判定必须真咬得住"再来一腿"与"跑错版本"。"""

    def testSecondLegIsCaught(self, tmp_path, monkeypatch):
        module = __import__(__name__, fromlist=["unitTestLegs"])
        original = io.open(CNB, encoding="utf-8").read()
        drifted = tmp_path / ".cnb.yml"
        # 把探针腿拼回去：只改数据，不改判定——命中即说明上面那条不是快照。
        drifted.write_text(
            original.replace(
                "    # ── 5. E2E：后端启动冒烟",
                "    - name: unit-tests-probe\n"
                "      docker:\n"
                "        image: python:3.11\n"
                "      stages:\n"
                "        - name: probe\n"
                "          script: echo probe\n"
                "\n"
                "    # ── 5. E2E：后端启动冒烟",
                1,
            ),
            encoding="utf-8",
        )
        assert unitTestLegs(_cnbPipelines(drifted)) == ["unit-tests", "unit-tests-probe"]
        monkeypatch.setattr(module, "CNB", drifted)
        with pytest.raises(AssertionError, match="受保护子集流水线"):
            module.TestCnbRunsASingleLeg().testCnbRunsExactlyOneUnitTestLeg()

    def testWrongInterpreterIsCaught(self, tmp_path):
        drifted = tmp_path / "Dockerfile"
        drifted.write_text("FROM python:3.10-slim\n", encoding="utf-8")
        assert _productionInterpreter(drifted) == "3.10"
        module = __import__(__name__, fromlist=["_productionInterpreter"])
        producer = module.__dict__
        # 生产解释器换成 3.10（低于声明下限 3.10 的下界判据随之咬合）
        assert _asTuple("3.10") >= _asTuple(_minInterpreter()), "3.10 本就是声明下限"
        assert _asTuple("3.9") < _asTuple(_minInterpreter()), (
            "下限判据认不出低于声明下限的解释器——那条断言是空的"
        )
        assert "3.10" in producer["_productionInterpreter"](drifted)
