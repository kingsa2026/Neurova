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
REQUIREMENTS_FULL_LOCK = PROJECT_ROOT / "requirements-full.lock"
REQUIREMENTS_TXT = PROJECT_ROOT / "requirements.txt"
PLAYWRIGHT_CLI = PROJECT_ROOT / "scripts" / "ci" / "dev_env_playwright_install.sh"
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


def _dockerIgnoreExcludes(path: str, patterns: list) -> bool:
    """按 Docker 的 `.dockerignore` 语义判定 `path` 是否被排除（最后一条匹配生效）。

    Docker 的匹配器与 `fnmatch` 有两处不同，直接拿 `fnmatch` 当替身会漏判：

    - `**` 跨 `/`（`**/*.lock` 命中任意目录下的 `.lock`），而 `fnmatch` 里 `*`
      不跨 `/`、也不认 `**`；
    - 目录模式（`logs/`）排除其下所有内容。

    故此处把 `**/` 展开成「零个或多个目录段」再逐条比对；本函数只服务本文件的
    三条构建上下文判据，不做通用实现。
    """
    import re as _re

    def matches(pattern: str, candidate: str) -> bool:
        # 归一化：`**/` 可匹配零段，故先试「原地」再试「跨目录」两种形态。
        body = pattern.lstrip("/")
        variants = {body}
        if "**/" in body:
            variants.add(body.replace("**/", ""))
        for variant in variants:
            regex = _re.escape(variant).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
            if _re.fullmatch(regex, candidate):
                return True
            if _re.fullmatch(regex + "/.*", candidate):
                return True
        return False

    excluded = False
    for pattern in patterns:
        if pattern.startswith("!"):
            if matches(pattern[1:].lstrip("/"), path):
                excluded = False
        elif matches(pattern, path):
            excluded = True
    return excluded


def _isTracked(relative: str) -> bool:
    """文件是否处于 git 跟踪/可添加态——"能入库"是"平台取得声明"的前提。

    `.gitignore` 的 `.*/` 规则会连 `.ide/` 一起排除；声明了开发环境却入不了库，
    别人点按钮拿到的仍是平台默认镜像，而本地一切正常 —— 属静默失败。
    """
    import subprocess

    # 两步，缺一不可：
    #   1. 规则层：`.gitignore` 不得把该路径排除（`git check-ignore` 对**未跟踪**路径
    #      的判定，必须先 `--no-index` —— 否则已入库的文件永远返回"未被忽略"，
    #      本判据在 CI 上恒真，等于没做；这正是本判据第一版的洞）。
    #   2. 索引层：该文件必须处于可添加态（未被 ignore 才能进库）。
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", relative],
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
    """预装依赖必须取自既有锁/清单，不得另写一份依赖清单（教义第 6 条）。

    判定面取**整个开发环境声明面**（`.ide/Dockerfile` + `vscode` 事件的 stages），
    而不是只看 stages：后端全量依赖现在装在校镜像构建期（`.ide/Dockerfile`），
    前端 `npm ci` 留在 stages（它需要工作区就位）。两处各有其位，但都是同一份
    事实源的消费方——判定只看一处会漏掉另一处（"装了两遍"或"一处都没装"都看不出来）。
    """

    def testDependencySourcesAreTheExistingLocks(self):
        """后端取自 requirements*.lock、前端取自 NeurUI/package.json，且都真在仓。"""
        surface = _read(IDE_DOCKERFILE) + "\n" + _allStageScripts(_vscodeJob())
        assert re.search(r"requirements(-\w+)?\.lock", surface), (
            "开发环境声明面（.ide/Dockerfile + vscode stages）未引用任何 "
            "requirements*.lock——要么装不上后端依赖，要么另写了一份第二份清单。"
        )
        assert re.search(r"npm\s+(ci|install)", surface), (
            "开发环境声明面未安装前端依赖（NeurUI/package.json）——"
            "前端工具链在开发环境里缺席。"
        )
        for path in (REQUIREMENTS_FULL_LOCK, NEURUI_PACKAGE):
            assert path.is_file(), (
                f"开发环境引用的 {path.relative_to(PROJECT_ROOT)} 不存在——"
                "依赖事实源落空，环境创建必然失败。"
            )



