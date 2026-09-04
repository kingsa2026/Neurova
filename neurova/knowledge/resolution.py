"""图谱实体消解三段式（P1-1，Utopia 0005/adjudication.rs 裁剪版）。

三段式：
1. 精确召回：label 小写一致（含别名）的未合并节点对；
2. 相似度：difflib ratio ≥ 阈值的跨名对（宁分勿合）；
3. LLM 攒批裁决（llm_call 可注入，None=未配模型）：
   - 裁决缓存键与节点 ID 无关（sha256 名字|类型|描述摘要，双方排序）——
     重传文档/重建图不重复付费；
   - 高置信 same（≥auto_conf）→ 自动合并（manager.merge_nodes，可回滚）；
   - 高置信 different → 自动保持分开（关闭灰区对，记入裁决缓存防重提）；
   - 低置信/无 LLM/调用失败/畸形输出 → 转人工队列。

失败方向设计：
- 人工队列/裁决缓存独立于节点存储——漏读它们的后果是"少一个待审项"，
  不是"错误合并静默进图"；
- 消解全程异常不向上传播（后台增强，失败只少一个合并，绝不影响图谱读写）。
"""

from __future__ import annotations

import difflib
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_AUTO_CONF = 0.8
_SIMILARITY_THRESHOLD = 0.85
_DESCRIPTION_SLICE = 120


def _side_signature(node: Any) -> str:
    """裁决键的单侧签名：名字|类型|描述摘要（与节点 ID 无关）。"""
    label = str(getattr(node, "label", "") or "").strip().lower()
    node_type = getattr(getattr(node, "node_type", None), "value", "custom")
    description = ""
    props = getattr(node, "properties", None) or {}
    if isinstance(props, dict):
        description = str(props.get("description", "") or "")
    aliases = getattr(node, "aliases", None) or []
    alias_part = ",".join(sorted(str(a).strip().lower() for a in aliases if str(a).strip()))
    return f"{label}|{node_type}|{alias_part}|{description[:_DESCRIPTION_SLICE]}"


def pair_key(left: Any, right: Any) -> str:
    """裁决缓存键：双方签名排序后哈希（同对换序同键，同名对跨实例同键）。"""
    sides = sorted([_side_signature(left), _side_signature(right)])
    return hashlib.sha256("##".join(sides).encode("utf-8")).hexdigest()


