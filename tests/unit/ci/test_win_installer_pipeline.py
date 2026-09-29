# -*- coding: utf-8 -*-
"""Windows 自定义界面安装包流水线必须守自托管节点的两条硬语义。

为什么要有本守卫（Issue #332，路线 A）：自定义界面壳是 WPF(net48)，编译依赖
Windows 自带件（`csc.exe` / `robocopy`），容器是 Linux，故该包**只能**在根组织
自托管 Windows 构建机上产出。自托管节点与平台容器节点是两套语义：

  1) 脚本直接跑在宿主机上，**不经过 Docker** —— 写 `docker.image` 会被静默忽略，
     写 `runner.cpus` 同理无效（限额由宿主机整机资源决定）。这类"写了没用"的键
     不会有任何红：构建照样跑，只是配置表达了一个不存在的意图。
  2) 命中靠 `runner.namespace: group` + `runner.tags`（tags 必须是节点标签子集）。

判据（逐条咬合，防止把容器节点那套配置抄过来）：
  · 事件存在且挂在 `$` 下（api_trigger 家族的事件挂载点）；
  · 每条 Job 都必须 `namespace: group`（自托管），且**不得**出现 `docker` /
    `runner.cpus`（宿主直跑，Docker 与 cpus 限额均不生效）；
  · tags 的定义只出现在锚点里，Job 经锚点引用 —— 标签是单一定义；
  · 必须带 Windows 宿主自证 stage（`cmd /c ver`）与工具链点名。
"""
from __future__ import annotations

import re

from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[3]
_CNB_YML = _REPO / ".cnb.yml"
_EVENT = "api_trigger_win_installer"


def _doc() -> dict:
    return yaml.safe_load(_CNB_YML.read_text(encoding="utf-8"))


def _jobs() -> list[dict]:
    events = _doc().get("$", {})
    assert _EVENT in events, f"`.cnb.yml` 的 `$` 下缺 {_EVENT} 事件"
    return events[_EVENT]


def testEventIsMountedUnderDollar():
    """api_trigger 家族事件必须挂 `$` 下（分支级挂载点不认）。"""
    assert _EVENT in _doc().get("$", {})


def testJobsUseSelfHostedRunnerNamespace():
    """每条 Job 都必须 namespace: group（自托管节点）。"""
    for job in _jobs():
        runner = job.get("runner", {})
        assert runner.get("namespace") == "group", (
            f"{job.get('name')}: 自托管节点必须 namespace: group（实际 {runner.get('namespace')!r}）"
        )


def testNoDockerOrCpuLimitOnSelfHosted():
    """宿主直跑：docker.image 与 runner.cpus 均不生效，写上去是死配置。"""
    for job in _jobs():
        assert "docker" not in job, (
            f"{job.get('name')}: 自托管节点不经 Docker，不得写 docker 段"
        )
        assert "cpus" not in job.get("runner", {}), (
            f"{job.get('name')}: 宿主直跑，runner.cpus 无效不得写"
        )


def testRunnerTagsAreSingleDefinition():
    """tags 只在锚点里定义一处，Job 经锚点引用（不手抄标签名）。

    读**源文本**而不是解析后的 dict：YAML 锚点在解析期就已展开，
    展开后的 dict 里 tags 一定出现（那是锚点引用生效的证据），
    拿它判断"有没有手抄"只会把锚点引用误判成手抄。
    """
    src = _CNB_YML.read_text(encoding="utf-8")
    assert "&win-installer-tags" in src, "缺 tags 锚点定义（标签单一定义）"
    assert "*win-installer-runner" in src, "Job 未经 runner 锚点引用"
    # 事件块内不得出现第二份 `tags:` 字面量（只能来自锚点）。
    block = src.split("api_trigger_win_installer:", 1)[1]
    assert "tags:" not in block, (
        "事件块内出现了手抄的 `tags:` 字面量 —— 标签必须只由锚点定义"
    )


def testHostSelfProofAndToolchainNaming():
    """必须有 Windows 宿主自证 + 工具链逐件点名（缺席即失败，不静默跳过）。"""
    scripts = "\n".join(
        stage.get("script", "")
        for job in _jobs()
        for stage in job.get("stages", [])
    )
    assert "cmd /c ver" in scripts, "缺 Windows 宿主自证（cmd /c ver）"
    for tool in ("csc.exe", "makensis", "cargo", "python"):
        assert tool in scripts, f"工具链未点名：{tool}"


