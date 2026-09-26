# -*- coding: utf-8 -*-
"""NPC 配置守卫（.cnb.yml / .cnb/settings.yml）。

锁定几件已实锤踩过的事故，防同源复发：

1. **model 不得带思考强度后缀** —— `deepseek-v4.1-flash-{low,high,max}` 是
   "同一底座模型 + 不同思考强度"的变体名，合法 model ID 只有
   `deepseek-v4.1-flash`。把带后缀的名字传给 `npc:go.options.model`，
   平台网关会以 `400 (no body)` 拒收，且失败发生在真正发请求时
   （配置期不报错、流水线能启动）——表现为"配置都对却秒杀"。
2. **thinkingLevel 必须是字面量枚举值** —— `npc:go.options` 走平台
   配置阶段的 Schema 校验，而校验发生在变量替换之前，写成 `$VAR`
   会以"值不在枚举内"配置期直接红（本仓实测 100 条 Schema 报错）。
3. **档位角色与流水线一一对齐** —— 每个在册档位角色（含同档别名 DSCoder-max）
   都必须被 `.cnb.yml` 的合法挂载点覆盖到，且该挂载点的 thinkingLevel 与本仓
   档位表一致；否则角色被 @ 时静默回落平台默认档、乃至平台默认 **prompt**，
   用户以为切了档、其实没切，本仓 90+ 处引用的修复教义随之失效。
   合法挂载点**只有 `$`**（见第 6 条）：角色名顶层 key 在推送那一刻就是非法配置，
   所以「每个角色都有必达通道」不能靠再挂一个角色名 key 来实现——它由 `$` 兜底
   覆盖全部角色来满足，`LEVEL_BY_MOUNT` 落 `$` 一处不落二处。
4. **档位收敛不倒退** —— 本仓只保留 max 一档。`-low` / `-high` 两档与
   非 max 的 thinkingLevel 若重新出现（顶层 key、settings.yml 角色、
   或流水线里的档位值），守卫直接拦下：要么是有意恢复分档（需同步改
   档位表与本文档），要么是回归，两者都必须显式改测而非悄悄放过。
5. **maxTurns 的取值域由 `$` 兜底挂载点给出，不写死常量** —— 该参数走
   平台配置期 Schema 校验（字面量要求同第 2 条）；合法域是
   `[MIN_TURNS, maxTurnsCeiling(cnb_doc)]`，上限取 `$` 兜底挂载点的**现行
   取值**，取值形态按 `TURNS_SHAPE` 白名单。
   上限必须从流水线自己的现行配置推出：常量上限会把「合法上界」钉在某个
   具体数字上，分支只要调高轮数、`main` 又来不及同步，守卫就红——而它其实
   拦不住真正的配置非法（那由平台 Schema 拦）。由 `$` 现值给出，则
   「调高上限」= 先在主线上显式调高 `$` 段（一次可见的、会被 review 的配置
   改动），分支再跟随：上限永远不低于主线现行值，故「跟随主线」是绿的、
   「私自定义上限」是红的。
   **上限不再被"2h ÷ 单轮耗时"钳位**（Issue #236，构建 cnb-8dk-1k3c7a0e0）：
   那个算式把"轮数配额"当成了"一次 2h 会话能跑多少轮"，而两者本就不同源 ——
   平台墙钟约束的是**整轮会话**（实测 1 轮 / 2428ms 即正常撞顶 abort），
   除数却是仓库自己可优化的单轮耗时。相除得到的常量上界会**随优化反向收紧**：
   实测 2h / 35.3s ≈ 203 轮，连 `cnb-f1c-1k31garu5` 那次被掐断的 251 轮都够不着，
   于是 500 这样的配额被判非法并钳回 200 —— 判据把功能决策钉回了旧值。
   现在该算式只作**读数**（`spinCeilingReading()`），配额的合法域由
   `MIN_TURNS`、现行上限与「高于实测掐断轮数」共同给出
   （见 `TestTurnBudgetMultiplierIsNotAReachableSpinCeiling`）。
6. **顶层 key 只认分支名** —— 角色名挂顶层 key（如 `DSCoder-max:`）在**推送
   分支的那一刻**就是非法配置：Schema 的顶层未知 key 只有 `^\..` 锚点形态被
   放行，语义规则另把 `issue.*` 钉在 `$` 下。别名角色留在 settings.yml 侧，
   运行参数复用 `$` 的定义。
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

# 本仓的全部在册角色共用**同一份运行参数**：一个底座模型、一个最高思考档。
#
# 为什么不再按角色名枚举档位（Issue #272）：角色名此前带 `-low` / `-max` 这类档位后缀，
# 于是「角色名 → 期望档位」必须另建一张表，而那张表与 `.cnb/settings.yml` 的角色定义、
# 与 `$` 挂载点的现值是**三份**口径，任何一处改动都要三处同步。现在全部角色同为最高档，
# 档位只剩一处事实源：`$` 挂载点的 thinkingLevel 现值。
LEVEL_BY_MOUNT = {"$": "max"}

# 已取消的档位后缀：一旦重新出现在 .cnb.yml 顶层 key 或 settings.yml 角色名里即报错
RETIRED_SUFFIXES = ("-low", "-high")

#: maxTurns 的合法取值形态（正整数，可带 `k` 千位后缀）。
#: 形态白名单与"上限是多少"无关——上限属功能决策（由 `$` 挂载点现值给出），
#: 这里只钉"写出来必须是个能过 Schema 的轮数值"。
TURNS_SHAPE = re.compile(r"^[1-9][0-9]*[kK]?$")

#: 轮数下限（写入侧合理性）。平台没有公开的轮数下限；此值只挡住
#: `0` / `1` 这类明显会让 Agent 一轮都跑不完的写法，与耗时上界无关。
MIN_TURNS = 10

#: 平台单次构建硬上限（2h）。依据：构建 cnb-3k8-1k33gorhr 实测 7293033ms
#: （≈2h2m）被掐断，在册同类掐断另有 cnb-f1c-1k31garu5 / cnb-1q8-1k33cb2v9 等多例。
BUILD_HARD_LIMIT_SECONDS = 7200

#: 实测单轮均摊耗时（秒）的最大值（掐断读数）：
#:   cnb-2e8-1k341d9s1：201 轮 / 3191326ms（均摊 15.9s/轮）
#:   cnb-f1c-1k31garu5：251 轮 / 7262s（均摊 ≈29s/轮）
#:   cnb-m48-1k33grbms：207 轮 / 7300s（均摊 35.3s/轮）
#: 链路是自加速的：context 每轮重放（compaction 后仍 ~8MiB 输入、单轮 in≈19 万
#: token）⇒ 单轮耗时由早期 ~16s 涨到 30s+。
#:
#: 用途**仅限** `spinCeilingReading()` 这一个窄用途（回答"某一份单轮成本下
#: 一次 2h 会话最多容纳多少轮"）；它**不再**用来给 maxTurns 反推值或钳上界 ——
#: 那等于把"配额"与"单轮成本"混成一份口径（Issue #158 起了头，Issue #236 收口）。
SECONDS_PER_TURN = 35.3

#: maxTurns 的**基线配额**（功能决策）：一次会话跑 500 轮，跑满由收尾阶段接力下一轮。
#: 轮数触顶是**设计内的正常收官**，配额因此要留得下反复撞顶的余量。
#:
#: 为什么不再拿"2h ÷ 单轮耗时"反推它（Issue #236 的根因，构建 cnb-8dk-1k3c7a0e0）：
#: 那个算式把"配额"当成了"2h 里能跑多少轮"。而平台对 `npc:go` 会话的墙钟硬限
#: 约束的是**整轮会话**，Agent 多跑几十轮并不是"平台按轮数计费墙钟"——
#: 真撞顶探针 cnb-8dk-1k3c7a0e0 的读数是 1 轮 / 2428ms。
#: 被除数（平台墙钟）与除数（仓库自己可优化的单轮耗时）本来就不同源，
#: 相除得出的"可用轮数"因此是一个**会随优化反向收紧**的常量上界：
#: 单轮越快，这个上界反而把配额压得越死（实测 2h / 35.3s ≈ 203 轮 < 251 轮 ——
#: 连 `cnb-f1c-1k31garu5` 那次**被掐断**的轮数都够不着）。
#:
#: 现在这条上界只用于「读数」：`spinCeilingReading()` 回答"某一份实测单轮成本下，
#: 一次会话最多容纳多少轮"，供人评估接力链是否还成立；**它不再是判据的钳位**。
#: 配额本身的合法域由 `MIN_TURNS` 与「高于实测掐断轮数」共同给出
#: （见 `TestTurnBudgetMultiplierIsNotAReachableSpinCeiling`）。
MAX_TURNS_BASELINE = 500


def spinCeilingReading(cost_per_turn: float | None = None) -> int:
    """某一份单轮耗时下，一次 2h 会话最多容纳的轮数（**读数，不是判据**）。

    调用方必须显式给出成本口径（默认取 `SECONDS_PER_TURN`）——
    参数化是刻意的：它让"这个算式依赖哪个成本读数"在调用点可见，
    而不是变成一个隐式的全局常量（Issue #236 的形态）。
    """
    cost = SECONDS_PER_TURN if cost_per_turn is None else cost_per_turn
    return int(BUILD_HARD_LIMIT_SECONDS / cost)


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
    """合法上限 = `$` 兜底挂载点的现行取值（下钳 `MIN_TURNS`，**无上钳**）。

    上限必须从流水线自己的现行配置推出，不能写成孤立的常量：

    - 常量上限会把「合法上界」钉在某个具体数字上，分支只要调高轮数、
      `main` 又来不及同步，守卫就红——而它其实拦不住真正的配置非法（Schema 才拦）；
    - 由 `$` 现值给出，则「调高上限」= 先在主线上显式调高 `$` 段（一次可见的、
      会被 review 的配置改动），分支再跟随。上限永远不低于主线现行值，
      所以"分支跟着主线调高"是绿的，"分支私自定义上限"是红的。

    下钳只防"非法值被洗白"（`$` 写成 0 / `many` 时落基线配额，不下探）；
    **不再有上钳**（Issue #236）：上限曾被 `2h ÷ SECONDS_PER_TURN` 钳死，
    于是主线把配额调成 500 也被钳回 200。配额是功能决策，
    它的合法性由 `TestTurnBudgetMultiplierIsNotAReachableSpinCeiling`
    给出的下限（高于实测掐断轮数）负责，不由某个耗时算式负责。
    """
    main_options = [
        opt
        for path, opt in _iter_npc_go_options({"$": (cnb_doc or {}).get("$") or {}})
        if "issue.comment@npc" in path or "pull_request.comment@npc" in path
    ]
    parsed = [parseTurnBudget(opt.get("maxTurns")) for opt in main_options]
    parsed = [v for v in parsed if isinstance(v, int)]
    if not parsed:
        return MAX_TURNS_BASELINE
    return max(max(parsed), MIN_TURNS)


def _load(path: Path):
    return yaml.safe_load(io.open(path, encoding="utf-8").read())


def _iter_npc_go_options(node, path=""):
    """递归收集所有 npc:go 任务，产出 (路径, options)。

    `npc:go.options` **不认 `prompt` 键**（平台 Schema 只声明 role / systemPrompt /
    userPrompt / model / maxTurns / contextWindow / maxTokens / thinkingLevel /
    supportImage），写进去被静默忽略（允许集事实源见 `.cnb/npc_schema_keys.txt`；
    守卫见 tests/unit/ci/test_npc_pipeline_time_budget.py）；
    故这里不再读取 `options.prompt` 做断言 —— 那是一条永不生效的通路，
    以它为准的绿灯是假的（Issue #158）。
    """
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
            f"下钳 {MIN_TURNS}、无上钳。）\n"
            "确需调高上限：先在主线显式调高 `$` 段，再让分支跟随——"
            "上限永远不低于主线现值，故「跟随主线」是绿的、「私自定义上限」是红的。"
        )

    def test_spin_ceiling_stays_a_reading_not_a_budget_clamp(self, npc_options):
        """「一次会话能容纳多少轮」是**读数**，不得再回头钳住配额（Issue #236）。

        这条替代了旧的 `test_max_turns_leaves_room_under_platform_hard_limit`。
        旧条要求 `maxTurns ≤ 2h ÷ 单轮均摊耗时`（实测 ≈203 轮），于是主线把配额
        调成 500 也被判非法并钳回 200 —— 判据把功能决策钉回了旧值，
        而它声称要防的"配额永不触达"其实另有判据负责
        （见 `TestTurnBudgetMultiplierIsNotAReachableSpinCeiling`：
        配额必须**高于**实测掐断轮数才是可达的）。

        本条的判据分两层，缺一不可：
        1. 算式本身仍按实测成本给出正确读数（老读数 203 轮不变，可复算）；
        2. 该读数**不构成**对现行配额的钳位 —— 现行上限高于它正是期望形态。
        """
        # 第 1 层：算式读数（老读数不变，改动改的是它与配额的关系）
        assert spinCeilingReading(35.3) == int(BUILD_HARD_LIMIT_SECONDS / 35.3) == 203
        assert spinCeilingReading(2.428) > spinCeilingReading(35.3), (
            "单轮越快、一次会话能容纳的轮数应越多 —— 算式方向反了"
        )

        # 第 2 层：配额高于该读数（不是钳回读数）
        ceiling = maxTurnsCeiling(_load(CNB))
        spin_ceiling = spinCeilingReading()
        assert ceiling > spin_ceiling, (
            f"现行上限 {ceiling} 不高于一次会话的容纳读数 {spin_ceiling} 轮 ——"
            "上限又被耗时算式钳住了（Issue #236 的根因复现）。\n"
            "配额是功能决策：把「跑满后由收尾阶段接力」作为正常收官形态，"
            "而不是把配额压到单个 2h 会话之内。"
        )
        declared = sorted({
            parseTurnBudget(options.get("maxTurns"))
            for _path, options in npc_options
            if isinstance(parseTurnBudget(options.get("maxTurns")), int)
        })
        assert declared, "没有任何 npc:go 声明了合法的 maxTurns —— 本判据空转"

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
        """`$` 写成非法值时上限落**基线**配额（不被非法值洗白），合法值原样接受。

        与 Issue #236 之前的差别只有一处、且是判据修正的关键：
        `maxTurns: 1000` 曾经被钳回 200（"2h ÷ 单轮耗时"的上钳），
        现在原样成为现行上限 —— 上限只反映主线声明了什么，
        "这个配额合理吗"由
        `TestTurnBudgetMultiplierIsNotAReachableSpinCeiling` 独立回答。
        """
        assert maxTurnsCeiling({"$": {}}) == MAX_TURNS_BASELINE
        assert maxTurnsCeiling({"$": {"issue.comment@npc": [
            {"type": "npc:go", "options": {"maxTurns": "many"}}
        ]}}) == MAX_TURNS_BASELINE
        assert maxTurnsCeiling({"$": {"issue.comment@npc": [
            {"type": "npc:go", "options": {"maxTurns": 10}}
        ]}}) == MIN_TURNS
        # 合法值原样接受：上钳已删（Issue #236）——配额是功能决策，不是耗时反推值
        assert maxTurnsCeiling({"$": {"issue.comment@npc": [
            {"type": "npc:go", "options": {"maxTurns": 1000}}
        ]}}) == 1000
        assert maxTurnsCeiling({"$": {"issue.comment@npc": [
            {"type": "npc:go", "options": {"maxTurns": 120}}
        ]}}) == 120


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

    def test_every_role_shares_the_single_declared_level(self, settings_doc, cnb_doc):
        """全部在册角色共用同一档 —— 档位事实源只有 `$` 挂载点的现值。

        替代此前那张「角色名 → 档位」表：本仓全部角色同档，那张表就是一份
        与 `$` 现值并列的第二份口径，改一处漏一处不会有任何红（教义第 6 条）。
        """
        roles = (settings_doc.get("npc") or {}).get("roles") or []
        assert roles, ".cnb/settings.yml 未声明任何 NPC 角色"
        expected = LEVEL_BY_MOUNT["$"]
        levels = {
            opt.get("thinkingLevel")
            for _path, opt in _iter_npc_go_options(cnb_doc)
        }
        assert levels == {expected}, (
            f"npc:go 的 thinkingLevel 读数 {sorted(levels)} 与本仓声明的 {expected!r} 不一致。"
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
            issue_body = body.get("issue.comment@npc")
            pr_body = body.get("pull_request.comment@npc")
            if issue_body is None or pr_body is None:
                continue
            # 两处按设计就该不同（自接力事件名、对话载体键），其余逐字一致
            # —— 差异点由 _strip_self_event 逐字点名，不是"允许漂移"。
            if _strip_self_event(issue_body) != _strip_self_event(pr_body):
                problems.append(
                    f"{mount} 下 issue 与 PR 事件定义不一致"
                    "（除自接力事件名与对话载体键外应逐字相同）"
                )
            elif _self_apply_events(issue_body) != {"api_trigger_npc_handoff"} or \
                    _self_apply_events(pr_body) != {"api_trigger_npc_handoff"}:
                problems.append(
                    f"{mount} 下 issue / PR 的收尾接力事件名错位"
                    "（应同为本仓的接力落点事件 api_trigger_npc_handoff）"
                )
            elif not _handoff_carries_context(issue_body, "handoffIssueIid") or \
                    not _handoff_carries_context(pr_body, "handoffPrIid"):
                problems.append(
                    f"{mount} 下 issue / PR 的收尾接力未把自己那侧的对话载体传下去"
                    "（api_trigger 流水线里拿不到 CNB_ISSUE_IID / CNB_PULL_REQUEST_IID）"
                )
        assert not problems, "\n  ".join(problems)

    def test_every_registry_role_falls_into_a_legal_mount(self, cnb_doc, settings_doc):
        """每个在册角色都必须被合法挂载点覆盖——「静默回落平台默认 prompt」的根因处判据。

        本批冲突消解（2026-09-22，PR #136 并入 main）：本 PR 侧的诊断洞见是
        「角色名没有配置期必达通道时，被 @ 会静默回落平台默认 prompt，本仓 90+ 处
        引用的修复教义随之失效，而平台不会报错」，当时靠补一个 `DSCoder:` 顶层 key 来满足。
        main 侧（PR #134）用平台 Schema 证明角色名顶层 key 在推送那一刻就非法，
        真通道只有 `$`——`$` 不是「某一档的兜底」，而是**全部角色**的兜底。

        于是不变量改成（结论取 main，洞见收下）：在册角色名无论是否在
        `.cnb.yml` 有专属顶层 key，都必须命中一份合法挂载点；顶层 key 只准
        `$` 或 `^\..` 锚点形态（后者只承载锚点定义，不作角色挂载）。
        若哪天有人真的加回角色名顶层 key，这条会连同
        `test_no_role_named_top_level_keys` 一起红——两条判据咬合，不靠自觉。
        """
        roles = (settings_doc.get("npc") or {}).get("roles") or []
        assert roles, ".cnb/settings.yml 未声明任何 NPC 角色"

        # 合法顶层 key 的判据与 test_no_role_named_top_level_keys 同源：
        # 分支名 / `main` / `include` / `crontab:` / `^\..` 锚点定义。
        illegal_keys = [
            key for key in cnb_doc
            if not (key == "$" or key == "main" or key == "include"
                    or str(key).startswith("crontab:") or str(key).startswith("."))
        ]
        assert not illegal_keys, (
            f".cnb.yml 出现角色名/非锚点的顶层 key: {illegal_keys}\n"
            "顶层 key 只认分支名；角色一律靠 `$` 兜底覆盖——补一个角色名 key "
            "不是「加了必达通道」，而是把一份过不了 Schema 的配置推上分支。"
        )

        # `$` 段必须声明两个事件：它是全部角色的唯一挂载点，漏一个事件就等于
        # 该场景下角色没有配置期必达通道（平台改走默认行为）。
        fallback = cnb_doc.get("$") or {}
        uncovered = [
            role.get("name") for role in roles
            if not {"issue.comment@npc", "pull_request.comment@npc"} <= set(fallback)
        ]
        assert not uncovered, (
            f"在册角色 {uncovered} 没有配置期必达通道（`$` 段缺事件声明）——"
            "角色名未命中专属 key 时会回落平台默认 prompt，人设与修复教义静默失效。"
        )


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


# 会话内必须出现的时长纪律条目（人设 prompt 的硬约束子串）。
# 这些字符串同时是"给 Agent 的行为约束"与"守卫的判据"，
# 改动任一侧都会让另一侧变红——防后人把纪律删干净后无感回归。
DURATION_DISCIPLINE_MARKERS = (
    "单次构建上限 2h",
    "禁止 sleep",
    "禁止在单次会话里反复跑全量测试套件",
    "长任务要分段交付",
)


class TestNpcBuildDurationDiscipline:
    """NPC 人设必须载明构建时长纪律（2h 硬上限的根因处修复）。

    只调 maxTurns 治不了这个病：cnb-f1c-1k31garu5（251 轮）与
    cnb-3k8-1k33gorhr（204 轮）两次掐断的轮数都远低于 1000 配额，
    真正的死因是单轮耗时（sleep 轮询 + 单轮全量 pytest + 上下文压缩开销）。
    故纪律写在人设里（被 @ 时必加载），并由本守卫常驻钉住。
    """

    def test_every_role_states_build_hard_limit(self, settings_doc):
        roles = (settings_doc.get("npc") or {}).get("roles") or []
        assert roles, "settings.yml 未声明任何 NPC 角色"
        problems = []
        for role in roles:
            prompt = role.get("prompt") or ""
            missing = [m for m in DURATION_DISCIPLINE_MARKERS if m not in prompt]
            if missing:
                problems.append(f"{role.get('name')}: 缺 {missing}")
        assert not problems, (
            "NPC 人设缺少构建时长纪律:\n  " + "\n  ".join(problems) +
            f"\n平台单次构建上限 {BUILD_HARD_LIMIT_SECONDS}s，超时即整条流水线失败、"
            "会话成果全丢。纪律属根因处修复，不可省。"
        )

    def test_duration_discipline_identical_across_roles(self, settings_doc):
        """同档别名角色（DSCoder / DSCoder-max）的时长纪律必须逐字一致。"""
        roles = (settings_doc.get("npc") or {}).get("roles") or []
        rendered = {}
        for role in roles:
            prompt = role.get("prompt") or ""
            rendered[role.get("name")] = tuple(
                line for line in prompt.splitlines()
                if any(m in line for m in DURATION_DISCIPLINE_MARKERS)
            )
        values = set(rendered.values())
        assert len(values) == 1, (
            "各角色的构建时长纪律不一致（会各自漂移）:\n  "
            + "\n  ".join(f"{k}: {len(v)} 行" for k, v in rendered.items())
        )


#: 收尾接力里「对话载体」的键名——issue 侧传 Issue 标识、PR 侧传 PR 标识，
#: 这正是两条事件定义**必然不同**的第二处（第一处是自接力事件名本身）。
#: `cnb:apply` 的 event 只能落在 `api_trigger_*` 上（平台准入，见
#: tests/unit/ci/test_npc_turn_handoff_execution.py），故上下文不再由
#: "拉同一个评论事件"继承，只能靠 env 显式传递，两个键名因此不同。
HANDOFF_CONTEXT_KEYS = ("handoffIssueIid", "handoffPrIid")


def _strip_self_event(pipeline):
    """把两份事件定义中**按设计就该不同**的部分置为占位。

    允许的不同只有两类，且都是逐字点名的：
      1. 自接力事件名（`event`）——历史上是「issue 拉 issue」，现在是
         统一的 `api_trigger_npc_handoff`，占位逻辑保留以兼容两种形态；
      2. 对话载体键（`handoffIssueIid` / `handoffPrIid`）——三条以上差异
         一律视为漂移，由调用方的断言拦下。
    """
    def walk(node):
        if isinstance(node, list):
            return [walk(i) for i in node]
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "event" and isinstance(v, str) and v.endswith("@npc"):
                    out[k] = "<self-event>"
                elif k in HANDOFF_CONTEXT_KEYS:
                    # 键名与取值都占位：两侧传的是不同的平台变量
                    # （$CNB_ISSUE_IID / $CNB_PULL_REQUEST_IID），这就是它们该不同的地方。
                    out["<handoff-context>"] = "<context-var>"
                else:
                    out[k] = walk(v)
            return out
        return node

    return walk(pipeline)


#: 收尾接力唯一允许的内置任务类型。
#: 为什么不是 `cnb:apply`（Issue #170，构建 cnb-i5m-1k355ooo1 实测）：
#:   `cnb:apply` 的适用事件白名单里没有 `@npc` 一族（也没有其宿主
#:   `issue.comment` / `pull_request.comment`），写在 `@npc` 流水线的
#:   `endStages` 里**在写下那一刻就注定执行不了** —— 校验看的是宿主事件，
#:   不是 `options.event` 的取值。`cnb:trigger` 的适用事件是「所有事件」，
#:   是同一件事（触发本仓自定义事件流水线）在 `@npc` 宿主下唯一可行的通道。
HANDOFF_TRIGGER_TYPE = "cnb:trigger"

#: 平台在收尾时刻注入的**事实**变量（Issue #158 的判据来源；v2 见 Issue #272）。
#: 实测读数（探针 cnb-c9g-1k3c3dqg7 / cnb-p2q-1k3c2g7u3 / cnb-o8q-1k3c25fpt，
#: 2026-09-25）：`endStages` 里 `CNB_PIPELINE_STATUS=error`；
#: 同一 Job 的 `failStages` 里 `CNB_PIPELINE_STATUS` 为空串。
PLATFORM_STATUS_VAR = "CNB_PIPELINE_STATUS"

#: v2 的第二个事实源：**失败 stage 名**（Issue #272）。
#: 为什么不是 `CNB_BUILD_FAILED_MSG`：实测（探针 cnb-m16-1k3f5s0ri，2026-09-26）
#: 证明该变量取的是**失败 stage 最后一行输出** —— Job 超时被 SIGKILL 后它是
#: 脚本自己最后 echo 的 `start`，不是平台文案。按文案片段匹配等于看运气。
PLATFORM_FAILED_STAGE_VAR = "CNB_BUILD_FAILED_STAGE_NAME"

#: npc:go 所在 stage 名里的 ASCII 标记（判据按它匹配）。
GO_STAGE_MARKER = "npc-go"


def _handoff_carries_context(pipeline, key):
    """收尾接力的 env 里有没有把指定对话载体键传下去（逐字点名，不看注释）。"""
    found = []

    def walk(node):
        if isinstance(node, list):
            for i in node:
                walk(i)
            return
        if isinstance(node, dict):
            if node.get("type") == HANDOFF_TRIGGER_TYPE:
                env = (node.get("options") or {}).get("env") or {}
                if isinstance(env, dict):
                    found.append(env)
            for v in node.values():
                walk(v)

    walk(pipeline)
    return any(isinstance(env.get(key), str) and env.get(key).strip() for env in found)


def _self_apply_events(pipeline):
    """收集流水线里所有收尾接力声明的事件名（接力判据）。"""
    found = set()

    def walk(node):
        if isinstance(node, list):
            for i in node:
                walk(i)
            return
        if isinstance(node, dict):
            if node.get("type") == HANDOFF_TRIGGER_TYPE:
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
    轮次预算），所以接力必须在配置里显式写出来：收尾阶段用 `cnb:trigger`
    再拉一次自定义事件（`api_trigger_npc_handoff`），并由**平台在收尾时刻注入的
    事实变量**把「本轮真撞顶」与「用户新发的 `@`」区分开，防止同一条评论被无限
    重跑。`turnLimitReached` 那条预写判据已由 Issue #158 证伪并删净（它由 Agent
    开工前的步骤无条件写成 1，跟"是否撞顶"无关）。

    判据落在**是否有这笔接力 + 判据读的是不是平台事实**上，不落在
    `$变量` 替换后的形态上：`api_trigger_pipeline` 的 options 在配置期做
    Schema 校验，事件名写成 `$VAR` 会被平台拒掉；且内置任务的 `env` 值只接受 `$变量`
    （见 tests/unit/test_ci_thin_env_guards.py 同型的薄环境事故）。
    """

    #: 上一代用于判定接力轮的标记名。现已作废 —— 保留常量只为**反向钉住**
    #: "它不得再出现"，见 `test_no_self_fabricated_relay_flag_survives_in_the_config`。
    HANDOFF_FLAG = "turnLimitReached"

    #: 平台在收尾期注入的事实（平台「环境变量」篇，`endStages` 内可读）。
    #: 真 `npc:go` 撞 `maxTurns` 的读数见构建 cnb-s4f-1k3c46us9。
    #: v2（Issue #272）：第二个事实源改为**失败 stage 名** ——
    #: `CNB_BUILD_FAILED_MSG` 实测是失败 stage 的最后一行输出（不可靠）。
    STATUS_VAR = "CNB_PIPELINE_STATUS"
    FAILED_STAGE_VAR = "CNB_BUILD_FAILED_STAGE_NAME"

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

    #: `cnb:apply` 的 `event` 唯一能拉的自定义事件前缀（平台文档：apply.md）。
    #: 「下一轮」落在 `api_trigger_*` 上，而不是同名评论事件——后者在
    #: `cnb:apply` 的适用事件白名单之外，运行期被平台以 error 拒掉
    #: （构建 cnb-k6e-1k34osn4f 实测）。
    HANDOFF_APPLY_EVENT_PREFIX = "api_trigger"

    def test_npc_pipeline_carries_turn_handoff(self, cnb_doc):
        """每条 npc:go 流水线都要有收尾接力（trigger + 轮次上限标记）。

        判据的历史（Issue #158 / #170，三次修，形态各不同）：
          * 第一批断言 `event` 与触发事件**同名**（issue 拉 issue）——已被平台
            证伪：`cnb:apply` 只认 `push`/`api_trigger` 等固定事件。
          * 第二批改成「接力指向一条 `api_trigger_*` 事件，且该事件在 `$` 下
            真实存在、其内跑 npc:go」——**判据方向仍然错了**：平台校验的是
            承载 `cnb:apply` 的**宿主事件**，而不是 `options.event` 的取值。
            在 `@npc` 流水线的 `endStages` 里放 `cnb:apply`，注定执行不了
            （Issue #170，构建 cnb-i5m-1k355ooo1 实测 error）。
          * 现判据：接力用 `cnb:trigger`（适用**所有**事件），指向本仓的
            `api_trigger_*` 落点，且该事件在 `$` 下真实存在、其内跑 npc:go。
        """
        problems = []
        seen = 0
        for where, event, job in self._npc_pipelines(cnb_doc):
            seen += 1
            end_stages = [s for s in (job.get("endStages") or []) if isinstance(s, dict)]
            triggers = [s for s in end_stages if s.get("type") == HANDOFF_TRIGGER_TYPE]
            if not triggers:
                problems.append(
                    f"{where}: endStages 无 {HANDOFF_TRIGGER_TYPE}，轮数触顶后无人接力"
                )
                continue
            for stage in triggers:
                options = stage.get("options") or {}
                target = options.get("event")
                if not (isinstance(target, str) and target.startswith(self.HANDOFF_APPLY_EVENT_PREFIX)):
                    problems.append(
                        f"{where}: 接力的 event={target!r} 不是 api_trigger* 事件，"
                        "运行期会被平台以 error 拒掉"
                    )
                elif target not in (cnb_doc.get("$") or {}):
                    problems.append(
                        f"{where}: 接力的 event={target!r} 在 `$` 下不存在——"
                        "指向一个拉不起的流水线，接力仍是空转"
                    )
                # slug 必填：`cnb:trigger` 不默认当前仓库，缺它就触发不了。
                if not str(options.get("slug") or "").strip():
                    problems.append(
                        f"{where}: 接力未给 slug —— `cnb:trigger` 的 slug 是必填项"
                        "（目标仓库完整路径），缺它触发不了"
                    )
            # 无限接力的拦阻改由**平台事实**承担（Issue #189 / #158）：
            # 收尾 `if` 读 `$CNB_PIPELINE_STATUS` + `$CNB_BUILD_FAILED_MSG`，
            # 正常收官（status=success）第一条即为假 ⇒ 不接力。
            # 上一代用 env 传一个自造标记，那条链路已被证伪为**恒真**：
            #   cnb-2q8-1k3buskao / cnb-kdg-1k3bv22ct 均 Agent stage success
            #   （未撞顶）却照拉下一轮（cnb-lga-1k3c0itrj / cnb-fln-1k3c2rjk7）；
            # 实测四条父构建在 76~164 轮即被接力，接力落点 32 次构建 / 22.2h 墙钟。
            # 故判据从"标记传下来了吗"改成"判据读的是平台事实吗"，
            # 并反向钉住"不许再有自造标记"。
            conditions = stage.get("if") or []
            if isinstance(conditions, str):
                conditions = [conditions]
            blob = "\n".join(str(item) for item in conditions)
            for needed in (self.STATUS_VAR, self.FAILED_STAGE_VAR):
                if needed not in blob:
                    problems.append(
                        f"{where}: 收尾接力未读 ${needed} —— "
                        "无限接力的拦阻必须落在平台事实上，不是上一轮预写的值"
                    )
            if GO_STAGE_MARKER not in blob:
                problems.append(
                    f"{where}: 收尾接力未匹配 npc:go 的 stage 名标记 {GO_STAGE_MARKER!r}"
                )
            if self.HANDOFF_FLAG in (job.get("env") or {}):
                problems.append(
                    f"{where}: job.env 仍在传自造的 {self.HANDOFF_FLAG} "
                    "（该标记恒真，等于没有空轮防护）"
                )
        assert seen, "未在 .cnb.yml 找到任何 npc:go 流水线——守卫失效（判据空转）"
        assert not problems, (
            "NPC 轮数触顶后没有接力（构建 cnb-m48-1k33grbms 的丢成果形态）:\n  "
            + "\n  ".join(problems) +
            "\n平台没有「轮数用满自动重跑」的原生开关，接力必须显式写在 endStages："
            "`type: cnb:trigger` + `event: <api_trigger_* 事件>` + "
            f"`if: [ $${self.STATUS_VAR} = error 且 $${self.FAILED_STAGE_VAR} 命中 "
            f"{GO_STAGE_MARKER} 标记 ]`，"
            "且该 api_trigger 事件要在 `$` 下真实存在并跑 npc:go ——"
            "由开工前的步骤预写标记只会让接力变成'每次都接力'（Issue #158）。"
            "改完请同步 .cnb.yml 注释里的轮次上界推演。"
        )

    #: 平台文档列出的 `cnb:apply` **适用事件**白名单（apply.md「适用事件」节）。
    #: 判据落在「当前流水线自己的触发事件」上，不是 `options.event` 的取值 ——
    #: 后者只决定"拉哪条自定义事件"，前者决定这次 `cnb:apply` 能不能被执行。
    APPLY_HOST_EVENT_WHITELIST = frozenset({
        "push",
        "commit.add",
        "branch.create",
        "pull_request.target",
        "pull_request.mergeable",
        "tag_push",
        "pull_request.merged",
        "api_trigger",
        "web_trigger",
        "crontab",
        "tag_deploy",
    })

    def test_the_apply_host_event_is_whitelisted(self, cnb_doc):
        """`cnb:apply` 所在的**宿主事件**必须在平台的适用事件白名单内。

        根因（构建 cnb-i5m-1k355ooo1 实测，收尾 Stage 以 error 收场）：

            cnb:apply can only be used in push/commit.add/branch.create/
            pull_request.target/pull_request.mergeable/tag_push/
            pull_request.merged/api_trigger/web_trigger/crontab/tag_deploy events

        前几批把判据落在 `options.event` 是 `api_trigger_*` 上，**判据方向错了**：
        平台校验的是承载 `cnb:apply` 的那条流水线自己的触发事件
        （这里是 `issue.comment@npc` / `pull_request.comment@npc`），
        它不在白名单里，于是这笔接力**在写下的那一刻就注定执行不了**。
        此前一直被 `if` 恒假的 `skipped` 掩盖 —— 判据不真就走不到准入检查；
        一轮让 `if` 真的为真的改动（自造燃料，见 Issue #189 的作废记录）之后，
        平台的准入检查终于被执行到，问题才第一次响亮。

        `@npc` 事件不在白名单内，故**收尾阶段不能放 `cnb:apply`** ——
        这是平台约束，不是配置写法问题；接力必须换一条真正可用的通道
        （现形态为 `cnb:trigger`，见 `TestHandoffRidesAnAllowedChannel`）。

        可证伪路径：把 `@npc` 事件的 `endStages` 里再放一个 `cnb:apply` → 立刻转红。
        """
        offenders = []
        for where, event, job in self._npc_pipelines(cnb_doc):
            # 事件名形如 `issue.comment@npc` / `pull_request.comment@npc`；
            # 去掉 `@npc` 后缀取平台事件名（`issue.comment` 一族同样不在白名单）。
            host_event = event.split("@", 1)[0]
            for stage in (job.get("endStages") or []):
                if isinstance(stage, dict) and stage.get("type") == "cnb:apply":
                    offenders.append(f"{where}: 宿主事件 {event!r} 承载了 cnb:apply")
            if host_event in self.APPLY_HOST_EVENT_WHITELIST:
                continue
        assert not offenders, (
            "cnb:apply 被放在平台不允许的事件下，运行期必然以 error 收场：\n  "
            + "\n  ".join(offenders) +
            "\n平台白名单只认 " + " / ".join(sorted(self.APPLY_HOST_EVENT_WHITELIST)) + "。"
            "`@npc` 事件（及其 `issue.comment` / `pull_request.comment` 宿主）不在列，"
            "且这一点**无法靠 options.event 绕开** —— 该校验看的是宿主事件。\n"
            "构建 cnb-i5m-1k355ooo1 实测原文：cnb:apply can only be used in "
            "push/commit.add/branch.create/... events。"
        )


    def test_npc_personas_declare_handoff_protocol(self, settings_doc):
        """每个 NPC 角色的人设都要写清接力协议，并**禁止**自己写状态标记。

        判据随根因一起改了（Issue #158 / #189）：旧协议要求 Agent 在触顶那一轮
        写标记，而那件事平台根本不给它机会做（撞顶即中止、不执行任何收尾指令）；
        随后改成"由开工前的门禁预写"，又变成与"是否撞顶"无关的恒真判据。
        现协议是：**判据由平台在收尾时刻自己判定，Agent 什么都不用写** ——
        人设必须把这一点讲明白，否则下一轮 Agent 会去新建第二套状态文件。
        """
        roles = (settings_doc.get("npc") or {}).get("roles") or []
        assert roles, ".cnb/settings.yml 无角色——NPC 人设未入库"
        missing = []
        for role in roles:
            prompt = role.get("prompt") or ""
            if (self.STATUS_VAR not in prompt or self.FAILED_STAGE_VAR not in prompt
                    or GO_STAGE_MARKER not in prompt):
                missing.append(f"{role.get('name')}: 未点明接力判据读的平台事实")
            if "别去写任何状态文件或标记" not in prompt:
                missing.append(f"{role.get('name')}: 未显式禁止写状态文件/标记")
            if "不需要你做任何事" not in prompt or "分段" not in prompt:
                missing.append(f"{role.get('name')}: 未写清「判据由平台判定 + 分段落评论」")
        assert not missing, (
            "NPC 角色人设未写明轮数触顶接力协议:\n  " + "\n  ".join(missing) +
            f"\n`.cnb.yml` 的收尾 `if` 读 ${self.STATUS_VAR} 与 "
            f"${self.FAILED_STAGE_VAR}（后者命中 {GO_STAGE_MARKER} 标记）；"
            "人设里不写清楚，Agent 会以为接力还需要它配合，或另造一套平行判据。"
        )


