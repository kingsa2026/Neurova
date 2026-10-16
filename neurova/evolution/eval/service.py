"""文本进化服务 — 把 runner 接成可被 API/pipeline 消费的生产闭环。

链路(全环):
  选目标技能 → 评测集(golden → 会话挖掘 → 合成 三级回退)
    → SkillEvolutionRunner(留出集 + 约束闸 + bench 门)
    → 通过 → 落 pending 提案(proposals.json,含改进前后与三集分数)
    → 人工批准 → 写回技能正文;拒绝 → 标记 rejected
 审计:每次运行落 data/agents/<id>/evolution/runs/*.json。

执行器默认用 SimulatedAgent
只需替换 agent 参数。

提案绝不自动应用:approve 必须显式调用(C10 评审闸哲学在进化面的延伸)。
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from neurova.core.data_root import get_data_root
from neurova.core.logger import get_logger
from neurova.evolution.eval.config import EvolutionConfig, text_evolution_enabled
from neurova.evolution.eval.dataset import EvalDataset, dataset_dir_for
from neurova.evolution.eval.runner import EvolutionRunResult
from neurova.evolution.proposal_lifecycle import (
    ProposalStatus,
    ProposalTransitionError,
    assert_can_decide,
    normalize_legacy_status,
    require_approver,
)

logger = get_logger(__name__)

# 状态字面量收口到提案生命周期契约（§6-2 阶段①，单一事实源）。
# 历史行的 "approved"（批准即生效）在读路径归一为规范值 "applied"；
# STATUS_APPROVED 随死状态退役——批准是原子决定，终态即 applied。
STATUS_PENDING = ProposalStatus.PENDING.value
STATUS_APPLIED = ProposalStatus.APPLIED.value
STATUS_REJECTED = ProposalStatus.REJECTED.value


def best_anchor_from_ledger(entries: Optional[list[dict]]) -> Optional[float]:
    """历史最优留出分（P2-4 锚定地板）：台账里各次运行的绝对 holdout_after 最大值。

    台账自 2026-10-07 起记录绝对留出分（runner 端 patch）；旧条目无此键、
    参与不了锚——锚随台账自然预热，不另造第二份历史账本。
    """
    values = [e.get("holdout_after") for e in (entries or [])
              if isinstance(e, dict) and isinstance(e.get("holdout_after"), (int, float))]
    return max(values) if values else None

class SimulatedAgent:
    """技能→输出的模拟执行器。

    llm_call 可注入离线测试;默认走 llm_router。
    """

    def __init__(self, llm_call: Any = None, model: str = ""):
        self._llm_call = llm_call
        self.model = model

    async def run(self, *, skill_text: str, task_input: str) -> str:
        messages = [
            {
                "role": "system",
                "content": "严格按照以下技能指令完成任务,只输出任务结果本身。\n\n"
                f"【技能指令】\n{skill_text}",
            },
            {"role": "user", "content": task_input},
        ]
        if self._llm_call is not None:
            result = await self._llm_call(messages, self.model)
        else:
            try:
                from neurova.llm.multi_model_client import get_multi_model_client

                result = await get_multi_model_client().chat(messages, model=self.model or None)
            except Exception as e:  # noqa: BLE001
                logger.debug("SimulatedAgent LLM 失败: %s", e)
                return ""
        if not result.get("success"):
            return ""
        return str(result.get("response") or "").strip()


#: 未记基座的分组键：读数里"这条证据没绑定过任何型号"必须自成一组、不许消失，
#: 也不许被折进某个型号（折进去就是把未知读成已知）。
UNRECORDED_MODEL_KEY = "__unrecorded__"


def resolveModelUnderTest(executor: Any) -> str:
    """这轮评测实际跑在**哪个基座**上——由真正拿去执行的那个对象推导。

    与 `isRealAgentTrajectoryExecutor` 同一条纪律：能力/事实**不许写成旗标或手工传参**，
    否则实装被摘掉后读数照样说真，而下游有理由继续信它。

    三种如实形态：
    - 模拟臂自己带着执行用的 `model` ⇒ 直接回报那个值；没指名 ⇒ `"client_default"`
      （事实是"交给多模型客户端按路由选"，不是某个型号）。注意默认装配的
      `SimulatedAgent(model=cfg.judge_model)`——判分模型顺手当了被执行模型，
      这一格第一次把这件事变成可见读数。
    - 真轨迹臂 ⇒ `"agent_routed"`：模型选择发生在 agent 的请求期，执行器自己不持模型，
      编一个型号就是伪造"已绑定基座的证据"。
    - 取不到 ⇒ 空串（未记）。不兜默认名——兜一个出来，覆盖读数就会多出一个假分组。

    本值只作**读数**：`accept/reject` 的判定链不许读它（用户裁定"只出读数不判"，
    判据链里出现即红，见 `tests/.../test_evalResultIsKeyedByModelUnderTest.py`）。
    """
    if executor is None:
        return ""
    if isRealAgentTrajectoryExecutor(executor):
        return "agent_routed"
    model = getattr(executor, "model", None)
    if isinstance(model, str):
        return model.strip() or "client_default"
    return ""


def modelCoverageReadout(proposals: list) -> dict:
    """把"哪些验收证据绑定过哪个基座"按型号分组——只呈报，不判定。

    存在的理由：本仓基座是管理员运行时可换的配置，而一条技能正文的 `holdout_after`
    从来不记录它跑在哪个模型上。换基座之后，历史批准记录对新模型**没有任何证据**——
    这一格把那件看不见的事量出来，供人决定要不要复跑（复跑触发点的裁定见 §7.1-Q3，
    本批不进判据）。未记基座的条目折进 `UNRECORDED_MODEL_KEY`，不消失也不冒充已知型号。
    """
    byModel: dict = {}
    for item in proposals or []:
        if not isinstance(item, dict):
            continue
        model = str(item.get("model_under_test") or "").strip() or UNRECORDED_MODEL_KEY
        row = byModel.setdefault(model, {"proposals": 0, "approved": 0})
        row["proposals"] += 1
        # 批准词值取**写侧那一份**（`STATUS_APPLIED`——批准即应用是本仓提案生命周期词汇），
        # 不在读数里再造第二个词；端点入参的 "approved" 与它的对不上属既有口径差，另批。
        if str(item.get("status") or "") == STATUS_APPLIED:
            row["approved"] += 1
    return {
        "by_model": byModel,
        "unrecorded_key": UNRECORDED_MODEL_KEY,
        "total": sum(r["proposals"] for r in byModel.values()),
    }


def resolveEvolutionExecutor(agent: Any = None, *, config: Optional[EvolutionConfig] = None) -> Any:
    """生产装配路径的执行器**唯一出处**。

    为什么要收成一处：`evolve()` 与 `ab_compare()` 过去各写一遍
    `agent or SimulatedAgent(model=...)`——同一条回落存在两份定义（教义第 6 条）。
    后果不是难看，是**改不动**：接真轨迹时只会改到其中一条，另一条静默留在旧语义上，
    而两条路径都自称"评测"。历史代价本仓已实测过一次：`agent=None` 的回落会接上
    **真**多模型客户端，三个用例因此真花 LLM 配额并把整目录跑测挂死
    （来历见 `tests/unit/evolution/eval/conftest.py` 首段）。

    本函数只回答"装配时用什么执行器"。`SkillEvolutionRunner` 自己的离线兜底
    （`runner._DefaultAgent`）不动——那是直接构造对象时的库层默认，不是装配路径；
    §8 前置 2 的探针问的必须是这里，不是那里。
    """
    if agent is not None:
        return agent
    cfg = config or EvolutionConfig()
    return SimulatedAgent(model=cfg.judge_model)


def isRealAgentTrajectoryExecutor(executor: Any) -> bool:
    """这道能力问的是"**执行判据的那一步是否真跑 agent 回合**"（§8 前置 2）。

    能力**不许写成常量旗标**：旗标会在实装被摘掉之后继续说真，而那比"没做实"更糟——
    下游有理由继续信任这条判据。所以这里由**结构**推导：真轨迹执行器必须既持有
    `agent_ref`（AGENTS.md §3 的深模块注入约定），又显式声明自己跑真回合；缺一即 False。
    评测替身与 `SimulatedAgent`/`_DefaultAgent` 都不带这两样，因此不会被误认成同域。

    唯一读方是 `rsi/automation_prerequisites.probeRealTrajectoryExecutor`，它问的必须是
    **生产装配点实际拿到的执行器**（`resolveEvolutionExecutor`），不是 runner 的离线兜底
    `_DefaultAgent`——换掉兜底就把旗标翻真，那是弱保护（台账 §6-97 记的这处口径缺陷）。
    """
    if executor is None:
        return False
    if not getattr(executor, "agent_ref", None):
        return False
    declares = getattr(executor, "declaresRealAgentTrajectory", None)
    return bool(declares()) if callable(declares) else False


#: `_persist_run` 生成的运行 id 形态：`run_` + 时间戳(数字与 T) + `_` + 6 位十六进制。
#: 读侧按它拒掉一切带分隔符/`..`/绝对路径的输入（见 `SkillEvolutionService.readRun`）。
_RUN_ID_PATTERN = re.compile(r"^run_[0-9A-Za-z_]+$")


@dataclass
class EvolutionProposal:
    """一条待审进化提案(永不自动应用)。"""

    proposal_id: str
    agent_id: str
    skill_id: str
    artifact_type: str
    baseline_text: str
    improved_text: str
    status: str = STATUS_PENDING
    # §6-95 后半：这条提案凭哪一次运行出街。审计文件此前只写不读（`_persist_run` 落
    # `runs/*.json`，全仓零读方），关联键落在这里，详情端点才有一条既有的读路径可走
    # ——不新建端点，也不靠文件名猜。改动之前落盘的旧记录没有这一键（空串 = 当轮未记）。
    run_id: str = ""
    # M-C：这条验收证据跑在哪个基座上（`resolveModelUnderTest` 由执行器对象推导）。
    # 只作读数与分组证据，不参与 accept/reject；旧记录没这一键 ⇒ 空串 = 未记，
    # 在覆盖读数里自成一组，不折进任何型号。
    model_under_test: str = ""
    holdout_before: float = 0.0
    holdout_after: float = 0.0
    # P0-2：真留出报告集证据（0.0 = 本轮无 heldout 集）。只供审批人参考，
    # 提案的可接受性仍由 runner 的 selection 判据决定。
    heldout_before: float = 0.0
    heldout_after: float = 0.0
    heldout_improvement: float = 0.0
    iterations_run: int = 0
    # 例级不退化门读数（§8 前置 1）：容忍度内的退化照样出提案，但审批人必须
    # 看见"均值涨了而这条用例被改坏了"。形状只由 runner 侧 caseGateReadout()
    # 定义一处，此处只搬运不另算。
    case_gate: dict = field(default_factory=dict)
    created_at: str = ""
    decided_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

class SkillEvolutionService:
    """单 agent 的文本进化服务(API/pipeline 共用门面)。"""

    def __init__(self, agent_id: str, base_dir: Optional[Path] = None):
        self.agent_id = agent_id
        # 显式 base_dir 就是进化目录本身；缺省才按数据根推出 agents/<id>/evolution
        self._dir = Path(base_dir) if base_dir else get_data_root() / "agents" / str(agent_id) / "evolution"
        self._proposals_file = self._dir / "proposals.json"
        self._history_ledger = None  # P1-4：懒创建
        self._skill_journal = None  # P2-11：懒创建

    @property
    def journal(self):
        """P2-11 技能正文日志仓（journal.git）——批准即 commit 的可追溯链。"""
        if self._skill_journal is None:
            from neurova.evolution.eval.skill_journal import SkillJournal

            self._skill_journal = SkillJournal(self._dir / "journal.git")
        return self._skill_journal

    @property
    def ledger(self):
        """P1-4 编辑历史台账（history/<skill>.jsonl）——runner 逐候选记账 +
        变异器回喂已证伪假设的数据源。"""
        if self._history_ledger is None:
            from neurova.evolution.eval.history_ledger import EvolutionLedger

            self._history_ledger = EvolutionLedger(self._dir / "history")
        return self._history_ledger

    # ── 评测集三级回退 ──

    def _golden_dataset(self, skill_id: str) -> Optional[EvalDataset]:
        path = dataset_dir_for(skill_id)
        ds = EvalDataset.load(path)
        return ds if ds.all_examples else None

    async def build_dataset(
        self,
        skill_id: str,
        skill_text: str,
        *,
        source: str = "auto",
        messages: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[EvalDataset]:
        """golden → 会话挖掘 → 合成;全空返回 None。

        物化成功即喂结晶入库闸的语料工件（P1-1）：入库围栏与评测消费
        同一份题面——评测集长什么样，围栏就守什么。
        """
        ds = await self._build_dataset_inner(
            skill_id, skill_text, source=source, messages=messages)
        if ds is not None and ds.all_examples:
            from neurova.evolution.eval.eval_corpus import update_eval_corpus

            update_eval_corpus(self.agent_id, ds)
        return ds

    async def _build_dataset_inner(
        self,
        skill_id: str,
        skill_text: str,
        *,
        source: str = "auto",
        messages: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[EvalDataset]:
        """golden → 会话挖掘 → 合成;全空返回 None。"""
        if source in ("auto", "golden"):
            ds = self._golden_dataset(skill_id)
            if ds:
                return ds
            if source == "golden":
                return None
        cfg = EvolutionConfig()
        if source in ("auto", "mined"):
            from neurova.evolution.eval.miner import build_dataset as mine_dataset
            from neurova.evolution.eval.miner import messages_from_sessions

            msgs = messages if messages is not None else messages_from_sessions(self.agent_id)
            ds = await mine_dataset(
                skill_name=skill_id, skill_text=skill_text, messages=msgs, seed=cfg.seed
            )
            if ds.all_examples:
                return ds
            if source == "mined":
                return None
        from neurova.evolution.eval.synthetic import SyntheticDatasetBuilder

        ds = await SyntheticDatasetBuilder(cfg).generate(skill_text, "skill")
        return ds if ds.all_examples else None

    # ── 进化主流程 ──

    async def evolve(
        self,
        *,
        skill_id: str,
        skill_text: str,
        dataset: Optional[EvalDataset] = None,
        iterations: Optional[int] = None,
        artifact_type: str = "template",
        agent: Any = None,
        config: Optional[EvolutionConfig] = None,
        judge: Any = None,
        mutate: Any = None,
        bench_gate: Any = None,
    ) -> tuple[EvolutionRunResult, Optional[EvolutionProposal]]:
        """跑一次进化;通过闸 → 产出 pending 提案(不落库技能,等人批准)。

        总开关关闭 → 拒绝(reason=disabled),不装配 runner。
        judge/mutate/bench_gate/agent 可注入(离线测试与未来真实执行器接线)。
        """
        cfg = config or EvolutionConfig()
        result = EvolutionRunResult(baseline_text=skill_text, deployed_text=skill_text)
        if not text_evolution_enabled():
            result.rejected = True
            result.reject_reason = "disabled"
            return result, None
        if dataset is None:
            dataset = await self.build_dataset(skill_id, skill_text)
        if not dataset or not dataset.all_examples:
            result.rejected = True
            result.reject_reason = "empty_dataset"
            return result, None

        # P0-2 holdout 防污染：配置了 heldout_ratio 且数据集没有真留出集时，
        # 从 holdout 尾部划出（确定性）。heldout 只做验收证据，不参与判定。
        if cfg.heldout_ratio > 0 and not dataset.heldout:
            dataset = dataset.carve_heldout(cfg.heldout_ratio)

        from neurova.evolution.eval.factory import make_skill_evolution_runner

        # 执行器在此**一次** resolve（装配单点不变），基座读数由**真正拿去执行的那个对象**
        # 推导——手工传一个模型名就是伪造证据。
        executor = resolveEvolutionExecutor(agent, config=cfg)
        modelUnderTest = resolveModelUnderTest(executor)
        runner = make_skill_evolution_runner(
            cfg,
            agent=executor,
            judge=judge,
            mutate=mutate,
            bench_gate=bench_gate,
            ledger=self.ledger,
        )
        if runner is None:  # factory 与上面双保险
            result.rejected = True
            result.reject_reason = "disabled"
            return result, None

        # P0-1 噪声地板：noise_repeats>1 时对同一基线自动校准 δ（按数据集
        # 指纹缓存，同一批用例不重复花评测预算）；校准失败诚实降级为无带
        # （判据回退 min_improvement），不阻断进化本身。
        noise_band = None
        if cfg.noise_repeats > 1:
            noise_band = await self._noise_band_for(cfg, runner, dataset, artifact_type,
                                                    baseline_text=skill_text)

        # P2-4 历史最优锚：台账里本技能各次运行的绝对留出分最大值
        # （锚随台账预热；无记录 = None = 本轮只有无技能锚参与）
        anchor_best = best_anchor_from_ledger(
            self.ledger.recent(skill_id)) if cfg.anchor_floor_enabled else None

        result = await runner.run(
            baseline_text=skill_text, artifact_type=artifact_type,
            dataset=dataset, iterations=iterations, noise_band=noise_band,
            ledger_key=skill_id, anchor_best=anchor_best,
        )
        run_id = self._persist_run(skill_id, artifact_type, result,
                                   model_under_test=modelUnderTest)

        proposal: Optional[EvolutionProposal] = None
        if not result.rejected and result.changed:
            proposal = EvolutionProposal(
                proposal_id=f"evo_{uuid.uuid4().hex[:12]}",
                agent_id=self.agent_id,
                skill_id=skill_id,
                artifact_type=artifact_type,
                run_id=run_id,
                model_under_test=modelUnderTest,
                baseline_text=skill_text,
                improved_text=result.deployed_text,
                holdout_before=round(result.holdout_before, 4),
                holdout_after=round(result.holdout_after, 4),
                heldout_before=round(result.heldout_before, 4),
                heldout_after=round(result.heldout_after, 4),
                heldout_improvement=round(result.heldout_improvement, 4),
                iterations_run=result.iterations_run,
                case_gate=result.caseGateReadout(),
                created_at=datetime.now(UTC).isoformat(),
            )
            self._append_proposal(proposal)
            logger.info(
                "文本进化提案产出: %s/%s (holdout %.2f→%.2f)",
                self.agent_id, skill_id, result.holdout_before, result.holdout_after,
            )
        return result, proposal

    # ── P0-1 噪声校准 ──

    async def _noise_band_for(self, cfg: EvolutionConfig, runner: Any,
                              dataset: EvalDataset, artifact_type: str,
                              *, baseline_text: str):
        """按数据集指纹缓存校准噪声带；评测集选取与 runner 终审同源
        （evaluation_split 单一事实源）。"""
        from neurova.evolution.eval.calibration import (
            calibrate_noise_band,
            dataset_fingerprint,
            load_cached_band,
            save_cached_band,
        )
        from neurova.evolution.eval.dataset import evaluation_split

        split = evaluation_split(dataset)
        if not split:
            return None
        fingerprint = dataset_fingerprint(split)
        cache_path = self._dir / "calibration.json"
        cached = load_cached_band(cache_path, fingerprint)
        if cached is not None:
            return cached
        # P2-9 语义修正：判分不可用时不校准不缓存——给死 judge 做的校准
        # 是伪证据（全 0 分的 sd=0 会被当成"确定性评测"）。
        if not await runner._judge_available(baseline_text, split, artifact_type):
            return None
        try:
            band = await calibrate_noise_band(
                baseline_text=baseline_text, artifact_type=artifact_type,
                examples=split, evaluate_fn=runner._evaluate_avg,
                z=cfg.noise_z, repeats=cfg.noise_repeats,
            )
        except Exception as e:  # noqa: BLE001 - 校准失败不造证据，诚实降级为无带
            logger.debug("噪声带校准失败, 判据回退 min_improvement: %s", e)
            return None
        # 校准期出现单例失败（P2-9 记 0）→ 得分被污染、δ 不可信，不缓存不使用
        if getattr(runner, "_run_eval_errors", 0):
            logger.debug("校准期出现单例评测失败, 丢弃本次噪声带")
            return None
        save_cached_band(cache_path, fingerprint, band)
        return band

    # ── P1-7b 双臂试评 ──

    async def ab_compare(self, *, baseline_text: str, candidate_text: str,
                         dataset: EvalDataset, config: EvolutionConfig,
                         agent: Any = None, judge: Any = None) -> dict:
        """双臂试评：两份正文在同一任务集上、同判分器对照。

        任务集：heldout 优先（P0-2 真留出集，未被搜索过程消耗），否则
        判据集（evaluation_split）。**只读评测**——不产提案、不改技能、
        不入台账，供审批人在 decide 之前对候选做干净集核验。
        """
        from neurova.evolution.eval.dataset import evaluation_split

        # 执行面先resolve：kind 必须由**真正拿去执行的那个对象**推导，两条返回路径
        # 都要带——模拟面与真轨迹面的数字混成一栏时，审批人会拿模拟分当线上证据，
        # 不可逆的是解释而不是数据。
        executor = resolveEvolutionExecutor(agent, config=config)
        kind = "real_agent" if isRealAgentTrajectoryExecutor(executor) else "simulated"
        # 基座读数同由**这个**执行器推导；两条返回路径都得带——空集那条若不带，
        # "没跑成"就会被读成"没有这个维度"。
        modelUnderTest = resolveModelUnderTest(executor)

        split = dataset.heldout or evaluation_split(dataset)
        if not split:
            return {"task_split": "none", "n": 0, "baseline_avg": 0.0,
                    "candidate_avg": 0.0, "delta": 0.0, "per_task": [],
                    "executor_kind": kind, "model_under_test": modelUnderTest}
        if judge is None:
            from neurova.evolution.eval.fitness import LLMJudge

            judge = LLMJudge(config)
        from neurova.evolution.eval.runner import SkillEvolutionRunner

        runner = SkillEvolutionRunner(
            config, judge=judge,
            agent=executor,
        )
        # 同包装配：复用 runner 的评测路径（judge 适配/执行器注入同源），
        # 禁止另写第二套打分。
        baseline_avg, baseline_details = await runner._evaluate(baseline_text, split, "skill")
        candidate_avg, candidate_details = await runner._evaluate(candidate_text, split, "skill")
        per_task = [
            {"task_input": ex.task_input,
             "baseline": round(float(b), 4), "candidate": round(float(c), 4)}
            for (ex, b, _o, _f, _bf, _env), (_ex2, c, _o2, _f2, _cf, _env2)
            in zip(baseline_details, candidate_details)
        ]
        return {
            "task_split": "heldout" if dataset.heldout else "selection",
            "n": len(split),
            "baseline_avg": round(float(baseline_avg), 4),
            "candidate_avg": round(float(candidate_avg), 4),
            "delta": round(float(candidate_avg - baseline_avg), 4),
            "per_task": per_task,
            "executor_kind": kind,
            "model_under_test": modelUnderTest,
        }

    # ── 提案审批(人工闭环终点)──

    def list_proposals(self, status: Optional[str] = None) -> list[dict]:
        try:
            items = json.loads(self._proposals_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(items, list):
            return []
        # 历史行 "approved" 读路径归一为规范值 "applied"（§6-2 阶段①；
        # 下一次 decide 落盘时整表落规范值）
        items = [{**p, "status": normalize_legacy_status(p.get("status"))}
                 for p in items if isinstance(p, dict)]
        if status:
            return [p for p in items if p.get("status") == status]
        return items

    def decide(self, proposal_id: str, approve: bool, registry: Any = None,
               approver: str = "") -> bool:
        """批准=写回技能正文并持久化;拒绝=只改状态。**唯一变更点在此**。

        审批语义单源于提案生命周期契约（§6-2 阶段①）：仅 PENDING 可被决定
        （assert_can_decide）；批准必须记录非空审批人（require_approver）——
        决策可归因，此前文本臂缺这层（API 拿到认证身份却没传进 decide）。
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        lock_path = self._proposals_file.with_suffix(".lock")
        with lock_path.open("a+"):
            items = self.list_proposals()
            target = next((p for p in items if p.get("proposal_id") == proposal_id), None)
            if target is None:
                return False
            try:
                assert_can_decide(target.get("status", ""))
            except ProposalTransitionError:
                return False
            if approve:
                approver = require_approver(approver, action="批准提案")
                ok = self._apply_to_skill(target, registry)
                if not ok:
                    return False
                target["status"] = STATUS_APPLIED
                self._journal_append(target)  # P2-11：批准即 commit（失败降级不阻断）
            else:
                target["status"] = STATUS_REJECTED
            if approver.strip():
                target["decided_by"] = approver.strip()
            target["decided_at"] = datetime.now(UTC).isoformat()
            self._write_proposals(items)
            return True

    def _journal_append(self, target: dict) -> None:
        """P2-11：批准即提交——正文变更进 per-agent git 日志仓。git 缺失
        或失败诚实降级（journal.append 返回 None），审批主链不受损。"""
        try:
            self.journal.append(
                skill_id=str(target.get("skill_id") or ""),
                before=str(target.get("baseline_text") or ""),
                after=str(target.get("improved_text") or ""),
                proposal_id=str(target.get("proposal_id") or ""),
                evidence={
                    "holdout_before": target.get("holdout_before"),
                    "holdout_after": target.get("holdout_after"),
                    "heldout_improvement": target.get("heldout_improvement"),
                },
            )
        except Exception as e:  # noqa: BLE001 - 日志仓故障不阻断审批主链
            logger.debug("技能日志仓写入失败: %s", e)

    def _apply_to_skill(self, proposal: dict, registry: Any) -> bool:
        from neurova.skills.skill_service import SkillService

        try:
            svc = SkillService(agent_id=self.agent_id)
            info = svc.get_skill_info(proposal["skill_id"])
            if info is None:
                logger.debug("提案 %s 目标技能已不存在", proposal.get("proposal_id"))
                return False
            config = dict((info.get("manifest") or {}).get("config") or {})
            if not config:
                logger.debug("技能 %s 无 manifest.config,无法应用提案", proposal["skill_id"])
                return False
            config["context_template"] = proposal["improved_text"]
            version = str(info.get("version") or "1.0.0")
            parts = version.split(".")
            while len(parts) < 3:
                parts.append("0")
            parts[2] = str(int(parts[2]) + 1)
            # 提案应用 = 人工批准终点（内容已过留出集/约束/bench 门），
            # 豁免质量门避免"进化的门"与"维护的门"互相打架。这里直接按
            # 老契约调用（测试替身/applied 探针依赖精确的调用形态）。
            return svc.update_auto_skill(
                proposal["skill_id"], version=".".join(parts), config=config
            )
        except Exception as e:  # noqa: BLE001 - 应用失败提案保持 pending
            logger.debug("应用进化提案失败: %s", e)
            return False

    # ── 审计落盘 ──

    def _persist_run(self, skill_id: str, artifact_type: str,
                     result: EvolutionRunResult,
                     *, model_under_test: str = "") -> str:
        """落一次运行的审计文件，回它的 `run_id`（写失败回空串，不假造一个 id）。

        返回 id 而不是 None：提案要能指回这次运行（§6-95 后半）。"文件没落成"与
        "落成了但没人知道它的名字"是两件事——前者必须让提案侧记成空串，否则详情面会
        拿着一个不存在的 id 报"运行不见了"，把写侧的失败洗成读侧的失败。
        """
        try:
            runsDir = self._runsDir()
            runsDir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            runId = f"run_{ts}_{uuid.uuid4().hex[:6]}"
            payload = {"skill_id": skill_id, "artifact_type": artifact_type,
                       "at": datetime.now(UTC).isoformat(),
                       "run_id": runId,
                       # 审计文件也要绑定基座：审批人日后追问"这条证据在哪个模型上量的"，
                       # 只能靠这次运行的落盘字节，不能靠内存里的提案。
                       "model_under_test": model_under_test,
                       **result.to_dict()}
            (runsDir / f"{runId}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return runId
        except OSError as e:
            logger.debug("进化运行审计落盘失败: %s", e)
            return ""

    # ── 审计运行的读面（§6-95 后半：runs/*.json 从"只写不读"接上读者）──

    def _runsDir(self) -> Path:
        """运行审计目录的唯一出处（写侧与读侧共用，不各拼一份）。"""
        return Path(self._dir) / "runs"

    def runLookup(self, run_id: str) -> tuple[str, Optional[dict]]:
        """一次取数回两件事：`(状态, 内容)`——详情面据此出声，不静默省略。

        - `none_recorded`：提案没带 run_id（改动之前的旧记录，或那次落盘失败）；
        - `missing`：带了 id 但文件不在（被清、被搬，或 id 形态根本不合法）；
        - `attached`：取回了内容。

        为什么要有这一层而不是让 `readRun` 只回一个 None：把"当轮没记"与"记录不见了"
        混成同一个读数，详情面就只能在谎报与沉默之间选一个——教义第 2 条禁止的形态。
        状态与内容同处一出（而不是两个方法各读一遍），是为了让这两件事不可能互相矛盾。
        """
        if not run_id:
            return "none_recorded", None
        payload = self.readRun(run_id)
        return ("attached", payload) if payload is not None else ("missing", None)

    def readRun(self, run_id: str) -> Optional[dict]:
        """按 id 取回一次运行的审计内容；取不到回 None（不抛、不猜）。

        `run_id` 来自磁盘上的提案记录，等于来自外部输入 ⇒ 只认本仓自己生成的文件名
        形态（`run_` + 字母数字）：路径分隔符、`..`、绝对路径一律拒读。这一跳不校验
        就等于给提案文件开一个"读仓内任意 json"的入口。
        """
        if not isinstance(run_id, str) or not _RUN_ID_PATTERN.match(run_id):
            return None
        try:
            payload = json.loads(
                (self._runsDir() / f"{run_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _append_proposal(self, proposal: EvolutionProposal) -> None:
        items = self.list_proposals()
        items.append(proposal.to_dict())
        del items[:-50]  # 有界:只留最近 50 条
        self._write_proposals(items)

    def _write_proposals(self, items: list[dict]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._proposals_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._proposals_file)
