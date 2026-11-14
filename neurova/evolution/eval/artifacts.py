"""V5 可部署工件 —— 冠军与非劣变体的版本化打包（2026-11-14）。

对照档：docs/08-research/videoevolve_vs_neurova_harness_evolution_comparison_2026-11-14.md §3-V5。
论文（arXiv 2610.01766）：开发期搜索结束，**部署的是固定 harness**——冠军与
非劣变体（Pareto 多档）是可交付物，不是散落在运行审计里的中间读数。
HarnessPro 对照档登记的残差（N5 工件化）：本仓的 pareto_variants 此前只是
结果面读数＋adopt-variant 单点采纳，没有版本化工件形态。

本模块三件事：
1. `buildArtifact`：把一次过门运行打包成工件（冠军正文＋基线正文＋非劣变体
   ＋证据指针 run/proposal/journal commit＋成本指纹＋面读数＋评分），纯装配；
2. `ArtifactStore`：工件的落盘与读取（<进化目录>/artifacts/*.json，有界由
   调用方治理）；id 只认自家文件名形态（与 run 审计读侧同款路径纪律）；
3. 状态机：pending（提案产出）→ applied（人工批准）/ rolled_back（按工件
   回滚）——状态只由 service 的批准/回滚路径改写。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 工件 id 形态：`art_` + 时间戳 + `_` + 6 位十六进制（与 run 审计同款口径）。
#: 读侧按它拒掉一切带分隔符/`..`/绝对路径的输入。
_ARTIFACT_ID_PATTERN = re.compile(r"^art_[0-9A-Za-z_]+$")

#: 工件状态词值单源（service 批准/回滚路径与 API 读数都取这里）。
ARTIFACT_PENDING = "pending"
ARTIFACT_APPLIED = "applied"
ARTIFACT_ROLLED_BACK = "rolled_back"


def buildArtifact(*, skill_id: str, artifact_type: str, proposal: Dict[str, Any],
                  result: Any, config: Any) -> Dict[str, Any]:
    """把一次过门运行装配成可部署工件（纯装配，不落盘）。

    `proposal` 取 to_dict() 形态（deployment_cost/surface 等读数都在）；
    `result` 取 EvolutionRunResult（pareto_variants/评分在这里）。
    """
    from neurova.evolution.eval.surfaces import surfaceReadout

    return {
        "status": ARTIFACT_PENDING,
        "skill_id": str(skill_id or ""),
        "artifact_type": str(artifact_type or ""),
        "experiment_fingerprint": str(proposal.get("experiment_fingerprint") or ""),
        # 冠军 = 提案正文（质量最优者）；基线 = 批准前的在役正文（回滚锚点）
        "champion_text": str(proposal.get("improved_text") or ""),
        "baseline_text": str(proposal.get("baseline_text") or ""),
        # Pareto 非劣变体（N1 多档交付的可部署形态；按预算选档走 adopt-variant）
        "variants": list(getattr(result, "pareto_variants", None) or []),
        "scores": {
            "holdout_before": round(float(getattr(result, "holdout_before", 0.0) or 0.0), 4),
            "holdout_after": round(float(getattr(result, "holdout_after", 0.0) or 0.0), 4),
            "heldout_before": round(float(getattr(result, "heldout_before", 0.0) or 0.0), 4),
            "heldout_after": round(float(getattr(result, "heldout_after", 0.0) or 0.0), 4),
            "heldout_improvement": round(
                float(getattr(result, "heldout_improvement", 0.0) or 0.0), 4),
        },
        # 证据指针：凭哪次运行、哪条提案、哪个 journal commit 出街
        "evidence": {
            "run_id": str(proposal.get("run_id") or ""),
            "proposal_id": str(proposal.get("proposal_id") or ""),
            "journal_commit": None,
        },
        # 成本指纹（V6 部署形态成本差）与面读数（V3 可进化面）
        "cost": dict(proposal.get("deployment_cost") or {}),
        "surface": surfaceReadout(artifact_type, config),
    }


class ArtifactStore:
    """工件的落盘与读取（每 agent 进化目录下的 artifacts/）。"""

    def __init__(self, base_dir: Path):
        self._dir = Path(base_dir)

    def _dirMkdir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, artifact: Dict[str, Any]) -> str:
        """落一份工件，回它的 artifact_id（写失败上抛 OSError——工件丢了必须
        让装配方知道，不能像审计面那样静默降级：工件是交付物不是附注）。"""
        self._dirMkdir()
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        artifact_id = f"art_{ts}_{uuid.uuid4().hex[:6]}"
        payload = {"artifact_id": artifact_id,
                   "created_at": datetime.now(UTC).isoformat(),
                   **artifact}
        (self._dir / f"{artifact_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return artifact_id

    def get(self, artifact_id: Any) -> Optional[Dict[str, Any]]:
        """按 id 取工件；取不到回 None（不抛、不猜）。id 来自磁盘记录 =
        外部输入 ⇒ 只认自家文件名形态（路径分隔符/`..`/绝对路径一律拒读）。"""
        if not isinstance(artifact_id, str) or not _ARTIFACT_ID_PATTERN.match(artifact_id):
            return None
        try:
            payload = json.loads(
                (self._dir / f"{artifact_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def list(self, skill_id: str = "") -> List[Dict[str, Any]]:
        """列工件（新→旧）；给了 skill_id 只列该技能的。读失败回空表。"""
        if not self._dir.exists():
            return []
        rows: List[Dict[str, Any]] = []
        try:
            paths = sorted(self._dir.glob("art_*.json"), reverse=True)
        except OSError:
            return []
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            if skill_id and payload.get("skill_id") != skill_id:
                continue
            rows.append(payload)
        return rows

    def patch(self, artifact_id: str, fields: Dict[str, Any]) -> bool:
        """就地合并更新（状态机流转/证据回填）；工件不存在回 False。"""
        payload = self.get(artifact_id)
        if payload is None:
            return False
        for key, value in (fields or {}).items():
            if key == "evidence" and isinstance(payload.get("evidence"), dict):
                payload["evidence"] = {**payload["evidence"], **(value or {})}
            else:
                payload[key] = value
        try:
            (self._dir / f"{artifact_id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            logger.debug("工件回写失败: %s", e)
            return False
        return True
