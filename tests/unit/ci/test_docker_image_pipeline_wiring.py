# -*- coding: utf-8 -*-
"""手动镜像构建流水线的接线判据（Issue #90「做一个 docker 镜像跑一下」）。

## 为什么要有这一支

本仓有三种交付形态（Dockerfile / compose / Helm）与覆盖它们的跨文件门禁
（`scripts/ci/deploy_config_consistency_check.py` 的 R1~R12），但**没有任何一处
把镜像真的构建出来、真的运行起来**：

- `deploy-config` 只做静态一致性比对（读文件、比字段），不执行 `docker build`；
- `e2e-backend-boot` 跑的是**源码直启**（`python start_server.py`），
  不是镜像里的那份运行时；
- Helm/compose 是给运维用的编排定义，本仓 CI 里没有任何一条会去拉起容器。

于是「Dockerfile 真的能构建出可运行的镜像吗」「镜像里的后端真的能起来吗」
这两件事，此前只能靠人手动执行——而人不会每次提交都做。

## 修法：把"真构建 + 真运行 + 真探活"钉成一条**手动触发**的流水线

它不是合并门禁：全量依赖（含 torch 与 CUDA 运行库）下载 + 构建实测约 12 分钟、
镜像层数 GB 量级，放进 `main.push` 就是 Issue #223 消灭的那种"每次提交都付一遍"
的代价。故落在 `main.api_trigger_docker_image`，由 `cnb build start-build` /
页面按钮按需触发。

## 本守卫钉五件事（都可证伪）

- **A 事件在且只在手动口**：`main.api_trigger_docker_image` 存在，且**不在**
  `main.push` 里（那条数组是合并门禁，逐条上报提交状态）。可证伪：把它挪进
  `main.push` → 红。
- **B 构建的是本仓 Dockerfile**：`docker build` 的上下文是本仓根、不加 `-f`
  指向别的 Dockerfile（那份才是三种交付形态里的生产镜像）。可证伪：改成
  `-f 别的文件` → 红。
- **C 真运行 + 真探活，且端口/路径不由流水线手抄**：脚本里的端口与探活路径
  **取 Dockerfile 的 `EXPOSE` 与 `HEALTHCHECK`**（本文件解析后逐字断言）。
  Dockerfile 改端口而流水线没跟着改，是"探活探到别的端口照样绿"的经典形态——
  故这里不许手抄第二份口径。可证伪：改 Dockerfile 的 EXPOSE → 红。
- **D 推送落点是本仓 Docker 制品库，tag 可追溯**：必须用
  `${CNB_DOCKER_REGISTRY}/${CNB_REPO_SLUG_LOWERCASE}` 与 `${CNB_COMMIT_SHORT}`。
  可证伪：把 tag 改成写死的字符串 → 红。
- **E 守卫自己在 CI 上跑**：本文件在 `scripts/ci/protected_tests.txt` 里，
  否则 A~D 在 CI 上无人执行。

## 与既有守卫的边界

`main.push` 的条数与逐条命令由 `tests/unit/test_ci_parity_guard.py` 钉（对齐
GitHub 侧的 9 个 job）；本文件**不碰**那条数组，只钉这条非门禁的手动流水线。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"
DOCKERFILE = PROJECT_ROOT / "Dockerfile"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 手动触发镜像构建的事件名（`.cnb.yml` 的 `main` 下）。
IMAGE_EVENT = "api_trigger_docker_image"

#: 触发镜像构建的入口：CNB Docker 制品库的两段路径与提交短号。
REGISTRY_VAR = "CNB_DOCKER_REGISTRY"
REPO_SLUG_VAR = "CNB_REPO_SLUG_LOWERCASE"
COMMIT_SHORT_VAR = "CNB_COMMIT_SHORT"

#: 探活面：`/health` 是三种交付形态共用的健康检查路径（deploy-config R2 同源），
#: 但**本文件不手抄这个字符串**，而是从 Dockerfile 的 HEALTHCHECK 里解析出来。
HEALTH_PROBE_HOST = "127.0.0.1"


@pytest.fixture(scope="module")
def cnb_doc() -> dict:
    assert CNB.exists(), ".cnb.yml 丢失"
    return yaml.safe_load(io.open(CNB, encoding="utf-8").read())


def _image_jobs(cnb_doc: dict) -> list[dict]:
    """手动镜像构建事件的流水线体（`main.api_trigger_docker_image`）。"""
    body = (cnb_doc.get("main") or {}).get(IMAGE_EVENT)
    if not isinstance(body, list):
        return []
    return [job for job in body if isinstance(job, dict)]


def _image_scripts(cnb_doc: dict) -> str:
    out: list[str] = []
    for job in _image_jobs(cnb_doc):
        for stage in job.get("stages") or []:
            if isinstance(stage, dict) and stage.get("script"):
                out.append(str(stage["script"]))
    return "\n".join(out)


def _dockerfile_expose_port() -> int:
    text = io.open(DOCKERFILE, encoding="utf-8").read()
    ports = [int(p) for p in re.findall(r"^EXPOSE\s+(\d+)", text, re.M)]
    assert ports, (
        "Dockerfile 无 EXPOSE —— 镜像端口的事实源缺失，本判据会静默空转"
    )
    return ports[0]


def _dockerfile_health_probe() -> str:
    """Dockerfile HEALTHCHECK 里的探活 URL（端口 + 路径）。"""
    text = io.open(DOCKERFILE, encoding="utf-8").read()
    match = re.search(r"^HEALTHCHECK\b((?:.*\\\n)*.*)$", text, re.M)
    assert match, "Dockerfile 无 HEALTHCHECK —— 镜像探活契约的事实源缺失"
    url = re.search(r"http://localhost:(\d+)(/[^\s,]+)", match.group(1))
    assert url, (
        "Dockerfile HEALTHCHECK 里解析不到 http://localhost:<port><path> —— "
        "探活路径的事实源缺失（deploy-config R2 也读同一处）"
    )
    return f"{HEALTH_PROBE_HOST}:{url.group(1)}{url.group(2)}"


class TestEventLivesOnTheManualTriggerOnly:
    """A. 真构建很贵，它只能挂在手动口上，不得进合并门禁。"""

    def test_event_exists(self, cnb_doc):
        assert _image_jobs(cnb_doc), (
            f"`.cnb.yml` 的 main 下缺 {IMAGE_EVENT} 事件（或流水线体为空）——"
            "「Dockerfile 真能构建出可运行镜像吗」重新退化为只能靠人手动执行。"
        )

    def test_event_is_not_a_merge_gate(self, cnb_doc):
        """`main.push` 是合并门禁（逐条上报提交状态），镜像构建不得混进去。

        判据：push 数组里不得出现拉起 `docker build` 的流水线。全量依赖下载 +
        构建实测约 12 分钟，挂在每次提交上就是 Issue #223 消灭的那种代价。
        """
        offenders = []
        for index, pipe in enumerate((cnb_doc.get("main") or {}).get("push") or []):
            if not isinstance(pipe, dict):
                continue
            for stage in pipe.get("stages") or []:
                if isinstance(stage, dict) and "docker build" in str(stage.get("script") or ""):
                    offenders.append(f"main.push[{index}]({pipe.get('name')})")
        assert not offenders, (
            "镜像构建被挂进合并门禁（每次提交都要下载数 GB 依赖并构建十几分钟）: "
            + ", ".join(offenders)
            + "\n它应只存在于手动触发口（cnb build start-build / 页面按钮）。"
        )


class TestBuildsTheRepoImage:
    """B. 构建的必须是三种交付形态里的那份生产镜像。"""

    def test_build_uses_repo_dockerfile(self, cnb_doc):
        scripts = _image_scripts(cnb_doc)
        assert "docker build" in scripts, f"{IMAGE_EVENT} 未执行 docker build"
        assert not re.search(r"docker build[^\n]*-f\s", scripts), (
            f"{IMAGE_EVENT} 的 docker build 用 `-f` 指向了别的 Dockerfile —— "
            "compose / Helm 消费的镜像由仓库根的 Dockerfile 定义，构建别的文件等于"
            "验证的是一份没人部署的镜像。"
        )


class TestRunsAndProbesTheRealContainer:
    """C. 镜像要真的跑起来、真的探活，且端口/探活口径**只有 Dockerfile 一份**。"""

    def test_container_is_run_and_probed(self, cnb_doc):
        scripts = _image_scripts(cnb_doc)
        assert "docker run" in scripts, (
            f"{IMAGE_EVENT} 只构建不运行 —— 「能被构建」与「能跑起来」是两件事，"
            "前者不蕴含后者（入口、非 root 用户、运行期配置资产缺失都是构建期看不出的故障）。"
        )
        assert "docker stop" in scripts and "docker rm" in scripts, (
            f"{IMAGE_EVENT} 未回收探活用的容器（残留容器会占住端口，"
            "让下一次构建的探活打到上一具尸体上）"
        )

    def test_probe_contract_is_derived_from_the_dockerfile(self, cnb_doc):
        """端口与探活 URL 必须**在脚本里从 Dockerfile 派生**，不得手抄第二份口径。

        这是本条与"断言脚本里写着 9527"的关键区别：手抄的判据只能证明
        "此刻两边恰好相同"，改 Dockerfile 时它同样绿（探活打到别的端口）。
        故判据钉两件可证伪的事：

        - 派生存在：脚本里出现了对 Dockerfile 的 `EXPOSE` / 探活 URL 的解析；
        - 手抄不存在：Dockerfile 里那个端口字面量**不得**出现在脚本里
          （它一旦出现，就说明有人把这份口径复制了第二遍）。
        """
        scripts = _image_scripts(cnb_doc)
        port = _dockerfile_expose_port()
        assert "EXPOSE" in scripts and "Dockerfile" in scripts, (
            f"{IMAGE_EVENT} 未从 Dockerfile 派生容器端口 —— 端口口径出现了第二份来源。"
        )
        assert "http://localhost:" in scripts, (
            f"{IMAGE_EVENT} 未从 Dockerfile 的 HEALTHCHECK 派生探活 URL"
            "（同一镜像的探活路径必须是同一处事实源，否则两者可以各自漂移）。"
        )
        offenders = re.findall(rf"(?<![0-9]){port}(?![0-9])", scripts)
        assert not offenders, (
            f"{IMAGE_EVENT} 把 Dockerfile 的端口 {port} 手抄进了脚本（{len(offenders)} 处）——"
            "改 Dockerfile 的 EXPOSE 而流水线没跟着改时，探活会打到别的端口上照样报绿。"
            "修法：运行时从 Dockerfile 派生，脚本里不留字面量。"
        )


class TestPushesToTheRepoTargetRegistry:
    """D. 推送到本仓 Docker 制品库，tag 与提交绑定。"""

    def test_push_target_is_the_repo_registry(self, cnb_doc):
        scripts = _image_scripts(cnb_doc)
        assert "docker push" in scripts, f"{IMAGE_EVENT} 未推送镜像（构建产物无法落到制品库）"
        for var in (REGISTRY_VAR, REPO_SLUG_VAR, COMMIT_SHORT_VAR):
            assert f"${{{var}}}" in scripts or f"${var}" in scripts, (
                f"{IMAGE_EVENT} 的推送落点未使用 ${{{var}}} —— "
                "制品库路径与提交短号是平台注入的事实，手抄一份即与真实落点脱钩。"
            )

    def test_services_declares_docker(self, cnb_doc):
        """用 `docker build/push` 就必须声明 docker 服务（否则环境里没有 daemon）。"""
        jobs = _image_jobs(cnb_doc)
        assert jobs, f"`main.{IMAGE_EVENT}` 无流水线体"
        missing = [i for i, job in enumerate(jobs) if "docker" not in (job.get("services") or [])]
        assert not missing, (
            f"`main.{IMAGE_EVENT}` 的流水线未声明 services: [docker]（下标 {missing}）——"
            "平台只在声明该服务时才注入 daemon 与 cli，未声明时 `docker build` 直接 command not found。"
        )


class TestManualButtonPointsAtTheSameEvent:
    """F. 页面上那个手动按钮指向的必须是同一条事件（否则按钮点了没反应）。"""

    def test_web_trigger_button_uses_the_pipeline_event(self):
        button = PROJECT_ROOT / ".cnb" / "web_trigger.yml"
        if not button.exists():
            pytest.skip("本仓未配置页面手动按钮（CLI 触发路径仍可用）")
        text = io.open(button, encoding="utf-8").read()
        assert IMAGE_EVENT in text, (
            f".cnb/web_trigger.yml 的按钮未指向 {IMAGE_EVENT} —— "
            "按钮点下去触发的是别的事件（或什么都不触发），而页面不会报错。"
        )


class TestGuardRunsInCi:
    """E. 本守卫必须在受保护子集里，否则 A~D 在 CI 上无人执行。"""

    def test_listed_in_protected_tests(self):
        listed = io.open(PROTECTED, encoding="utf-8").read()
        rel = "tests/unit/ci/test_docker_image_pipeline_wiring.py"
        assert rel in listed, f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
