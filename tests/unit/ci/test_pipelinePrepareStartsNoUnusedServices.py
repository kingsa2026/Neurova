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