class TestDevelopmentEnvironmentPreinstallsTheFullRuntime:
    """开发环境必须是"开箱即用的整装环境"，不是"装个薄壳再让 stages 补"。

    用户诉求（Issue #289 评论）：不要平台默认镜像，把 neurova 的**运行环境**
    都预装好。这里的"运行环境"有确定的外延，不是"多装几个包"：

    - 后端：生产镜像装的就是 `requirements.txt`（`Dockerfile` 第 25 行
      `pip install -r requirements.txt`），故开发环境的后端依赖事实源也是它，
      且以 `requirements-full.lock` 锁定 —— 与 `requirements.txt` 同源
      （`uv pip compile --universal requirements.txt -o requirements-full.lock`），
      不是第二份清单；
    - 前端：`NeurUI/package-lock.json` 的 `npm ci` 是 CI 的同源装法；
    - 浏览器：`playwright` 在 `requirements.txt` 里是硬声明，且真实功能路径
      （`neurova/web_reach/` 抓取、Computer Use 截图）需要**浏览器二进制**，
      而 `pip install playwright` 只装客户端、不装浏览器 —— 这是"预装了却跑不动"
      最典型的一种，故必须显式 `playwright install`（含系统依赖）。

    判据只断言"装的是哪份事实源"，不手抄包名 —— 与
    `TestDevEnvironmentDoesNotForkTheDependencySource` 同一口径（教义第 6 条）。
    """

    def testImageInstallsTheFullProductionRuntime(self):
        """镜像构建期必须装 `requirements-full.lock`（生产运行环境全量）。

        只装 `requirements-ci.lock` 得到的是"能跑静态门禁的薄环境"：
        `onnxruntime` / `sentence-transformers` / `edge-tts` / `playwright` /
        `pyautogui` 这些都在 `requirements-ci.txt` 的**刻意排除**列表里。
        用它当开发环境，本仓大半功能路径（语义检索、TTS、抓取、桌面自动化）
        开箱即 import 失败 —— 而"预装好运行环境"正是本项的诉求。
        """
        dockerfile = _read(IDE_DOCKERFILE)
        assert re.search(r"requirements-full\.lock", dockerfile), (
            ".ide/Dockerfile 未在构建期装 requirements-full.lock——"
            "只装 requirements-ci.lock 是薄环境，本仓全量运行依赖（语义检索/TTS/"
            "抓取/桌面自动化）缺席，开发环境开箱即 import 失败。"
        )
        assert REQUIREMENTS_FULL_LOCK.is_file(), (
            "requirements-full.lock 不存在——开发环境引用的全量锁文件落空，"
            "pip 会以非 0 退出而环境创建失败。"
        )

    def testFullLockIsCompiledFromTheSingleRequirementsSource(self):
        """全量锁必须与 `requirements.txt` 同源，不得是第二份手写清单。

        `requirements-full.lock` 的头部记录了它的生成命令；判据读那一行，
        确认来源是 `requirements.txt`——引用一份来源不明的锁，等于开发环境
        装了一套"看起来像生产、其实谁也不知道是什么"的依赖。
        """
        header = _read(REQUIREMENTS_FULL_LOCK).splitlines()[:4]
        text = "\n".join(header)
        assert "requirements.txt" in text, (
            "requirements-full.lock 头部未记录来自 requirements.txt 的编译命令——"
            "开发环境装的全量锁与生产镜像的依赖事实源脱钩，二者必然漂移。"
        )

    def testPlaywrightBrowsersAreInstalled(self):
        """`playwright` 浏览器二进制必须真装（pip 装包 ≠ 能跑浏览器）。

        `requirements.txt` 声明了 `playwright`，但 `pip install playwright`
        只装**客户端**：真正抓取/截图时它会去 `~/.cache/ms-playwright` 找浏览器，
        找不到就报 "Executable doesn't exist"。这是"依赖装了却跑不动"的典型形态，
        在开发环境里必须一次装好（含 `--with-deps` 的系统库）。
        """
        assert re.search(r"^\s*RUN\b[^\n]*playwright[^\n]*install", _read(IDE_DOCKERFILE), re.M) or re.search(
            r"playwright[^\n]*install", _allStageScripts(_vscodeJob())
        ), (
            "开发环境未执行 playwright 浏览器安装（真装指令 `RUN ... playwright install`）"
            "——pip 只装了客户端，实际抓取/截图时浏览器二进制缺席、运行时报错。"
            "判定只认真装指令，注释里提到不算（本仓在 code-server/openssh 上修过的同一形态）。"
        )

    def testSystemLibrariesForHeadlessToolsAreInstalled(self):
        """无图形界面容器里跑浏览器/桌面工具所需的系统库必须预装。

        HEADLESS 容器里 `playwright` / `pyautogui` 依赖的 X11/字体/编解码库
        不在基础镜像里；缺了它表现为"包都装了、一跑就崩在 libXXX.so"。
        官方给的装法是 `playwright install --with-deps`，本仓据此收口。
        """
        real_directive = re.search(
            r"^\s*RUN\b[^\n]*playwright[^\n]*install[^\n]*--with-deps",
            _read(IDE_DOCKERFILE),
            re.M,
        ) or re.search(
            r"playwright[^\n]*install[^\n]*--with-deps", _allStageScripts(_vscodeJob())
        )
        assert real_directive, (
            "playwright 安装未带 --with-deps——无图形界面容器缺 X11/字体/编解码库，"
            "浏览器会在运行时报 libXXX.so 缺失，而不是装的时候报。"
            "判定只认真装指令，注释里提到不算。"
        )


