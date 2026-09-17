# -*- coding: utf-8 -*-
"""CI 双远端门禁对齐守卫（.cnb.yml vs .github/workflows/ci.yml）。

背景：cnb 侧 CI 曾长期是样例空壳（只 echo），前端门禁只在 GitHub 生效；
2026-09-17 补齐 .cnb.yml 后，两份配置存在"各自演进、静默漂移"的风险——
一侧加门禁另一侧不知道，放行标准悄然分叉。

本守卫锁定四件事：

1. **覆盖集**：GitHub 每个 job 必须在 cnb 有对应流水线（unit-tests 的
   matrix 两格对应 py311/py312 两条流水线）；反向不得有多余流水线；
2. **命令同源**：每对 job/pipeline 的核心门禁命令逐字一致（语义漂移
   最常见形态就是命令被"顺手改一下"）；
3. **放行标准**：非阻塞语义对齐（GitHub continue-on-error ↔ cnb allowFailure）；
4. **防再生**：cnb 不得退回样例空壳（echo 流水线 = 无门禁）。

合法的映射变更流程：同时改两份配置 + 同步更新本文件的 EXPECTED 映射表，
提交说明写明差异原因。
"""
import io
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CNB = PROJECT_ROOT / ".cnb.yml"
GHW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"

# job 名（GitHub）→ 流水线名列表（cnb）；unit-tests matrix 两格拆两条
EXPECTED_MAP = {
    "static-gate": ["static-gate"],
    "lint": ["lint"],
    "import-and-regression": ["import-and-regression"],
    "unit-tests": ["unit-tests-py311", "unit-tests-py312"],
    "e2e": ["e2e-backend-boot"],
    "frontend": ["frontend"],
    "dependency-audit": ["dependency-audit"],
}

# 非阻塞（允许失败）的 job：两侧行为必须一致
EXPECTED_NON_BLOCKING = {"dependency-audit"}

# 每对 job/pipeline 的核心门禁命令（"存在于该侧全部脚本中"断言）。
# 命令改动若属两例试图不同步，这里会红。
EXPECTED_CORE_COMMANDS = {
    "static-gate": ["python scripts/ci_static_gate.py --skip-import"],
    "lint": ["python -m ruff check neurova tests --no-cache"],
    "import-and-regression": [
        "python scripts/ci_static_gate.py",
        "python -m pytest tests/unit/test_audit_regressions.py -q",
    ],
    "unit-tests": [
        "scripts/ci/protected_tests.txt",
        "--cov-fail-under=60",
        "requirements-ci.lock",
    ],
    "e2e": ["python -m pytest tests/e2e/test_backend_boot.py -q --timeout 240"],
    "frontend": ["npx vue-tsc --noEmit", "npx vitest run"],
    "dependency-audit": ["python -m pip_audit -r requirements-ci.lock"],
}


@pytest.fixture(scope="module")
def cnb_pipelines():
    assert CNB.exists(), ".cnb.yml 丢失——cnb 门禁退化为无"
    data = yaml.safe_load(io.open(CNB, encoding="utf-8").read())
    main = data.get("main") or {}
    push = main.get("push")
    assert isinstance(push, list), ".cnb.yml main.push 不是流水线数组（可能退回样例空壳）"
    by_name = {}
    for p in push:
        if isinstance(p, dict) and p.get("name"):
            by_name[p["name"]] = p
    # 防再生：echo 空壳必须被抓住
    assert by_name, ".cnb.yml 无具名流水线——cnb 门禁退化为样例空壳"
    return by_name


@pytest.fixture(scope="module")
def ghw_jobs():
    assert GHW.exists(), ".github/workflows/ci.yml 丢失——GitHub 门禁退化为无"
    data = yaml.safe_load(io.open(GHW, encoding="utf-8").read())
    jobs = (data.get("jobs") or {})
    assert jobs, "ci.yml 无 job 定义"
    return jobs


def _pipeline_scripts(pipe: dict) -> str:
    out = []
    for stage in pipe.get("stages") or []:
        if isinstance(stage, dict) and stage.get("script"):
            out.append(str(stage["script"]))
    return "\n".join(out)


def _job_scripts(job: dict) -> str:
    out = []
    for step in job.get("steps") or []:
        if isinstance(step, dict) and step.get("run"):
            out.append(str(step["run"]))
    return "\n".join(out)



def _pipeline_array_for_pr(data):
    """取 PR 事件流水线：优先 main.pull_request，其次 main.pull_request@<分支> 形态。"""
    main = data.get("main") or {}
    if isinstance(main, dict):
        if isinstance(main.get("pull_request"), list):
            return main["pull_request"]
        for key, value in main.items():
            if isinstance(key, str) and key.startswith("pull_request") and isinstance(value, list):
                return value
    return None