class TestAnchoredConfigHasConsumer:
    """`.cnb.yml` 的锚点定义必须有消费方：只写不读的配置就是断点。

    平台不解析 YAML 锚点语义（那是 YAML 解析期的事），故「有没有人读」
    只能由本仓自己守。`^\..` 形态的顶层键在 Schema 里合法、平台也不报错，
    一份无人读的档位表就此长期留在配置里，且会被顺手改成与档位收敛口径
    相反的值（main 的 `DSCoder: high` 即此形态）——规则与行为不一致时
    没有任何一处会响亮。

    判据取 YAML 事件流：声明锚点（AnchorEvent）与引用锚点（AliasEvent）
    都出自**同一份配置文本**，逐名比对，可证伪路径 = 重新写一份无人引用的
    `&xxx` 锚点定义 → 立刻转红。
    """

    @staticmethod
    def _anchor_names():
        declared, used = set(), set()

        class _Recorder(yaml.SafeLoader):
            def compose_node(self, parent, index):
                event = self.peek_event()
                anchor = getattr(event, "anchor", None)
                if anchor:
                    (used if isinstance(event, yaml.events.AliasEvent)
                     else declared).add(anchor)
                return super().compose_node(parent, index)

        with io.open(CNB, encoding="utf-8") as fh:
            _Recorder(fh.read()).get_single_data()
        return declared, used

    def test_every_declared_anchor_is_referenced(self):
        declared, used = self._anchor_names()
        assert declared, ".cnb.yml 里一个锚点都没解析到——本判据已失效"
        orphans = sorted(declared - used)
        assert not orphans, (
            f".cnb.yml 声明了无人引用的锚点: {orphans}\n"
            "只写不读的配置是断点（AGENTS.md 协作红线「不留断点」）："
            "要么接到消费方，要么连同它承载的那份重复定义一起删净"
            "（教义第 6 条：发现第二份定义就收口并删净）。"
        )

    def test_tier_table_has_no_unread_second_copy(self, cnb_doc):
        """档位口径只准有一份（`.cnb.yml` 的 `$` 现值），不许再放一份无人读的表。

        本仓的档位事实源是 `$` 挂载点 + `.cnb/settings.yml` 的角色定义，
        由 `LEVEL_BY_ROLE` / `LEVEL_BY_MOUNT` 常驻校验。`.cnb.yml` 里若再出现
        一份「角色名 → thinkingLevel」的映射，那就是第三份口径，且平台不读、
        守卫也不读，只能静默漂移（main 的 `DSCoder: high` 即此形态，
        与同一份文件里 `thinkingLevel: xhigh` 的收敛口径相反）。
        """
        role_names = {
            (r or {}).get("name")
            for r in ((_load(SETTINGS).get("npc") or {}).get("roles") or [])
        }
        offenders = []
        for key, value in (cnb_doc or {}).items():
            if not isinstance(key, str) or not key.startswith("."):
                continue
            if not isinstance(value, dict):
                continue
            if set(value) & role_names:
                offenders.append(f"{key}: {value}")
        assert not offenders, (
            "`.cnb.yml` 里出现了第二份无人读的档位表:\n  " + "\n  ".join(offenders) +
            "\n档位口径只有一处：`$` 挂载点的 thinkingLevel 现值，"
            "加上 `.cnb/settings.yml` 的角色定义。"
        )