# ── 自托管节点的「进程环境冻结」硬语义（Issue #332 实机踩到）────────────────
# 自托管 Runner 以**服务**形态常驻，其进程环境在服务启动那一刻定型。此后用
# `choco install python312` 之类往**机器 PATH**（HKLM\...\Environment）写新条目，
# 正在跑的 Runner **读不到** —— 只有重启服务才会重新读。
#
# 实机证据（2026-09-30，节点 orange-connector，20C/31G）：
#   machine PATH 含 `C:\Python312\`         ← 已装
#   Runner 进程 PATH 只有 `...\chocolatey\bin`（无 Python、无 NSIS）
#   于是 `Get-Command python` / `makensis` 全部 MISSING —— 而它们**就在盘上**。
#
# 这对本流水线是致命的：`Prepare` 与 stage 脚本都在 Runner 进程里跑，
# 于是「机器上明明装了」与「构建期查不到」分裂成两个事实。不修的话失败形态是
# 「工具链缺席：makensis, python」——看起来像整机没装，实际是环境没刷新，
# 人会去打一场打不赢的仗（重装、换机器），而根因在环境继承。
#
# 根修点：**流水线自己从机器注册表刷新 PATH**，而不是指望管理员重启 Runner 服务。
# 判据（看结构不看措辞）：
#   · 事件块内必须有刷新机器 PATH 的语句（`GetEnvironmentVariable(...,"Machine")`）；
#   · 该刷新必须发生在工具链探测**之前**（探测读的就是被刷新的那份 PATH）。


def _scripts() -> str:
    return "\n".join(
        stage.get("script", "")
        for job in _jobs()
        for stage in job.get("stages", [])
    )


def testMachinePathIsRefreshedBeforeToolchainProbe():
    """自托管 Runner 进程环境在服务启动时冻结；工具链探测前必须刷新机器 PATH。

    刷新逻辑是**单一定义**：落在仓内 `scripts/desktop/refresh_machine_path.ps1`，
    各 stage 一行 dot-source（`testEveryToolInvokingStageRefreshesPath` 钉住覆盖面）。
    本守卫钉「读机器级注册表」与「先于探测」两件。
    """
    repo = Path(__file__).resolve().parents[3]
    helper = repo / "scripts" / "desktop" / "refresh_machine_path.ps1"
    helper_src = helper.read_text(encoding="utf-8") if helper.exists() else ""
    assert 'GetEnvironmentVariable("Path", "Machine")' in helper_src, (
        "刷新 helper 必须真读机器级注册表 PATH —— "
        "自托管 Runner 进程环境冻结，后装的 python 在盘上却查不到"
    )

    src = _scripts()
    # env 自证 stage 必须 dot-source 刷新，且先于探测。
    refresh_at = src.find("refresh_machine_path.ps1")
    probe_at = src.find("$probes =")
    assert refresh_at != -1, "env 自证 stage 缺 refresh_machine_path.ps1 dot-source"
    assert probe_at != -1, "缺工具链逐件点名段落"
    assert refresh_at < probe_at, (
        "机器 PATH 刷新必须发生在工具链探测之前 —— 探测读的就是刷新后的 PATH"
    )


def testEveryToolInvokingStageRefreshesPath():
    """每个调用 python/cargo/npx 的 stage 都必须先刷新机器 PATH。

    实机证据（2026-09-30，节点 orange-connector）：CNB 的流水线 stage **各自独立**
    起一个 PowerShell 进程（同 Runner，但环境不跨 stage 继承）。把刷新只写在
    「环境自证」stage 里，到第 2 个 stage 就失效了 —— 实测 `python` 在 env 自证里
    解析成功（`C:\\Python312\\python.exe`），到 bundle_backend stage 立刻
    `无法将"python"项识别为 cmdlet`（`CommandNotFoundException`）。

    故刷新必须**逐 stage**生效。单一定义靠仓内 helper（不逐 stage 手抄 8 行）：
    每个需要的 stage 只写一行 dot-source，helper 本体只此一份（教义第 6 条）。
    """
    repo = Path(__file__).resolve().parents[3]
    helper = repo / "scripts" / "desktop" / "refresh_machine_path.ps1"
    assert helper.exists(), (
        "缺 scripts/desktop/refresh_machine_path.ps1 —— 刷新逻辑要有单一定义，"
        "不逐 stage 手抄"
    )
    helper_src = helper.read_text(encoding="utf-8")
    assert 'GetEnvironmentVariable("Path", "Machine")' in helper_src, (
        "helper 必须真读机器级注册表 PATH"
    )

    # 每个 script 里出现工具调用的 stage，都必须 dot-source 这个 helper。
    dot_source = "refresh_machine_path.ps1"
    offenders: list[str] = []
    for job in _jobs():
        for stage in job.get("stages", []):
            script = stage.get("script", "")
            if not script:
                continue
            usesTool = any(
                re.search(rf"(?<![\w.-]){tool}(?![\w.-])", script)
                for tool in ("python", "cargo", "rustc", "npx")
            )
            if usesTool and dot_source not in script:
                offenders.append(stage.get("name", "<无名 stage>"))
    assert offenders == [], (
        "下列 stage 调用了 python/cargo/npx 却没刷新机器 PATH —— "
        "跨 stage 不继承，工具会在这些 stage 里 CommandNotFound：\n  - "
        + "\n  - ".join(offenders)
    )