class TestCoverage:
    def test_every_github_job_has_cnb_counterpart(self, cnb_pipelines, ghw_jobs):
        missing = []
        for job_name in ghw_jobs:
            expected = EXPECTED_MAP.get(job_name)
            if expected is None:
                continue  # 新 job 未登记映射 → 由 test_mapping_registry_is_complete 红
            for pipe_name in expected:
                if pipe_name not in cnb_pipelines:
                    missing.append(f"ci.yml job '{job_name}' 缺 cnb 流水线 '{pipe_name}'")
        assert not missing, (
            "GitHub 门禁在 cnb 侧缺失（放行标准分叉）:\n  " + "\n  ".join(missing) +
            "\n合法流程：补齐 .cnb.yml 并同步 EXPECTED_MAP。"
        )

    def test_no_extra_cnb_pipelines(self, cnb_pipelines, ghw_jobs):
        """cnb 侧不得有映射表之外的流水线（防一侧私自加门禁/残留死流水线）。"""
        known = {name for names in EXPECTED_MAP.values() for name in names}
        extra = sorted(set(cnb_pipelines) - known)
        assert not extra, (
            f"cnb 存在未登记映射的流水线: {extra}。\n"
            "同步 EXPECTED_MAP 并确认 GitHub 侧有等价 job（单一放行标准）。"
        )

    def test_mapping_registry_is_complete(self, ghw_jobs):
        """GitHub 新增 job 必须登记映射（否则上一条测不到它）。"""
        unregistered = sorted(set(ghw_jobs) - set(EXPECTED_MAP))
        assert not unregistered, (
            f"ci.yml 新增 job 未登记 EXPECTED_MAP: {unregistered}——"
            "补登记并补 cnb 流水线，否则对齐守卫对它失效。"
        )


class TestCommandParity:
    @pytest.mark.parametrize("job_name", sorted(EXPECTED_MAP))
    def test_core_commands_on_both_sides(self, cnb_pipelines, ghw_jobs, job_name):
        pipe_names = EXPECTED_MAP[job_name]
        ghw_scripts = _job_scripts(ghw_jobs[job_name])
        cnb_scripts = "\n".join(
            _pipeline_scripts(cnb_pipelines[n]) for n in pipe_names if n in cnb_pipelines
        )
        for cmd in EXPECTED_CORE_COMMANDS[job_name]:
            assert cmd in ghw_scripts, f"ci.yml job '{job_name}' 缺核心命令: {cmd}"
            assert cmd in cnb_scripts, (
                f".cnb.yml 流水线 {pipe_names} 缺核心命令: {cmd}\n"
                f"ci.yml 对应 job 有而 cnb 无——命令被单侧改动，放行标准漂移。"
            )


class TestNonBlockingParity:
    @pytest.mark.parametrize("job_name", sorted(EXPECTED_NON_BLOCKING))
    def test_allow_failure_aligned(self, cnb_pipelines, ghw_jobs, job_name):
        pipe_names = EXPECTED_MAP[job_name]
        ghw_job = ghw_jobs[job_name]
        ghw_ok = bool(ghw_job.get("continue-on-error"))
        for n in pipe_names:
            pipe = cnb_pipelines.get(n)
            assert pipe is not None, f"cnb 流水线 {n} 缺失"
            cnb_ok = bool(pipe.get("allowFailure"))
            assert cnb_ok == ghw_ok, (
                f"非阻塞语义不一致: ci.yml '{job_name}' continue-on-error={ghw_ok}, "
                f"cnb '{n}' allowFailure={cnb_ok}"
            )

    @pytest.mark.parametrize("job_name", sorted(set(EXPECTED_MAP) - EXPECTED_NON_BLOCKING))
    def test_blocking_jobs_stay_blocking(self, cnb_pipelines, ghw_jobs, job_name):
        """阻塞门禁不得被单侧悄悄放宽为非阻塞（最危险的漂移形态）。"""
        for n in EXPECTED_MAP[job_name]:
            pipe = cnb_pipelines.get(n) or {}
            assert not pipe.get("allowFailure"), (
                f"cnb 流水线 '{n}'（对应阻塞门禁 '{job_name}'）被设为 allowFailure——"
                "放行标准被单侧放宽"
            )
            assert not ghw_jobs[job_name].get("continue-on-error"), (
                f"ci.yml job '{job_name}' 被设为 continue-on-error——"
                "GitHub 侧放行标准被放宽"
            )


