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


class TestContainerOwnHealthConverges:
    """G. 镜像**自己声明的**探针也必须收敛到 healthy，不只是宿主 curl 到 200。

    ## 为什么这两件事不是同一件（本批实测读数）

    最终形态流水线的第一次 live 跑（构建 cnb-neq-1k3e0m107）逐字给出：

        health_http_code=200                                   ← 宿主 curl 通了
        container_health={"Status":"starting","FailingStreak":1,
                          "Log":[{... "curl: (7) Failed to connect to l..."}]}

    即：宿主的 curl 与容器内 `HEALTHCHECK` 走的是同一处 URL（都由 Dockerfile 派生），
    但**容器自己的探针当时还没收敛**（start-period 30s、interval 30s，
    应用约 40s 才监听）。compose 的 `healthcheck` 与 Helm 的探针走的是容器内的
    这一套语义，所以「宿主通」并不蕴含「部署编排会认为它健康」——
    Dockerfile 的 `start-period` / `interval` 若被改成不够用的值，
    宿主探针照样绿，而容器会被编排判为不健康并反复重启。

    故探活段必须在**有界等待**内确认 `docker inspect .State.Health.Status` 收敛到
    `healthy`，未收敛则打日志并判红（不许只 `|| true` 印一行了事）。
    """

    def test_script_waits_for_the_containers_own_health_status(self, cnb_doc):
        scripts = _image_scripts(cnb_doc)
        assert ".State.Health.Status" in scripts, (
            f"{IMAGE_EVENT} 未读取容器自身的健康状态（.State.Health.Status）——"
            "「宿主 curl 通」与「容器内声明的探针收敛」不是同一件事，"
            "后者才是 compose / Helm 判定健康的依据。"
        )
        assert "healthy" in scripts, (
            f"{IMAGE_EVENT} 未把容器自身健康状态与 healthy 比较 —— "
            "读出来只印一行（`|| true`）等于没有判据。"
        )

    def test_unhealthy_container_fails_the_stage(self, cnb_doc):
        """未收敛到 healthy 时必须判红，且把容器日志带出来。

        判据分三件，各自可证伪（第一版把它们写成"脚本里出现过 healthy 与
        exit 1"，两个词各自出现即可满足——反向控制 A/B 当场把这条判据证伪：

            A 摘掉判定条件里的 `|| [ "$HEALTH" != "healthy" ]` → 不判红
            B 把状态读取换成写死 `HEALTH=healthy`（假收敛）      → 不判红

        故改成：读的是容器运行期真值、比较是**否定式**、且判红与比较同处一段）。
        """
        text = _image_scripts(cnb_doc)
        lines = text.splitlines()

        # 一、状态必须读自容器运行期（反向控制 B：写死一个 healthy 不算读）
        fake = [line.strip() for line in lines if re.match(r'^HEALTH=("?healthy"?)$', line.strip())]
        assert not fake, (
            f"{IMAGE_EVENT} 把容器健康状态写死成 healthy: {fake} —— "
            "那不是读运行期真值，是假收敛（反向控制 B 的形态）。"
        )

        # 二、比较必须是否定式（`!= "healthy"`），且其后 20 行内判红
        judged = [i for i, line in enumerate(lines)
                  if "healthy" in line and "!=" in line]
        assert judged, (
            f"{IMAGE_EVENT} 未把容器健康状态与 healthy 做**否定式**比较 ——"
            "只读出来印一行、或只在循环里做肯定式 break，都等于没有判据。"
        )
        offenders = [i for i in judged
                     if not any("exit 1" in tail for tail in lines[i:i + 20])]
        assert not offenders, (
            f"{IMAGE_EVENT} 比较了容器健康状态却不判红（行号 {offenders}）—— "
            "报错要么被根修，要么以诚实形态暴露（教义第 2 条）。"
        )

        # 三、判红前必须带出容器日志（失败原因可归因）
        assert "docker logs" in text, (
            f"{IMAGE_EVENT} 判红前未打印容器日志 —— 失败原因不可归因。"
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


class TestManualButtonPointsAtAWebTriggerEvent:
    """F. 页面按钮只支持 `web_trigger*` 事件（平台约束），且两条事件只能有一份定义。

    ## 根因（本批自己踩到的形态，2026-09-26）

    第一版把按钮指向 `api_trigger_docker_image` —— 而平台文档（web-trigger.md 的
    Button 定义）逐字写着 `event`「仅支持 web_trigger 自定义事件」。按钮点下去
    不会报任何错，只是什么都不发生，或者以 `CONFIG_EVENT_EMPTY` 收场 ——
    这正是本仓反复出现的形态：**配置写了一个平台不支持的形态，平台不报错，
    只在真被执行时才响亮**。

    故按钮指向的事件必须是 `web_trigger` 或以 `web_trigger_` 开头。

    ## 但 CLI 触发（`cnb build start-build --event`）只认 `api_trigger*`

    两个入口的事件名空间互不通用（平台 `--event` 参数校验「须为 api_trigger 或以
    它开头」；按钮只认 web_trigger）。于是同一条流水线必须被两个事件名覆盖 ——
    而**定义只能有一份**（教义第 6 条）：此处用 YAML 锚点让两个事件名解析到
    同一份对象，判据取 `is`（同一对象）而不是「内容相等」——
    内容相等允许两份各自演化的副本，同一对象不允许。
    """

    #: 按钮入口的事件名。
    BUTTON_EVENT = "web_trigger_docker_image"

    def test_button_targets_a_web_trigger_event(self):
        button = PROJECT_ROOT / ".cnb" / "web_trigger.yml"
        if not button.exists():
            pytest.skip("本仓未配置页面手动按钮（CLI 触发路径仍可用）")
        doc = yaml.safe_load(io.open(button, encoding="utf-8").read())
        buttons = [
            item
            for group in (doc.get("branch") or [])
            for item in ((group or {}).get("buttons") or [])
        ]
        assert buttons, ".cnb/web_trigger.yml 未声明任何按钮 —— 本判据会静默空转"
        offenders = [
            b.get("event") for b in buttons
            if not str(b.get("event") or "").startswith("web_trigger")
        ]
        assert not offenders, (
            f"页面按钮指向了非 web_trigger 事件: {offenders} —— "
            "平台文档（web-trigger.md 的 Button 定义）写明 `event` 仅支持 "
            "web_trigger 自定义事件；写成别的形态时按钮点下去不报错、只是没反应。"
        )

    def test_button_event_is_declared_in_the_config(self, cnb_doc):
        main = cnb_doc.get("main") or {}
        assert main.get(self.BUTTON_EVENT), (
            f"`.cnb.yml` 的 main 下缺 {self.BUTTON_EVENT} —— "
            "按钮指向一个平台上不存在的事件，点下去只会以 CONFIG_EVENT_EMPTY 收场。"
        )

    def test_both_entrypoints_share_one_definition(self, cnb_doc):
        """CLI 口与页面口必须解析到**同一份**流水线对象（不是两份内容相同的副本）。"""
        main = cnb_doc.get("main") or {}
        cli_body = main.get(IMAGE_EVENT)
        button_body = main.get(self.BUTTON_EVENT)
        assert cli_body and button_body, (
            f"两个入口的事件未同时声明（{IMAGE_EVENT} / {self.BUTTON_EVENT}）——"
            "CLI 触发与页面按钮各有其一，缺一个就等于该入口静默失效。"
        )
        assert cli_body is button_body, (
            f"`{IMAGE_EVENT}` 与 `{self.BUTTON_EVENT}` 解析出的不是同一份对象 ——"
            "两条定义会各自演化（同一个事实的第二份手抄，教义第 6 条）。"
            "修法：用 YAML 锚点让第二个事件名引用第一处定义。"
        )


class TestGuardRunsInCi:
    """E. 本守卫必须在受保护子集里，否则 A~D 在 CI 上无人执行。"""

    def test_listed_in_protected_tests(self):
        listed = io.open(PROTECTED, encoding="utf-8").read()
        rel = "tests/unit/ci/test_docker_image_pipeline_wiring.py"
        assert rel in listed, f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
