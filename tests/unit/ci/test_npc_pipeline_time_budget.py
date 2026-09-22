# -*- coding: utf-8 -*-
"""NPC 流水线的时间预算守卫。

## 为什么需要这份守卫

NPC 的执行体在 `.cnb.yml`（`.cnb/settings.yml` 只放人设）。两条硬约束：

1. **Job 有墙钟上界**：未声明 `timeout` 时默认 2h，声明后最长 12h；
   整个 Agent 会话只受流水线 20h 上限约束（`npc:go` 的 `timeout` 作用于
   **每一次工具执行**，不是整个会话）。
2. **`maxTurns` 是轮数配额，不是耗时上界** —— Agent 自己调用
   `sleep 300/420/480` 串起等待时，配额没吃满而墙钟先破。

实测（构建 `cnb-f1c-1k31garu5`）：251 轮 / 7262s，均摊 ≈29s/轮，
被平台 2h 上限掐断。若按「轮数上限 = 耗时上界」去压 `maxTurns`，
只是把正常长任务拦腰砍断，等待仍在漏。

## 一次真实事故（构建 `cnb-1q8-1k33cb2v9`，2026-09-22）

Agent 为一项「浏览器级 live」收尾任务反复 `sleep` 轮询构建容器内**根本不存在**的
常驻前后端进程，并在第 340 轮用 `pkill -f start_server.py` 收尾 —— `pkill -f`
按完整命令行子串匹配，把 NPC 自己所在的构建容器一并打掉。Stage status=error，
平台只报「构建环境异常终止，或流水线超过最大运行时长（2h）」，耗时 7261220ms。
整条流水线 **7260s 全部耗在一次零产出的等待上**，构建号失效、Issue 上没有任何回复。

## 这份守卫钉四件事（全部可证伪）

- **A. 预算显式**：`maxTurns` 是字面量整数且落在声明区间；每份 NPC 事件定义的
  Job 显式声明 `timeout`；`npc:go.options` 的键必须在平台 Schema 允许集内
  （写错键会被静默忽略——**配置者以为已生效，实际什么都没发生**）。
- **B. 时间条款落在真正必达的通道**：`npc:go.options` 不认 `prompt` / `systemPrompt`
  这类字段（评论触发时提示词由 `.cnb/settings.yml` 的角色自带），故时间预算条款
  必须写进**每个档位角色**的 `prompt`，并覆盖两类死因（sleep 轮询 / 宽匹配 pkill）。
- **C. 枚举仍在**：角色名不得被悄悄重命名 —— 名字一改，`DSCoder-max` 就失去配置期
  唯一必达通道，只得回落到平台默认 prompt（本仓 90+ 处引用的纪律随之失效），
  而平台不会报错。
- **D. 守卫自洽**：本文件必须留在受保护子集里，否则 A/B/C 三条在 CI 上无人执行。

可证伪路径：

- 把某个档位角色 `prompt` 里的时间条款删掉 → B 红；
- 把 `pkill` 那一条改写掉 → B 红；
- 把任一份 NPC 事件定义的 Job `timeout` 删掉 → A 红；
- 在 `npc:go.options` 里写平台不认的键 → A 红；
- 从 `scripts/ci/protected_tests.txt` 摘掉本文件 → D 红。
"""
import io
import re

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"
SETTINGS = PROJECT_ROOT / ".cnb" / "settings.yml"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
SCHEMA = PROJECT_ROOT / ".cnb" / "npc_schema_keys.txt"

# 本仓的档位角色枚举（2026-09-18 收敛为单档）。
# 这些名字同时出现在：
#   .cnb/settings.yml 的角色定义（人设 + 时间条款的唯一必达通道）
#   .cnb/npc_schema_keys.txt（平台 Schema 允许的 options 键，防止写错键被静默忽略）
#   本文件（枚举事实源，防重命名漂移）
LEVEL_ROLES = ("DSCoder", "DSCoder-max")

