# -*- coding: utf-8 -*-
"""云原生开发环境（`.ide/Dockerfile` + `.cnb.yml` 的 `vscode` 事件）契约守卫。

## 为什么需要这道门禁

仓库此前**没有任何**开发环境声明：`.ide/Dockerfile` 不存在、`.cnb.yml` 里没有
`vscode` 事件 —— 点「云原生开发」拿到的是平台默认镜像（`cnbcool/default-dev-env`），
里面既没有本仓的生产解释器，也没有前端工具链。于是本地开发环境与 CI / 生产镜像
**三份口径各写各的**，而没有任何一条自动化检查把它们对齐。

这不是整洁性问题：开发环境跑 Python 3.11 而生产镜像跑 3.12（`Dockerfile` 的
`FROM`），前端跑 Node 18 而 CI 跑 Node 20 —— 同一个 commit 在两处行为分叉，
且故障只在某一侧可见。本仓已有同型事故的记账（`docker-compose.yml` 里前端
从不安装 `code-server` 的 `node:18-alpine`，注释自陈"本地 dev 与 CI 跑不同
大版本"）。

## 判据只读活事实源，不新造第二份

全部取值都从**已有的单一事实源**派生，本文件不手工抄任何版本号：

- 解释器：`Dockerfile` 的 `FROM python:`（与 `deploy_config_consistency_check.py`
  的 R4 同源），下限取 `scripts/config.py` 的 `MIN_PYTHON_VERSION`；
- Node 大版本：`.github/workflows/ci.yml` 的 `node-version`（与 compose 前端镜像
  同源，R4 已钉）；
- 依赖声明：`requirements-ci.lock` / `NeurUI/package.json` —— 开发环境**不得**
  携带第三份依赖清单（教义第 6 条）。

## 反向控制

"是否安装 code-server"决定平台走单容器还是双容器模式（官方《单/双容器模式》）：
容器里没有 `code-server` 时平台另起一个 `code-server` 容器，WebIDE 连的是那一侧，
开发容器反而要多一层跨容器终端。本文件因此把"装了 code-server ⇒ 单容器"钉住，
而不只是断言"字面上出现了某个包名"。
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
IDE_DOCKERFILE = PROJECT_ROOT / ".ide" / "Dockerfile"
CNB = PROJECT_ROOT / ".cnb.yml"
GHW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
PROD_DOCKERFILE = PROJECT_ROOT / "Dockerfile"
SCRIPTS_CONFIG = PROJECT_ROOT / "scripts" / "config.py"
COMPOSE = PROJECT_ROOT / "docker-compose.yml"
REQUIREMENTS_CI_LOCK = PROJECT_ROOT / "requirements-ci.lock"
NEURUI_PACKAGE = PROJECT_ROOT / "NeurUI" / "package.json"

#: `vscode` 事件下 Job 的 `services` 必须声明的两个服务：WebIDE 与 docker CLI。
EXPECTED_SERVICES = ("vscode", "docker")


def _read(path: Path) -> str:
    assert path.is_file(), f"{path.relative_to(PROJECT_ROOT)} 不存在——开发环境契约无从作答"
    return io.open(path, encoding="utf-8").read()


def _productionInterpreter(path: Path | None = None) -> str:
    """生产解释器版本——`Dockerfile` 的 `FROM python:`（唯一事实源）。"""
    versions = set(
        re.findall(r"^FROM\s+python:(\d+\.\d+)", _read(path or PROD_DOCKERFILE), re.M)
    )
    assert len(versions) == 1, f"Dockerfile 的 FROM python: 版本不唯一：{sorted(versions)}"
    return versions.pop()


def _minInterpreter(path: Path | None = None) -> str:
    match = re.search(
        r"MIN_PYTHON_VERSION\s*=\s*\((\d+),\s*(\d+)\)",
        _read(path or SCRIPTS_CONFIG),
    )
    assert match, "scripts/config.py 取不到 MIN_PYTHON_VERSION——下限判据无从作答"
    return f"{match.group(1)}.{match.group(2)}"


def _ideInterpreter(path: Path | None = None) -> str:
    """开发环境基础镜像的解释器版本——`.ide/Dockerfile` 的 `FROM python:`。"""
    versions = set(
        re.findall(r"^FROM\s+python:(\d+\.\d+)", _read(path or IDE_DOCKERFILE), re.M)
    )
    assert len(versions) == 1, (
        f".ide/Dockerfile 的 FROM python: 版本不唯一：{sorted(versions)}——"
        "开发环境跑哪个解释器无从作答。"
    )
    return versions.pop()


def _ciNodeMajor(path: Path | None = None) -> str:
    match = re.search(r'node-version:\s*"(\d+)"', _read(path or GHW))
    assert match, "ci.yml 取不到 node-version——Node 大版本判据无从作答"
    return match.group(1)


def _ideNodeMajor(path: Path | None = None) -> str:
    """开发环境里 Node 的大版本——`.ide/Dockerfile` 的安装源派生（单一事实源）。

    本文件的 Node **不是**一个独立的 `FROM node:` 阶段：开发环境是一个容器
    （`FROM python:3.12-slim`），Node 装在它内部。故大版本的事实源是安装指令
    本身（NodeSource 的 `setup_<major>.x`）。不读 `apt install nodejs` 那种写法
    —— 它在 Debian 系给出旧大版本，与 CI 的 node-version 分叉，正是本道门禁
    要拦的那种漂移。
    """
    versions = set(
        re.findall(r"deb\.nodesource\.com/setup_(\d+)\.x", _read(path or IDE_DOCKERFILE))
    )
    assert len(versions) == 1, (
        f".ide/Dockerfile 里 Node 大版本的安装源不唯一：{sorted(versions)}（应为 1）——"
        "前端工具链跑哪个大版本无从作答。"
    )
    return versions.pop()


def _vscodePipelines(path: Path | None = None) -> list:
    """`.cnb.yml` 的 `$` 兜底块下声明的 `vscode` 事件流水线。

    开发环境必须挂在 `$`（兜底匹配所有分支）上：挂在 `main` 下意味着只有在
    main 分支页面点按钮才有反应，而"要在别的分支上开发"正是它的用途。
    """
    data = yaml.safe_load(_read(path or CNB))
    fallback = data.get("$") or {}
    pipelines = fallback.get("vscode")
    assert isinstance(pipelines, list) and pipelines, (
        ".cnb.yml 的 `$` 下没有 `vscode` 事件流水线——点「云原生开发」会落到"
        "平台默认镜像，本仓的生产解释器与前端工具链都不在其中。"
    )
    return pipelines


def _vscodeJob(path: Path | None = None) -> dict:
    return _vscodePipelines(path)[0]


def _stageScripts(job: dict) -> str:
    return "\n".join(
        str(stage.get("script", ""))
        for stage in job.get("stages") or []
        if isinstance(stage, dict)
    )


def _aptPackages(dockerfile_text: str) -> set:
    """`apt-get install` 调用面里真被点名的包名集合。

    只认 `apt-get install ...` 到行尾反斜杠续行结束那一段，跳过注释行；
    这样"注释里提到某包但没装"不会替安装发合格证。
    """
    packages: set = set()
    lines = dockerfile_text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.search(r"apt-get\s+install\b", line) and not line.lstrip().startswith("#"):
            chunk = [line.split("install", 1)[1]]
            while chunk[-1].rstrip().endswith("\\") and index + 1 < len(lines):
                index += 1
                chunk.append(lines[index])
            for token in re.split(r"[\s\\]+", " ".join(chunk)):
                token = token.strip()
                if token and not token.startswith("-") and not token.startswith("$"):
                    packages.add(token)
        index += 1
    return packages


def _allStageScripts(job: dict) -> str:
    scripts = [_stageScripts(job)]
    for stage in job.get("endStages") or []:
        if isinstance(stage, dict):
            scripts.append(str(stage.get("script", "")))
    return "\n".join(scripts)


def _isTracked(relative: str) -> bool:
    """文件是否处于 git 跟踪/可添加态——"能入库"是"平台取得声明"的前提。

    `.gitignore` 的 `.*/` 规则会连 `.ide/` 一起排除；声明了开发环境却入不了库，
    别人点按钮拿到的仍是平台默认镜像，而本地一切正常 —— 属静默失败。
    """
    import subprocess

    result = subprocess.run(
        ["git", "check-ignore", "-q", relative],
        cwd=PROJECT_ROOT,
        capture_output=True,
    )
    return result.returncode != 0


class TestDevEnvironmentDeclarationIsShippable:
    def testIdeDockerfileIsNotGitignored(self):
        """.ide/Dockerfile 必须能入库：平台从 git 取它构建开发环境。

        `.gitignore` 的 `.*/` 会把隐藏目录整目录排除（`.cnb/` 因此有一条显式
        反向规则）。开发环境定义若被排除，本地什么都对、别人点按钮拿到平台
        默认镜像——静默失败的一种。
        """
        assert _isTracked(".ide/Dockerfile"), (
            ".ide/Dockerfile 被 git 忽略——平台从 git 取本文件构建开发环境，"
            "入不了库等于声明不存在（`.gitignore` 的 `.*/` 需按 `.cnb/` 的方式放行）"
        )


class TestIdeImageRidesTheRepoInterpreter:
    def testDevelopmentImageRunsTheProductionInterpreter(self):
        """.ide/Dockerfile 的解释器必须与生产镜像同版本（不新造第二个版本口径）。"""
        assert _ideInterpreter() == _productionInterpreter(), (
            f"开发环境跑 python:{_ideInterpreter()}，生产镜像跑 "
            f"python:{_productionInterpreter()}——同一 commit 在两处行为分叉，"
            "而故障只在其中一侧可见。开发环境的解释器事实源就是生产 Dockerfile。"
        )

    def testDevelopmentInterpreterMeetsDeclaredFloor(self):
        """下限不因开发环境而破：不得低于项目最低版本。"""
        floor = tuple(int(part) for part in _minInterpreter().split("."))
        actual = tuple(int(part) for part in _ideInterpreter().split("."))
        assert actual >= floor, (
            f".ide/Dockerfile 的 python:{_ideInterpreter()} 低于 "
            f"scripts/config.py 声明的 MIN_PYTHON_VERSION={_minInterpreter()}"
        )


class TestIdeFrontendToolchainMatchesCi:
    def testDevelopmentNodeMajorMatchesCi(self):
        """.ide/Dockerfile 的 Node 大版本必须与 CI 一致（vitest/vite 行为不因环境分叉）。"""
        assert _ideNodeMajor() == _ciNodeMajor(), (
            f"开发环境跑 node:{_ideNodeMajor()}，CI 跑 node-version "
            f"{_ciNodeMajor()}——前端工具链在两个大版本上行为分叉。"
        )

    def testDevelopmentNodeMajorMatchesComposeFrontend(self):
        """与 compose 前端镜像同源（R4 已钉住 compose↔CI，此处补第三面）。"""
        compose = yaml.safe_load(_read(COMPOSE))
        frontend = (compose.get("services") or {}).get("frontend") or {}
        image = str(frontend.get("image", ""))
        match = re.match(r"^node:(\d+)", image)
        assert match, f"compose frontend.image={image!r} 取不到 Node 大版本"
        assert _ideNodeMajor() == match.group(1), (
            f"开发环境跑 node:{_ideNodeMajor()}，compose 前端跑 {image}——"
            "三种交付形态的前端大版本必须同源。"
        )


class TestWebIdeRunsInTheDevelopmentContainer:
    def testCodeServerIsInstalledForSingleContainerMode(self):
        """装了 code-server ⇒ 平台走单容器模式，WebIDE 与开发环境同容器。

        未安装时平台另起 `code-server` 容器（双容器模式），WebIDE 连的是那一侧，
        开发容器要多一层跨容器终端——而本仓的路由、插件、调试都在开发容器里。

        判定取**真安装指令**（执行 code-server 官方 install.sh 的那条 `RUN`），
        不取字符串出现在注释里的形态——后者会让注释替安装发合格证
        （摘掉安装但留下注释，门禁照样绿）。
        """
        dockerfile = _read(IDE_DOCKERFILE)
        installed = re.search(
            r"^RUN\b.*code-server\.dev/install\.sh", dockerfile, re.M
        )
        assert installed, (
            ".ide/Dockerfile 没有真正的 code-server 安装指令"
            "（`RUN ... code-server.dev/install.sh`）——平台会回落到双容器模式，"
            "WebIDE 连到另一侧、访问不到开发容器里的本仓工具链。"
        )

    def testSshServerIsInstalledForRemoteClients(self):
        """VSCode / Cursor / CodeBuddy 客户端经 Remote-SSH 连入，须预装 openssh-server。

        判定取**apt 安装块里真被点名的包**（`apt-get install` 调用面），
        不取字符串出现在注释里的形态——同 code-server 那条的理由。
        """
        assert "openssh-server" in _aptPackages(_read(IDE_DOCKERFILE)), (
            ".ide/Dockerfile 的 apt 安装面里没有 openssh-server——官方的"
            " VSCode/Cursor/CodeBuddy 客户端远程连接要求自定义环境预装 SSH 服务。"
        )


class TestVscodePipelineIsWiredOnEveryBranch:
    def testFallbackBlockCarriesTheVscodeEvent(self):
        """开发环境挂在 `$` 兜底块上（不是只在 main 才有效）。"""
        data = yaml.safe_load(_read(CNB))
        assert "vscode" in (data.get("$") or {}), (
            ".cnb.yml 的 `$` 下没有 `vscode` 事件——分支页面点「云原生开发」时"
            "本仓配置不参与，开发环境落到平台默认镜像。"
        )
        assert "vscode" not in (data.get("main") or {}), (
            "`vscode` 挂在 `main` 下时只有 main 分支页面生效；"
            "它的用途恰恰是「要在别的分支上开发」。"
        )

    def testPipelineBuildsTheRepoDockerfileWithFallbackImage(self):
        """构建本仓 `.ide/Dockerfile` 并声明回退镜像（构建失败不得让环境创建不出来）。"""
        docker = _vscodeJob().get("docker") or {}
        assert docker.get("build") == ".ide/Dockerfile", (
            f"vscode 事件的 docker.build={docker.get('build')!r}——"
            "不构建本仓 .ide/Dockerfile 就等于没有自定义开发环境。"
        )
        assert docker.get("image"), (
            "vscode 事件缺 docker.image 回退镜像——.ide/Dockerfile 构建失败时"
            "开发环境直接创建不出来（官方文档：image 作为构建失败时的回退镜像）。"
        )

    def testPipelineDeclaresWebIdeAndDockerServices(self):
        """`services` 必须同时声明 vscode 与 docker（官方示例的接线面）。"""
        services = _vscodeJob().get("services") or []
        for expected in EXPECTED_SERVICES:
            assert expected in services, (
                f"vscode 事件缺 services 项 {expected!r}（现有 {services!r}）"
            )


class TestDevEnvironmentDoesNotForkTheDependencySource:
    def testBootstrapInstallsFromTheExistingLockFiles(self):
        """预装依赖必须取自既有锁/清单，不得在开发环境里另写一份依赖清单。

        教义第 6 条：参数、枚举、口径、配置只允许一处定义。开发环境的
        `stages` 若自己列一串包名，就与 `requirements-ci.lock` / `NeurUI/package.json`
        成了两份定义，二者必然漂移——而漂移的代价是 CI 绿、开发环境跑不起来。
        """
        scripts = _allStageScripts(_vscodeJob())
        assert "requirements" in scripts, (
            "vscode 事件的 stages 未从 requirements*.lock 安装依赖——"
            "要么开发环境装不上后端依赖，要么另写了一份第二份清单。"
        )
        assert re.search(r"npm\s+(ci|install)", scripts), (
            "vscode 事件的 stages 未安装前端依赖（NeurUI/package.json）——"
            "前端工具链在开发环境里缺席。"
        )

    def testReferencedDependencySourcesExist(self):
        """引用的依赖事实源必须真的在仓（引用不存在的锁文件是最坏的一种静默失败）。"""
        assert REQUIREMENTS_CI_LOCK.is_file(), (
            "requirements-ci.lock 不存在——开发环境引用的锁文件落空，"
            "pip 会以非 0 退出而环境创建失败。"
        )
        assert NEURUI_PACKAGE.is_file(), "NeurUI/package.json 不存在——前端依赖无从安装"
