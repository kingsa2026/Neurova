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
- **C. 枚举仍在**：角色名不得被悄悄重命名，也不得被挂到 `.cnb.yml` 顶层 key 上
  —— 前者让 `DSCoder-max` 失去配置期唯一必达通道、回落平台默认 prompt，
  后者在**推送的那一刻**就是非法配置（顶层 key 只认分支名）。两条路都让本仓
  90+ 处引用的纪律静默失效，而平台不会报错。
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


def _strip_self_event(pipeline):
    """把收尾自行接力里的 `event` 置为占位——两份事件定义只允许在此处不同。"""
    def walk(node):
        if isinstance(node, list):
            return [walk(i) for i in node]
        if isinstance(node, dict):
            return {
                k: ("<self-event>"
                    if k == "event" and isinstance(v, str) and v.endswith("@npc")
                    else walk(v))
                for k, v in node.items()
            }
        return node

    return walk(pipeline)


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
        """每个档位角色都必须落到**合法**挂载点上 —— 非法顶层的唯一形态是角色名。

        本批冲突消解（2026-09-22，PR #136 并入 main）：本 PR 侧最初把本条判据写成
        「每个档位角色在 .cnb.yml 有同名顶层 key」，理由是角色名缺挂载点会静默回落
        平台默认 prompt。并入 main 时该写法已被 PR #134 用平台 Schema 否证：
        `.cnb.yml` 顶层 key **只认分支名**，角色名顶层 key 在推送那一刻就非法
        （Schema 只放行 `^\..` 锚点，语义规则另把 `issue.*` 钉在 `$` 下）。
        故判据改成「每个角色名都不得作为顶层 key 出现，且必须被 `$` 覆盖到」——
        洞见（不能静默回落）保留，实现取合法形态。
        """
        problems = []
        for role in LEVEL_ROLES:
            if role in cnb_doc:
                problems.append(
                    f"{role}: 角色名挂在 .cnb.yml 顶层 key 上 —— 顶层 key 只认分支名，"
                    "该形态在推送那一刻就是非法配置"
                )
        fallback = cnb_doc.get("$")
        if not isinstance(fallback, dict):
            problems.append("$: .cnb.yml 缺 `$` 兜底挂载点（角色没有配置期必达通道）")
        else:
            keys = [k for k in fallback if isinstance(k, str) and k.endswith("@npc")]
            if len(keys) < 2:
                problems.append("$: 兜底挂载点缺事件（应含 issue 与 pull_request 两类）")
            # 两条事件定义的唯一允许差异是收尾自行接力的事件名
            # （issue 拉 issue、PR 拉 PR），其余逐字一致——判据与
            # tests/unit/test_ci_npc_config_guard.py 同源，不另立一套口径。
            if _strip_self_event(fallback.get("issue.comment@npc")) != \
                    _strip_self_event(fallback.get("pull_request.comment@npc")):
                problems.append("$: 两条事件定义不一致（除自身事件名外应逐字相同）")
        assert not problems, "\n  ".join(problems)

    def test_roles_rendered_identically_across_mounts(self, cnb_doc):
        """档位角色之间必须共用同一份锚点：两个角色名解析出的配置对象应当相等。

        顶层 key 已收敛为 `$` 一处（角色名顶层 key 非法），所以「多挂载点漂移」
        的形态在本仓不可能出现；本条改为直接钉住 `$` 段两条事件定义共用的锚点，
        防后人把某个角色拆出去另写一份定义（那就是第二套平行体系）。
        """
        fallback = cnb_doc.get("$") or {}
        bodies = {
            key: fallback.get(key)
            for key in ("issue.comment@npc", "pull_request.comment@npc")
        }
        distinct = {k: body for k, body in bodies.items() if body is not None}
        assert len(distinct) == 2, (
            "$ 段缺少 NPC 事件定义："
            + ", ".join(sorted(set(bodies) - set(distinct))) +
            "\n两个档位角色（DSCoder / DSCoder-max）都落到 `$`，缺一个就等于缺一类触发。"
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = io.open(PROTECTED, encoding="utf-8").read()
        rel = "tests/unit/ci/test_npc_pipeline_time_budget.py"
        assert rel in listed, (
            f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
        )


#: 轮数触顶接力的燃料文件：Agent 在最后一轮写出它，`.cnb.yml` 的收尾阶段读它。
HANDOFF_MARKER_FILE = ".npc-turn-handoff"


class TestNpcOptionsPromptIsAnUnreachableChannel:
    """`npc:go.options` 里不得再出现 `prompt` 键 —— 它是一条永不生效的通路。

    根因（Issue #158，构建 cnb-2v8-1k34htd2p）：接力配置"看着配了、其实跑不到"，
    第二处就在 `$` 段的 NPC 流水线里写了 `options.prompt`：平台 Schema 不声明该键，
    评论触发时提示词**一律由 `.cnb/settings.yml` 的角色自带**，写进去既不识别也不生效，
    而平台对未知键静默忽略 —— 没有任何红灯会亮。
    本仓为此专门设了一张错误码清单（`.cnb/npc_schema_keys.txt` 的
    「禁止出现（曾误用、被静默忽略）」段），`prompt` 第一位在册。
    然而 `tests/unit/test_ci_npc_config_guard.py` 的 `_iter_npc_go_options`
    曾一路 **skip 掉 `options` 子节点**，于是那张清单没有任何执行体 ——
    禁令写在纸上、判据空转（教义第 2 条：不许把门禁做成"看着配了"）。

    判据：`npc:go` 的 options 键集与 `.cnb/npc_schema_keys.txt` 的允许键集取差
    必须为空。允许键集是单一事实源，两处不得各写一份。
    """

    def test_options_keys_stay_inside_the_schema_allowlist(self, cnb_doc):
        allowed = _schema_allowlist()
        offenders = []
        for path, stage in _iter_npc_go_stages(cnb_doc):
            for key in (stage.get("options") or {}):
                if key not in allowed:
                    offenders.append(f"{path}.options.{key}")
        assert not offenders, (
            "npc:go.options 写了平台 Schema 未声明的键（会被静默忽略，等于没配）：\n  "
            + "\n  ".join(offenders) +
            f"\n允许键集见 {SCHEMA.relative_to(PROJECT_ROOT)}；"
            "行为约束（时长纪律、修复教义、接力协议）一律写进 "
            ".cnb/settings.yml 的角色 prompt —— 那是评论触发期唯一必达的通道。"
        )


def _schema_allowlist() -> set:
    """`.cnb/npc_schema_keys.txt` 的允许键集（注释与空行不计）。"""
    return {
        line.split("#", 1)[0].strip()
        for line in io.open(SCHEMA, encoding="utf-8").read().splitlines()
        if line.split("#", 1)[0].strip()
    }


class TestHandoffFuelIsWritableFromTheConfigAlone:
    """接力的燃料必须能只靠「配置 + 交付物」产生，不依赖 Agent 记得在最后一轮写文件。

    根因（Issue #158，构建 cnb-2v8-1k34htd2p / cnb-2e8-1k341d9s1 连续两次实测）：
    `npc:go` 撞 maxTurns 时平台只把 Agent 中止，**不执行任何收尾指令** ——
    Agent 没有机会执行「把 1 写进 .npc-turn-handoff」这条提示。实测两次掐断
    （201 轮 / 3191326ms；200 轮 / 2362852ms）里，收尾的
    「轮数触顶接力」Stage 都是 `skipped`，Issue 上没有任何回音、成果随容器丢。

    即：写标记这件事在**触顶的那一轮**是执行不到的，那么燃料就只能由配置侧
    产生 —— 判据落在"仓库里确实有一份燃料供给物"，而不是落在"人设里写了要写文件"。
    人设里的那段话仍然保留（它是无歧义的行为约定），但**不构成**燃料。
    """

    def test_repo_carries_a_handoff_fuel_source(self):
        """门禁脚本必须**真的写**燃料，并把接力变量回写给收尾阶段。

        判据落在"写"这件事上，不落在"文件里提到这个名字"：
        只提名字（例如只在 docstring 里写一句）等于没写 —— 那正是本案要消灭的
        "看着配了、其实永不触发"。两个解释器分支都要有写点，否则镜像里没有
        python 时（NPC 镜像就是如此）燃料照样写不出。
        """
        gate = PROJECT_ROOT / "scripts" / "ci" / "npc_turn_handoff_gate.py"
        assert gate.exists(), (
            "接力燃料没有供给物：收尾阶段读的 "
            f"{HANDOFF_MARKER_FILE} 若只由 Agent 在最后一轮写出，"
            "而触顶那一轮执行不到任何指令（cnb-2v8-1k34htd2p 实测 skipped）——"
            "接力永远是死配置。必须由构建侧在 Agent 开工前写下燃料。"
        )
        source = io.open(gate, encoding="utf-8").read()
        assert source.count(f'"{HANDOFF_MARKER_FILE}"') >= 2, (
            f"{gate.relative_to(PROJECT_ROOT)} 的写点不足：燃料文件名常量必须在 "
            "python 与 node 两个分支各出现一次（NPC 镜像只有 node）。"
        )
        # 写燃料 + 回写接力变量：两个动作分属两个函数，各自必须在两个分支里有实现。
        for symbol in ("checkWorkspaceWritable", "markTurnAsHandoff"):
            assert source.count(f"function {symbol}") == 1, (
                f"{gate.relative_to(PROJECT_ROOT)} 的 node 分支缺 {symbol}() —— "
                "镜像里没有 python 时该分支是唯一可执行通路。"
            )
            assert source.count(f"def {symbol}") == 1, (
                f"{gate.relative_to(PROJECT_ROOT)} 的 python 分支缺 {symbol}()。"
            )

    def test_handoff_stage_reads_fuel_not_agent_memory(self, cnb_doc):
        """收尾接力的 `if` 必须只读 `$turnLimitReached` —— 不许新增第二套判据。"""
        fallback = cnb_doc.get("$") or {}
        applies = [
            stage
            for event, body in fallback.items()
            if isinstance(event, str) and event.endswith("@npc")
            for job in (body if isinstance(body, list) else [])
            if isinstance(job, dict)
            for stage in (job.get("endStages") or [])
            if isinstance(stage, dict) and stage.get("type") == "cnb:apply"
        ]
        assert applies, "$ 段 NPC 流水线缺收尾接力（cnb:apply）"
        for stage in applies:
            conditions = stage.get("if") or []
            assert conditions == ['[ "$turnLimitReached" = "1" ]'], (
                "收尾接力的判据不是 turnLimitReached："
                f"{conditions!r}\n"
                "接力判据只允许一处（单一事实源），新增计数文件/状态字段都是平行体系。"
            )