# e2e 冒烟装依赖为 "requirements.txt --no-deps + 显式点名" 两段式：
# --no-deps 不解析依赖树，conftest/被测 import 面用到的第三方包全靠显式点名带入。
# 历史上 bcrypt 只经 requirements.txt 的 passlib[bcrypt] extra 隐式带入 → 点名行漏写它，
# cnb/GitHub 双侧 e2e 同时 ModuleNotFoundError 挂掉（本守卫即为此立的常驻护栏）。
# 注意：这些包不得进 scripts/ci_static_gate.py 的 KNOWN_OPTIONAL_DEPS——
# 该表只收"缺席可优雅降级"项，它们缺席即 import 崩。
E2E_REQUIRED_PACKAGES = (
    "fastapi", "uvicorn", "httpx", "pydantic", "pydantic-settings", "pytest",
    "pytest-timeout",  # `--timeout 240` 需要，缺席是 usage error 而非 import 失败
    "bcrypt",  # neurova.auth.password_hasher 裸 import（conftest 必经）
    "passlib",  # 同上，声明侧算法来源
    "python-dotenv",  # 配置加载
    "aiosqlite",  # sqlite 依赖
    "prometheus_client",  # /metrics 暴露面
)


class TestAntiRegression:
    def test_cnb_not_echo_shell(self, cnb_pipelines):
        """防再生：任何流水线的 script 都不得只是 echo/占位（历史空壳形态）。"""
        shells = [
            name for name, pipe in cnb_pipelines.items()
            if _pipeline_scripts(pipe).strip() == ""
            or all(
                line.strip().startswith("echo")
                for line in _pipeline_scripts(pipe).splitlines()
                if line.strip()
            )
        ]
        assert not shells, f"cnb 流水线退化为样例空壳: {shells}"

    def test_push_and_pr_share_same_pipeline_definition(self, cnb_pipelines):
        """push 与 pull_request 必须共用同一份流水线（锚点别名，单一事实来源）。"""
        data = yaml.safe_load(io.open(CNB, encoding="utf-8").read())
        main = data["main"]
        pr = main.get("pull_request")
        # 常用形态是 YAML 锚点别名 `pull_request: *pipelines`（同一对象）。
        # 若写成展开副本，也允许——但逐条流水线必须与 push 侧深比较相等，
        # 否则 PR 门禁与 push 门禁分叉（历史上就是靠这一条抓到的）。
        if pr is None:
            pr = _pipeline_array_for_pr(data)
        assert pr == main["push"], (
            "main.push 与 main.pull_request 定义不一致——PR 门禁与 push 门禁分叉"
        )

    def test_referenced_files_exist(self):
        """两份配置引用的门禁构件必须真实存在（缺一个 = 该门禁上线即红）。"""
        for f in (
            "requirements-ci.txt", "requirements-ci.lock",
            "scripts/ci_static_gate.py", "scripts/ci/protected_tests.txt",
            "tests/e2e/test_backend_boot.py", "tests/unit/test_audit_regressions.py",
            "NeurUI/package-lock.json",
        ):
            assert (PROJECT_ROOT / f).exists(), f"CI 配置引用的门禁构件缺失: {f}"

    @pytest.mark.parametrize("side", ["cnb", "github"])
    def test_e2e_smoke_deps_are_explicitly_pinned(self, side, cnb_pipelines, ghw_jobs):
        """e2e 冒烟的显式点名集合必须覆盖 import 面（--no-deps 不解析依赖树）。

        `requirements.txt --no-deps` + 显式点名是刻意的薄环境做法，代价是
        点名行即唯一依赖来源：漏一个裸 import 包，双侧 e2e 一起 import 崩。
        """
        if side == "cnb":
            scripts = _pipeline_scripts(cnb_pipelines["e2e-backend-boot"])
        else:
            scripts = _job_scripts(ghw_jobs["e2e"])
        # 折行续行先归一，避免点名集合换行即假红
        flat = scripts.replace("\\\n", " ")
        for pkg in E2E_REQUIRED_PACKAGES:
            assert pkg in flat, (
                f"{side} 侧 e2e 显式点名缺包: {pkg}\n"
                "--no-deps 下该包不会被依赖树带入，冒烟 import 面必崩。\n"
                "改点名集合请同步 E2E_REQUIRED_PACKAGES 并说明 import 面变化。"
            )

    @pytest.mark.parametrize("side", ["cnb", "github"])
    def test_e2e_smoke_keeps_no_deps_and_test_path(self, side, cnb_pipelines, ghw_jobs):
        """e2e 冒烟的两段式安装语义不得被单侧改胖（全量装会让冒烟退化为慢门禁）。"""
        if side == "cnb":
            scripts = _pipeline_scripts(cnb_pipelines["e2e-backend-boot"])
        else:
            scripts = _job_scripts(ghw_jobs["e2e"])
        flat = scripts.replace("\\\n", " ")
        assert "requirements.txt --no-deps" in flat, (
            f"{side} 侧 e2e 的 `requirements.txt --no-deps` 丢失——"
            "冒烟会退化为全量依赖安装（慢且与 GitHub 侧语义分叉）"
        )
        assert "tests/e2e/test_backend_boot.py" in flat, (
            f"{side} 侧 e2e 冒烟测试路径丢失"
        )
