"""技能经验库（SkillExperienceStore）— 经验与技能定义分离 + usage_stats。

对齐 jiuwenswarm evolutions.json 模型（2026-09-11 对比研究启发 #2）：

- **经验与定义分离**：进化经验作为 applied 记录存本库，立即生效（组合进
  技能描述，LLM 下一轮工具面即可见）；技能定义基线保持纯净
  （skill.config["base_description"]），随时可回溯。
- **usage_stats**：times_presented / times_used / positive / negative 四计数，
  是技能级自动淘汰的数据依据（此前技能"只生不死"——只有工具级遗忘曲线）。
- **定期重建**：未合并 applied 记录攒够阈值 → 重建技能定义（先归档、
  可回滚）。重建语义是"持久化压缩"而非行为变更——重建前后有效文本
  一致（合并进定义的记录不再重复注入）。
- **淘汰**：min_uses + 成功率上限双门槛圈出候选；自动禁用默认关
  （NEUROVA_SKILL_AUTO_RETIRE=1 才生效），默认只上报候选（日志）。

持久化：复用 PersistedStateMixin（data/evolution/skill_experiences.json，
env NEUROVA_EVOLUTION_SKILL_EXPERIENCE 覆盖）；由 bootstrap_evolution_persistence
装配、flush_evolution_persistence 关停落盘。
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.evolution.persistence import PersistedStateMixin

logger = get_logger(__name__)

# 未合并 applied 记录达到该数即触发重建
DEFAULT_REBUILD_THRESHOLD = 5
# 注入/合并进描述的指引上限（最近 N 条，防描述膨胀）
INJECTION_MAX_RECORDS = 5
# 每技能保留的归档份数（可回滚窗口）
ARCHIVE_KEEP = 3
# 淘汰双门槛：使用次数下限 / 成功率上限
DEFAULT_RETIRE_MIN_USES = 10
DEFAULT_RETIRE_MAX_SUCCESS_RATE = 0.3


@dataclass
class SkillExperienceRecord:
    """单条 applied 经验记录（写入即生效，直到被重建合并进定义）。"""

    record_id: str
    skill_id: str
    source: str  # improver | manual | rebuild
    content: str  # 行为指引文本（生效的载体）
    context: str = ""
    created_at: float = field(default_factory=time.time)
    merged: bool = False  # 已被重建合并进定义（不再重复注入）
    merged_version: str = ""


class SkillExperienceStore(PersistedStateMixin):
    """技能经验库：applied 记录 + usage_stats + 归档 + 淘汰台账。"""

    def __init__(
        self,
        rebuild_threshold: int = DEFAULT_REBUILD_THRESHOLD,
        retire_min_uses: int = DEFAULT_RETIRE_MIN_USES,
        retire_max_success_rate: float = DEFAULT_RETIRE_MAX_SUCCESS_RATE,
    ):
        self._lock = threading.RLock()
        self._rebuild_threshold = max(1, int(rebuild_threshold))
        self._retire_min_uses = max(1, int(retire_min_uses))
        self._retire_max_success_rate = float(retire_max_success_rate)

        # skill_id -> applied 记录（按时间序）
        self._records: Dict[str, List[SkillExperienceRecord]] = {}
        # 待审批记录（C10 治理收紧：improver/attribution 等自动化来源在评审闸
        # 开启时先进待审——批准后移入 _records 生效，计入重建阈值）
        self._pending_records: List[SkillExperienceRecord] = []
        # skill_id -> {times_presented, times_used, positive, negative}
        self._usage: Dict[str, Dict[str, Any]] = {}
        # skill_id -> 归档列表（重建/回滚前的定义快照，有界）
        self._archives: Dict[str, List[Dict[str, Any]]] = {}
        # skill_id -> {retired_at, reason} 淘汰台账（幂等）
        self._retired: Dict[str, Dict[str, Any]] = {}

        self._init_state_persistence()
        logger.debug("SkillExperienceStore initialized")

    # ────── applied 记录（立即生效通道）──────

    def record_experience(
        self,
        skill_id: str,
        content: str,
        source: str = "improver",
        context: str = "",
        registry: Optional[Any] = None,
    ) -> Optional[SkillExperienceRecord]:
        """写入一条 applied 经验记录（同技能同内容去重）。

        registry 在场时立即组合进技能描述（LLM 下一轮工具面可见）——
        这是"applied 记录立即生效"的落地；定义基线首次落 config.base_description。
        """
        content = str(content or "").strip()
        skill_id = str(skill_id or "").strip()
        if not skill_id or not content:
            return None

        with self._lock:
            records = self._records.setdefault(skill_id, [])
            if any(r.content == content for r in records):
                return None  # 同内容去重
            if any(r.content == content for r in self._pending_records):
                return None  # 待审队列同内容去重

        # C10 治理收紧（2026-09-12）：自动化来源（improver/attribution）的
        # applied 记录在评审闸开启时先进待审——批准后注入描述并计入重建
        # （对齐 jiuwenswarm auto_save 默认 false：提案审批后才入经验库）
        from neurova.evolution.skill_review_gate import skill_review_gate_enabled

        if skill_review_gate_enabled() and source in ("improver", "attribution"):
            record = SkillExperienceRecord(
                record_id=f"exp_{uuid.uuid4().hex[:12]}",
                skill_id=skill_id,
                source=source,
                content=content,
                context=str(context or ""),
            )
            with self._lock:
                if any(r.content == content for r in self._pending_records):
                    return None
                self._pending_records.append(record)
                del self._pending_records[:-50]  # 有界
            self._maybe_persist()
            logger.info("经验记录进待审队列: %s (%s)", skill_id, content[:40])
            return record

        record = SkillExperienceRecord(
            record_id=f"exp_{uuid.uuid4().hex[:12]}",
            skill_id=skill_id,
            source=source,
            content=content,
            context=str(context or ""),
        )
        with self._lock:
            self._records.setdefault(skill_id, []).append(record)

        if registry is not None:
            self._apply_to_skill(skill_id, registry)
        self._maybe_persist()
        return record

    def get_records(self, skill_id: str) -> List[SkillExperienceRecord]:
        with self._lock:
            return list(self._records.get(skill_id, []))

    # ── 待审批队列（C10 治理收紧）──

    def list_pending_experiences(self, skill_id: Optional[str] = None) -> List[SkillExperienceRecord]:
        """待审批的 applied 记录（可按技能过滤）。"""
        with self._lock:
            items = list(self._pending_records)
        if skill_id:
            items = [r for r in items if r.skill_id == skill_id]
        return items

    def approve_experience(self, record_id: str, registry: Optional[Any] = None) -> bool:
        """批准待审经验：移入正式记录（立即生效，计入重建阈值）。"""
        with self._lock:
            record = next((r for r in self._pending_records if r.record_id == record_id), None)
            if record is None:
                return False
            self._pending_records.remove(record)
            self._records.setdefault(record.skill_id, []).append(record)
        if registry is not None:
            self._apply_to_skill(record.skill_id, registry)
        self._maybe_persist()
        logger.info("经验记录 %s 已批准生效 (%s)", record_id, record.skill_id)
        return True

    def reject_experience(self, record_id: str) -> bool:
        """拒绝待审经验：直接丢弃（不入台账）。"""
        with self._lock:
            record = next((r for r in self._pending_records if r.record_id == record_id), None)
            if record is None:
                return False
            self._pending_records.remove(record)
        self._maybe_persist()
        logger.info("经验记录 %s 已拒绝", record_id)
        return True

    def _apply_to_skill(self, skill_id: str, registry: Any) -> bool:
        """把未合并经验组合进技能描述（定义基线保持纯净）。"""
        try:
            skill = registry.get_skill(skill_id)
        except Exception:  # noqa: BLE001 - registry 形态各异，fail-soft
            skill = None
        if skill is None:
            return False

        config = getattr(skill, "config", None)
        if not isinstance(config, dict):
            config = {}
            skill.config = config
        base = config.get("base_description")
        if not base:
            base = str(getattr(skill, "description", "") or "")
            config["base_description"] = base

        with self._lock:
            unmerged = [r for r in self._records.get(skill_id, []) if not r.merged]
        skill.description = self.compose_effective_description(skill_id, base_description=base)
        logger.debug("技能 %s 经验已生效（%d 条未合并）", skill_id, len(unmerged))
        return True

    def compose_effective_description(
        self, skill_id: str, base_description: Optional[str] = None
    ) -> str:
        """基线描述 + 未合并经验指引（最多最近 5 条，防膨胀）。"""
        with self._lock:
            unmerged = [r for r in self._records.get(skill_id, []) if not r.merged]
        contents = [r.content for r in unmerged][-INJECTION_MAX_RECORDS:]
        base = str(base_description if base_description is not None else "")
        if not contents:
            return base
        return base + "\n\n[经验指引]\n" + "\n".join(f"- {c}" for c in contents)

    # ────── usage_stats（淘汰数据依据）──────

    def record_usage(self, skill_id: str, success: bool) -> None:
        """技能执行成败计数（times_used/positive/negative）。"""
        with self._lock:
            usage = self._usage.setdefault(
                skill_id,
                {"times_presented": 0, "times_used": 0, "positive": 0, "negative": 0},
            )
            usage["times_used"] = int(usage.get("times_used", 0)) + 1
            if success:
                usage["positive"] = int(usage.get("positive", 0)) + 1
            else:
                usage["negative"] = int(usage.get("negative", 0)) + 1
        self._maybe_persist()

    def get_usage(self, skill_id: str) -> Dict[str, Any]:
        with self._lock:
            usage = self._usage.get(skill_id, {})
        return {
            "times_presented": int(usage.get("times_presented", 0)),
            "times_used": int(usage.get("times_used", 0)),
            "positive": int(usage.get("positive", 0)),
            "negative": int(usage.get("negative", 0)),
        }

    # ────── 定期重建（归档可回滚）──────

    def pending_rebuild(self, skill_id: str) -> int:
        """未合并 applied 记录数。"""
        with self._lock:
            return sum(1 for r in self._records.get(skill_id, []) if not r.merged)

    def get_archives(self, skill_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._archives.get(skill_id, []))

    def rebuild_skill(self, skill_id: str, registry: Any, skill_service: Optional[Any] = None) -> bool:
        """把未合并经验合并进技能定义（先归档，可回滚）。

        语义是持久化压缩：合并后记录不再注入（有效文本不变）；只取最近
        INJECTION_MAX_RECORDS 条进描述，其余记录同样标记已合并（让位于
        最新指引，防重建churn）。版本 minor 位递增。
        """
        with self._lock:
            records = [
                r for r in self._records.get(skill_id, []) if not r.merged
            ]
        if len(records) < self._rebuild_threshold:
            return False

        try:
            skill = registry.get_skill(skill_id)
        except Exception:  # noqa: BLE001
            skill = None
        if skill is None:
            return False

        config = getattr(skill, "config", None)
        if not isinstance(config, dict):
            config = {}
            skill.config = config
        base = str(config.get("base_description") or getattr(skill, "description", "") or "")

        # 1) 归档当前定义（有界）
        with self._lock:
            archives = self._archives.setdefault(skill_id, [])
            archives.append(
                {
                    "version": str(getattr(skill, "version", "") or "1.0.0"),
                    "description": str(getattr(skill, "description", "") or ""),
                    "archived_at": time.time(),
                    "reason": "rebuild",
                }
            )
            del archives[:-ARCHIVE_KEEP]

        # 2) 合并：基线 + 最近 N 条经验；全部 pending 标记已合并
        contents = [r.content for r in records][-INJECTION_MAX_RECORDS:]
        new_description = base + "\n\n[经验指引]\n" + "\n".join(f"- {c}" for c in contents)

        with self._lock:
            # 版本 minor 位递增（1.0.x → 1.1.0）
            try:
                parts = str(getattr(skill, "version", "") or "1.0.0").split(".")
                while len(parts) < 3:
                    parts.append("0")
                parts[1] = str(int(parts[1]) + 1)
                parts[2] = "0"
                new_version = ".".join(parts)
            except (ValueError, IndexError):
                new_version = "1.1.0"

            for r in self._records.get(skill_id, []):
                if not r.merged:
                    r.merged = True
                    r.merged_version = new_version

        skill.description = new_description
        skill.version = new_version

        # 3) 落盘 manifest（改进持久化通道；失败不回滚内存态）
        if skill_service is not None:
            try:
                skill_service.update_auto_skill(skill_id=skill_id, version=new_version, config=skill.config)
            except Exception as svc_err:  # noqa: BLE001
                logger.warning("重建落盘失败 %s: %s", skill_id, svc_err)

        self._maybe_persist()
        logger.info("技能 %s 已重建 → v%s（归档 %d 份）", skill_id, new_version, len(archives))
        return True

    def rollback_skill(self, skill_id: str, registry: Any, skill_service: Optional[Any] = None) -> bool:
        """回滚到最近一次归档的定义。

        回滚的重建所合并的记录保持 merged=True（留在台账供审计，但不再
        注入、也不会被自动重建再次合并——自动重建尊重人工回滚决定）。
        """
        with self._lock:
            archives = self._archives.get(skill_id, [])
            if not archives:
                return False
            archive = archives.pop()

        try:
            skill = registry.get_skill(skill_id)
        except Exception:  # noqa: BLE001
            skill = None
        if skill is None:
            # 归档已弹出但技能不存在：塞回避免状态丢失
            with self._lock:
                self._archives.setdefault(skill_id, []).append(archive)
            return False

        config = getattr(skill, "config", None)
        if not isinstance(config, dict):
            config = {}
            skill.config = config
        # 基线在重建中从未被改动，回滚不覆盖它（归档的 description 可能
        # 已含经验组合文本——写回会污染纯净基线）。仅基线从未捕获时补记。
        config.setdefault("base_description", archive["description"])
        skill.description = archive["description"]
        skill.version = archive["version"]

        if skill_service is not None:
            try:
                skill_service.update_auto_skill(skill_id=skill_id, version=skill.version, config=skill.config)
            except Exception as svc_err:  # noqa: BLE001
                logger.warning("回滚落盘失败 %s: %s", skill_id, svc_err)

        self._maybe_persist()
        logger.info("技能 %s 已回滚至 v%s", skill_id, archive["version"])
        return True

    # ────── 淘汰（usage_stats 驱动）──────

    def get_retirement_candidates(
        self,
        min_uses: Optional[int] = None,
        max_success_rate: Optional[float] = None,
    ) -> List[str]:
        """按使用统计圈淘汰候选：次数达标且成功率低于上限、未淘汰过。"""
        min_uses = self._retire_min_uses if min_uses is None else max(1, int(min_uses))
        max_rate = (
            self._retire_max_success_rate if max_success_rate is None else float(max_success_rate)
        )
        candidates: List[str] = []
        with self._lock:
            for skill_id, usage in self._usage.items():
                if skill_id in self._retired:
                    continue
                used = int(usage.get("times_used", 0))
                if used < min_uses:
                    continue
                success_rate = int(usage.get("positive", 0)) / used
                if success_rate < max_rate:
                    candidates.append(skill_id)
        return candidates

    def mark_retired(self, skill_id: str, reason: str = "") -> bool:
        """写入淘汰台账（幂等；重复淘汰返回 False）。"""
        with self._lock:
            if skill_id in self._retired:
                return False
            self._retired[skill_id] = {
                "retired_at": time.time(),
                "reason": str(reason or ""),
                "usage": dict(self._usage.get(skill_id, {})),
            }
        self._maybe_persist()
        return True

    def is_retired(self, skill_id: str) -> bool:
        with self._lock:
            return skill_id in self._retired

    # ────── 持久化钩子 ──────

    def _snapshot_payload(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": 1,
                "records": {
                    skill_id: [asdict(r) for r in records]
                    for skill_id, records in self._records.items()
                },
                "usage": {k: dict(v) for k, v in self._usage.items()},
                "archives": {k: [dict(a) for a in v] for k, v in self._archives.items()},
                "retired": {k: dict(v) for k, v in self._retired.items()},
                "pending_records": [asdict(r) for r in self._pending_records],
            }

    def _restore_payload(self, data: Dict[str, Any]) -> None:
        records: Dict[str, List[SkillExperienceRecord]] = {}
        for skill_id, raw_records in (data.get("records") or {}).items():
            restored = []
            for raw in raw_records:
                try:
                    restored.append(
                        SkillExperienceRecord(
                            record_id=str(raw.get("record_id", "")),
                            skill_id=str(raw.get("skill_id", skill_id)),
                            source=str(raw.get("source", "improver")),
                            content=str(raw.get("content", "")),
                            context=str(raw.get("context", "")),
                            created_at=float(raw.get("created_at", 0.0)),
                            merged=bool(raw.get("merged", False)),
                            merged_version=str(raw.get("merged_version", "")),
                        )
                    )
                except (TypeError, ValueError):
                    continue
            records[str(skill_id)] = restored
        with self._lock:
            self._records = records
            self._usage = {
                str(k): dict(v) for k, v in (data.get("usage") or {}).items()
            }
            self._archives = {
                str(k): [dict(a) for a in v] for k, v in (data.get("archives") or {}).items()
            }
            self._retired = {
                str(k): dict(v) for k, v in (data.get("retired") or {}).items()
            }
            pending_raw = data.get("pending_records") or []
            self._pending_records = [
                SkillExperienceRecord(
                    record_id=str(raw.get("record_id", "")),
                    skill_id=str(raw.get("skill_id", "")),
                    source=str(raw.get("source", "improver")),
                    content=str(raw.get("content", "")),
                    context=str(raw.get("context", "")),
                    created_at=float(raw.get("created_at", 0.0)),
                    merged=bool(raw.get("merged", False)),
                    merged_version=str(raw.get("merged_version", "")),
                )
                for raw in pending_raw
                if isinstance(raw, dict)
            ]


# ────── 维护入口（post_chat RSI 步每轮调用）──────


def run_skill_experience_maintenance(
    registry: Optional[Any] = None,
    skill_service: Optional[Any] = None,
    store: Optional[SkillExperienceStore] = None,
    ledger: Optional[Any] = None,
    agent_id: str = "default",
) -> Dict[str, Any]:
    """每轮维护：失败归因 → 到阈值重建 → 淘汰扫描。

    失败归因（ledger 在场时）：把 SelfModelEngine 的活跃工具级教训归因到
    具体技能并写入经验库（applied 立即生效）——归因在重建之前执行，
    归因写入计入 pending，可触发重建。ledger 缺席时归因跳过（向后兼容）。

    淘汰自动禁用默认关（NEUROVA_SKILL_AUTO_RETIRE=1 才执行
    registry.set_skill_enabled(False) + skill_service.disable_skill），
    默认只上报候选——淘汰依据可见，执行有人工闸门。
    """
    store = store or get_skill_experience_store()
    result: Dict[str, Any] = {"attributed": [], "rebuilt": [], "retired": [], "retire_candidates": []}

    # 0) 失败归因：工具级教训 → 技能粒度（教训落到技能层的入口）
    if ledger is not None and registry is not None:
        try:
            from neurova.evolution.skill_attribution import attribute_failures_to_skills

            attr = attribute_failures_to_skills(
                registry, store=store, ledger=ledger, agent_id=agent_id
            )
            result["attributed"] = attr.get("attributed", [])
        except Exception as e:  # noqa: BLE001 - 归因失败不拖垮重建/淘汰
            logger.debug("失败归因跳过: %s", e)

    # 1) 重建：pending 达阈值的技能（registry 缺席时跳过——重建需要改定义）
    if registry is not None:
        with store._lock:
            skill_ids = list(store._records.keys())
        for skill_id in skill_ids:
            if store.pending_rebuild(skill_id) >= store._rebuild_threshold:
                try:
                    if store.rebuild_skill(skill_id, registry, skill_service=skill_service):
                        result["rebuilt"].append(skill_id)
                except Exception as e:  # noqa: BLE001 - 单技能失败不拖垮其余
                    logger.warning("技能 %s 重建失败: %s", skill_id, e)

    # 2) 淘汰：候选圈定（可见）；自动禁用走 env 闸门
    candidates = store.get_retirement_candidates()
    result["retire_candidates"] = candidates
    if candidates:
        if os.environ.get("NEUROVA_SKILL_AUTO_RETIRE") == "1" and registry is not None:
            for skill_id in candidates:
                disabled = False
                try:
                    disabled = bool(registry.set_skill_enabled(skill_id, False))
                except Exception as e:  # noqa: BLE001
                    logger.warning("技能 %s 自动禁用失败: %s", skill_id, e)
                if skill_service is not None:
                    try:
                        skill_service.disable_skill(skill_id)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("技能 %s manifest 禁用失败: %s", skill_id, e)
                store.mark_retired(skill_id, reason="usage_stats_below_threshold")
                result["retired"].append(skill_id)
                logger.info("🔴 技能 %s 已按使用统计自动淘汰（%s）", skill_id, "disabled" if disabled else "disabled-failed")
        else:
            logger.info("🟡 技能淘汰候选（NEUROVA_SKILL_AUTO_RETIRE=1 启用自动禁用）: %s", candidates)
    return result


# ────── 单例管理 ──────

_experience_store_instance: Optional[SkillExperienceStore] = None
_store_lock = threading.Lock()


def get_skill_experience_store(**kwargs) -> SkillExperienceStore:
    global _experience_store_instance
    if _experience_store_instance is None:
        with _store_lock:
            if _experience_store_instance is None:
                _experience_store_instance = SkillExperienceStore(**kwargs)
    return _experience_store_instance


def reset_skill_experience_store() -> None:
    global _experience_store_instance
    with _store_lock:
        _experience_store_instance = None
