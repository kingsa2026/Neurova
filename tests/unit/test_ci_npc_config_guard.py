# -*- coding: utf-8 -*-
"""NPC 配置守卫（.cnb.yml / .cnb/settings.yml）。

锁定四件已实锤踩过的事故，防同源复发：

1. **model 不得带思考强度后缀** —— `deepseek-v4.1-flash-{low,high,max}` 是
   "同一底座模型 + 不同思考强度"的变体名，合法 model ID 只有
   `deepseek-v4.1-flash`。把带后缀的名字传给 `npc:go.options.model`，
   平台网关会以 `400 (no body)` 拒收，且失败发生在真正发请求时
   （配置期不报错、流水线能启动）——表现为"配置都对却秒杀"。
2. **thinkingLevel 必须是字面量枚举值** —— `npc:go.options` 走平台
   配置阶段的 Schema 校验，而校验发生在变量替换之前，写成 `$VAR`
   会以"值不在枚举内"配置期直接红（本仓实测 100 条 Schema 报错）。
3. **档位角色与流水线一一对齐** —— 每个声明的档位角色名（含同档别名
   DSCoder-max，以及 `$` 兜底挂载点）必须在 `.cnb.yml` 有对应 NPC 事件
   流水线，且其 thinkingLevel 与本仓档位表一致；否则角色被 @ 时静默回落
   平台默认档，用户以为切了档、其实没切。
4. **档位收敛不倒退** —— 本仓只保留 max 一档。`-low` / `-high` 两档与
   非 max 的 thinkingLevel 若重新出现（顶层 key、settings.yml 角色、
   或流水线里的档位值），守卫直接拦下：要么是有意恢复分档（需同步改
   档位表与本文档），要么是回归，两者都必须显式改测而非悄悄放过。
5. **maxTurns 只准在自己的分支上改** —— 该参数走平台配置期 Schema 校验
   （字面量要求同第 2 条），且 Agent 分支常把 `maxTurns` 当"耗时上限"反复
   收紧（`500 → 120 → 1000` 来回改）。这类分支若被归档而不清理，**每次**产生
   分支名的流水线都会以同一个 `invalid configuration` 收场：配置在推送分支的
   那一刻就已经非法，与轮数取值、任务内容都无关。
   本守卫把这条前置条件钉成红/绿：合法取值域是
   `[MIN_TURNS, maxTurnsCeiling(cnb_doc)]`，上限由 `$` 兜底挂载点的现行取值得出
   （上限自身被钳在 `MAIN_TURNS_FLOOR`，无法把"非法值合法化"），
   取值形态按 `TURNS_SHAPE` 白名单。
   历史：`cnb-f1c-1k31garu5` 实测 251 轮吃满平台 2h 硬上限（7262s，均摊 ≈29s/轮），
   但那次的死因是 Agent 自己 `sleep` 轮询叠加单轮 20 分钟的全量 pytest，不是轮数配额 ——
   轮数与耗时上限的换算关系无法从本仓证据推出，故不再在守卫里断言某个具体数字。
"""
import io
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CNB = PROJECT_ROOT / ".cnb.yml"
SETTINGS = PROJECT_ROOT / ".cnb" / "settings.yml"

# 平台 Schema 的 thinkingLevel 枚举（docs.cnb.cool conf-schema-zh.json）
THINKING_LEVELS = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}

# 已知的思考强度后缀变体名（不是合法 model ID）
SUFFIX_VARIANTS = ("-low", "-high", "-max")

# 本仓只保留 max 一档（2026-09-18 收敛）：
# 档位角色名 → 期望的 thinkingLevel
LEVEL_BY_ROLE = {"DSCoder-max": "xhigh"}
# NPC **挂载点**（.cnb.yml 顶层 key）→ 期望的 thinkingLevel。
#
# `$` 是唯一允许的挂载点：.cnb.yml 的顶层 key 在平台 Schema 里只认分支名
# （未知 key 只有 `^\..` 锚点形态被放行），`DSCoder-max` 这类角色名顶层 key
# 会同时过不了 Schema 与「仓库级事件只能在 $ 下」的语义规则。
# 别名角色（DSCoder-max）因此只保留在 settings.yml 侧，运行参数复用 `$` 的定义——
# 见 `LEVEL_BY_ROLE`，若将来别名需要不同参数，正确做法是拆出**分支**而不是再造顶层 key。
LEVEL_BY_MOUNT = {"$": "xhigh"}
# 已取消的档位后缀：一旦重新出现在 .cnb.yml 顶层 key 或 settings.yml 角色名里即报错
RETIRED_SUFFIXES = ("-low", "-high")