class TestMountClaimMatchesTheRealMount:
    """`.cnb/settings.yml` 不得宣称角色名顶层 key 挂载 —— 那是已删净的非法形态。

    根因与 `TestAnchoredConfigHasConsumer` 同源：档位表（`.档位映射: &npc-level`）
    已被删净，顶层 key 收敛为 `$` 一处，角色名顶层 key 在推送那一刻就是非法配置。
    而 `.cnb/settings.yml` 的头部与角色注释仍在宣称「档位挂在 `.cnb.yml` 同名顶层 key」——
    一句读不出任何真实挂载点、且与现行配置相反的陈述，同属「只写不读的第二份定义」：
    后人照着它去补顶层 key，就会推一份过不了 Schema 的配置上分支。

    判据：`.cnb/settings.yml` 的**全部**文本里不得再出现「同名顶层 key」这一宣称形态。
    可证伪路径 = 把该句写回去 → 立刻转红。
    """

    def test_settings_never_claims_a_role_named_top_level_mount(self):
        text = io.open(SETTINGS, encoding="utf-8").read()
        offenders = [
            f"第 {number} 行: {line.strip()}"
            for number, line in enumerate(text.splitlines(), start=1)
            if "同名顶层 key" in line
        ]
        assert not offenders, (
            ".cnb/settings.yml 仍在宣称角色名顶层 key 挂载（该形态已删净且为非法配置）:\n  "
            + "\n  ".join(offenders) +
            "\n顶层 key 只认分支名；角色一律靠 `$` 兜底覆盖——"
            "档位事实源是 `$` 挂载点的 thinkingLevel 现值加本文件的角色定义。"
        )


