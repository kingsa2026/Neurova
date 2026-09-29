# -*- coding: utf-8 -*-
"""镜像运行时自证：镜像里那些「绝对路径契约」必须真的成立（Issue #330）。

## 现象

`api_trigger_docker_image` 流水线（Issue #90 建的镜像真运行自证）红在
「起容器并真探活」：宿主 `curl` 与容器自身 `HEALTHCHECK` 双双拿不到 200，
`docker logs` 点名的是**模型下载三源全败**，而不是探针本身：

    curl: (7) Failed to connect to localhost port 9527 ... Could not connect
    [E1022] Failed to create SDK directories: [Errno 13] Permission denied: '/home/neurova/.modelscope'
    Ignored error while writing commit hash to /home/neurova/.cache/...
        ^ [Errno 13] Permission denied: '/home/neurova/.cache'
    RuntimeError: 所有下载源均失败: ...

## 根因

镜像用 `USER neurova`（非 root，无 home 目录）跑 `start_server.py`。Python
启动时对 `$HOME` 不可写**先告警、随后照旧执行**（`site.addusersitepackages`
报 "Can't create user site-packages directory" 不会让进程退出），于是非 root
身份带下来了，而 HOME 仍是 `/home/neurova` —— 该目录被 root 持有、模式 755，
uid 不匹配、位不含写。所有"默认落在 `$HOME` 下"的运行时契约当场失效：

- `~/.local/lib/pythonX.Y/site-packages`（`PYTHONPATH=/app` 不含它）读不到；
  实测日志里 `huggingface_hub` / `modelscope` 的路径正是
  `/home/neurova/.local/lib/python3.12/site-packages/...`，说明这一半侥幸成立；
- `~/.modelscope`（ModelScope SDK 的缓存根）建不出来；
- `~/.cache/huggingface`（HF Xet 落点）不可写。

三源依次失败 ⇒ `ensure_model("bge-small-zh-v1.5")` 抛 `RuntimeError` ⇒
`onnx_embedding` 初始化失败 ⇒ 后端启动失败（或在别的时点静默降级）⇒ 探针 30s
超时后仍是 `000` / `unhealthy`。

镜像**本来**已经只拷了 ONNX 路径需要的权重，`model.onnx` 是随代码走的资产、
不走下载；下载器那三个源是运行容器里的**兜底**，不该在权重齐备时被触碰。

## 判据面

`issubclass` 式地逐条反证两类"只写不读的声明"，两者都不是跑一次 CI 才暴露的：

1. **Dockerfile 声明的运行时落点**（`EXPOSE` / `HEALTHCHECK` / `WORKDIR` /
   `USER` 的 HOME）必须是容器里真的成立的事实——`WORKDIR` 就是应用读资产的
   CWD，`$HOME` 就是各 SDK 的缓存根；
2. **反向控制**：`~/.local` 的用户级 site-packages 若不在 `sys.path` 上，则
   依赖只装在用户目录的镜像**启动即崩**，而构建阶段一个字都不会报。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_DOCKERFILE = io.open(PROJECT_ROOT / "Dockerfile", encoding="utf-8").read()


def dockerfileUser() -> str:
    """Dockerfile 声明的运行用户（最后一个 `USER` 生效；未声明即 root）。"""
    users = re.findall(r"^\s*USER\s+(\S+)\s*$", _DOCKERFILE, re.MULTILINE)
    return users[-1] if users else "root"


def userHome(user: str) -> str:
    """该用户在镜像里的 home 目录。

    `useradd` 未显式给 `-d` 时，shadow 的默认是 `/<user>`（本仓 `useradd -r`
    不建家目录、也不授 `-m`）——故这里按 Dockerfile 的 `useradd` 行取，
    取不到再退回 `/<user>`。
    """
    match = re.search(rf"^\s*RUN\s+.*useradd\b[^\n]*\b{re.escape(user)}\b", _DOCKERFILE, re.MULTILINE)
    segment = match.group(0) if match else ""
    explicit = re.search(r"-d\s+(\S+)", segment)
    if explicit:
        return explicit.group(1).rstrip("/")
    return f"/{user}"


def dockerignoreRules() -> list:
    return [
        line.strip()
        for line in io.open(PROJECT_ROOT / ".dockerignore", encoding="utf-8").read().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _patternMatches(path: str, pattern: str) -> bool:
    import fnmatch

    return (
        fnmatch.fnmatch(path, pattern)
        or path.startswith(pattern + "/")
        or fnmatch.fnmatch(path.split("/")[-1], pattern)
    )


def ignoredByDockerignore(path: str) -> bool:
    state = False
    for rule in dockerignoreRules():
        negate = rule.startswith("!")
        pattern = (rule[1:] if negate else rule).rstrip("/")
        if _patternMatches(path, pattern):
            state = not negate
    return state


class TestImageRunsAsNonRootWithAWritableHome:
    """镜像以 `USER <非 root>` 运行时，HOME 必须真的可写。

    这不是"风格问题"：HOME 不可写会让 `modelscope` / `huggingface_hub` 这类
    "缓存默认落 $HOME"的 SDK 在**运行期**建目录失败，且 Python 不会因此退出
    （site 只告警）——故障被推迟到第一次真正用到它们时。
    """

    def test_homeOfTheRuntimeUserIsMadeWritableByItsOwner(self):
        user = dockerfileUser()
        if user == "root":
            pytest.skip("镜像以 root 运行，不存在 HOME 权限面")
        home = userHome(user)
        # 判据只看 Dockerfile 是否**显式**把该 home 交给运行用户（或显式把
        # HOME 指到别处）：`chown -R <user>` / `chown <user>` 命中它即可。
        # 路径前不能用 `\b`：`/` 非单词字符，`\b/home` 只在斜杠前是单词字符时才成立
        # （`a/home` 能匹配、`" /home"` 不能）——这正是"判据写错会静默空转"的形态，
        # 故用负向后视锚定 token 起点。
        homeToken = rf"(?<![\w/]){re.escape(home)}(?![\w/])"
        userToken = rf"\b{re.escape(user)}\b"
        assert re.search(
            rf"chown\b[^\n]*{userToken}[^\n]*{homeToken}"
            rf"|chown\b[^\n]*{homeToken}[^\n]*{userToken}",
            _DOCKERFILE,
        ) or re.search(rf"^\s*ENV\s+HOME\s*=\s*\S+", _DOCKERFILE, re.MULTILINE), (
            f"镜像以 `USER {user}` 运行，但 Dockerfile 没有任何一句把 `{home}` 交给它，"
            "也没有把 `HOME` 指到别处——\n"
            "Python 对不可写 HOME 只告警不退出（site 的 Can't create user site-packages），"
            "于是 modelscope / huggingface_hub 的缓存根（`~/.modelscope`、`~/.cache`）"
            "在运行期建不出来，模型下载源会**全部**失败，而构建阶段一个字都不会报。\n"
            f"补一句 `chown -R {user}:{user} {home}`（或显式声明 `ENV HOME=<可写目录>`）。"
        )


class TestUserSitePackagesAreActuallyImportable:
    """用户级 site-packages 必须在 `sys.path` 上（否则依赖只在用户目录 = 启动即崩）。

    镜像里依赖是 `pip install --user` 装的：**装在哪个仓**（`COPY` 的目标）与
    **Python 去哪找**（`site.getusersitepackages()`，按 `$HOME` 推导）必须落到同
    一个目录——`PYTHONPATH=/app` 不含它。非 root 运行时 HOME 隶属 root 时 Python
    的用户站点直接不挂载，镜像会在 `import uvicorn` 处崩。

    第一版判据写的是「有没有 `chown <user> <home>`」——那是**空转**：摘掉 `--chown`
    与改落点后它照样绿（`chown` 只为缓存可写，不承担导入面）。本版按镜像语义取数：
    把 `COPY` 的落点、`ENV` 的 `$HOME`/`PYTHONPATH` 解析出来再判相等。
    """

    #: `COPY --from=builder [--chown=U:G] <源> <落点>`（本判据只认单源形态）
    USERCOPY_RE = re.compile(
        r"^\s*COPY\s+--from=\S+\s+(?P<opts>--\S+\s+)*(?P<src>\S+)\s+(?P<dest>\S+)\s*$",
        re.MULTILINE,
    )

    def copiedDestinations(self) -> list:
        return [m.group("dest") for m in self.USERCOPY_RE.finditer(_DOCKERFILE)]

    def resolvedHome(self, user: str) -> str | None:
        """镜像里该用户看到的 `$HOME`：显式 `ENV HOME=` 优先，否则 shadow 默认。"""
        envHome = re.search(r"^\s*ENV\s+HOME\s*=\s*(\S+)\s*$", _DOCKERFILE, re.MULTILINE)
        if envHome:
            return envHome.group(1).rstrip("/")
        if user == "root":
            return "/root"
        declared = re.search(rf"^\s*RUN\s+.*useradd\b[^\n]*\b{re.escape(user)}\b", _DOCKERFILE, re.MULTILINE)
        explicit = re.search(r"-d\s+(\S+)", declared.group(0)) if declared else None
        return (explicit.group(1).rstrip("/") if explicit else f"/{user}")

    def test_dependenciesLandingInUserSiteAreOnTheImportPath(self):
        user = dockerfileUser()
        if user == "root":
            pytest.skip("root 用户的 site-packages 默认就在 sys.path 上")
        envBlob = "\n".join(re.findall(r"^\s*ENV\s+(.+)$", _DOCKERFILE, re.MULTILINE))
        if "PYTHONNOUSERSITE" in envBlob or "PYTHONUSERBASE" in envBlob:
            return  # 显式关掉/改写了用户站点，导入面不再依赖 HOME
        home = self.resolvedHome(user)
        userSite = f"{home}/.local"
        dests = self.copiedDestinations()
        assert dests, (
            "Dockerfile 里解析不到任何 `COPY --from=builder` 的落点——判据会静默空转。"
            "禁止用「没找到就算过」短路它。"
        )
        onPath = re.search(r"PYTHONPATH\s*=\s*[^\n]*\.local", envBlob)
        landed = [d for d in dests if d == userSite or d.startswith(userSite + "/")]
        assert onPath or landed, (
            f"`USER {user}` 的 `$HOME` 是 `{home}`，用户站点在 `{userSite}/lib/pythonX.Y/site-packages`，"
            "而 `PYTHONPATH=/app` 不含它——\n"
            f"镜像里的 `COPY --from=builder` 落点是 {dests}，没有任何一条落进 `{userSite}`。\n"
            "于是依赖只在盘上、`import` 找不到（非 root 且 HOME 不可写时 Python 直接"
            "跳过用户站点），镜像在 `import uvicorn` 处崩。\n"
            f"把依赖 `COPY --from=builder --chown={user}:{user} <源> {userSite}/...`，"
            "或把用户站点挂进 `PYTHONPATH`。"
        )


class TestImageAssetEntrypointsAreNotBlockedByDockerignore:
    """镜像入口声明的路径不得被 .dockerignore 挡在构建上下文之外。

    这条是 Issue #289 那条判据的**入口侧**补面：资产在不在是那一条的事，
    入口（`WORKDIR` = 应用 CWD、`COPY` 的目标）能不能被填满是这一条的事。
    """

    def test_workingDirectoryIsCopiedOrCreated(self):
        workdirs = re.findall(r"^\s*WORKDIR\s+(\S+)\s*$", _DOCKERFILE, re.MULTILINE)
        assert workdirs, "Dockerfile 没有 WORKDIR —— 应用的资产落点锚（CWD）不明"
        workdir = workdirs[-1]
        assert workdir.startswith("/"), (
            f"最后的 WORKDIR 是相对路径 {workdir!r}——Docker 允许，但应用侧的资产锚"
            "（repoAsset 的仓库根）会随上一级 WORKDIR 漂移。"
        )
        created = re.search(
            rf"mkdir\s+(-p\s+)?[^\n]*{re.escape(workdir)}\b", _DOCKERFILE
        ) or re.search(rf"COPY\s+[^\n]*\s+{re.escape(workdir.rstrip('/'))}/", _DOCKERFILE)
        assert created, (
            f"WORKDIR {workdir} 既没有 `mkdir` 创建、也没有任何 `COPY` 落进去——"
            "Docker 会隐式建它（root 持有），但应用在非 root 下往里写就会 EACCES。"
        )
