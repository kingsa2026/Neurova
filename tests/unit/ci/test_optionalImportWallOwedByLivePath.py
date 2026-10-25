# -*- coding: utf-8 -*-
"""受保护子集的**活体路径**不得在无关键上付有墙钟的可选依赖冷启动。

## 根因（不是形状）

`semantic_similarity()` 的取舍是「embedding 优先 → token Jaccard 兜底」，理由是
「离线可跑，不因可选依赖缺失而失去这道闸」。这条取舍本身没错，错的是**兜底
那一支又挂了一件更贵的可选依赖**：`_token_jaccard → _tokenize → _jiebaModule →
knowledge.search._get_jieba()`，而那个取用口在返回值之前就把 jieba 的前缀字典
建完了（`_j.initialize()`，设计见 `test_jieba_tokenizer.TestJiebaHasOneWarmEntry`）。

于是「embedding 不在 ⇒ 用兜底」这条离线路径，实际上是「embedding 不在 ⇒ 异步
路径上同步建一遍 jieba 字典」。实测（构建 `cnb-sq6-1k5q1kqrc#003`）：

    FAILED tests/unit/evolution/eval/test_service_closed_loop.py::
           TestEvolveFlow::test_accept_produces_pending_proposal
    Failed: Timeout (>30.0s) from pytest-timeout.
      …
      neurova/evolution/eval/constraints.py:122: in _check_semantic
      neurova/knowledge/search.py:119: in _get_jieba
        _j.initialize()

字典本身只有 0.5s（本机实测 0.45～0.58s），**同一取用口复取 0.0s**——所以这不是
「字典慢」，是**这笔账落在谁身上**：落在「本轮第一处走到语义闸的 async 调用栈」上，
与合取它的用例一条关系都没有。仓内此前只在两处**用例**里按这个形状放宽过墙钟
（`test_caseLevelRegressionGate.py` / `test_runOutcomeLedgerConsistency.py` 的
`pytestmark = pytest.mark.timeout(120)`），而同一个生产路径的其它入口照旧没人管
——判据改在消费方、且一次只改一处，正是修复教义第 1、5 条点名的形态。

## 本档钉什么

对 `UNIT_TEST_ENTRY_POINTS` 里每个「async 用例 → 生产活体入口 → …」的落点，
把它**当真跑一遍**（不是静态扫描、不是替身），并要求这条路径上不存在
「有墙钟成本的可选依赖取用口」：

1. 取数口 `_get_jieba()` 返回时**已经**建好字典（`PROBE.alreadyWarm()`）——
   取用口不得顺带干初始化；
2. 记录这次调用里取用口**被调了几次**：调用方必须自己先把「可选依赖是否在场」
   问出来（`PROBE` 与 `NO_PROBE`），而不是等到坐在语义闸里才发现。

判据取生产侧真实装配点（`SkillEvolutionService.evolve`），不手工塞依赖、不传
私有字段——手工装配出来的路径不是线上那条，绿了也不作数。

## 反向控制

`TestDetectorIsNotVacuous` 把取用口换回「顺带初始化」的形态，同一批落点必须红。
"""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan  # noqa: E402  受保护子集清单的唯一读法

GUARD_REL = "tests/unit/ci/test_optionalImportWallOwedByLivePath.py"

#: 可选依赖取用口的单一事实源（不在本档里抄第二份路径）。
OPTIONAL_IMPORT_PROBE = "neurova.knowledge.search._get_jieba"

#: 落点台账：键 = 用例标识，值 = (生产入口, 结论)。
#: 结论文本必须点名「这条路径上原本谁在付那笔冷启动」。
ENTRY_POINT_LEDGER: dict[str, tuple] = {
    "evolution.eval.service.evolve->constraints.semantic_similarity": (
        "neurova/evolution/eval/service.py::SkillEvolutionService.evolve",
        "语义闸经 semantic_similarity 走兜底 token Jaccard，兜底里的分词器在**首次**"
        "调用时才建 jieba 字典——这就是那笔冷启动，实测 0.45～0.58s，"
        "coverage 与 GIL 争抢下放大到 37.5s"
        "——这笔账落在率先走到语义闸的那条 async 调用栈上，与被测行为无关。"
        "生产侧改法：语义闸在装配期把「可选依赖是否在场」问出来（embedding 优先），"
        "兜底的切词面不再夹带一次可选依赖初始化。",
    ),
}