# ── 时间预算条款（必须出现在每个档位角色的 prompt 里）──────────────────────
# 条款锚点：整段以它开头，守卫据此定位条款正文。
CLAUSE_ANCHOR = "【时间预算硬约束"
# 条款正文的结束锚点（之后是事故依据与人设各自的收尾，不参与逐字比对）。
CLAUSE_END_ANCHOR = "事故依据（2026-09-22"

# 条款必须覆盖的死因，逐条对应本案的一个动作。
REQUIRED_CLAUSE_TERMS = {
    "sleep": "sleep 轮询（本案把 2h 墙钟烧在等待上）",
    "轮询": "循环等待（同上，换任何写法都不改变语义）",
    "pkill": "宽匹配 pkill（本案把 NPC 自己所在的容器一并打掉）",
    "timeout": "单条命令自带超时（防单步挂死吃满流水线）",
}

# 轮数配额的声明区间：低于 1 无意义，高于上限撑爆墙钟。
MIN_TURNS, MAX_TURNS = 1, 1000

# 与 `.cnb/npc_schema_keys.txt` 的绑定关系由本文件校验（防两份事实源漂移）。
SCHEMA_SENTINEL = "# 平台 Schema：npc:go.options 允许的键"


def _iter_nodes(node, path=""):
    """递归产出 (路径, 节点)，路径用于把违规点定位到配置的具体一行。"""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_nodes(item, f"{path}[{i}]")
        return
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _iter_nodes(value, f"{path}.{key}" if path else str(key))


def _iter_npc_go_stages(node, path=""):
    """递归收集所有 npc:go 任务及其所在 Job。"""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_npc_go_stages(item, f"{path}[{i}]")
        return
    if isinstance(node, dict):
        if node.get("type") == "npc:go":
            yield path, node
        for key, value in node.items():
            yield from _iter_npc_go_stages(value, f"{path}.{key}" if path else str(key))


@pytest.fixture(scope="module")
def cnb_doc():
    assert CNB.exists(), ".cnb.yml 丢失"
    return yaml.safe_load(io.open(CNB, encoding="utf-8").read())


@pytest.fixture(scope="module")
def settings_doc():
    assert SETTINGS.exists(), ".cnb/settings.yml 丢失"
    return yaml.safe_load(io.open(SETTINGS, encoding="utf-8").read())


@pytest.fixture(scope="module")
def level_roles(settings_doc):
    """档位角色名 → prompt 正文。角色名不在枚举内的另有用例拦。"""
    return {
        (role or {}).get("name"): (role or {}).get("prompt")
        for role in ((settings_doc.get("npc") or {}).get("roles") or [])
    }


class TestNpcGoOptionsKeysAreSchemaKnown:
    """`npc:go.options` 的键必须在平台 Schema 允许集内。

    为什么这条必须独立钉：`options` 不在平台的 `additionalProperties: false` 约束下，
    写错的键**不报错、不告警、静默忽略**。配置者以为加了约束，实际什么都没发生 ——
    这类"看着配了、其实没配"是本文件最要防的形态（`prompt` 就曾这么被误用过）。
    """

    def test_allowlist_file_lives_with_the_config(self):
        assert SCHEMA.exists(), (
            f"{SCHEMA.relative_to(PROJECT_ROOT)} 丢失 —— options 键的允许集没了事实源"
        )
        text = io.open(SCHEMA, encoding="utf-8").read()
        assert SCHEMA_SENTINEL in text, (
            f"{SCHEMA.relative_to(PROJECT_ROOT)} 缺来源标记「{SCHEMA_SENTINEL}」"
        )

    def test_unknown_option_keys_are_rejected(self, cnb_doc):
        allowed = {
            line.split("#", 1)[0].strip()
            for line in io.open(SCHEMA, encoding="utf-8").read().splitlines()
            if line.split("#", 1)[0].strip()
        }
        unknown = []
        for path, stage in _iter_npc_go_stages(cnb_doc):
            for key in (stage.get("options") or {}):
                if key not in allowed:
                    unknown.append(f"{path}.options.{key}")
        assert not unknown, (
            "npc:go.options 出现平台 Schema 未声明的键（会被静默忽略，等于没配）：\n  "
            + "\n  ".join(unknown) +
            f"\n允许集见 {SCHEMA.relative_to(PROJECT_ROOT)}；"
            "新增键前先核对 https://docs.cnb.cool/conf-schema-zh.json 的 npc:go 定义。"
        )


