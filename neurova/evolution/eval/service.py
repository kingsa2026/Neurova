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
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from neurova.core.data_root import get_data_root
from neurova.core.logger import get_logger
from neurova.evolution.eval.config import EvolutionConfig, text_evolution_enabled
from neurova.evolution.eval.dataset import EvalDataset, dataset_dir_for
from neurova.evolution.eval.runner import EvolutionRunResult

logger = get_logger(__name__)

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

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
    holdout_before: float = 0.0
    holdout_after: float = 0.0
    # P0-2：真留出报告集证据（0.0 = 本轮无 heldout 集）。只供审批人参考，
    # 提案的可接受性仍由 runner 的 selection 判据决定。
    heldout_before: float = 0.0
    heldout_after: float = 0.0
    heldout_improvement: float = 0.0
    iterations_run: int = 0
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
        self._runs_dir = self._dir / "runs"

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

        runner = make_skill_evolution_runner(
            cfg,
            agent=agent or SimulatedAgent(model=cfg.judge_model),
            judge=judge,
            mutate=mutate,
            bench_gate=bench_gate,
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

        result = await runner.run(
            baseline_text=skill_text, artifact_type=artifact_type,
            dataset=dataset, iterations=iterations, noise_band=noise_band,
        )
        self._persist_run(skill_id, artifact_type, result)

        proposal: Optional[EvolutionProposal] = None
        if not result.rejected and result.changed:
            proposal = EvolutionProposal(
                proposal_id=f"evo_{uuid.uuid4().hex[:12]}",
                agent_id=self.agent_id,
                skill_id=skill_id,
                artifact_type=artifact_type,
                baseline_text=skill_text,
                improved_text=result.deployed_text,
                holdout_before=round(result.holdout_before, 4),
                holdout_after=round(result.holdout_after, 4),
                heldout_before=round(result.heldout_before, 4),
                heldout_after=round(result.heldout_after, 4),
                heldout_improvement=round(result.heldout_improvement, 4),
                iterations_run=result.iterations_run,
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
        try:
            band = await calibrate_noise_band(
                baseline_text=baseline_text, artifact_type=artifact_type,
                examples=split, evaluate_fn=runner._evaluate_avg,
                z=cfg.noise_z, repeats=cfg.noise_repeats,
            )
        except Exception as e:  # noqa: BLE001 - 校准失败不造证据，诚实降级为无带
            logger.debug("噪声带校准失败, 判据回退 min_improvement: %s", e)
            return None
        save_cached_band(cache_path, fingerprint, band)
        return band

    # ── 提案审批(人工闭环终点)──

    def list_proposals(self, status: Optional[str] = None) -> list[dict]:
        try:
            items = json.loads(self._proposals_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(items, list):
            return []
        if status:
            return [p for p in items if p.get("status") == status]
        return items

    def decide(self, proposal_id: str, approve: bool, registry: Any = None) -> bool:
        """批准=写回技能正文并持久化;拒绝=只改状态。**唯一变更点在此**。"""
        self._dir.mkdir(parents=True, exist_ok=True)
        lock_path = self._proposals_file.with_suffix(".lock")
        with lock_path.open("a+"):
            items = self.list_proposals()
            target = next((p for p in items if p.get("proposal_id") == proposal_id), None)
            if target is None or target.get("status") != STATUS_PENDING:
                return False
            if approve:
                ok = self._apply_to_skill(target, registry)
                if not ok:
                    return False
                target["status"] = STATUS_APPROVED
            else:
                target["status"] = STATUS_REJECTED
            target["decided_at"] = datetime.now(UTC).isoformat()
            self._write_proposals(items)
            return True

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

    def _persist_run(self, skill_id: str, artifact_type: str, result: EvolutionRunResult) -> None:
        try:
            self._runs_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            payload = {"skill_id": skill_id, "artifact_type": artifact_type,
                       "at": datetime.now(UTC).isoformat(), **result.to_dict()}
            (self._runs_dir / f"run_{ts}_{uuid.uuid4().hex[:6]}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            logger.debug("进化运行审计落盘失败: %s", e)

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
