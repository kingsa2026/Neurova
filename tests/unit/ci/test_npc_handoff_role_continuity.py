# -*- coding: utf-8 -*-
"""NPC 续跑的**角色连续性**守卫（Issue #272）。

## 根因（静态可证，不是推测）

NPC 事件的流水线用的是**NPC 所属仓库**的 `.cnb.yml`（平台「自定义 NPC」篇：
「NPC 事件触发时，系统通过 include 自动合并系统默认配置和 NPC 仓库的 `.cnb.yml`」）。
本仓在 `$` 下把 `issue.comment@npc` / `pull_request.comment@npc` /
`api_trigger_npc_handoff` 三条事件都声明了，故本仓自定义角色的续跑链路成立；
而续跑落点（`api_trigger_npc_handoff`）里的 `npc:go.options.role` 此前写死为
`DSCoder` —— 在 PR #273 把角色改名为 `DSCoder-Red/Green/Yello/Blue` 的那一批里，
它一度**不在册**（名字与名单是两份口径，改名漏改不会有任何红）。

平台对 `role` 的解析规则（平台「npc:go」篇）：`role` 需在 `.cnb/settings.yml` 的
`npc.roles` 中定义；名字未命中时**静默回落**平台默认 prompt —— 不报错、不告警。
于是从第二轮起：

* Agent 丢掉本仓人设与修复教义（90+ 处「AGENTS.md 修复教义第 N 条」的约束全部失效）；
* Agent 丢掉角色准入自证、运行期预算纪律与交接协议的入口约定；
* 而它在日志里的样子与「角色解析成功」完全一样。

Issue #272 的角色改名（`DSCoder` → `DSCoder-Red/Green/Yello/Blue`）正是这条死链的
触发点：`role` 是一个**跨轮硬编码**的角色名，与 `.cnb/settings.yml` 的名单是两份口径，
改一处漏一处不会有任何红（教义第 6 条）。

## 本文件钉三件事（都可证伪）

- **A 角色名必须在册**：`.cnb.yml` 里每一处 `npc:go.options.role` 的**字面量**取值，
  都必须在 `.cnb/settings.yml` 的 `npc.roles[].name` 里；写成 `$变量` 的形态另由 C 判。
  且**载体不得硬编码任何在册名字**（哪怕改回某个当前在册的名字，下一位改名即再断）。
  可证伪：把载体 `role` 改回任一字面量角色名 → 立刻红。
- **B 续跑必须把角色身份带下去**：收尾接力的 `cnb:trigger.options.env` 必须把
  `$CNB_NPC_NAME`（平台注入的当前角色名）传给下一轮，落点再把它喂给
  `npc:go.options.role` —— 否则每一轮都只能硬编码一个角色名，与名单再次分叉。
  可证伪：把 `handoffRole` 从 env 删掉 → 立刻红。
- **C 变量替换有据**：`role` 用 `$handoffRole` 属**平台支持的变量替换**范畴
  （平台「环境变量」篇：内置任务 `options` 支持变量替换；NPC 接续文档 `role: $role`
  是官方示例形态）。且「变量无值替换为空串」是平台的既定行为，故落点必须有
  兜底：`handoffRole` 缺失时退到 `defaultRole`，不得退成空串静默回落平台默认 prompt。

角色名唯一事实源是 `.cnb/settings.yml` 的 `npc.roles`，本文件不抄第二份：
它读同一份配置逐条比对。

## D 名单保留无后缀的 `DSCoder`（五角色口径）

用户口径已改：无后缀 `DSCoder` 与四个后缀角色**并存**（共五个在册角色）。
早期一版判据把 `DSCoder` 钉成「已退役、不得回归」，本文件据此把该前提反转 ——
判据不再针对某个具体名字，而是钉住**形态**（载体只能 `$变量`），
另加一条正向判据钉「`DSCoder` 在册」。两向都可证伪。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"
SETTINGS = PROJECT_ROOT / ".cnb" / "settings.yml"

#: 平台注入的当前角色名（平台「默认环境变量」篇 NPC 类变量）。
NPC_NAME_VAR = "CNB_NPC_NAME"

#: 接力经 env 传给下一轮的载体键（角色身份）。
HANDOFF_ROLE_KEY = "handoffRole"

#: 收尾接力落点事件。
HANDOFF_EVENT = "api_trigger_npc_handoff"

#: 变量引用形态（`$NAME`）；仅接受环境变量名形态，避免把 `$$` / 字面量误判。
VARIABLE_FORM = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")


@pytest.fixture(scope="module")
def cnb_doc():
    return yaml.safe_load(CNB.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def settings_doc():
    return yaml.safe_load(SETTINGS.read_text(encoding="utf-8"))


def _registryRoleNames(settings_doc) -> set:
    """在册角色名（事实源：`.cnb/settings.yml` 的 `npc.roles[].name`）。"""
    roles = ((settings_doc.get("npc") or {}).get("roles") or [])
    return {(role or {}).get("name") for role in roles if (role or {}).get("name")}


def _defaultRoleName(settings_doc):
    return (settings_doc.get("npc") or {}).get("defaultRole")


def _walk(node, path=""):
    """深度遍历，产出 (配置路径, 叶子值)。"""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")
    else:
        yield path, node


def _npcGoRoleReadings(cnb_doc):
    """`.cnb.yml` 里全部 `npc:go.options.role` 的 (路径, 原文取值)。"""
    readings = []
    for path, value in _walk(cnb_doc):
        if path.endswith("/options/role"):
            readings.append((path, value))
    return readings


def _handoffCarrier(cnb_doc):
    """收尾接力落点流水线体。"""
    fallback = cnb_doc.get("$") or {}
    return fallback.get(HANDOFF_EVENT) or []


def _iterNodes(node, path=""):
    """遍历**全部** dict 节点（`_walk` 只给叶子，够不到 options 这类中间节点）。"""
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _iterNodes(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iterNodes(value, f"{path}[{index}]")


def _handoffTriggerEnvs(cnb_doc):
    """收尾接力的 `cnb:trigger.options.env` 列表（三条事件 + 落点自己的收尾）。"""
    envs = []
    for path, node in _iterNodes(cnb_doc):
        if not path.endswith("/options"):
            continue
        if node.get("event") != HANDOFF_EVENT:
            continue
        envs.append((path, node.get("env") or {}))
    return envs


class TestNpcGoRoleMustBeInRegistry:
    """A：任何 `npc:go.options.role` 的字面量都必须在册。

    这条钉的正是「续跑从第二轮起静默回落平台默认 prompt」的根因：
    角色名与名单是两份口径，而平台对未命中的名字**不报错**。
    """

    def test_literal_roles_are_registered(self, cnb_doc, settings_doc):
        names = _registryRoleNames(settings_doc)
        assert names, ".cnb/settings.yml 未声明任何 NPC 角色"
        problems = []
        for path, value in _npcGoRoleReadings(cnb_doc):
            if not isinstance(value, str):
                problems.append(f"{path}: role 不是字符串（{value!r}）")
                continue
            if VARIABLE_FORM.match(value.strip()):
                continue  # 变量形态由 TestNpcRoleContinuityAcrossRounds 判
            if value.strip() not in names:
                problems.append(
                    f"{path}: role={value!r} 不在册（在册：{' / '.join(sorted(names))}）"
                )
        assert not problems, (
            "npc:go.options.role 落到了不在册的角色名——平台会**静默回落**平台默认 prompt，"
            "本轮 Agent 丢掉本仓人设与修复教义，而日志里看不出任何异常：\n  "
            + "\n  ".join(problems)
        )

    def test_carrier_role_is_never_a_bare_retired_literal(self, cnb_doc, settings_doc):
        """载体不得**硬编码**任何角色字面量 —— 身份随轮传递才能免受改名影响。

        与早期「退役名字面量不得回归」的区别：本判据不针对某个具体名字，
        而是钉住**形态**（载体的 role 只能是 `$变量`）。所以无论名单里有哪些角色
        （含无后缀的 DSCoder），硬编码一个名字都是漂移源，一律红。
        """
        names = _registryRoleNames(settings_doc)
        offenders = [
            (path, value) for path, value in _npcGoRoleReadings(cnb_doc)
            if isinstance(value, str) and value.strip() in names
        ]
        assert not offenders, (
            "npc:go.options.role 硬编码了在册角色名（应改用 $变量随轮传递）："
            f"{offenders}\n角色一改名即从第二轮起静默回落平台默认 prompt。"
        )


class TestNpcRoleContinuityAcrossRounds:
    """B + C：续跑必须把角色身份经 env 带下去，且落点有兜底。

    只把 `role` 改成某一个**当前在册**的角色名仍不够：角色名会再改名。
    根治的形态是让身份随轮传递 —— 收尾把 `$CNB_NPC_NAME` 供上，
    落点读它；缺失时退到 `defaultRole`（`$` 变量无值在平台侧替换为空串，
    空 role 同样静默回落，故兜底不可省）。
    """

    def test_handoff_forwards_the_current_role(self, cnb_doc):
        envs = _handoffTriggerEnvs(cnb_doc)
        assert envs, f"找不到任何指向 {HANDOFF_EVENT} 的 cnb:trigger"
        problems = []
        for path, env in envs:
            if HANDOFF_ROLE_KEY not in env:
                problems.append(f"{path}: 接力 env 未把角色身份带下去（缺 {HANDOFF_ROLE_KEY}）")
                continue
            value = str(env[HANDOFF_ROLE_KEY] or "").strip()
            # 三条评论侧事件供上真实角色名；落点自己的收尾供上上一跳传来的同名键。
            allowed = {
                f"${NPC_NAME_VAR}",
                f"${HANDOFF_ROLE_KEY}",
            }
            if VARIABLE_FORM.match(value) and value in allowed:
                continue
            problems.append(
                f"{path}: {HANDOFF_ROLE_KEY}={value!r} 既不是 ${NPC_NAME_VAR} 也不是 "
                f"${HANDOFF_ROLE_KEY}（角色身份只能取自平台注入或上一跳传递）"
            )
        assert not problems, (
            "续跑链未把角色身份带下去——每一轮只能硬编码一个角色名，"
            "角色一改名就从第二轮起静默回落平台默认 prompt：\n  " + "\n  ".join(problems)
        )

    def test_handoff_carrier_reads_the_forwarded_role(self, cnb_doc):
        carrier = _handoffCarrier(cnb_doc)
        assert carrier, f"$ 段缺少接力落点 {HANDOFF_EVENT}"
        roles = [
            stage.get("options", {}).get("role")
            for job in (carrier if isinstance(carrier, list) else [])
            if isinstance(job, dict)
            for stage in (job.get("stages") or [])
            if isinstance(stage, dict) and stage.get("type") == "npc:go"
        ]
        assert roles, f"{HANDOFF_EVENT}: 没有 npc:go"
        problems = []
        for role in roles:
            if not isinstance(role, str) or not VARIABLE_FORM.match(role.strip()):
                problems.append(
                    f"{HANDOFF_EVENT}: npc:go.options.role={role!r} 必须是 $变量形态"
                    f"（读上一跳传下来的 ${HANDOFF_ROLE_KEY}），不得硬编码角色名"
                )
        assert not problems, "\n  ".join(problems)

    def test_role_variable_resolves_from_a_real_source(self, cnb_doc, settings_doc):
        """`$handoffRole` 必须真有来源，且根节点是平台注入的当前角色名。

        平台对**无值变量替换为空串**（环境变量篇：「若 env_name 无值，则替换为空字符串」），
        空 role 同样静默回落平台默认 prompt。平台**没有** `${VAR:-default}` 语法，
        故「兜底」只能落在**供值侧**：三条评论侧事件必须把 `$CNB_NPC_NAME` 供上，
        落点自己的收尾必须把 `$handoffRole` 继续传下去。
        本判据据此断言来源链完整（根 = `CNB_NPC_NAME`），而不是找一个语法上不存在的默认值。
        """
        providers = []
        for path, env in _handoffTriggerEnvs(cnb_doc):
            value = str(env.get(HANDOFF_ROLE_KEY) or "").strip()
            if value == f"${NPC_NAME_VAR}":
                providers.append((path, "platform"))
            elif value == f"${HANDOFF_ROLE_KEY}":
                providers.append((path, "carry"))
        kinds = {kind for _, kind in providers}
        assert "platform" in kinds, (
            f"没有任何接力触发点把平台注入的 ${NPC_NAME_VAR} 供上——"
            f"${HANDOFF_ROLE_KEY} 无根节点，落点读到的会是空串（平台把无值变量换为空串），"
            "角色身份在第二轮就断。"
        )
        assert "carry" in kinds, (
            f"接力落点自己的收尾没有把 ${HANDOFF_ROLE_KEY} 继续传下去——"
            "链条到这一轮就结束，第三轮起角色身份断。"
        )

    def test_registry_default_role_is_in_use_as_the_root(self, cnb_doc, settings_doc):
        """`npc.defaultRole` 必须在册，且根角色名只有一个事实源。

        `defaultRole` 是「未匹配到角色名时」的兜底（平台「NPC 配置」）。
        续跑链路的根取 `CNB_NPC_NAME`（平台按实际被 @ 的角色名注入），
        故 `defaultRole` 只作名单自洽性读数：它不在册时，任何回落到默认角色的
        场景都会拿到一个平台解析不到的名字，同样是静默回落。
        """
        names = _registryRoleNames(settings_doc)
        fallback = _defaultRoleName(settings_doc)
        assert fallback, ".cnb/settings.yml 未声明 npc.defaultRole"
        assert fallback in names, (
            f"npc.defaultRole={fallback!r} 不在册（{sorted(names)}）—— "
            "回落到默认角色的场景会静默回落平台默认 prompt"
        )


class TestRosterKeepsTheBareDSCoderRole:
    """D：名单必须保留无后缀的 `DSCoder`（五角色口径）。

    早期一版判据把无后缀 `DSCoder` 钉成「已退役、不得回归」。用户口径已改：
    `DSCoder` 与四个后缀角色并存，`@kingsa2026/neurova(DSCoder)` 必须仍能召到
    本仓人设。故在此把**正反两面**都钉住：

    * 正向：`DSCoder` 在册（缺了即红）；
    * 反向可证伪：把它从名单摘掉，本判据立刻红。

    名单事实源仍是 `.cnb/settings.yml` 的 `npc.roles`，本判据不抄第二份。
    """

    #: 用户点名要保留的无后缀主角色。
    BARE_ROLE = "DSCoder"

    def test_bare_role_is_registered(self, settings_doc):
        names = _registryRoleNames(settings_doc)
        assert self.BARE_ROLE in names, (
            f"名单里没有无后缀的 {self.BARE_ROLE} —— "
            "用户口径要求它与四个后缀角色并存（共五个在册角色）。"
            f"\n现有：{sorted(names)}"
        )

    def test_bare_role_is_callable_through_admission(self):
        """准入脚本对 `DSCoder` 必须放行（否则被 @ 时静默不住册、白烧 token）。"""
        import os
        import subprocess
        import sys

        script = PROJECT_ROOT / "scripts" / "ci" / "npc_role_admission.py"
        env = {k: v for k, v in os.environ.items() if k != "CNB_NPC_NAME"}
        env.setdefault("CNB_BUILD_WORKSPACE", str(PROJECT_ROOT))
        env["CNB_NPC_NAME"] = self.BARE_ROLE
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env, timeout=60,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr


class TestRosterRestoresTheMaxAliasRole:
    """E：名单必须恢复 `DSCoder-max`（六角色口径）。

    `DSCoder-max` 曾是 `DSCoder` 的同档别名（max 档），在 PR #273 的批量改名里
    与 `GLMCoder` 一起退场。用户口径已定：**恢复**，与无后缀 `DSCoder` 及
    四个后缀角色并存（共六个在册角色），`@kingsa2026/neurova(DSCoder-max)`
    必须仍能召到本仓人设。

    判据两向可证伪：
    * 正向：`DSCoder-max` 在册（缺了即红）；
    * 反向：把它从名单摘掉，本判据立刻红。

    名单事实源仍是 `.cnb/settings.yml` 的 `npc.roles`，本判据不抄第二份；
    共用的运行参数与档位另由 `tests/unit/test_ci_npc_config_guard.py` 咬合。
    """

    #: 用户点名要恢复的同档别名角色。
    RESTORED_ROLE = "DSCoder-max"

    def test_restored_role_is_registered(self, settings_doc):
        names = _registryRoleNames(settings_doc)
        assert self.RESTORED_ROLE in names, (
            f"名单里没有 {self.RESTORED_ROLE} —— "
            "用户口径要求恢复该同档别名角色，与无后缀 DSCoder 及四个后缀角色并存"
            f"（共六个在册角色）。\n现有：{sorted(names)}"
        )

    def test_restored_role_is_callable_through_admission(self):
        """准入脚本对 `DSCoder-max` 必须放行（否则被 @ 时静默不住册、白烧 token）。"""
        import os
        import subprocess
        import sys

        script = PROJECT_ROOT / "scripts" / "ci" / "npc_role_admission.py"
        env = {k: v for k, v in os.environ.items() if k != "CNB_NPC_NAME"}
        env.setdefault("CNB_BUILD_WORKSPACE", str(PROJECT_ROOT))
        env["CNB_NPC_NAME"] = self.RESTORED_ROLE
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env, timeout=60,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_restored_role_is_an_alias_of_the_bare_role(self, settings_doc):
        """同档别名与本尊的运行约束必须逐字一致，不得各自漂移。

        别名与本尊的差异只允许在**卡片字段**（`name` / `slogan`）与身份行上；
        人设正文（含时长纪律、修复教义、接力判据）逐字复用，否则「同档」名不副实。
        判据按**共享正文的指纹**（去掉身份行后逐行比对）咬合。
        """
        roles = {
            (role or {}).get("name"): (role or {})
            for role in ((settings_doc.get("npc") or {}).get("roles") or [])
        }
        bare = roles.get("DSCoder") or {}
        alias = roles.get(self.RESTORED_ROLE) or {}
        assert bare and alias, (
            f"缺少比对对象：DSCoder={bool(bare)} {self.RESTORED_ROLE}={bool(alias)}"
        )

        def sharedBody(prompt: str) -> list:
            """去掉**身份行**后的正文行。

            身份行有两处形态，都随角色名变化：
              * 开头的「你是 `<角色名>` —— …」；
              * 结尾的「身份统一为 `<角色名>`，…」。
            其余正文（核心原则 / 修复教义 / 预算纪律 / 接力判据 / 协作红线）
            必须逐字一致 —— 那才是「同档」的判据。
            """
            return [
                line for line in (prompt or "").splitlines()
                if not line.strip().startswith("你是 ")
                and not line.strip().startswith("身份统一为 ")
            ]

        assert sharedBody(bare.get("prompt")) == sharedBody(alias.get("prompt")), (
            f"{self.RESTORED_ROLE} 与 DSCoder 的共享正文不一致 —— "
            "同档别名只允许卡片字段与身份行不同，正文漂移不会有任何红。"
        )