class TestBudgetFieldsAreLiterals:
    """预算字段出现时必须是字面量（Schema 校验先于变量替换，$VAR 不展开）。"""

    def test_max_turns_within_declared_range(self, cnb_doc):
        problems = []
        for path, stage in _iter_npc_go_stages(cnb_doc):
            turns = (stage.get("options") or {}).get("maxTurns")
            if not isinstance(turns, int):
                problems.append(f"{path}: maxTurns={turns!r} 未声明或非整数")
            elif not (MIN_TURNS <= turns <= MAX_TURNS):
                problems.append(f"{path}: maxTurns={turns} 不在 [{MIN_TURNS}, {MAX_TURNS}]")
        assert not problems, (
            "npc:go 的轮数配额超出声明区间：\n  " + "\n  ".join(problems) +
            "\n轮数是配额、不是耗时上界：实测 251 轮/7262s 吃满平台上限的根因是"
            "Agent 自己 sleep 轮询，压轮数只会砍断正常长任务。"
        )

    def test_no_variable_in_max_turns(self, cnb_doc):
        bad = [
            f"{path}: maxTurns={value!r}"
            for path, node in _iter_nodes(cnb_doc)
            for value in (node.get("maxTurns"),)
            if isinstance(value, str)
        ]
        assert not bad, (
            "maxTurns 不可用变量/字符串：\n  " + "\n  ".join(bad) +
            "\noptions 走平台配置期 Schema 校验，校验发生在变量替换之前。"
        )


class TestAgentJobDeclaresTimeout:
    """每个 npc:go 所在的 Job 都要显式声明 `timeout`。

    平台依依据（docs.cnb.cool/zh/build/timeout.md、
    /zh/build/internal-steps/npc/go.md）：未声明时「连续 10 分钟无输出」即中断，
    Job 默认最长 2h；声明后无输出阈值与最长执行时间都按该值走。
    声明它让这两个数从平台隐含默认变成仓内可见 —— 事故复盘时
    「到底哪个阈值先破」不必再靠猜。
    """

    def test_every_npc_go_job_declares_timeout(self, cnb_doc):
        missing = [
            path for path, stage in _iter_npc_go_stages(cnb_doc)
            if "timeout" not in stage
        ]
        assert not missing, (
            "以下 npc:go 任务未声明 Job 级 timeout：\n  " + "\n  ".join(missing) +
            "\n未声明时按平台默认（无输出 10 分钟 / 最长 2h）执行，阈值不在仓内可见。"
        )