#: 单轮耗时（秒）的实测读数 —— **不是** `SECONDS_PER_TURN` 那一个值。
#: 那一处是"2h ÷ 单轮耗时 ≈ 能跑多少轮"的窄用途读数；本处回答的是另一个问题：
#: 「1 轮 = 平台一次墙钟的整数倍吗？」
#:
#: 读数（两类来源，四条独立构建，2026-09-25）：
#:   * 真撞顶探针 cnb-8dk-1k3c7a0e0：1 轮 / 2428ms —— 平台按 1:1 走一轮；
#:   * 评论触发的父构建实际均摊（轮数 ÷ 墙钟，见
#:     tests/unit/ci/test_npc_turn_handoff_predicate.py 的模块 docstring）：
#:       cnb-f1c-1k31garu5  251 轮 / 7262s  ≈ 29s
#:       cnb-m48-1k33grbms  207 轮 / 7300s  ≈ 35s
#:       cnb-2e8-1k341d9s1  201 轮 / 3191s  ≈ 15.9s
#:       cnb-1q8-1k33cb2v9  340 轮 / 7261s  ≈ 21.4s
#: 均摊远小于两倍 —— 故「一轮 ≈ 一次墙钟」这个前提在实测域内成立。
#: 它的**用途是判据的适用前提**：记录每轮成本的量级（< MAX_TURNS 的一半），
#: 使「轮数配额 = 平台墙钟倍数」这条契约不至于被后人理解成"1 轮 = 1 墙钟"。
#: 确切上界不与平台能力挂钩：预算是**配额**（让出的值），不是墙钟反推值。
MEASURED_SECONDS_PER_TURN_READINGS = (2.428, 15.9, 21.4, 29.0, 35.3)