class TestBuildContextCarriesWhatTheIdeImageCopies:
    """`.ide/Dockerfile` 的 `COPY` 源必须真在构建上下文里（`.dockerignore` 不得挡）。

    `.dockerignore` 挡掉 `COPY` 源时，`docker build` **直接构建失败**，不是"少拷一个
    文件"——开发环境因而整个创建不出来。这与本仓在 `models/` 权重上修过的形态同型
    （跨目录通配挡住真源 ⇒ COPY 失败）。判据从 Dockerfile 的 `COPY` 面反推，
    不手抄第二份清单。
    """

    def testEveryCopiedLockFileSurvivesDockerignore(self):
        """Dockerfile 里 `COPY` 的每个锁/清单文件都不得被 `.dockerignore` 排除。"""
        dockerfile = _read(IDE_DOCKERFILE)
        copied = set(
            re.findall(r"^COPY\s+(\S+)\s", dockerfile, re.M)
        )
        assert copied, ".ide/Dockerfile 没有任何 COPY 指令——镜像里不会有依赖声明"
        ignores = [
            line.strip()
            for line in _read(PROJECT_ROOT / ".dockerignore").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        for source in sorted(copied):
            assert (PROJECT_ROOT / source).is_file(), (
                f".ide/Dockerfile 的 COPY 源 {source} 在仓里不存在——"
                "docker build 直接失败，开发环境创建不出来。"
            )
            assert not _dockerIgnoreExcludes(source, ignores), (
                f".ide/Dockerfile 的 COPY 源 {source} 被 .dockerignore 排除——"
                "构建上下文里没有它，docker build 直接失败（不是少拷一个文件）。"
            )

    def testFullLockIsNotBlockedByBlanketIgnoreRules(self):
        """全量锁必须放行：它是开发环境后端依赖的唯一来源。

        判定走**真排除结果**（把规则跑一遍看 `requirements-full.lock` 是否被挡），
        不做模式串搜索 —— 后者只认死某一种写法（`*.lock`），换 `**/*.lock`
        或 `requirements*.lock` 就逃逸，而真实后果一样是构建失败。
        """
        patterns = [
            line.strip()
            for line in _read(PROJECT_ROOT / ".dockerignore").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        for lock in ("requirements-full.lock", "requirements.txt"):
            assert not _dockerIgnoreExcludes(lock, patterns), (
                f".dockerignore 排除了 {lock}——开发环境构建上下文里没有它，"
                "`COPY` 直接失败（不是少拷一个文件），或依赖来源落空。"
            )


class TestDevelopmentEnvironmentEnablesCodeBuddyWeb:
    """`codebuddy` 命令必须在镜像里（CodeBuddy Web 入口的启用条件）。

    官方《CodeBuddy Web》：云开发入口页只在镜像满足「装有 `codebuddy` 且版本
    >= 2.137.0」时才展示该入口。本仓的开发流程大量借助 AI 角色（NPC），
    CodeBuddy Web 正是"在浏览器里用 AI 编码"的入口 —— 自定义镜像不装它，
    就等于把平台自带的一条入口静默丢掉，而症状只是"入口页少一个按钮"，
    没人会把它和 Dockerfile 联系起来。

    判定只认真安装指令（`npm install -g @tencent-ai/codebuddy-code`），
    注释里提到不算 —— 与 code-server 那条同一口径。
    """

    def testCodebuddyCliIsInstalledForTheWebEntry(self):
        dockerfile = _read(IDE_DOCKERFILE)
        real_install = re.search(
            r"^\s*RUN\b[^\n]*npm\s+(install|i)\b[^\n]*@tencent-ai/codebuddy-code",
            dockerfile,
            re.M,
        ) or re.search(
            r"@tencent-ai/codebuddy-code", _allStageScripts(_vscodeJob())
        )
        assert real_install, (
            ".ide/Dockerfile 未安装 @tencent-ai/codebuddy-code（真装指令 "
            "`RUN ... npm install -g @tencent-ai/codebuddy-code`）——"
            "官方《CodeBuddy Web》：镜像缺 `codebuddy` 时云开发入口页不展示该入口。"
            "判定只认真装指令，注释里提到不算。"
        )


class TestDevelopmentEnvironmentDeclaresItsResourceSpec:
    """资源规格必须**声明**（而不是靠平台默认值），且与启动按钮口径一致。

    官方《自定义云原生开发流水线》：`runner.cpus` 决定容器资源（内存 = cpus × 2GiB）。
    开发环境要跑 pytest 子集 + vitest，不声明就等于"配了什么资源无从作答"。
    两个落点（`.cnb.yml` 的 `runner.cpus` 与 `.cnb/settings.yml` 的 `workspace.launch.cpus`）
    必须一致：前者是流水线实际申请的资源，后者是按钮展示与创建时用的规格，
    二者分叉就是"按钮说 8 核、实际跑 4 核"这类不可见的降配。
    """

    def testVscodePipelineDeclaresRunnerCpus(self):
        job = _vscodeJob()
        runner = job.get("runner") or {}
        assert runner.get("cpus"), (
            "vscode 事件未声明 `runner.cpus`——开发环境的资源规格无从作答，"
            "落到平台默认值；官方语法：`runner.cpus` 决定 CPU 核数（内存 = cpus × 2GiB）。"
        )

    def testRunnerCpusMatchesTheLaunchButtonSpec(self):
        pipeline_cpus = (_vscodeJob().get("runner") or {}).get("cpus")
        settings = yaml.safe_load(_read(PROJECT_ROOT / ".cnb" / "settings.yml"))
        launch = ((settings.get("workspace") or {}).get("launch") or {})
        button_cpus = launch.get("cpus")
        assert button_cpus, (
            ".cnb/settings.yml 的 workspace.launch 未声明 cpus——"
            "启动按钮的规格无从作答。"
        )
        assert pipeline_cpus == button_cpus, (
            f"vscode 流水线的 runner.cpus={pipeline_cpus} 与启动按钮声明的 "
            f"cpus={button_cpus} 不一致——按钮展示的规格与实际申请的资源分叉，"
            "表现为「按钮说 8 核、实际跑另一个数」的不可见降配。"
        )


class TestRuntimeDependenciesReachEveryUserSession:
    """依赖必须装在**系统** site-packages，不能只落 `/root/.local`。

    `pip install --user` 在构建期（root）把包装到 `/root/.local`，而该路径只在
    root 的 `sys.path` 里。平台若以非 root 身份起开发会话（CloudIDE 的常见形态），
    `import onnxruntime` 立刻 ModuleNotFoundError —— 镜像里明明装着，谁都看不出
    为什么。这是"预装了却用不上"最隐蔽的一种。
    """

    def testBackendDepsAreInstalledSystemWide(self):
        dockerfile = _read(IDE_DOCKERFILE)
        installs = re.findall(r"^\s*RUN\b[^\n]*pip install[^\n]*$", dockerfile, re.M)
        assert installs, ".ide/Dockerfile 没有 pip install 指令——依赖无从预装"
        offenders = [line for line in installs if "--user" in line]
        assert not offenders, (
            "pip install 带了 `--user`——包落 /root/.local，非 root 会话的 sys.path "
            "里没有它，`import` 立刻 ModuleNotFound 而镜像里明明装着。"
            f"命中：{offenders}"
        )