#: maxTurns 的合法取值形态（正整数，可带 `k` 千位后缀）。
#: 形态白名单与"上限是多少"无关——上限属功能决策（由 `$` 挂载点现值给出），
#: 这里只钉"写出来必须是个能过 Schema 的轮数值"。
TURNS_SHAPE = re.compile(r"^[1-9][0-9]*[kK]?$")

#: 轮数下限（写入侧合理性）。平台没有公开的轮数下限；此值只挡住
#: `0` / `1` 这类明显会让 Agent 一轮都跑不完的写法，与耗时上界无关。
MIN_TURNS = 10

#: 无法从 `$` 现值推出上限时（该挂载点缺失或写成非法值）的兜底下界：
#: 10k 轮在 29s/轮 的实测口径下 ≈ 80h，远高于平台 2h 硬上限，
#: 任何"真实需要更多轮"的分支都够用——不会把正常分支误判为超上限。
MAIN_TURNS_FLOOR = 10_000


def parseTurnBudget(value):
    """把 `maxTurns` 的现行取值（含 `1k` 写法）解析成整数；非法返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        raw = value.strip()
        if not TURNS_SHAPE.match(raw):
            return None
        return int(raw[:-1]) * 1000 if raw[-1] in "kK" else int(raw)
    return None


def maxTurnsCeiling(cnb_doc) -> int:
    """合法上限 = `$` 兜底挂载点的现行取值（钳在 `MAIN_TURNS_FLOOR` 之上）。

    上限必须从流水线自己的现行配置推出，不能写成常量：

    - 常量上限会把「合法上界」钉在某个具体数字上，分支只要调高轮数、
      `main` 又来不及同步，守卫就红——而它其实拦不住真正的配置非法（Schema 才拦）；
    - 由 `$` 现值给出，则「调高上限」= 先在主线上显式调高 `$` 段（一次可见的、
      会被 review 的配置改动），分支再跟随。上限永远不会低于主线现行值，
      所以"分支跟着主线调高"是绿的，"分支私自定义上限"是红的。
    """
    main_options = [
        opt
        for path, opt in _iter_npc_go_options({"$": (cnb_doc or {}).get("$") or {}})
        if "issue.comment@npc" in path or "pull_request.comment@npc" in path
    ]
    parsed = [parseTurnBudget(opt.get("maxTurns")) for opt in main_options]
    parsed = [v for v in parsed if isinstance(v, int)]
    if not parsed:
        return MAIN_TURNS_FLOOR
    return max(min(parsed), MAIN_TURNS_FLOOR)


def _load(path: Path):
    return yaml.safe_load(io.open(path, encoding="utf-8").read())


def _iter_npc_go_options(node, path=""):
    """递归收集所有 npc:go 任务的 options 及其路径。"""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_npc_go_options(item, f"{path}[{i}]")
        return
    if isinstance(node, dict):
        if node.get("type") == "npc:go" and isinstance(node.get("options"), dict):
            yield path, node["options"]
        for k, v in node.items():
            if k == "options":
                continue
            yield from _iter_npc_go_options(v, f"{path}.{k}" if path else str(k))


@pytest.fixture(scope="module")
def cnb_doc():
    assert CNB.exists(), ".cnb.yml 丢失"
    return _load(CNB)


@pytest.fixture(scope="module")
def settings_doc():
    assert SETTINGS.exists(), ".cnb/settings.yml 丢失——NPC 角色定义未入库"
    return _load(SETTINGS)


@pytest.fixture(scope="module")
def npc_options(cnb_doc):
    opts = list(_iter_npc_go_options(cnb_doc))
    assert opts, ".cnb.yml 未找到任何 npc:go 任务"
    return opts


class TestModelIdHygiene:
    def test_no_thinking_suffix_in_model(self, npc_options):
        """model 不得是带思考强度后缀的变体名（400 事故的根因形态）。"""
        bad = []
        for path, opt in npc_options:
            model = opt.get("model")
            if isinstance(model, str) and model.endswith(SUFFIX_VARIANTS):
                bad.append(f"{path}: model={model}")
        assert not bad, (
            "npc:go 的 model 写成带思考强度后缀的变体名:\n  " + "\n  ".join(bad) +
            "\n这些名字不是合法 model ID，平台会以 400 拒收；"
            "请只传底座 ID（不带后缀），思考强度改由 thinkingLevel 表达。"
        )

    def test_model_is_platform_known_id_or_absent(self, npc_options):
        """model 只能留空或写底座 ID（本仓已确认可用的白名单）。"""
        allowed = {"deepseek-v4.1-flash", "deepseek-v4-flash"}
        bad = []
        for path, opt in npc_options:
            model = opt.get("model")
            if model in (None, ""):
                continue
            if not isinstance(model, str) or model not in allowed:
                bad.append(f"{path}: model={model!r}")
        assert not bad, (
            "npc:go 的 model 不是本仓已知可用的底座 ID:\n  " + "\n  ".join(bad) +
            f"\n当前白名单: {sorted(allowed)}。"
            "要启用新模型：确认平台真实可用后同时更新白名单与配置，"
            "别只改一侧（上一轮 400 就是这么来的）。"
        )


class TestThinkingLevelLiteral:
    def test_thinking_level_is_literal_enum(self, npc_options):
        """thinkingLevel 必须写字面量枚举值：Schema 校验先于变量替换。"""
        bad = []
        for path, opt in npc_options:
            value = opt.get("thinkingLevel")
            if value is None:
                continue
            if not isinstance(value, str) or value not in THINKING_LEVELS:
                bad.append(f"{path}: thinkingLevel={value!r}")
        assert not bad, (
            "thinkingLevel 必须是字面量枚举值（$变量会在配置期被 Schema 拒掉）:\n  "
            + "\n  ".join(bad) +
            f"\n允许值: {sorted(THINKING_LEVELS)}"
        )

    def test_no_variable_in_thinking_level(self, npc_options):
        """显式拦住 $VAR 写法，附带说明原因（防后人"顺手 DRY"改回去）。"""
        bad = [
            f"{path}: thinkingLevel={opt['thinkingLevel']}"
            for path, opt in npc_options
            if isinstance(opt.get("thinkingLevel"), str)
            and opt["thinkingLevel"].startswith("$")
        ]
        assert not bad, (
            "thinkingLevel 不可用变量引用:\n  " + "\n  ".join(bad) +
            "\n原因：npc:go.options 的 Schema 校验发生在变量替换之前，"
            "枚举字段写 $VAR 会以「值不在枚举内」在配置期直接红。"
        )


class TestTurnBudget:
    """maxTurns 的合法性：取值必须能过平台配置期 Schema。

    参数化的合法取值域由 `.cnb.yml` 自身推出（见 `maxTurnsCeiling`），
    不写死某个具体数字——写死会把「轮数该给多少」这个功能决策伪装成守卫契约，
    而它拦不住的恰恰是真正的配置非法（那由平台 Schema 拦）。
    """

    def test_max_turns_declared_and_shaped(self, npc_options, cnb_doc):
        """每条 npc:go 流水线都必须声明正整数形态的 maxTurns，且不超现行上限。"""
        ceiling = maxTurnsCeiling(cnb_doc)
        problems = []
        for path, opt in npc_options:
            turns = opt.get("maxTurns")
            if turns is None:
                problems.append(f"{path}: 未声明 maxTurns")
                continue
            parsed = parseTurnBudget(turns)
            if parsed is None:
                problems.append(
                    f"{path}: maxTurns={turns!r} 不是合法轮数值"
                    f"（形态要求 {TURNS_SHAPE.pattern}，拒收变量/浮点/布尔）"
                )
                continue
            if parsed < MIN_TURNS:
                problems.append(f"{path}: maxTurns={parsed} < 下限 {MIN_TURNS}")
            if parsed > ceiling:
                problems.append(f"{path}: maxTurns={parsed} > 现行上限 {ceiling}")
        assert not problems, (
            "npc:go 的 maxTurns 缺失或取值非法（该类配置**在推送分支的那一刻**就非法，"
            "每次产生分支名的构建都会以 invalid configuration 收场，与任务内容无关）:\n  "
            + "\n  ".join(problems) +
            f"\n现行合法域: [{MIN_TURNS}, {ceiling}]（上限 = `$` 兜底挂载点现值，"
            f"低于 {MAIN_TURNS_FLOOR} 时按兜底下限计）。\n"
            "确需调高上限：先在主线显式调高 `$` 段，再让分支跟随——"
            "上限永远不低于主线现值，故「跟随主线」是绿的、「私自定义上限」是红的。"
        )

    def test_max_turns_is_literal_int(self, npc_options):
        """maxTurns 必须写字面量整数：Schema 校验先于变量替换。"""
        bad = [
            f"{path}: maxTurns={opt['maxTurns']!r}"
            for path, opt in npc_options
            if isinstance(opt.get("maxTurns"), str)
            and not TURNS_SHAPE.match(opt["maxTurns"].strip())
        ]
        assert not bad, (
            "maxTurns 不可用变量/字符串:\n  " + "\n  ".join(bad) +
            "\n原因同 thinkingLevel：options 走平台配置期 Schema 校验，"
            "校验发生在变量替换之前。"
        )

    def test_ceiling_cannot_be_laundered_by_illegal_main_value(self):
        """`$` 写成非法值时，上限不得被"洗白"成那个非法值。"""
        assert maxTurnsCeiling({"$": {}}) == MAIN_TURNS_FLOOR
        assert maxTurnsCeiling({"$": {"issue.comment@npc": [
            {"type": "npc:go", "options": {"maxTurns": "many"}}
        ]}}) == MAIN_TURNS_FLOOR
        assert maxTurnsCeiling({"$": {"issue.comment@npc": [
            {"type": "npc:go", "options": {"maxTurns": 10}}
        ]}}) == MAIN_TURNS_FLOOR
        assert maxTurnsCeiling({"$": {"issue.comment@npc": [
            {"type": "npc:go", "options": {"maxTurns": 12000}}
        ]}}) == 12000


class TestTurnBudgetParsing:
    """取值解析：形态与数值的边界（守卫要用它判"是不是能过 Schema 的轮数"）。"""

    def test_parses_plain_and_suffix_forms(self):
        assert parseTurnBudget(1000) == 1000
        assert parseTurnBudget("1000") == 1000
        assert parseTurnBudget("2k") == 2000
        assert parseTurnBudget("2K") == 2000

    def test_rejects_non_numeric_and_variable_forms(self):
        for bad in (None, "", "$TURNS", "1.5", "0", "-5", 0, -5, True, 1.0, [], {}):
            assert parseTurnBudget(bad) is None, bad


class TestRolePipelineAlignment:
    def test_mount_points_have_pipeline_at_expected_level(self, cnb_doc):
        """每个 NPC 挂载点都要有两个事件，且档位与本仓库位表一致。"""
        problems = []
        for mount, expected in sorted(LEVEL_BY_MOUNT.items()):
            body = cnb_doc.get(mount)
            if not isinstance(body, dict):
                problems.append(f"{mount}: .cnb.yml 缺该挂载点（应为事件映射）")
                continue
            for event_key in ("issue.comment@npc", "pull_request.comment@npc"):
                if event_key not in body:
                    problems.append(f"{mount} 缺事件 {event_key}")
                    continue
                levels = {
                    opt.get("thinkingLevel")
                    for _, opt in _iter_npc_go_options({event_key: body[event_key]})
                }
                if levels != {expected}:
                    problems.append(
                        f"{mount}.{event_key}: thinkingLevel={sorted(levels)} 期望 {expected!r}"
                    )
        assert not problems, (
            "NPC 挂载点档位与档位表不一致（被 @ 时会静默回落默认档）:\n  "
            + "\n  ".join(problems)
        )

    def test_no_role_named_top_level_keys(self, cnb_doc, settings_doc):
        """顶层 key 只准是分支名 / `crontab:` / `.` 锚点——角色名挂顶层 key 是非法配置。

        这类 key 会在**推送的那一刻**就非法（Schema 的顶层 key 只认分支名 +
        `^\..` 锚点；平台语义规则另把 `issue.*` 钉在 `$` 下），而不是等到跑任务才失败。
        本仓曾用 `DSCoder-max:` 顶层 key 挂同档别名——别名与主角色运行参数本就没有差异，
        第二份 key 是纯多余面，且是过不了 Schema 的那一份。
        """
        role_names = {
            (r or {}).get("name")
            for r in ((settings_doc.get("npc") or {}).get("roles") or [])
        }
        bad = sorted(
            k for k in cnb_doc
            if isinstance(k, str)
            and k not in ("main", "include")
            and not k.startswith(".")
            and not k.startswith("crontab:")
            and k in role_names
        )
        assert not bad, (
            f".cnb.yml 把 NPC 角色名当作顶层 key 挂载: {bad}\n"
            "平台 Schema 的顶层 key 只认分支名（未知 key 仅 `^\\.` 锚点形态放行），"
            "角色名 key 会以 invalid configuration 收场。别名角色请留在 settings.yml 侧，"
            "运行参数复用 `$` 兜底挂载点的定义。"
        )

    def test_no_retired_level_roles_in_settings(self, settings_doc):
        """已取消的 -low / -high 档位角色不得重新出现（收敛不倒退）。"""
        roles = [
            (r or {}).get("name")
            for r in ((settings_doc.get("npc") or {}).get("roles") or [])
        ]
        bad = sorted(
            r for r in roles
            if isinstance(r, str) and r.endswith(RETIRED_SUFFIXES)
        )
        assert not bad, (
            f".cnb/settings.yml 出现了已取消的档位角色: {bad}\n"
            "本仓只保留 max 一档（DSCoder / DSCoder-max）。"
            "若确要恢复分档，请同步更新守卫的 LEVEL_BY_ROLE / LEVEL_BY_MOUNT 与文档说明。"
        )

    def test_settings_level_roles_match_declared_table(self, settings_doc):
        """带档位后缀的角色名必须在本仓档位表内（防新增角色漏挂顶层 key）。"""
        roles = [
            (r or {}).get("name")
            for r in ((settings_doc.get("npc") or {}).get("roles") or [])
        ]
        level_roles = {
            r for r in roles
            if isinstance(r, str) and r.endswith(SUFFIX_VARIANTS)
        }
        unknown = sorted(level_roles - set(LEVEL_BY_ROLE))
        assert not unknown, (
            f"档位角色未在守卫档位表登记: {unknown}\n"
            "新增档位需同时改 .cnb.yml 挂载点、settings.yml 角色与守卫档位表。"
        )

    def test_no_retired_level_mounts_in_cnb(self, cnb_doc):
        """已取消的档位挂载点不得重新出现在 .cnb.yml 顶层 key。"""
        bad = sorted(
            k for k in cnb_doc
            if isinstance(k, str) and k.endswith(RETIRED_SUFFIXES)
        )
        assert not bad, f".cnb.yml 出现已取消的档位挂载点: {bad}（本仓只保留 max 档）"

    def test_npc_events_declared_and_aliased(self, cnb_doc):
        """每个 NPC 挂载点下 issue / PR 两个事件都要声明，且共用同一份流水线。

        挂载点集合 = `$`（兜底，唯一允许的角色挂载点）+ `LEVEL_BY_MOUNT` 登记项；
        不再从"哪些顶层 key 长得像事件映射"反推——那会把非法形态当成合法挂载点收进来。
        """
        mounts = {"$": cnb_doc.get("$") or {}}
        for key in LEVEL_BY_MOUNT:
            if key == "$":
                continue
            value = cnb_doc.get(key)
            if isinstance(value, dict):
                mounts[key] = value

        problems = []
        for mount, body in mounts.items():
            for key in ("issue.comment@npc", "pull_request.comment@npc"):
                if key not in body:
                    problems.append(
                        f"{mount} 缺 {key}——NPC 配置按事件独立合并，漏配会走默认行为"
                    )
            if body.get("issue.comment@npc") != body.get("pull_request.comment@npc"):
                problems.append(f"{mount} 下 issue 与 PR 事件定义不一致（两侧会各自漂移）")
        assert not problems, "\n  ".join(problems)


class TestSettingsRoleHygiene:
    def test_every_role_enable_thinking(self, settings_doc):
        """角色若声明 enableThinking，应为真值（思考档位才有意义）。"""
        roles = (settings_doc.get("npc") or {}).get("roles") or []
        bad = [
            r.get("name") for r in roles
            if "enableThinking" in r and not r["enableThinking"]
        ]
        assert not bad, (
            f"角色 enableThinking 为假却依赖 thinkingLevel 切档: {bad}\n"
            "enableThinking=false 时思考档位不生效，档位角色形同虚设。"
        )

    def test_role_names_unique(self, settings_doc):
        names = [r.get("name") for r in (settings_doc.get("npc") or {}).get("roles") or []]
        dupes = sorted({n for n in names if names.count(n) > 1})
        assert not dupes, f"角色名重复: {dupes}"