class EntityResolver:
    """消解器：灰区召回 + 攒批裁决 + 人工队列（独立 JSON 持久化）。"""

    def __init__(self, graph: Any, storage_dir: Optional[str] = None) -> None:
        self._graph = graph
        dir_ = storage_dir or getattr(graph, "_storage_dir", None)
        self._path = Path(dir_) / "resolution.json" if dir_ else None
        self._reviews: Dict[str, Dict[str, Any]] = {}
        self._verdicts: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ── 持久化 ────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                reviews = data.get("reviews")
                verdicts = data.get("verdicts")
                self._reviews = {
                    k: v for k, v in (reviews or {}).items() if isinstance(v, dict)
                }
                self._verdicts = {
                    k: v for k, v in (verdicts or {}).items() if isinstance(v, dict)
                }
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to load entity resolution store: %s", e)

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    {"reviews": self._reviews, "verdicts": self._verdicts},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to save entity resolution store: %s", e)

    # ── 召回 ──────────────────────────────────────────────────

    def find_candidates(
        self, similarity_threshold: float = _SIMILARITY_THRESHOLD
    ) -> Dict[str, List[Dict[str, Any]]]:
        """灰区对召回。已裁决（缓存/在审）的对不再进灰区——防重复提议。"""
        nodes = [n for n in self._graph._nodes.values() if n.node_id not in self._graph._merge_log]
        pending_keys = {
            r.get("pair_key") for r in self._reviews.values() if r.get("status") == "pending"
        }
        grey: List[Dict[str, Any]] = []
        seen_keys = set()
        for i, a in enumerate(nodes):
            for b in nodes[i + 1 :]:
                key = pair_key(a, b)
                if key in self._verdicts or key in pending_keys or key in seen_keys:
                    continue
                a_names = {a.label.lower()} | {x.lower() for x in (a.aliases or [])}
                b_names = {b.label.lower()} | {x.lower() for x in (b.aliases or [])}
                if a_names & b_names:
                    sim = 1.0
                else:
                    sim = difflib.SequenceMatcher(None, a.label.lower(), b.label.lower()).ratio()
                    if sim < similarity_threshold:
                        continue
                seen_keys.add(key)
                grey.append(
                    {
                        "left_id": a.node_id,
                        "right_id": b.node_id,
                        "left_label": a.label,
                        "right_label": b.label,
                        "similarity": round(sim, 4),
                    }
                )
        return {"grey": grey}

    # ── 攒批裁决 ──────────────────────────────────────────────

    def run_adjudication(
        self,
        llm_call: Optional[Callable[[str], str]] = None,
        auto_conf: float = _AUTO_CONF,
    ) -> Dict[str, int]:
        """消费灰区对。返回 {"merged": n, "kept": n, "escalated": n}。"""
        result = {"merged": 0, "kept": 0, "escalated": 0}
        grey = self.find_candidates()["grey"]
        if not grey:
            return result

        to_ask: List[Tuple[Dict[str, Any], str]] = []
        for pair in grey:
            key = self._key_of(pair)
            cached = self._verdicts.get(key)
            if cached is not None:
                if self._apply(pair, cached.get("same"), float(cached.get("confidence", 0)), auto_conf):
                    result["merged" if cached.get("same") else "kept"] += 1
                else:
                    result["escalated"] += 1
                continue
            to_ask.append((pair, key))

        if to_ask:
            for pair, key in to_ask:
                same: Optional[bool] = None
                confidence = 0.0
                if llm_call is not None:
                    verdict = self._ask_llm(llm_call, pair)
                    if verdict is not None:
                        same, confidence = verdict
                        self._verdicts[key] = {
                            "same": same,
                            "confidence": confidence,
                            "created_at": time.time(),
                        }
                if self._apply(pair, same, confidence, auto_conf):
                    result["merged" if same else "kept"] += 1
                else:
                    result["escalated"] += 1
        self._save()
        return result

    def _key_of(self, pair: Dict[str, Any]) -> str:
        a = self._graph.get_node(pair["left_id"])
        b = self._graph.get_node(pair["right_id"])
        if a is None or b is None:
            return "missing:" + pair["left_id"] + pair["right_id"]
        return pair_key(a, b)

    def _ask_llm(
        self, llm_call: Callable[[str], str], pair: Dict[str, Any]
    ) -> Optional[Tuple[bool, float]]:
        """单对裁决调用。异常/畸形输出返回 None（转人工），绝不向上抛。"""
        try:
            prompt = (
                "判断下面两个图谱实体是否指同一事物，输出严格 JSON "
                '{"verdict": "same"|"different", "confidence": 0~1}：\n'
                f'实体A：{pair["left_label"]}\n'
                f'实体B：{pair["right_label"]}'
            )
            raw = llm_call(prompt)
            data = json.loads(raw) if isinstance(raw, str) else None
            if not isinstance(data, dict):
                return None
            verdict = str(data.get("verdict", "")).lower()
            if verdict not in ("same", "different"):
                return None
            confidence = float(data.get("confidence", 0.5))
            return verdict == "same", max(0.0, min(1.0, confidence))
        except Exception as e:  # noqa: BLE001 - LLM 不可用转人工
            logger.warning("entity resolution: LLM 裁决失败: %s", e)
            return None

    def _apply(
        self, pair: Dict[str, Any], same: Optional[bool], confidence: float, auto_conf: float
    ) -> bool:
        """按裁决处置灰区对。返回 True=已处置（合并/保持）；False=转人工。"""
        left_id, right_id = pair["left_id"], pair["right_id"]
        if same is True and confidence >= auto_conf:
            # 合并方向稳定：node_id 大者并入小者（target 取较小者）
            src, dst = sorted([left_id, right_id], reverse=True)
            ok = self._graph.merge_nodes(src, dst, reason=f"auto|adjudication {confidence:.2f}")
            if ok:
                return True
            same = None  # 合并失败（一方已消失）：转人工
        if same is False and confidence >= auto_conf:
            return True  # 保持分开：灰区对经缓存过滤自然关闭
        self._reviews[str(uuid.uuid4())] = {
            "left_id": left_id,
            "right_id": right_id,
            "left_label": pair.get("left_label", ""),
            "right_label": pair.get("right_label", ""),
            "similarity": pair.get("similarity", 0),
            "stage": "human",
            "status": "pending",
            "pair_key": self._key_of(pair),
            "created_at": time.time(),
            "resolved_by": None,
            "resolved_at": None,
        }
        return False

    # ── 人工队列 ──────────────────────────────────────────────

    def list_human_reviews(self, status: str = "pending") -> List[Dict[str, Any]]:
        recs = [
            dict(r, review_id=rid)
            for rid, r in self._reviews.items()
            if r.get("status") == status
        ]
        recs.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        return recs

    def resolve_human(self, review_id: str, decision: str, decided_by: str = "") -> bool:
        """人工裁决：merged 走合并原语；kept 关闭灰区并写裁决缓存防重提。"""
        if decision not in ("merged", "kept"):
            raise ValueError("未知裁决: %r（有效值: merged / kept）" % decision)
        rec = self._reviews.get(review_id)
        if rec is None or rec.get("status") != "pending":
            return False
        if decision == "merged":
            src, dst = sorted([rec["left_id"], rec["right_id"]], reverse=True)
            if not self._graph.merge_nodes(src, dst, reason=f"human|{decided_by}"):
                raise LookupError("节点不存在或已合并: %s/%s" % (rec["left_id"], rec["right_id"]))
        rec["status"] = "resolved"
        rec["resolution"] = decision
        rec["resolved_by"] = str(decided_by or "")
        rec["resolved_at"] = time.time()
        # kept 决定进裁决缓存：同名对不再被重复提议（rejected_facts 同理）
        if decision == "kept":
            self._verdicts[rec.get("pair_key") or "kept:" + review_id] = {
                "same": False,
                "confidence": 1.0,
                "via": "human",
                "created_at": time.time(),
            }
        self._save()
        return True
