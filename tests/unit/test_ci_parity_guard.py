# -*- coding: utf-8 -*-
"""CI 双远端门禁对齐守卫（.cnb.yml vs .github/workflows/ci.yml）。

背景：cnb 侧 CI 曾长期是样例空壳（只 echo），前端门禁只在 GitHub 生效；
2026-09-17 补齐 .cnb.yml 后，两份配置存在"各自演进、静默漂移"的风险——
一侧加门禁另一侧不知道，放行标准悄然分叉。

本守卫锁定四件事：

1. **覆盖集**：GitHub 每个 job 必须在 cnb 有对应流水线（一对一；受保护子集
   自 Issue #301 起只跑一腿，见 `tests/unit/ci/test_unit_tests_single_leg.py`）；
   反向不得有多余流水线；
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

# job 名（GitHub）→ 流水线名列表（cnb）；现为一对一
# perf-gate（Issue #55 新增）：两侧同跑 scripts/ci/perf_gate.py，阻断语义一致
EXPECTED_MAP = {
    # static-gate 与 lint 是同一条流水线（Issue #223 第 2 条）：pyflakes 与 ruff
    # 都在读同一片全仓 AST，拆两条只是多一次容器启动 + 多一遍全仓遍历。
    # 合并只改「读几遍」，两条命令逐字不动（见下 EXPECTED_CORE_COMMANDS）。
    "static-gate": ["static-gate"],
    # deploy-config（Issue #61 新增）：部署配置一致性（Dockerfile / compose /
    # Helm / requirements 跨文件不变量），两侧同跑同一脚本、同为阻断。
    "deploy-config": ["deploy-config"],
    "import-and-regression": ["import-and-regression"],
    # unit-tests（Issue #301）：受保护子集只跑一腿，且那一腿是生产解释器
    # （3.12）。收敛依据与判据见 tests/unit/ci/test_unit_tests_single_leg.py：
    # 101 次 PR 构建里两腿状态完全一致（单边红 0 次）。
    "unit-tests": ["unit-tests"],
    "e2e": ["e2e-backend-boot"],
    "frontend": ["frontend"],
    "perf-gate": ["perf-gate"],
    "dependency-audit": ["dependency-audit"],
    # 经验质量基准（工单 009 新增）：真实语料 A/B 读数 + 低质探针自证，双侧同命令。
    "experience-quality": ["experience-quality"],
}

# 非阻塞（允许失败）的 job：两侧行为必须一致。
# 2026-09-18 起 dependency-audit 转阻塞（Issue #56）：pip-audit 曾 continue-on-error，
# 扫出漏洞不拦合并 = 门禁形同虚设。现双侧一致阻塞，本集合为空是刻意契约，
# 由 test_no_non_blocking_jobs 明文锁定（防被重新放宽而无人察觉）。
EXPECTED_NON_BLOCKING = set()

# 每对 job/pipeline 的核心门禁命令（"存在于该侧全部脚本中"断言）。
# 命令改动若属两例试图不同步，这里会红。
EXPECTED_CORE_COMMANDS = {
    "static-gate": [
        "python scripts/ci_static_gate.py --skip-import",
        "python -m ruff check neurova tests --no-cache",
    ],
    "deploy-config": ["python scripts/ci/deploy_config_consistency_check.py"],
    "import-and-regression": [
        "python scripts/ci_static_gate.py",
        "python -m pytest tests/unit/test_audit_regressions.py -q",
        # 装的是锁不是声明（Issue #223 第 3 条）：无锁 pip 解析是这三种装法里
        # 最慢的一种，三条 job 装同一份精简依赖时尤其明显。
        "python -m pip install -r requirements-ci.lock",
    ],
    "unit-tests": [
        "scripts/ci/protected_tests.txt",
        "--cov-fail-under=60",
        "requirements-ci.lock",
    ],
    "e2e": ["python -m pytest tests/e2e/test_backend_boot.py -q --timeout 240"],
    "frontend": ["npm audit --audit-level=high", "npx vue-tsc --noEmit", "npx vitest run"],
    "perf-gate": [
        "python scripts/ci/perf_gate.py",
        "python -m pip install -r requirements-ci.lock",
    ],
    "dependency-audit": [
        "python -m pip_audit -r requirements-ci.lock",
        # 生产全量依赖锁（requirements-full.lock）：CI 精简锁覆盖不到
        # curl_cffi/onnxruntime/transformers/playwright/paramiko 等运行时包
        "python -m pip_audit -r requirements-full.lock",
        # 非 pip 依赖树（Issue #56 残留边界）：Tauri Cargo.lock（Rust crates）
        # + tools/npx-runtime 锁（运行时 `npx -y` 现拉的包）。pip-audit 与
        # npm audit 都看不到它们，此前完全无人审计。
        #
        # 预取离线库那一步**不进本表**：它刻意带 `|| true`（允许失败），
        # 而本表锁的是「阻塞门禁的核心命令」。两侧都已显式登记预取步骤，
        # 命令逐字一致由 `test_offline_prefetch_is_declared_on_both_sides` 守。
        #
        # 门禁本体**不带** `--require-offline`：预取是 best-effort（`|| true`），
        # 门禁就不能要求「预取必须成功」——否则预取一失败就是阻塞红灯，且与
        # 「真有未允许漏洞」在合并流程里同形。缓存不齐时门禁回退直连并点名
        # 缺哪一份，红的成因可读（判据收口在 resolveVerdictChannel 一处）。
        "python scripts/ci/osv_audit.py",
    ],
    # 经验质量基准（工单 009）：读数取自 EKB.quality_snapshot，语料冻结在仓内，
    # 每次运行先自证低质探针会被判红（详见 scripts/ci/experience_quality_gate.py）。
    "experience-quality": [
        "python scripts/ci/experience_quality_gate.py",
        "python -m pip install -r requirements-ci.lock",
    ],

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


class TestOfflineDatabasePathIsDeclaredOnBothSides:
    """离线库预取必须两侧都在，且命令逐字一致（否则一侧仍依赖实时可达性）。"""

    _PREFETCH = "python scripts/ci/osv_audit.py --prefetch-offline-databases"
    _GATE = "python scripts/ci/osv_audit.py"

    def test_offline_prefetch_is_declared_on_both_sides(self, cnb_pipelines, ghw_jobs):
        job = "dependency-audit"
        ghw = _job_scripts(ghw_jobs[job])
        cnb = "\n".join(
            _pipeline_scripts(cnb_pipelines[n])
            for n in EXPECTED_MAP[job]
            if n in cnb_pipelines
        )
        # `|| true` 是这一步的语义（允许失败），逐字比对时把它钉住
        expected = self._PREFETCH + " || true"
        assert expected in ghw, f"ci.yml job '{job}' 缺离线库预取步骤"
        assert expected in cnb, (
            f".cnb.yml 流水线 {EXPECTED_MAP[job]} 缺离线库预取步骤——"
            "cnb 侧仍会现查 api.osv.dev，网络不可达时门禁红得无从归因"
        )

    def test_prefetch_is_best_effort_and_gate_does_not_require_it(self, cnb_pipelines):
        """两句话必须同口径：预取允许失败（`|| true`），门禁就不得要求它成功。

        修复前这里是反的——预取 `|| true`、门禁 `--require-offline`。于是
        「允许失败的前置步骤」与「必须成功的门禁」互相抵消：预取一失败就是阻塞
        红灯，而这与「真有未允许漏洞」在合并流程里同形，读日志的人只能重跑
        （2026-09-22 PR #121 的红就是这么来的，本单要消灭的正是这个形态）。

        正确口径：预取 best-effort，门禁缓存不齐时**回退直连并点名**，
        红只留给「真有未允许漏洞」（判据收口在 resolveVerdictChannel 一处）。
        """
        for name in EXPECTED_MAP["dependency-audit"]:
            pipe = cnb_pipelines.get(name)
            if pipe is None:
                continue
            scripts = _pipeline_scripts(pipe)
            assert self._PREFETCH + " || true" in scripts, (
                f"流水线 {name} 的预取步骤没带 `|| true`——预取失败会阻塞合并，"
                "而它只是「网络能不能拿到最新库」这一件事"
            )
            assert self._GATE + " --require-offline" not in scripts, (
                f"流水线 {name} 门禁要求了离线，而它上面那步预取被允许失败——"
                "预取一失败就是阻塞红灯，与「真有未允许漏洞」同形"
            )
            assert self._GATE in scripts, (
                f"流水线 {name} 缺门禁本体命令"
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

    def test_no_non_blocking_jobs(self):
        """依赖审计不得退回非阻塞（Issue #56 收口：扫出漏洞必须拦合并）。

        放宽此契约须同时改 .cnb.yml / ci.yml / 本文件，并说明为何放行。
        """
        assert EXPECTED_NON_BLOCKING == set(), (
            "存在非阻塞门禁: "
            f"{sorted(EXPECTED_NON_BLOCKING)}——依赖审计类门禁必须阻塞，"
            "否则扫出漏洞也拦不住合并（Issue #56 的原始缺口）。"
        )

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
            "requirements-ci.txt", "requirements-ci.lock", "requirements-full.lock",
            # Issue #56 残留边界：非 pip 依赖树审计的输入与允许清单
            "NeurUI/src-tauri/Cargo.lock", "tools/npx-runtime/package-lock.json",
            "scripts/ci/osv_audit.py", "scripts/ci/osv-allowlist.toml",
            "scripts/ci_static_gate.py", "scripts/ci/protected_tests.txt",
            "tests/e2e/test_backend_boot.py", "tests/unit/test_audit_regressions.py",
            "NeurUI/package-lock.json", "scripts/ci/perf_gate.py",
            # 工单 009：经验质量基准的脚本与两份语料（真实冻结语料 + 低质探针）。
            # 少一份 = 门禁上线即红（探针缺失时无法自证不空转）。
            "scripts/ci/experience_quality_gate.py",
            "tests/fixtures/experience_quality_corpus.json",
            "tests/fixtures/experience_quality_corpus_low_signal.json",
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