#: 平台对 `npc:go` 会话的墙钟硬限（秒）。会话横跨任意多轮，
#: 配额用满只是换一个会话继续 —— 与 `SECONDS_PER_TURN` 描述的"2h 能跑几轮"不是同一件事。
PLATFORM_SESSION_WALLCLOCK_LIMIT_SECONDS = 7200

#: 平台墙钟倍数（现行值，功能决策）：一次会话跑满的墙钟不落在单个 2h 会话里。
#: 记录本轮修复的**唯一本意**：把"跑满配额 = 平台反复掐断（无告警、无收尾、
#: worktree 成果直接丢）"换成"撞顶正常收官、由收尾阶段接力（成果经评论交接）"。
#: 与上下文窗口同理：窗口不足时用接力续跑，而不是把单轮压到 6 千 token。
#:
#: ⚠️ 这个基数**不是**可用轮数：任何降低单轮耗时的改动都会放大它
#: （见 `TestTurnBudgetMultiplierIsNotAReachableSpinCeiling`）。
TURN_BUDGET_MULTIPLIER = 500


def _spinCeilingUnderCurrentTurnCost():
    """按实测单轮耗时算：一次 2h 会话最多能容纳多少轮。

    它是**读数**，不是配额 —— 用途是回答"把配额写在它之上，撞顶还等得到吗"。
    """
    return spinCeilingReading()


