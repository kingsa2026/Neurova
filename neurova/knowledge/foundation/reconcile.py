"""E1 收口对账：预测 vs 实跑（工单 015，§9 E1 出口判据）。

宽重构最危险的漂移是"我以为的规则"和"实际跑出来的规则"分叉。本模块用同一套规则对象
（`normalizedKey` + `SubjectResolver` + `admit()` 的映射契约）走两条独立路径：
一条在内存里解析旧库、算出应当折成多少事实与主体；一条把同一批旧库真灌进一次性底座。
两边逐个数字必须相等，不等就报出是哪一维、差多少。

对账全程只读旧库，写只发生在传入的回放库路径上。
"""

from __future__ import annotations

from typing import Any, Dict, List

from neurova.core.content_identity import normalized_key

from .admission import AdmissionRequest, productionAdmissionGate
from .knowledge_facts import KnowledgeFactStore
from ..identity.subject_resolver import SubjectResolver

_IMPORTER_PREFIXES = ("import:", "url:", "datasource:", "kb_builder")


def _assertionFor(agentId: str, item: Dict[str, Any],
                  mediumFallback: str = "legacy:knowledge.json") -> Dict[str, Any]:
    """按旧行已有字段如实合成断言（来源串 + 属主 + 标题）。

    咽喉在写入前就要求"不能有主不明的知识"，所以映射必须自带断言——
    缺了它，回放根本进不去血缘段，也就测不到生产写入的真实形状。
    不为回填行编造置信度：那是 G11 要灭的病，不能由对账器重新犯。

    `mediumFallback` 是唯一按来源分叉的参数：搬家进来的旧行确实来自那个 JSON 文件，
    而实时写入的条目没有来源串时，诚实的说法是"来源就是这条条目本身"（entry:<kid>），
    不是把一个历史文件名安到它头上。
    """
    source = str(item.get("source", "") or "").strip()
    owner = str(item.get("owner_user_id", "") or "").strip()
    lowered = source.lower()
    if lowered.startswith(_IMPORTER_PREFIXES):
        actorType = "importer"
    elif owner:
        actorType = "user"
    else:
        actorType = "pipeline"
    return {
        "actorType": actorType,
        "actorId": owner or "legacy-unknown",
        "mediumRef": source or mediumFallback,
        "statementText": str(item.get("title", "") or "").strip() or "(untitled legacy entry)",
        "verification_state": "unverified",
    }


def _requestsFromRepository(repo: Any) -> List[AdmissionRequest]:
    """旧条目 → 咽喉入参的唯一映射，两条路径共用，避免各写一套映射造成假对账。

    条目本来就是文档，所以按 `record_kind='narrative'` 发：谓词由咽喉固定，
    客体是 knowledge_id。以前这里把 category 塞进谓词、把条目伪造成三元组，
    读起来像"标题 described_as 某分类"，实际谁也不这么问——表示法不对，
    冲突判定与图投影都只能跟着歪。
    """
    requests: List[AdmissionRequest] = []
    for agentId, items in getattr(repo, "_items", {}).items():
        for item in items:
            knowledgeId = str(item.get("knowledge_id", ""))
            requests.append(AdmissionRequest(
                agentId=agentId,
                subjectLabel=str(item.get("title", "")).strip() or ("untitled-" + knowledgeId),
                recordKind="narrative",
                objectTerm=knowledgeId,
                content=str(item.get("content", "") or ""),
                assertions=[_assertionFor(agentId, item)],
                sourceTurnId="legacy:%s" % knowledgeId,
            ))
    return requests


