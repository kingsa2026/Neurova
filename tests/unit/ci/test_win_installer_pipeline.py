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
