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

# npc:go 的 maxTurns 上限。
# 依据：维护者在 main（commit「修改超时限制」）把 $ 段显式调到 1000，
# 即「轮数配额按任务够用来给，不压到 120」。构建 cnb-f1c-1k31garu5 实测
# 251 轮 / 7262s（平台 2h 硬上限被吃满，均摊 ≈29s/轮）证明轮数不是死因，
# 死因是 Agent 自己 sleep 轮询 + 单轮 20 分钟的全量 pytest。
# 故上限放回 1000，真正的硬禁令改由「禁止 sleep 轮询」承担。
MAX_TURNS_LIMIT = 1000


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
            "npc:go 的 maxTurns 缺失或超出耗时上界:\n  " + "\n  ".join(problems) +
            f"\n上限 {MAX_TURNS_LIMIT} 为维护者在 main 上的显式决定（「修改超时限制」）。"
            "构建 cnb-f1c-1k31garu5 实测 251 轮吃满平台 2h 硬上限（均摊 ≈29s/轮），"
            "根因是 sleep 轮询 + 单轮 20 分钟的全量 pytest，不是轮数配额；"
            "确需调低/调高：请同步改守卫、.cnb.yml 注释与 issue/PR 两份事件定义。"
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
            issue_body = body.get("issue.comment@npc")
            pr_body = body.get("pull_request.comment@npc")
            if issue_body is None or pr_body is None:
                continue
            # 事件名必须不同（接力时要各拉各的事件），其余逐字一致
            # —— 唯一的差异点由下面这条断言钉死，不是"允许漂移"。
            if _strip_self_event(issue_body) != _strip_self_event(pr_body):
                problems.append(
                    f"{mount} 下 issue 与 PR 事件定义不一致（除自身事件名外应逐字相同）"
                )
            elif _self_apply_events(issue_body) != {"issue.comment@npc"} or \
                    _self_apply_events(pr_body) != {"pull_request.comment@npc"}:
                problems.append(
                    f"{mount} 下 issue / PR 的收尾自行接力事件名错位"
                    "（PR 事件拉到 issue 流水线会跑错上下文）"
                )
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


def _strip_self_event(pipeline):
    """把收尾自行接力里的 `event` 置为占位——两份事件定义只允许在此处不同。"""
    def walk(node):
        if isinstance(node, list):
            return [walk(i) for i in node]
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "event" and isinstance(v, str) and v.endswith("@npc"):
                    out[k] = "<self-event>"
                else:
                    out[k] = walk(v)
            return out
        return node

    return walk(pipeline)


def _self_apply_events(pipeline):
    """收集流水线里所有 cnb:apply 声明的事件名（接力判据）。"""
    found = set()

    def walk(node):
        if isinstance(node, list):
            for i in node:
                walk(i)
            return
        if isinstance(node, dict):
            if node.get("type") == "cnb:apply":
                event = (node.get("options") or {}).get("event")
                if isinstance(event, str):
                    found.add(event)
            for v in node.values():
                walk(v)

    walk(pipeline)
    return found


