# -*- coding: utf-8 -*-
"""H2-7 · ①：「带病完成」的读数必须有**一处**结算口径与**一个**真读者（§6-87）。

复算现场（台账 §6-78 J 条 2026-10-09 更正）：
- 传输面本来就通——`list_runs` 是 `SELECT *`（`store.py:347-349`），`GET /projects/{pid}`
  已把 `detail_json` 原样带出；缺的是读侧无人解析（`StudioProjectPage.vue:76-87` 只看 `status`，
  `done_with_fallback` 走的是 success 那一支）。
- 同根因仍有两个未扫到的落点（教义第 5 条）：`split_script` 把 `fallback` 成因写进
  `detail_json` 却无条件 `"status": RUN_DONE`（`services.py:117-122`）；`break_storyboards`
  的 LLM 异常只 `logger.warning` 后 `parsed = None`（`:249-253`），落 `RUN_DONE` + `{"shots": 0}`
  ——**一镜都没拆出来也算干净完成**。
- 成因文本的键名也是两份：`split_script` 写 `fallback`、`extract_assets` 写 `error`
  （`:195-198`）——同一件事两个键，读侧只能各猜各的。

判据（缺一环这条链就是断的）：
1. 三个 LLM 编排服务带病时落 `done_with_fallback`，不再压平成 `done`；
2. 成因文本收成一个键 `fallback`（不再 `error`/`fallback` 并存）；
3. `_settleRun` 把「判带病用的那两个数」以固定键写进 `detail_json`，给读侧一份稳定契约
   （读侧不许自己再 sum `blocked_*`——那等于把同一口径抄第二遍）；
4. 服务侧不许再手写终态：`services.py` 里 `update_run(...)` 带 `status` 的落点必须只剩
   `_settleRun` 一处（AST 结构守卫 + 反向对照，防"扫描器写错→永远绿"）。
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(90)

REPO = Path(__file__).resolve().parents[3]
_SERVICES_FILE = REPO / "neurova" / "aigc_studio" / "services.py"
TS_READSIDE = REPO / "NeurUI" / "src" / "composables" / "useStudioRun.ts"

STATUS_KEY = "status"
SETTLE_FN = "_settleRun"
#: 结算写进 `detail_json` 的固定读数键——写侧与前端读侧唯一共用的那份契约。
CONTRACT_KEYS = {"fallback_failed", "fallback_blocked", "fallback"}


@pytest.fixture()
def store(tmp_path):
    from neurova.aigc_studio.store import StudioStore

    return StudioStore(db_path=str(tmp_path / "studio.db"))


@pytest.fixture()
def runOf(store):
    """建一行台账并返回其 id（服务侧结算的目标行）。"""
    def _make(kind: str = "videos", title: str = "结算") -> str:
        project = store.create_project(owner_user_id="u1", title=title)
        return store.add_run({"project_id": project["id"], "kind": kind})["id"]
    return _make


async def _boom(prompt: str, system: str) -> str:
    raise RuntimeError("上游模型不可用")


def _handWrittenRunStatuses(src: str) -> list[str]:
    """`update_run(...)` 实参里带 `status` 键、且不在结算函数体内 → 各抄了一份终态口径。"""
    tree = ast.parse(src)
    exempt = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == SETTLE_FN:
            exempt.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) != "update_run":
            continue
        if node.lineno in exempt:
            continue
        for arg in ast.walk(node):
            if isinstance(arg, ast.Dict) and any(
                    isinstance(k, ast.Constant) and k.value == STATUS_KEY for k in arg.keys):
                offenders.append(f"line {node.lineno}")
                break
    return offenders


class TestOrchestrationServicesDoNotFlattenFallback:
    @pytest.mark.asyncio
    async def test_split_script_fallback_lands_done_with_fallback(self, store):
        """LLM 挂了 → 回退原文单集，这是**带病**（用户以为拆出了分集，其实只有一集原文）。"""
        from neurova.aigc_studio import services
        from neurova.aigc_studio.store import RUN_DONE_WITH_FALLBACK

        project = store.create_project(owner_user_id="u1", title="带病分集")
        rid = store.add_run({"project_id": project["id"], "kind": "script"})["id"]
        await services.split_script(store, project["id"], "第一段剧情。",
                                    llm=_boom, run_id=rid)
        row = store.get_run(rid)
        assert row["status"] == RUN_DONE_WITH_FALLBACK, (
            f"回退成因已写进 detail_json，终态却仍是 {row['status']!r}——"
            "读侧按状态字判成功，成因永远看不见（§6-78 J 条更正点名的这一格）")
        assert json.loads(row["detail_json"])["fallback"], row["detail_json"]
        assert (row["error"] or "").strip(), (
            "带病行没在 error 上留成因，台账里只剩一个状态字")

    @pytest.mark.asyncio
    async def test_break_storyboards_llm_failure_lands_done_with_fallback(self, store):
        """一镜都没拆出来（parsed=None）也是带病，不能记成「完成 · 0 镜」。"""
        from neurova.aigc_studio import services
        from neurova.aigc_studio.store import RUN_DONE_WITH_FALLBACK

        project = store.create_project(owner_user_id="u1", title="带病分镜")
        ep = store.add_episode(project["id"], {"number": 1, "content": "客厅夜"})
        rid = store.add_run({"project_id": project["id"], "kind": "storyboard"})["id"]
        shots = await services.break_storyboards(store, project["id"], ep["id"],
                                                 llm=_boom, run_id=rid)
        row = store.get_run(rid)
        assert shots == []
        assert row["status"] == RUN_DONE_WITH_FALLBACK, (
            f"拆解整步失败却落 {row['status']!r}：异常只在 logger 里过了一遍，"
            "台账上是一次干净的完成")
        assert json.loads(row["detail_json"])["fallback"], row["detail_json"]

    @pytest.mark.asyncio
    async def test_extract_assets_cause_text_uses_the_single_fallback_key(self, store):
        """成因文本只许一个键名：`error`/`fallback` 并存即两份口径（教义第 6 条）。"""
        from neurova.aigc_studio import services

        project = store.create_project(owner_user_id="u1", title="带病抽取")
        ep = store.add_episode(project["id"], {"number": 1, "content": "客厅夜"})
        rid = store.add_run({"project_id": project["id"], "kind": "extract"})["id"]
        await services.extract_assets(store, project["id"], ep["id"], llm=_boom, run_id=rid)
        detail = json.loads(store.get_run(rid)["detail_json"])
        assert detail.get("fallback") == "上游模型不可用", detail
        assert "error" not in detail, (
            f"detail_json 里还留着第二份成因键：{sorted(detail)}")


class TestSettleRunIsTheReadSideContract:
    def test_settle_run_writes_the_counts_that_decided_the_status(self, store, runOf):
        """读侧要能直接取「判带病用的那两个数」，不必自己重算 `blocked_*` 之和。"""
        from neurova.aigc_studio import services
        from neurova.aigc_studio.store import RUN_DONE_WITH_FALLBACK

        rid = runOf("videos", "带病计数")
        services._settleRun(store, rid, {
            "submitted": 4, "failed": 2, "blocked_no_frame": 1,
            "blocked_no_asset": 1, "skipped": 3}, "视频")
        row = store.get_run(rid)
        detail = json.loads(row["detail_json"])
        assert row["status"] == RUN_DONE_WITH_FALLBACK, row
        assert detail["fallback_failed"] == 2, detail
        assert detail["fallback_blocked"] == 2, (
            f"blocked_no_frame + blocked_no_asset 应收成 2，读数：{detail}")
        assert detail["skipped"] == 3, f"原始读数被改写：{detail}"

    def test_clean_batch_writes_zero_counts_not_missing_keys(self, store, runOf):
        """全成功也要把两个数写成 0——读侧据「键在不在」判版本会假分支。"""
        from neurova.aigc_studio import services
        from neurova.aigc_studio.store import RUN_DONE

        rid = runOf("images", "干净批量")
        services._settleRun(store, rid, {"done": 3, "failed": 0, "blocked_no_asset": 0}, "首帧")
        row = store.get_run(rid)
        detail = json.loads(row["detail_json"])
        assert row["status"] == RUN_DONE, row
        assert detail["fallback_failed"] == 0 and detail["fallback_blocked"] == 0, detail
        assert not (row["error"] or ""), f"全成功却被写成带病：{row['error']!r}"

    def test_skipped_only_is_not_degraded(self, store, runOf):
        """`skipped*` 是设计内跳过（§6-86 ① 的原口径），别把它判成带病。"""
        from neurova.aigc_studio import services
        from neurova.aigc_studio.store import RUN_DONE

        rid = runOf("videos", "只有跳过")
        services._settleRun(store, rid, {"done": 2, "skipped": 3, "failed": 0}, "视频")
        row = store.get_run(rid)
        assert row["status"] == RUN_DONE, row
        assert json.loads(row["detail_json"])["fallback_blocked"] == 0

    def test_fallback_text_alone_marks_the_row_as_degraded(self, store, runOf):
        """只有成因文本（无计数）也必须带病——`split_script` 那一步就是这个形态。"""
        from neurova.aigc_studio import services
        from neurova.aigc_studio.store import RUN_DONE_WITH_FALLBACK

        rid = runOf("script", "纯成因")
        services._settleRun(store, rid, {"episodes": 1, "fallback": "LLM 输出不可解析"}, "分集")
        row = store.get_run(rid)
        assert row["status"] == RUN_DONE_WITH_FALLBACK, row
        assert "LLM 输出不可解析" in (row["error"] or ""), row["error"]
        assert json.loads(row["detail_json"])["fallback"] == "LLM 输出不可解析"


class TestServicesSettleOnlyThroughOnePlace:
    def test_no_service_hand_writes_a_run_terminal_status(self):
        offenders = _handWrittenRunStatuses(_SERVICES_FILE.read_text(encoding="utf-8"))
        assert offenders == [], (
            f"services.py 里仍有 {SETTLE_FN} 之外手写 runs 终态的落点：{offenders}——"
            "带病判定就变成两处各判各的")

    def test_reverse_control_catches_a_hand_written_status(self):
        src = (
            "def other(store, rid):\n"
            "    store.update_run(rid, {\"status\": RUN_DONE})\n"
        )
        assert _handWrittenRunStatuses(src) == ["line 2"], "扫描器抓不到手写终态即恒绿"
        inside = (
            "def _settleRun(store, rid):\n"
            "    store.update_run(rid, {\"status\": RUN_DONE})\n"
        )
        assert _handWrittenRunStatuses(inside) == []
        no_status = "def f(store, rid):\n    store.update_run(rid, {\"error\": \"x\"})\n"
        assert _handWrittenRunStatuses(no_status) == []


class TestFrontendReadsExactlyTheContractKeys:
    """跨语言咬合（同 `test_studioRunStatusVocabulary` 那一族）：读侧取的键与写侧的契约键
    必须逐元素相等——生产改键名而 TS 没跟，界面上就是「永远读不到成因」的静默失效。"""

    def test_ts_readerKeysEqualTheContract(self):
        src = TS_READSIDE.read_text(encoding="utf-8")
        read = set(re.findall(r"facts\.([a-z_][a-z_0-9]*)", src))
        assert read == CONTRACT_KEYS, (
            f"前端取的 detail_json 键 {sorted(read)} 与结算契约 {sorted(CONTRACT_KEYS)} 不一致")

    def test_settleRunAlwaysWritesEveryContractKey(self, store, runOf):
        """三键恒在（不带计数的纯读数也补齐空值），否则读侧只能按"键在不在"猜版本。"""
        from neurova.aigc_studio import services

        rid = runOf("storyboard", "契约齐件")
        services._settleRun(store, rid, {"shots": 4}, "分镜")
        detail = json.loads(store.get_run(rid)["detail_json"])
        assert CONTRACT_KEYS <= set(detail), (
            f"结算少写契约键：{sorted(CONTRACT_KEYS - set(detail))}，读数={detail}")
