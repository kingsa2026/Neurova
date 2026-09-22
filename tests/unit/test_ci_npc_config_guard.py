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
5. **maxTurns 必须声明为字面量整数，且两侧事件同步** —— `maxTurns` 的
   字面量要求同第 2 条（Schema 校验先于变量替换）；上限取 1000，与
   main 上维护者的显式决定保持一致。构建 `cnb-f1c-1k31garu5` 实测 251 轮
   吃满平台 2h 硬上限（7262s，均摊 ≈29s/轮），说明「被掐断」的根因不是
   轮数给多了，而是 Agent 自己 `sleep` 轮询叠加单轮 20 分钟的全量 pytest ——
   故轮数放宽，时间预算改由「禁止 sleep 轮询」的硬禁令守住。
6. **maxTurns 必须自带耗时上界**（`MAX_TURNS_CEILING`）—— 第 5 条曾把
   maxTurns 当「够用就好」的软参数给到 1000，理由是「轮数不是死因」。
   构建 `cnb-m48-1k33grbms` 用实测把它否证了：同样的 2h 平台硬限被再次吃满
   （7300s、207 轮、均摊 35.3s/轮），且是被**外部**掐断——Agent 死在
   一条正常收尾的 pytest 上，没有告警轮、没有收尾。链路是自加速的：
   context 每轮重放（compaction 后仍 ~8MiB 输入、单轮 in≈19 万 token）⇒
   轮耗时由早期的 ~20s 涨到 30s+ ⇒ 2h/35s ≈ 205 轮 ⇒ 1000 的配额**永不触达**。
   配额在硬限之上就等于没有配额：被掐断比配额触发的收尾更糟（无告警、无收尾、
   worktree 里的成果直接丢）。故 maxTurns 必须有上界，且上界由硬限反推：
   本仓 2h 硬限 ⇒ `MAX_TURNS_CEILING = 200`（200 × 35s ≈ 116min，
   留 ~20% 机动；且与实测触发轮数 207 对齐）。
   确要放宽：请先给出「单轮耗时」与「2h ÷ 单轮耗时」的实测读数，
   而不是凭「任务够用」直觉调值。
"""
import io
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
# NPC 挂载点（$ 兜底 / 角色名顶层 key）→ 期望的 thinkingLevel
LEVEL_BY_MOUNT = {"$": "xhigh", "DSCoder-max": "xhigh"}
# 已取消的档位后缀：一旦重新出现在 .cnb.yml 顶层 key 或 settings.yml 角色名里即报错
RETIRED_SUFFIXES = ("-low", "-high")

# npc:go 的 maxTurns 配额（流水线声明值）。
MAX_TURNS_LIMIT = 1000

# maxTurns 的耗时上界：由平台 2h 硬限反推，不是「够用就好」的软参数。
#
# 实测读数（同一平台的两次掐断）：
#   cnb-f1c-1k31garu5：251 轮 / 7262s（均摊 ≈29s/轮）
#   cnb-m48-1k33grbms：207 轮 / 7300s（均摊 35.3s/轮）
# 两者都吃满 2h、都没触达配额。链路：context 每轮重放 ⇒ 单轮耗时随任务推进
# 上涨（30s+）⇒ 2h / 35s ≈ 205 轮。配额在硬限之上 = 没有配额，且被掐断比
# 配额触发的收尾更糟（无告警、无收尾、worktree 成果丢失）。
# 200 × 35s ≈ 116min，留 ~20% 机动，并与实测触发轮数 207 对齐。
MAX_TURNS_CEILING = 200


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
    """maxTurns 是构建耗时的上界，不是「够用就好」的软参数。"""

    def test_max_turns_declared_and_bounded(self, npc_options):
        """每条 npc:go 流水线都必须声明 maxTurns，且不超过本仓上限。"""
        problems = []
        for path, opt in npc_options:
            turns = opt.get("maxTurns")
            if not isinstance(turns, int):
                problems.append(f"{path}: maxTurns={turns!r} 未声明或非整数")
                continue
            if turns > MAX_TURNS_LIMIT:
                problems.append(f"{path}: maxTurns={turns} > 上限 {MAX_TURNS_LIMIT}")
        assert not problems, (
            "npc:go 的 maxTurns 缺失或超出配额:\n  " + "\n  ".join(problems) +
            f"\n配额 {MAX_TURNS_LIMIT} 是上限，不是目标值——真正的耗时上界见 "
            "test_max_turns_leaves_room_under_platform_hard_limit。"
            "确需调低/调高：请同步改守卫、.cnb.yml 注释与 issue/PR 两份事件定义。"
        )

    def test_max_turns_leaves_room_under_platform_hard_limit(self, npc_options):
        """maxTurns 必须落在耗时上界内，配额不得高于平台硬限能容纳的轮数。

        可证伪路径：把 .cnb.yml 的 maxTurns 改回 1000（本仓两次掐断时的值），
        本测试立刻转红 —— 因为 1000 × 35s/轮 ≈ 9.7h 远超平台 2h 硬限，
        配额在硬限之上就等于没有配额：Agent 会被外部掐断（无告警、无收尾）。
        """
        problems = []
        for path, opt in npc_options:
            turns = opt.get("maxTurns")
            if isinstance(turns, int) and turns > MAX_TURNS_CEILING:
                problems.append(f"{path}: maxTurns={turns} > 上界 {MAX_TURNS_CEILING}")
        assert not problems, (
            "npc:go 的 maxTurns 高于平台 2h 硬限能容纳的轮数（配额永不触达）:\n  "
            + "\n  ".join(problems) +
            f"\n上界 {MAX_TURNS_CEILING} 由 2h 硬限反推：实测单轮均摊 35.3s"
            "（cnb-m48-1k33grbms 207 轮 / 7300s），200 × 35s ≈ 116min。"
            "\n为何要上界而不是「够用就好」：构建 cnb-f1c-1k31garu5（251 轮 / 7262s）"
            "与 cnb-m48-1k33grbms（207 轮 / 7300s）两次都在 maxTurns=1000 下被平台"
            "2h 硬限外部掐断。链路是自加速的——context 每轮重放（compaction 后仍"
            "~8MiB 输入、单轮 in≈19 万 token），单轮耗时从早期 ~20s 涨到 30s+，"
            "2h / 35s ≈ 205 轮，配额根本到不了。"
            "\n确需放宽：请附「单轮耗时」与「2h ÷ 单轮耗时」的实测读数，"
            "并同步改 .cnb.yml、本守卫与 issue/PR 两份事件定义。"
        )

    def test_max_turns_is_literal_int(self, npc_options):
        """maxTurns 必须写字面量整数：Schema 校验先于变量替换。"""
        bad = [
            f"{path}: maxTurns={opt['maxTurns']!r}"
            for path, opt in npc_options
            if isinstance(opt.get("maxTurns"), str)
        ]
        assert not bad, (
            "maxTurns 不可用变量/字符串:\n  " + "\n  ".join(bad) +
            "\n原因同 thinkingLevel：options 走平台配置期 Schema 校验，"
            "校验发生在变量替换之前。"
        )


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
        """每个 NPC 挂载点下 issue / PR 两个事件都要声明，且共用同一份流水线。"""
        mounts = {"$": cnb_doc.get("$") or {}}
        for key, value in cnb_doc.items():
            if key in ("main", "include") or key.startswith("."):
                continue
            if isinstance(value, dict) and any(
                k.endswith("@npc") for k in value
            ):
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