class TestTurnHandoffCeiling:
    """轮数触顶后的接力：NPC 事件流水线必须在收尾把剩余工作交给下一次构建。

    根因（构建 cnb-m48-1k33grbms 实测）：`maxTurns` 撞顶时 `npc:go` 只是把
    Agent 中止，当前流水线随即结束——**没有消费者读这个中止事件**，worktree 里
    已改未提交的成果随容器一起丢，用户必须自己发现并手动催下一轮。
    平台没有「Agent 用满轮数后自动重跑同一条流水线」的原生开关
    （`retry` / `allowFailure` / `endStages` 都只管当前这条流水线，不产生新的
    轮次预算），所以接力必须在配置里显式写出来：收尾阶段用 `cnb:apply`
    再拉一次同一事件，`turnLimitReached` 标记把「接力轮」与用户新发的
    `@` 区分开，防止同一条评论被无限重跑。

    判据落在**是否有这笔接力**，不落在 `$变量` 替换后的形态上：
    `api_trigger_pipeline` 的 options 在配置期做 Schema 校验，事件名写成
    `$VAR` 会被平台拒掉；且 `type: cnb:apply` 的 `env` 值只接受 `$变量`
    （见 tests/unit/test_ci_thin_env_guards.py 同型的薄环境事故）。
    """

    #: 判定「这一轮是轮数触顶的接力轮」的标记名（run 计数器的唯一事实源）
    HANDOFF_FLAG = "turnLimitReached"

    @staticmethod
    def _npc_pipelines(cnb_doc):
        """collect: (挂载点, 事件名, 流水线体) —— 只取含 npc:go 的流水线。"""
        for mount, body in cnb_doc.items():
            if not isinstance(body, dict):
                continue
            for event, event_body in body.items():
                if not event.endswith("@npc"):
                    continue
                for i, job in enumerate(event_body if isinstance(event_body, list) else []):
                    if not isinstance(job, dict):
                        continue
                    has_npc = any(
                        stage.get("type") == "npc:go"
                        for stage in (job.get("stages") or [])
                        if isinstance(stage, dict)
                    )
                    if has_npc:
                        yield f"{mount}.{event}[{i}]", event, job

    def test_npc_pipeline_carries_turn_handoff(self, cnb_doc):
        """每条 npc:go 流水线都要有收尾接力（apply 同事件 + 轮次上限标记）。"""
        problems = []
        seen = 0
        for where, event, job in self._npc_pipelines(cnb_doc):
            seen += 1
            end_stages = [s for s in (job.get("endStages") or []) if isinstance(s, dict)]
            applies = [s for s in end_stages if s.get("type") == "cnb:apply"]
            if not applies:
                problems.append(f"{where}: endStages 无 cnb:apply，轮数触顶后无人接力")
                continue
            if not any((s.get("options") or {}).get("event") == event for s in applies):
                problems.append(
                    f"{where}: 接力的 event 未与触发事件 {event!r} 同名，"
                    "下一轮不会重新执行这份 NPC 配置"
                )
            # 标记必须由上一轮经 env 传下来、由 NPC 在触顶时写出，
            # 且两处变量名逐字一致——否则守卫会因为「标记永不为真」拦不住无限接力。
            passed_down = str(job.get("env", {}).get("turnLimitReached", ""))
            if passed_down.strip() != f"${self.HANDOFF_FLAG}":
                problems.append(
                    f"{where}: 收尾阶段缺 {self.HANDOFF_FLAG} 标记"
                    "（无标记则每轮都判定「已触顶」，同一评论会被无限接力）"
                )
        assert seen, "未在 .cnb.yml 找到任何 npc:go 流水线——守卫失效（判据空转）"
        assert not problems, (
            "NPC 轮数触顶后没有接力（构建 cnb-m48-1k33grbms 的丢成果形态）:\n  "
            + "\n  ".join(problems) +
            "\n平台没有「轮数用满自动重跑」的原生开关，接力必须显式写在 endStages："
            "`type: cnb:apply` + `event: <同名事件>` + `env: {"
            f"{self.HANDOFF_FLAG}: ${self.HANDOFF_FLAG}" + "}`。"
            "改完请同步 .cnb.yml 注释里的轮次上界推演。"
        )

    def test_handoff_flag_is_the_only_reading_of_reached_state(self, cnb_doc):
        """接力标记只允许出现在「读它」的位置，不许新增第二份判据。

        白名单是逐行判据，不是计数：每一行含标记的文本都必须落在
        （a）流水线 `env` 的传入/传出、（b）`if` 条件的判定
        这三类用途之内；任何新形态（例如 Agent 另写一个 state 文件、
        或再加一个 handoff 计数器）都会被这条拦下——那是平行体系。
        """
        allowed = ("turnLimitReached:", '"$turnLimitReached" = "1"')
        offenders = [
            f"{lineno}: {line.strip()}"
            for lineno, line in enumerate(io.open(CNB, encoding="utf-8"), 1)
            if self.HANDOFF_FLAG in line
            and not any(mark in line for mark in allowed)
        ]
        assert not offenders, (
            "接力标记出现在白名单之外的位置:\n  " + "\n  ".join(offenders) +
            "\n标记只有两个合法用途：流水线 env 传入/传出、if 条件判定。"
        )

    #: 接力协议的书写落点：NPC 人设必须把「怎么写出标记」讲清楚，
    #: 否则 .cnb.yml 里的收尾阶段永远读不到真值（写不出 → 永不接力 = 死配置）。
    HANDOFF_MARKER_FILE = ".npc-turn-handoff"

    def test_npc_personas_declare_handoff_protocol(self, settings_doc):
        """每个 NPC 角色的人设都要写明接力标记的写法与唯一的判据文件。"""
        roles = (settings_doc.get("npc") or {}).get("roles") or []
        assert roles, ".cnb/settings.yml 无角色——NPC 人设未入库"
        missing = [
            r.get("name") for r in roles
            if self.HANDOFF_MARKER_FILE not in (r.get("prompt") or "")
        ]
        assert not missing, (
            f"NPC 角色未写明轮数触顶接力协议: {missing}\n"
            f"人设里必须写清「用满轮数且还有未完成步骤时，把 1 写进 "
            f"$CNB_BUILD_WORKSPACE/{self.HANDOFF_MARKER_FILE}」——"
            "这是 .cnb.yml 收尾阶段唯一的读点，写不出就等于没有接力；"
            "同时要提醒 Agent 用评论落进度（工作树不跨轮保存）。"
        )