class FoundationReconciler:
    @staticmethod
    def plan(repo: Any) -> Dict[str, Any]:
        """静态解析旧库：按咽喉同一口径预测折叠结果，并给出可执行分组。"""
        requests = _requestsFromRepository(repo)
        keyed: Dict[Any, List[str]] = {}
        unkeyed: List[str] = []
        domains: set = set()
        for request in requests:
            domains.add(request.agentId)
            key = normalized_key(request.content)
            if key:
                keyed.setdefault((request.agentId, key), []).append(request.objectTerm)
            else:
                unkeyed.append(request.objectTerm)

        groups = sorted(
            (
                {"content_key": key, "agent_id": agent, "count": len(ids), "knowledge_ids": ids}
                for (agent, key), ids in keyed.items() if len(ids) > 1
            ),
            key=lambda g: (-g["count"], g["content_key"]),
        )
        return {
            "legacy_rows": len(requests),
            "per_agent_domains": len(domains),
            "predicted_facts": len(keyed) + len(unkeyed),
            "predicted_subjects": FoundationReconciler._predictSubjects(requests),
            "redundant_rows": sum(g["count"] - 1 for g in groups),
            "duplicate_group_count": len(groups),
            "no_identity_rows": len(unkeyed),
            "groups": groups,
        }

    @staticmethod
    def _predictSubjects(requests: List[AdmissionRequest]) -> int:
        """按同一解析器贪心走一遍，只数主体，不落库。

        顺序必须与咽喉一致：**内容去重在身份消解之前**（见 `admit()` 的段序），
        被折叠掉的行不会创建主体。工单 015 首次实跑就是靠这条差异抓出预测侧多算了一个主体。
        """
        known: Dict[str, List[Dict[str, Any]]] = {}
        seenContent: set = set()
        resolver = SubjectResolver()
        count: Dict[str, int] = {}
        for request in requests:
            key = normalized_key(request.content)
            if key:
                identity = (request.agentId, key)
                if identity in seenContent:
                    continue
                seenContent.add(identity)
            bucket = known.setdefault(request.agentId, [])
            outcome = resolver.resolve(request.subjectLabel, bucket)
            if outcome.subjectKey is None:
                synthetic = "pred_%s_%d" % (request.agentId, len(bucket))
                bucket.append({"subject_key": synthetic, "canonical_label": request.subjectLabel,
                               "type_term_id": "", "aliases": []})
                count[request.agentId] = count.get(request.agentId, 0) + 1
        return sum(count.values())

    @staticmethod
    def reconcile(repo: Any, replayDbPath: str) -> Dict[str, Any]:
        """把旧库灌进一次性底座，与 `plan()` 的预测逐维对账。"""
        predicted = FoundationReconciler.plan(repo)
        store = KnowledgeFactStore(replayDbPath)
        try:
            gate = productionAdmissionGate(store, toolVersion='reconcile-replay')
            for request in _requestsFromRepository(repo):
                gate.admit(request, allowPendingSegments=True)
            actual = {
                "facts": store.factCount(),
                "subjects": store.subjectCount(),
                "legacy_rows": predicted["legacy_rows"],
            }
        finally:
            store.close()

        diffs = [
            "%s 预测 %d 实跑 %d（差 %+d）" % (name, predicted[key], actual[name],
                                        actual[name] - predicted[key])
            for key, name in (("predicted_facts", "facts"), ("predicted_subjects", "subjects"))
            if predicted[key] != actual[name]
        ]
        return {
            "ok": not diffs,
            "predicted": {"facts": predicted["predicted_facts"],
                          "subjects": predicted["predicted_subjects"],
                          "redundant_rows": predicted["redundant_rows"],
                          "legacy_rows": predicted["legacy_rows"]},
            "actual": {"facts": actual["facts"], "subjects": actual["subjects"]},
            "diffs": diffs,
            "plan": predicted,
        }

    @staticmethod
    def summarize(report: Dict[str, Any]) -> str:
        return "旧库 %d 行 → 预测 %d 事实 / 实跑 %d 事实；主体 %d / %d；纯冗余 %d 行；对账%s" % (
            report["predicted"]["legacy_rows"], report["predicted"]["facts"], report["actual"]["facts"],
            report["predicted"]["subjects"], report["actual"]["subjects"],
            report["predicted"]["redundant_rows"], "一致" if report["ok"] else "有差异",
        )