class TestTurnBudgetMultiplierIsNotAReachableSpinCeiling:
    """`maxTurns` 是**配额**，不是"单轮数量"——它必须留得下反复撞顶的余量。

    ## 根因（Issue #236，构建 cnb-8dk-1k3c7a0e0 实测）

    本轮把配额从 200 提到 500 时，旧的 `MAX_TURNS_BUDGET` / `AFFORDABLE_TURNS`
    这套判据把"配额"与"2h 里能跑多少轮"混为一谈，于是 500 被判非法并被钳回 200。
    本文件修好前的红灯读数（本地实测原文）：

        tests/unit/test_ci_npc_config_guard.py:1191:
        TestTurnBudgetMultiplierIsNotAReachableSpinCeiling::test_declared_budget_exceeds_the_measured_interrupt_ceiling
        E   AssertionError: 现行配额上限 200 不高于实测掐断轮数 251

        ...::test_budget_leaves_room_for_repeated_topouts
        E   AssertionError: 现行配额 200 未超过「一次 2h 会话可容纳的 203 轮」
        E   assert 200 > 203

    该测试写于 `cnb-f1c-1k31garu5`（251 轮 / 7262s）与 `cnb-m48-1k33grbms`
    （207 轮 / 7300s）之后：平台把它们判成"2h 跑不完"而外部掐断，于是推断
    「配额写在硬限之上 = 撞顶永远等不到」。这只在**平台按轮数计费墙钟**时成立 ——
    而实测是反的：同一条流水线里 1 轮 Agent 会话在 2428ms 内正常 abort，
    多轮会话只受**每次工具执行**的 `timeout` 约束（`.cnb.yml` 的 `npc:go.timeout` 注释）。
    「2h ÷ 35s」这个算式在这里是**类别错误**：被除数是"平台墙钟"，
    除数却是"仓库自己可优化的单轮耗时"。

    修法（教义第 1 条，改根因不改症状）：把这两件事分开 ——
    配额是**声明的功能决策**，判据只钉形态与下限，不钉 2h 能跑多少轮。
    于是单轮耗时一旦优化，可用轮数单调上升，而不是被一个常量上界抹平。

    ## 可证伪路径

    - 把 `$` 段的 `maxTurns` 回填 200 → 第一条红（配额被钉回"掐断时刚好够用"）；
    - 把上限重新钳回「2h ÷ 单轮耗时」（上限 = min(现值, 203)）
      → 第二条红（"跑到撞顶"这件事在合法域内不可达）；
    - 把单轮耗时压到接近 `TURN_BUDGET_MULTIPLIER` 分之一 → 第二条红
      （配额相对单轮成本不再有反复撞顶的余量）。
    """

    def test_declared_budget_exceeds_the_measured_interrupt_ceiling(self, cnb_doc):
        """现行配额必须**高于**被外部掐断那两次实测的轮数（否则等于没有配额）。

        `cnb-f1c-1k31garu5` 251 轮、`cnb-m48-1k33grbms` 207 轮都是**被平台掐断**
        而非撞顶 —— 配额若落在它们附近，Agent 永远等不到"撞顶正常收官"，
        只有"外部掐断、无收尾、成果全丢"。
        """
        interrupt_turns = (251, 207)
        ceiling = maxTurnsCeiling(cnb_doc)
        problems = [
            f"现行配额上限 {ceiling} 不高于实测掐断轮数 {turns} —— "
            "配额落在掐断之后，撞顶永远不会发生，只有外部掐断"
            for turns in interrupt_turns if ceiling <= turns
        ]
        assert not problems, "\n  ".join(problems)

    def test_budget_leaves_room_for_repeated_topouts(self, cnb_doc):
        """配额相对实测单轮成本必须有反复撞顶的余量（不是一个 2h 会话的量）。

        反向自证：若某天单轮耗时被优化到与配额同量级，本条转红 ——
        那说明"配额"已经退化成"一次会话的轮数"，接力链没有存在的必要，
        该显式重新决策，而不是让它静默成立。
        """
        ceiling = maxTurnsCeiling(cnb_doc)
        spin_ceiling = _spinCeilingUnderCurrentTurnCost()
        assert ceiling > spin_ceiling, (
            f"现行配额 {ceiling} 未超过「一次 2h 会话可容纳的 {spin_ceiling} 轮」"
            f"（按实测单轮均摊 {SECONDS_PER_TURN}s）——"
            "配额退化成单会话轮数，撞顶无法正常收官。\n"
            "若这是刻意的（单轮成本已优化到配额量级），请先改这条判据与 "
            "TURN_BUDGET_MULTIPLIER 的取值依据，并说明接力链是否还需要。"
        )
        # 前提自证：判据成立的前提是"记录的单轮成本量级远小于配额"。
        # 有新的实测读数就追加到 MEASURED_SECONDS_PER_TURN_READINGS，
        # 不写死第二个 SECONDS_PER_TURN（那是第二份口径）。
        slowest = max(MEASURED_SECONDS_PER_TURN_READINGS)
        assert slowest * 2 < ceiling, (
            f"最慢单轮实测 {slowest}s × 2 已接近配额 {ceiling} 轮的量级 —— "
            "「轮数配额」与「单轮成本」被混在了一起（Issue #236 的根因形态）。"
        )