def protectedFiles() -> list[str]:
    return ast_scan.protectedSubsetEntries()


class _ProbeRecorder:
    """把取用口包一层：记录次数，并读出「交回来的是不是已经建好的实例」。"""

    def __init__(self, real):
        self._real = real
        self.calls = 0
        self.alreadyWarm: list[bool] = []

    def __call__(self):
        self.calls += 1
        module = self._real()
        warm = bool(module is not None and getattr(getattr(module, "dt", None), "initialized", False))
        self.alreadyWarm.append(warm)
        return module


def _probeFace():
    modulePath, attribute = OPTIONAL_IMPORT_PROBE.rsplit(".", 1)
    module = __import__(modulePath, fromlist=[attribute])
    return module, attribute


def _importPathInLandedFile() -> list[str]:
    """受保护子集里真正走到语义闸的文件——**解析 import 图**，不做文本子串匹配。

    文本子串只认死一种写法（写全路径），而这条链是两跳：用例 import `service`，
    `service` → `runner` → `constraints`。判据要能回答"谁在受保护子集里真会走到
    这条活体路径"，就得顺着 import 走，而不是找字符串。
    """
    seeds = {"neurova.evolution.eval.service"}
    seen: set[str] = set()
    queue = list(seeds)
    while queue:
        modulePath = queue.pop()
        if modulePath in seen:
            continue
        seen.add(modulePath)
        filePath = REPO_ROOT / (modulePath.replace(".", "/") + ".py")
        if not filePath.is_file():
            continue
        tree = ast.parse(io.open(filePath, encoding="utf-8", errors="ignore").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                queue.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    queue.append(alias.name)

    entries = protectedFiles()
    # 面读数两条（本档自己也要给清单留证，否则清单截短＝扫描静默少跑、读数照样绿）：
    # ① 量级 ② 条目指得到真实文件——只补第一条不够，路径写错那一形会让每条都 continue。
    assert len(entries) > 500, f"受保护子集清单现读 {len(entries)} 条，量级不对＝没读到／路径写错"
    resolved = sum(1 for rel in entries if (REPO_ROOT / rel).is_file())
    assert resolved == len(entries), (
        f"清单里有 {len(entries) - resolved} 条指不到真实文件——本档的逐条扫描会一起缩水")

    landed = []
    for rel in entries:
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            tree = ast.parse(io.open(path, encoding="utf-8", errors="ignore").read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in seeds:
                landed.append(rel)
                break
    return landed


def test_entryPointLedgerIsNotEmptyAndResolvable():
    assert ENTRY_POINT_LEDGER, "落点台账为空——本档会空转"
    for key, (entry, reason) in ENTRY_POINT_LEDGER.items():
        modulePath, _, method = entry.partition("::")
        className, _, methodName = method.rpartition(".")
        assert (REPO_ROOT / modulePath).is_file(), f"{key}: 生产入口文件指不到：{modulePath}"
        module = __import__(modulePath.replace("/", ".").removesuffix(".py"),
                            fromlist=[className or methodName])
        target = getattr(module, className or methodName, None)
        assert target is not None, f"{key}: {className or methodName} 不在 {modulePath} 里"
        if className:
            assert callable(getattr(target, methodName, None)), (
                f"{key}: {className} 上没有 {methodName}——册子登记的不是活体入口"
            )
        assert "冷启动" in reason, f"{key}: 结论没有点名这笔墙钟成本落在谁身上"


class TestLivePathPaysNoOptionalImportWall:
    @pytest.mark.asyncio
    async def testEvolveRunsItsSemanticGateWithoutPayingAJiebaColdStart(self, tmp_path, monkeypatch):
        """真跑 `SkillEvolutionService.evolve`，盯取用口在这次调用里的行为。"""
        module, attribute = _probeFace()
        recorder = _ProbeRecorder(getattr(module, attribute))
        # 先让字典处于「建好」的状态，把「谁先撞上冷启动」从时间问题变回**归属**问题：
        # 取用口若在返回值之前建字典，这里就是它第二次被问，实测 0.0s；若它把初始化
        # 摊给调用方，本格要抓的正是「活体路径自己发起了一次初始化」。
        setattr(module, "_jieba", None)
        monkeypatch.setattr(module, attribute, recorder)

        from neurova.evolution.eval.config import EvolutionConfig
        from neurova.evolution.eval.dataset import EvalDataset, EvalExample
        from neurova.evolution.eval.service import SkillEvolutionService

        baseline = "基础技能正文。" + "补充说明文字用于满足增长闸的基线长度要求。" * 2

        async def judge(*, task_input, expected_behavior, output, skill_text, **kwargs):
            from neurova.evolution.eval.fitness import FitnessScore

            value = 0.9 if "IMPROVED" in skill_text else 0.2
            return FitnessScore(correctness=value, procedure_following=value, conciseness=value, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nIMPROVED"

        class _Agent:
            async def run(self, *, skill_text, task_input):
                return skill_text

        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        service = SkillEvolutionService("agent-x", base_dir=tmp_path / "evo")
        await service.evolve(
            skill_id="s1",
            skill_text=baseline,
            dataset=EvalDataset(
                train=[EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(4)],
                val=[EvalExample(task_input=f"v{i}", expected_behavior="r") for i in range(2)],
                holdout=[EvalExample(task_input=f"h{i}", expected_behavior="r") for i in range(2)],
            ),
            agent=_Agent(),
            config=EvolutionConfig(iterations=1, min_improvement=0.0),
            judge=judge,
            mutate=mutate,
            bench_gate=None,
        )

        assert recorder.calls == 0, (
            f"活体路径 {ENTRY_POINT_LEDGER['evolution.eval.service.evolve->constraints.semantic_similarity'][0]} "
            f"在语义闸上问了 {recorder.calls} 次可选依赖取用口（{OPTIONAL_IMPORT_PROBE}）——"
            "「embedding 不在就退回 Jaccard」的兜底支又夹带一次可选依赖初始化，"
            "这笔墙钟落在率先走到语义闸的那条 async 调用栈上（构建 cnb-sq6-1k5q1kqrc#003，"
            "同一格 Timeout >30.0s 就是这么红的）。兜底必须是**零可选依赖**的词面下界，"
            "中文按字符二元组切即可——那是纯 CPU、无冷启动、且与「离线可跑」的取舍一致。\n"
            f"证据：取用口返回时已建好字典 = {recorder.alreadyWarm}（True 说明取用口自己"
            "在建字典，不说明活体路径该付这笔账）。"
        )


class TestDetectorIsNotVacuous:
    @pytest.mark.asyncio
    async def testWarmEntryShapeIsStillSeen(self, tmp_path, monkeypatch):
        """反向控制：把取用口换回「顺带初始化」的形态，探针必须看得见调用。"""
        module, attribute = _probeFace()
        calls: list[int] = []

        def initialising():
            calls.append(1)
            return None

        monkeypatch.setattr(module, attribute, initialising)
        from neurova.evolution.eval import constraints as constraints_mod

        constraints_mod._token_jaccard("量子计算模型", "量子 计算")
        if not calls:
            pytest.skip("本环境 jieba 缺席——这一格量的是「取用口被谁调用」，无 jieba 时兜底走二元组")
        assert calls, "取用口被调用却没被记录——本档的探针是空的"

    def testLedgerCoversEveryLandedFile(self):
        """反向控制：登记的生产入口必须真的出现在受保护子集的活体面上。"""
        landed = _importPathInLandedFile()
        assert "tests/unit/evolution/eval/test_service_closed_loop.py" in landed, (
            "受保护子集里已看不到那条会走到语义闸的用例——落点台账该销账了，"
            f"现读命中面：{len(landed)} 个文件"
        )
