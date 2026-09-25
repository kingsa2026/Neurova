# -*- coding: utf-8 -*-
"""CI 流水线耗时收口的常驻判据（Issue #223）。

## 为什么要有这份守卫

`.cnb.yml` 的 11 条流水线是"各自独立的门禁"，其**耗时构成**此前没有任何机器判据：

- 同一份依赖被装 8 次、同一片全仓代码被扫 3 遍——这些只有人去看构建日志才发现；
- 于是"把耗时收口"这件事改完就没有人守：下一个人回填一处 `--upgrade pip`、
  把合并过的两条流水线拆开、把离线库卷删掉，全部都不会有任何红，
  而用户看到的现象（"11 个检查要跑很久"）会原样回来。

本守卫把 Issue #223 的四条收口结论钉成可证伪的读数，
口径是**结构**（哪一步做什么）而不是**秒数**（秒数会随机器漂移，属
`tests/unit/test_ci_wallclock_assertion_ledger.py` 管的另一件事）：

| 结论 | 判据 |
|------|------|
| 1. OSV 离线库跨构建复用 | `dependency-audit` 声明 `/root/.cache/osv-scalibr` 卷 |
| 2. 静态门禁合并成一条 | GitHub 侧 `static-gate` job 同时跑 pyflakes 与 ruff |
| 3. 重复装的依赖改走同一份锁 | 三条流水线/Job 都装 `requirements-ci.lock` |
| 4. 不自举 pip | 所有 Job 里 `pip install` 不再带 `--upgrade pip` |

## 卷判据只认"缓存根由门禁脚本自己声明"

`scripts/ci/osv_audit.py` 的 `OSV_DB_CACHE` 是离线库落点的**唯一事实源**。
挂载点的判据取它所在目录（`~/.cache/osv-scalibr` → 卷 `/root/.cache/osv-scalibr`）
在两侧配置里都被声明成卷——不写死字符串，因为写死之后改脚本即与配置脱钩
（教义第 6 条：不新造平行口径）。
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CNB = PROJECT_ROOT / ".cnb.yml"
GHW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
AUDIT_SCRIPT = PROJECT_ROOT / "scripts" / "ci" / "osv_audit.py"

#: 三条"重复装同一份依赖"的流水线 / Job：Issue #223 第 3 条把它们收口到同一份锁。
#: 键 = cnb 流水线名（GitHub 侧取 EXPECTED_MAP 的同名 job）。
LOCKED_DEP_PIPELINES = ("import-and-regression", "perf-gate", "experience-quality")

#: 不自举 pip 的判定：`pip install --upgrade pip <包>` 这类自举形态。
_PIP_SELF_UPGRADE = re.compile(r"--upgrade\s+pip(\s|$)")


def _load(path: Path) -> dict:
    return yaml.safe_load(io.open(path, encoding="utf-8").read())


def _cnb_pipelines() -> dict:
    data = _load(CNB)
    out = {}
    for pipe in data["main"]["push"]:
        if isinstance(pipe, dict) and pipe.get("name"):
            out[pipe["name"]] = pipe
    return out


def _cnb_scripts(pipe: dict) -> str:
    return "\n".join(
        str(stage.get("script", ""))
        for stage in pipe.get("stages") or []
        if isinstance(stage, dict)
    )


def _ghw_jobs() -> dict:
    return _load(GHW)["jobs"]


def _ghw_runs(job: dict) -> str:
    return "\n".join(
        str(step.get("run", ""))
        for step in job.get("steps") or []
        if isinstance(step, dict)
    )


def _osvCacheRoot() -> str:
    """门禁脚本自己声明的离线库缓存根目录名（`osv-scalibr`），不写第二份。"""
    source = io.open(AUDIT_SCRIPT, encoding="utf-8").read()
    match = re.search(r'OSV_DB_CACHE\s*=\s*Path\.home\(\)\s*/\s*"\.cache"\s*/\s*"([^"]+)"', source)
    assert match, (
        "scripts/ci/osv_audit.py 里取不到 OSV_DB_CACHE 的目录名——"
        "本守卫的卷判据与它同源，取不到即无从作答（不许改成写死字符串）"
    )
    return match.group(1)


class TestOsvOfflineCacheIsSharedAcrossBuilds:
    """结论 1：OSV 离线漏洞库必须跨构建复用（每次重下 206MB 是纯网络往返）。

    判据：缓存根（由门禁脚本的 `OSV_DB_CACHE` 给出）所在目录在**两侧**都被
    声明成容器卷。缺任一侧即红。

    可证伪路径：从 `.cnb.yml` 的 `dependency-audit` 里删掉那条卷 → 转红。
    """

    def test_cnb_declares_the_cache_volume(self):
        cache_dir = f"/root/.cache/{_osvCacheRoot()}"
        pipe = _cnb_pipelines()["dependency-audit"]
        volumes = ((pipe.get("docker") or {}).get("volumes")) or []
        assert cache_dir in volumes, (
            f".cnb.yml 的 dependency-audit 未把离线库缓存 ({cache_dir}) 声明成卷——"
            "每一次构建都要重下整份 npm 漏洞库（实测 47s+），而这与门禁结论无关"
        )

    def test_github_caches_the_same_directory(self):
        cache_dir = f"/root/.cache/{_osvCacheRoot()}"
        job = _ghw_jobs()["dependency-audit"]
        steps = [s for s in job.get("steps") or [] if isinstance(s, dict)]
        caches = [
            re.sub(r"\s+", "", str(s.get("with", {}).get("path", "")))
            for s in steps
            if str(s.get("uses", "")).startswith("actions/cache")
        ]
        assert any(
            entry in ("~/.cache/" + _osvCacheRoot(), cache_dir)
            for entry in caches
        ), (
            f"ci.yml 的 dependency-audit 未缓存 {cache_dir}——"
            "GitHub 侧每次构建同样要现下整份漏洞库"
        )

    def test_cache_volume_is_not_a_second_cache_root(self):
        """卷必须落在门禁脚本自己用的那个目录上，不是另建一份缓存。

        可证伪路径：把卷改成 `~/.cache/osv`（另一个名字）→ 转红——
        那样扫描器读的还是自己的目录，卷只是白挂。
        """
        volumes = ((_cnb_pipelines()["dependency-audit"].get("docker") or {}).get("volumes")) or []
        cache_volumes = [v for v in volumes if "osv" in str(v)]
        assert cache_volumes == [f"/root/.cache/{_osvCacheRoot()}"], (
            f"OSV 缓存卷与门禁脚本的落点不同源：{cache_volumes}"
        )


class TestStaticGateAndLintAreOneGate:
    """结论 2：语法/未定义名巡检与 lint 合并成一条（都在读同一片 AST）。

    两侧都必须合并，否则放行标准分叉：cnb 侧把 `lint` 并进 `static-gate` 后
    删掉独立 `lint` 流水线，GitHub 侧同样并进 `static-gate` job。

    可证伪路径：把任一工具挪回独立 job → 转红。
    """

    def test_cnb_static_gate_runs_both_pyflakes_and_ruff(self):
        pipe = _cnb_pipelines()["static-gate"]
        scripts = _cnb_scripts(pipe)
        assert "scripts/ci_static_gate.py --skip-import" in scripts, (
            "static-gate 丢了 pyflakes 语法/未定义名巡检"
        )
        assert "python -m ruff check neurova tests --no-cache" in scripts, (
            "static-gate 未并进 ruff——全仓 AST 又有人各扫一遍"
        )

    def test_no_separate_lint_pipeline_on_either_side(self):
        pipelines = _cnb_pipelines()
        assert "lint" not in pipelines, (
            "cnb 仍保留独立 lint 流水线——与 static-gate 读同一片 AST，"
            "多一次容器启动与全仓遍历"
        )
        assert "lint" not in _ghw_jobs(), (
            "ci.yml 仍保留独立 lint job——两侧必须同时合并，否则放行标准分叉"
        )

    def test_github_static_gate_runs_both_tools(self):
        job = _ghw_jobs()["static-gate"]
        runs = _ghw_runs(job)
        assert "scripts/ci_static_gate.py --skip-import" in runs, (
            "ci.yml 的 static-gate 丢了 pyflakes 巡检"
        )
        assert "python -m ruff check neurova tests --no-cache" in runs, (
            "ci.yml 的 static-gate 未并进 ruff"
        )


class TestRepeatedDependencyInstallsUseOneLock:
    """结论 3：装同一份精简依赖的三条流水线改走同一份锁（不再各自解析依赖树）。

    判据：三条流水线都装 `requirements-ci.lock`，且**都不再**出现无锁的
    `-r requirements-ci.txt` 安装（无锁解析是这三个 Job 里最慢的一种装法）。

    可证伪路径：任一条改回 `-r requirements-ci.txt` → 转红。
    """

    @pytest.mark.parametrize("name", LOCKED_DEP_PIPELINES)
    def test_cnb_pipeline_installs_from_the_lock(self, name):
        scripts = _cnb_scripts(_cnb_pipelines()[name])
        assert "requirements-ci.lock" in scripts, (
            f".cnb.yml 的 {name} 未用 requirements-ci.lock 装依赖——"
            "同一份依赖三条流水线各解析一遍，是重复安装里最慢的一种"
        )
        assert "-r requirements-ci.txt" not in scripts, (
            f"{name} 仍有无锁安装（requirements-ci.txt）——锁与声明各装一份"
        )

    @pytest.mark.parametrize("name", LOCKED_DEP_PIPELINES)
    def test_github_job_installs_from_the_lock(self, name):
        runs = _ghw_runs(_ghw_jobs()[name])
        assert "requirements-ci.lock" in runs, (
            f"ci.yml 的 {name} 未用 requirements-ci.lock 装依赖"
        )
        assert "-r requirements-ci.txt" not in runs, (
            f"ci.yml 的 {name} 仍有无锁安装（requirements-ci.txt）"
        )

    def test_lock_file_exists(self):
        assert (PROJECT_ROOT / "requirements-ci.lock").is_file(), "锁文件缺失，门禁上线即红"


class TestNoPipSelfUpgrade:
    """结论 4：CI 里不再自举 pip（每次构建都去 PyPI 取最新 pip，纯网络往返）。

    判据扫**全部** Job / 流水线，不只改过的那几条——同一根因的命中点一次扫清
    （教义第 5 条）。

    可证伪路径：任意一个 Job 里写回 `pip install --upgrade pip ...` → 转红。
    """

    def test_cnb_pipelines_do_not_upgrade_pip(self):
        offenders = [
            name for name, pipe in _cnb_pipelines().items()
            if _PIP_SELF_UPGRADE.search(_cnb_scripts(pipe))
        ]
        assert not offenders, (
            "以下 cnb 流水线仍在自举 pip（每次构建一次 PyPI 网络往返）: "
            f"{offenders}\n镜像自带的 pip 足够装这些包；确需新版请钉进依赖清单。"
        )

    def test_github_jobs_do_not_upgrade_pip(self):
        offenders = [
            name for name, job in _ghw_jobs().items()
            if _PIP_SELF_UPGRADE.search(_ghw_runs(job))
        ]
        assert not offenders, f"以下 GitHub job 仍在自举 pip: {offenders}"

    def test_detector_is_not_vacuous(self):
        """反向控制：检出器真的能认出自举形态（否则上面两条恒真）。"""
        assert _PIP_SELF_UPGRADE.search("python -m pip install --upgrade pip pyflakes"), (
            "检出器认不出自举形态——上面两条断言是空的"
        )
        assert _PIP_SELF_UPGRADE.search("python -m pip install --upgrade pip -r a.txt")
        assert not _PIP_SELF_UPGRADE.search("python -m pip install --upgrade pyflakes")
        assert not _PIP_SELF_UPGRADE.search("python -m pip install pip-audit")