class TestTimeClauseLivesOnTheReachableChannel:
    """时间预算条款必须写进**每个档位角色**的 prompt。

    可达性依据：`npc:go.options` 没有 `prompt` 这个键（平台 Schema 只认
    role/systemPrompt/userPrompt/model/maxTurns/contextWindow/maxTokens/
    thinkingLevel/supportImage），且评论触发时提示词**一律由角色自带** ——
    写进流水线的 options 既不被识别、也不会生效。唯一必达通道是
    `.cnb/settings.yml` 的 `npc.roles[].prompt`。
    """

    def test_every_level_role_has_the_clause(self, level_roles):
        problems = []
        for role in LEVEL_ROLES:
            prompt = level_roles.get(role)
            if prompt is None:
                problems.append(f"{role}: 角色不存在于 .cnb/settings.yml")
            elif CLAUSE_ANCHOR not in prompt:
                problems.append(f"{role}: prompt 缺「{CLAUSE_ANCHOR}...」条款")
        assert not problems, (
            "档位角色的人设里缺少时间预算条款：\n  " + "\n  ".join(problems) +
            "\n没有该条款时，Agent 会把墙钟预算烧在等待上，"
            "并可能用宽匹配的 pkill 打掉自己所在的构建容器（实测 cnb-1q8-1k33cb2v9）。"
        )

    def test_clause_covers_every_known_failure_mode(self, level_roles):
        problems = []
        for role in LEVEL_ROLES:
            prompt = level_roles.get(role) or ""
            if CLAUSE_ANCHOR not in prompt:
                continue
            clause = prompt.split(CLAUSE_ANCHOR, 1)[1]
            for term, why in REQUIRED_CLAUSE_TERMS.items():
                if term not in clause:
                    problems.append(f"{role}: 条款未覆盖「{term}」（{why}）")
        assert not problems, "\n  ".join(problems)

    def test_clause_body_identical_across_roles(self, level_roles):
        """条款正文本身在各角色间逐字一致：防"某个角色改了措辞、另一个没改"的漂移。

        只比对条款正文（锚点 → 事故依据段结束），不比对各自的人设与身份收尾 ——
        那两段本来就按角色不同。
        """
        bodies = {}
        for role in LEVEL_ROLES:
            prompt = level_roles.get(role) or ""
            if CLAUSE_ANCHOR not in prompt:
                continue
            tail = prompt.split(CLAUSE_ANCHOR, 1)[1]
            bodies[role] = tail.split(CLAUSE_END_ANCHOR, 1)[0]
        assert len(set(bodies.values())) <= 1, (
            "时间预算条款正文在各档位角色间不一致（改一处必须同步另一处）："
            + ", ".join(sorted(bodies))
        )

    def test_clause_is_immediately_before_the_working_style_section(self, level_roles):
        """条款必须紧贴人设的「工作方式」段之前：位置漂移会让后文被挤掉。"""
        problems = []
        for role in LEVEL_ROLES:
            prompt = level_roles.get(role) or ""
            if CLAUSE_ANCHOR not in prompt:
                continue
            after = prompt.split(CLAUSE_ANCHOR, 1)[1]
            if "工作方式" not in after.split(CLAUSE_END_ANCHOR, 1)[-1]:
                problems.append(f"{role}: 条款之后找不到「工作方式」段")
        assert not problems, "\n  ".join(problems)


class TestLevelRoleEnumUnchanged:
    """档位角色名不得被悄悄重命名（改名即失去配置期唯一必达通道）。"""

    def test_settings_declares_every_level_role(self, level_roles):
        missing = [role for role in LEVEL_ROLES if role not in level_roles]
        assert not missing, (
            f".cnb/settings.yml 缺档位角色: {missing}\n"
            "角色名是 NPC 人设与时间条款的配置期唯一入口——改名而不同步流水线挂载点，"
            "被 @ 时会静默回落到平台默认 prompt（本仓的修复教义随之失效），"
            "而平台不会以任何方式报错。"
        )

    def test_every_level_role_has_mount_point(self, cnb_doc):
        problems = []
        for role in LEVEL_ROLES:
            body = cnb_doc.get(role)
            if not isinstance(body, dict):
                problems.append(f"{role}: .cnb.yml 缺同名挂载点")
                continue
            keys = [k for k in body if isinstance(k, str) and k.endswith("@npc")]
            if len(keys) < 2:
                problems.append(f"{role}: 挂载点缺事件（应含 issue 与 pull_request 两类）")
            if body.get("issue.comment@npc") != body.get("pull_request.comment@npc"):
                problems.append(f"{role}: 两条事件定义不一致（会各自漂移）")
        assert not problems, "\n  ".join(problems)

    def test_roles_rendered_identically_across_mounts(self, cnb_doc):
        """角色名挂载点之间必须逐字一致：共用锚点解析出的配置对象应当相等。"""
        bodies = {role: cnb_doc.get(role) for role in LEVEL_ROLES}
        distinct = {role: body for role, body in bodies.items() if body is not None}
        assert len({repr(body) for body in distinct.values()}) <= 1, (
            "档位角色挂载点之间的配置不一致："
            + ", ".join(sorted(distinct)) +
            "\n改一处必须同步另一处（或共用同一份 YAML 锚点）。"
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = io.open(PROTECTED, encoding="utf-8").read()
        rel = "tests/unit/ci/test_npc_pipeline_time_budget.py"
        assert rel in listed, (
            f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
        )