class TestDeclaredBudgetIsSingleSourcedIntoThePersonas:
    """配额的**数字**只准有一处事实源：`$` 挂载点的 `maxTurns` 现值。

    同一条事实（"配额是多少轮"）此前写在两处：`.cnb.yml` 的 `maxTurns`，
    与 `.cnb/settings.yml` 每个角色 prompt 里的「现行 N 轮」。两处都是**读得到的
    指令**（人设进 Agent 上下文，配置进平台），任一漂移都会让 Agent 报错误的工作量
    上限 —— 而平台与守卫都不会响亮。本轮把它收口成一处并加判据（Issue #236）：

    - `.cnb.yml`：配额现值（唯一可执行的字段）；
    - `.cnb/settings.yml`：不得出现与现行值不符的「maxTurns（现行 N 轮）」读数。

    可证伪路径：把任一角色 prompt 里的「现行 200 轮」改成旧值 → 立刻转红。
    """

    #: 人设里引用配额的行形态（唯一允许的写法）。
    BUDGET_CITATION = "npc:go 的 maxTurns（现行 {} 轮）"

    def test_personas_quote_the_current_budget(self, cnb_doc, settings_doc):
        ceiling = maxTurnsCeiling(cnb_doc)
        expected = self.BUDGET_CITATION.format(ceiling)
        stale = []
        cited = 0
        for role in (settings_doc.get("npc") or {}).get("roles") or []:
            prompt = role.get("prompt") or ""
            if "npc:go 的 maxTurns" not in prompt:
                stale.append(f"{role.get('name')}: 人设未引用配额现值")
                continue
            cited += 1
            if expected not in prompt:
                found = [
                    line.strip() for line in prompt.splitlines()
                    if "npc:go 的 maxTurns" in line
                ]
                stale.append(f"{role.get('name')}: {found} ≠ 「{expected}」")
        assert cited, "没有任何角色引用配额现值 —— 本判据空转"
        assert not stale, (
            f"人设里的配额读数与 .cnb.yml 现值（{ceiling}）不一致：\n  "
            + "\n  ".join(stale) +
            "\n配额的数字只有一处事实源：`$` 挂载点的 maxTurns 现值。"
            "改它时必须同步人设里的读数（人设是 Agent 唯一必达的指令通道，"
            "写旧值等于告诉 Agent 一个错误的工作量上限）。"
        )
