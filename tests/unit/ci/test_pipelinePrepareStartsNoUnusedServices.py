# -*- coding: utf-8 -*-
"""流水线不得为「不需要的服务」付 Prepare 的钱（构建 `cnb-13d-1k5pskuuj#004`）。

## 事故读数

`e2e-backend-boot` 那条流水线 4 段里没跑成任何一段，死在平台自己的 `Prepare`：

    - Service git-clone-yyds started [54.9s]
    - Service network-bus started [1m 2s]
    Pipeline prepare error: 任务超过最大执行时间而被强制关闭：1m0s

不声明 `services` 时平台给每条流水线自动起这两个服务，而它们的 `docker run`
算进 `Prepare` 的 **60s** 上限。同一构建里别的流水线这两个服务吃 0.7–13s，
故这件事平时不可见——它是「共享负载下的运气」，不是配置里的判据：
负载一高，任何一条流水线都可能以「一个 stage 都没跑」的形态变红。

## 判据为什么钉在这里

它与「装依赖」「跑测」都无关，红的时候日志里连一条 `FAILED` 都没有，
读日志的人只能重跑。要让下次回退当场变红，只有把「谁声明了服务、谁声明了空」
钉成会咬的断言 —— 顺带把「声明了服务却从不使用」也一并咬住。
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"

#: 平台自动起的两个服务（不声明 `services` 时的默认）。
PLATFORM_DEFAULT_SERVICES = ("git-clone-yyds", "network-bus")

#: 允许 `Prepare` 自带这两个服务的流水线：它们的 stage 要用 docker，或要起
#: 服务容器（镜像构建 / 开发环境）。新增例外必须在这里点名并写明用途。
SERVICE_DEPENDENT_PIPELINES = ("docker-image", "neurova-dev-env")


def _pipelines():
    """取出所有门禁流水线（`main.push` 与 PR 事件共用同一份锚点）。"""
    data = yaml.safe_load(io.open(CNB, encoding="utf-8"))
    return list(data["main"]["push"])


class TestPrepareMustNotPayForUnusedServices:
    def test_backend_boot_pipeline_declares_no_services(self):
        target = [p for p in _pipelines() if p.get("name") == "e2e-backend-boot"]
        assert target, "e2e-backend-boot 流水线不见了——本判据盯的就是它"
        pipeline = target[0]
        assert "services" in pipeline, (
            "e2e-backend-boot 没有显式声明 `services` ⇒ 平台自动起 git 克隆与网络"
            "两个服务，它们的 docker run 算进 Prepare 的 60s 上限，实测吃过 54.9s + 1m2s，"
            "整条流水线一个 stage 都没跑就被强杀（cnb-13d-1k5pskuuj#004）"
        )
        assert list(pipeline["services"]) == [], (
            f"e2e-backend-boot 为不需要的服务付了 Prepare 的钱：{pipeline['services']}"
            "——它只装依赖 + 跑 pytest，一个容器都不起"
        )

    def test_no_pipeline_asks_for_services_it_never_uses(self):
        """声明了服务就要在 stage 里用得上，否则那笔 Prepare 是白付的。"""
        offenders = []
        for pipeline in _pipelines():
            name = pipeline.get("name", "")
            declared = pipeline.get("services")
            if not declared or name in SERVICE_DEPENDENT_PIPELINES:
                continue
            body = "\n".join(
                str(stage.get("script", "")) for stage in pipeline.get("stages", [])
            )
            if "docker build" not in body and "docker compose" not in body:
                offenders.append(f"{name}: {declared}")
        assert not offenders, (
            "这些流水线声明了服务却没有任何 stage 用得上（Prepare 白付）："
            f"{offenders}。要么去掉 `services`，要么写清它服务的是哪一步"
        )

    def test_the_empty_list_is_explained_where_it_is_declared(self):
        """`services: []` 旁必须写明理由，且理由与实测读数一致。

        「声明空列表」本身是一句无法自证的话：读配置的人看不出它是笔误还是裁定。
        故判据同时咬住「理由在场」与「理由里的读数与事故对得上」——
        只写 `services: []` 而不写为什么，下一次有人会以为是漏配。
        """
        text = io.open(CNB, encoding="utf-8").read()
        for service in PLATFORM_DEFAULT_SERVICES:
            assert service in text, (
                f"`.cnb.yml` 没有点名平台默认服务 {service} —— "
                "`services: []` 的理由就无从复核"
            )
        assert "1m0s" in text, (
            "理由里没有那个硬上限的读数（`任务超过最大执行时间而被强制关闭：1m0s`）"
            "—— 少了它，「空列表」看起来就只是随手写的"
        )


#: `sh`（dash）不认的 bash 专有语法。这些 stage 的脚本由 `sh` 解释，写进去就是
#: 「整段跑完之后在收尾行自己炸」——构建 `cnb-8qu-1k5q3m315#003` 实测：
#: `7954 passed` / 覆盖率 88.10% / 一条全绿分隔线之后紧跟 `sh: 5: Bad substitution`，
#: stage 以 exit 2 收场。前几轮没撞见是因为它们都没活到那一行（137 OOM / 断言红）。
BASH_ONLY_SCRIPT_SYNTAX = (
    "${PIPESTATUS",        # 数组展开
    "set -o pipefail",     # dash 报 Illegal option
    "[[ ",                 # 双方括号
    "<<<",                 # here-string
)


class TestStageScriptsStayPortableToSh:
    """stage 脚本必须能被 `sh` 解释——判据不许只在 bash 下成立。"""

    def test_no_stage_script_uses_bash_only_syntax(self):
        offenders = []
        for pipeline in _pipelines():
            for stage in pipeline.get("stages", []):
                script = str(stage.get("script", ""))
                for token in BASH_ONLY_SCRIPT_SYNTAX:
                    if token in script:
                        offenders.append(
                            f"{pipeline.get('name')} / {stage.get('name')}: {token.strip()}")
        assert not offenders, (
            "这些 stage 脚本用了 `sh` 不认的语法，整段会在收尾行自己炸（exit 2），"
            f"与提交内容无关：{offenders}"
        )

    def test_protected_subset_verdict_survives_without_a_shell_array(self):
        """受保护子集的退出码判定必须能取到 **pytest** 的码，且不依赖数组。

        `$?` 直接取会拿到 `tee` 的（门禁从此恒绿）；`${PIPESTATUS[0]}` 是 bash 专有
        （门禁在 `sh` 下恒红）。两个坑都踩过，故判据同时咬两头。
        """
        target = [p for p in _pipelines() if p.get("name") == "unit-tests"]
        assert target, "unit-tests 流水线不见了"
        stage = next(s for s in target[0]["stages"] if "protected subset" in s["name"])
        script = str(stage["script"])
        assert "PIPESTATUS" not in script, (
            "受保护子集又用回了 ${PIPESTATUS[0]}——`sh` 下整段以 `Bad substitution` 收场，"
            "跑完全绿的测试也会把门禁判红（构建 cnb-8qu-1k5q3m315#003）"
        )
        assert "echo $? >" in script, (
            "退出码不是在管道里就地取 pytest 的那一个——写到管道外就只剩 `tee` 的码"
        )
        assert "cat \"$MARK\"" in script or "cat $MARK" in script, (
            "没有从标记文件读回 pytest 的退出码——门禁的判据不明"
        )
