"""知识共享与治理端点（share/unshare / 公共库审批 / 墓碑恢复 / 同值冲突）。

2026-09-16 自 knowledge.py 拆出；路径与响应契约不变。
共享 / 公共库审批的"字面路由必须注册在 /{knowledge_id} 之前防遮蔽"契约
由聚合器 include 顺序维持（见 test_knowledge_route_order.py）。

依赖方向（架构约束，2026-09-16 拆分后冻结；全图见 knowledge.py 头部）：
    本模块 ──▶ knowledge_common（模型 / 守卫 / repository 解析 / 用户名解析）
    禁止：本模块 import 兄弟叶子（core/remote/ingestion），也禁止 import
    聚合器 knowledge.py（成环）；共享需求下沉 knowledge_common。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service
from neurova.core.logger import get_logger
from neurova.api.endpoints.knowledge_common import (
    KnowledgeItem,
    KnowledgeReviewRequest,
    KnowledgeShareRequest,
    entry_or_403,
    entry_or_404,
    get_repository,
    get_request_id,
    guard,
    item_response,
    resolve_usernames,
)

logger = get_logger(__name__)

router = APIRouter()


class ConflictResolutionRequest(BaseModel):
    """冲突裁决请求（仅管理员）。两条轴的词汇不同：
    条目侧 keep_both / supersede_old；事实侧另可 dismiss，且 supersede_old 必须带 winner_fact_id。
    """

    resolution: str = Field(..., description="keep_both / supersede_old / dismiss")
    winner_fact_id: Optional[str] = Field(
        default=None,
        description="事实侧 supersede_old 的胜方事实 id（必须是该冲突的成员）；条目侧忽略")


@router.get("/public-submissions")
async def list_public_submissions(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """待审批的公共库提交清单（仅管理员）"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看公共库审批队列")
    repo = get_repository()
    return [item_response(i) for i in repo.pending_submissions()]


@router.get("/conflicts")
async def list_conflicts(
    request: Request,
    status: str = Query(default="pending", description="pending 待审 / resolved 裁决历史"),
    axis: str = Query(default="entry", pattern="^(all|entry|fact)$",
                      description="entry=同值条目（默认，与 016 之前的响应逐字相同）"
                      " / fact=治理层分歧 / all=两条都要"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """冲突队列（仅管理员）。两条轴、一个队列，靠 `axis` 判别而不是混成一种形状。

    默认只回 `entry`：旧调用方拿到的东西一字不改，要两侧就显式 `axis=all`。

    - `entry`：新条目疑似"同一事实的新说法"（旧契约字段一字不改）。
    - `fact`：治理层同一 (主体, 谓词) 上的分歧，带 kind / severity /
      recommended_policy / **policy_basis** / members。
    两条轴是两个对象（条目 vs 事实行），硬并成一张表要么丢信息要么来回翻译——
    语义合一的口径见工单 017 的"完成状态"。
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看冲突队列")
    repo = get_repository()
    rows: List[Dict[str, Any]] = []
    if axis in ("all", "entry"):
        rows = [dict(rec, axis="entry") for rec in repo.list_conflicts(status=status)]
    if axis in ("all", "fact"):
        rows += [_factConflictResponse(rec) for rec in _factStore().conflicts(status=status)]
    return rows


def _factStore():
    """治理层事实库句柄（生产即权威底座库）。"""
    from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store

    return get_knowledge_fact_store()


_FACT_CONFLICT_FIELDS = ("conflict_id", "kind", "subject_key", "predicate_term_id",
                         "member_fact_ids", "severity", "recommended_policy", "policy_basis",
                         "status", "detected_at", "winner_fact_id")


def _factConflictResponse(rec: Dict[str, Any]) -> Dict[str, Any]:
    """事实侧响应：治理层字段原名透出，另加两条只为"看得懂"的派生读数。

    `subject_label` 与 `members_summary` 是给治理者的，不是新权威——主体键与事实 id
    仍然原样在响应里， UI 要用哪个都能拿到。
    """
    store = _factStore()
    row = {key: rec.get(key) for key in _FACT_CONFLICT_FIELDS}
    row["axis"] = "fact"
    for key in ("resolution", "resolved_by", "resolved_at"):
        if key in rec:
            row[key] = rec.get(key)
    subject = store.subjectFor(str(rec.get("subject_key", ""))) or {}
    row["subject_label"] = str(subject.get("canonical_label", "") or "")
    row["members_summary"] = [
        "%s → %s" % (f.get("predicate_term_id", ""), f.get("object_term", ""))
        for f in store.factsByIds(list(rec.get("member_fact_ids") or []))
    ]
    return row


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(
    request: Request,
    conflict_id: str = Path(..., description="冲突记录ID"),
    body: ConflictResolutionRequest = ...,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """裁决冲突（仅管理员）。按账本归属分派：条目侧 supersede_old 会把旧条目移入墓碑（可复活），
    事实侧走 `KnowledgeFactStore.resolveConflict`（词汇含 dismiss）。响应如实回报分派到哪条轴。
    """
    get_request_id(request)
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可裁决冲突")
    repo = get_repository()
    actor = str(current_user.get("user_id", ""))
    if repo.has_conflict(conflict_id):
        try:
            ok = repo.resolve_conflict(conflict_id, body.resolution, resolved_by=actor)
        except ValueError as e:
            raise guard(e)
        except LookupError as e:
            raise guard(e)
        axis = "entry"
    else:
        try:
            ok = _factStore().resolveConflict(conflict_id, body.resolution,
                                             resolvedBy=actor,
                                             winnerFactId=body.winner_fact_id)
        except ValueError as e:
            raise guard(e)
        axis = "fact"
    if not ok:
        raise HTTPException(status_code=404, detail="Conflict '%s' not found or already resolved" % conflict_id)
    return {
        "code": 0,
        "message": "Conflict resolved (%s)" % body.resolution,
        "data": {"conflict_id": conflict_id, "resolution": body.resolution, "axis": axis},
    }


@router.get("/deleted")
async def list_deleted_knowledge(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """墓碑清单（仅管理员）：软删条目审计视图"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看墓碑清单")
    repo = get_repository()
    out = []
    for rec in repo.list_deleted():
        item = rec.get("item") or {}
        out.append(
            {
                "knowledge_id": rec.get("knowledge_id"),
                "title": item.get("title", ""),
                "owner_user_id": item.get("owner_user_id", ""),
                "deleted_at": rec.get("deleted_at"),
                "deleted_by": rec.get("deleted_by"),
                "superseded_by": rec.get("superseded_by"),
            }
        )
    return out


@router.post("/{knowledge_id}/restore")
async def restore_knowledge(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """从墓碑复活条目（属主或管理员）"""
    get_request_id(request)
    repo = get_repository()
    rec = next((r for r in repo.list_deleted() if r.get("knowledge_id") == knowledge_id), None)
    if rec is None:
        raise HTTPException(status_code=404, detail="Knowledge '%s' is not deleted" % knowledge_id)
    owner_id = str((rec.get("item") or {}).get("owner_user_id", "") or "")
    if current_user.get("role") != "admin" and str(current_user.get("user_id", "")) != owner_id:
        raise HTTPException(status_code=403, detail="仅条目属主或管理员可恢复")
    if not repo.restore_knowledge(knowledge_id):
        raise HTTPException(status_code=404, detail="Knowledge '%s' is not deleted" % knowledge_id)
    return {
        "code": 0,
        "message": "Knowledge '%s' restored" % knowledge_id,
        "data": {"knowledge_id": knowledge_id, "action": "restored"},
        "request_id": get_request_id(request),
    }


@router.post("/{knowledge_id}/share", response_model=KnowledgeItem)
async def share_knowledge(
    request: Request,
    body: KnowledgeShareRequest,
    knowledge_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """把私有条目共享给指定用户（只读；属主/管理员）"""
    repo = get_repository()
    entry_or_403(repo, knowledge_id, current_user)
    try:
        mapping = resolve_usernames(body.usernames)
        item = repo.share_entry(current_user, knowledge_id, list(mapping.values()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (PermissionError, LookupError) as exc:
        raise guard(exc)
    return item_response(item)


@router.post("/{knowledge_id}/unshare", response_model=KnowledgeItem)
async def unshare_knowledge(
    request: Request,
    body: KnowledgeShareRequest,
    knowledge_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """取消对指定用户的共享（属主/管理员）"""
    repo = get_repository()
    entry_or_403(repo, knowledge_id, current_user)
    try:
        mapping = resolve_usernames(body.usernames)
        item = repo.unshare_entry(current_user, knowledge_id, list(mapping.values()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (PermissionError, LookupError) as exc:
        raise guard(exc)
    return item_response(item)


@router.post("/{knowledge_id}/submit-public", response_model=KnowledgeItem)
async def submit_knowledge_to_public(
    request: Request,
    knowledge_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """把私有条目提交公共库（进入待审批；属主）并通知管理员审核"""
    repo = get_repository()
    entry_or_403(repo, knowledge_id, current_user)
    try:
        item = repo.submit_to_public(current_user, knowledge_id)
    except (PermissionError, LookupError, ValueError) as exc:
        raise guard(exc)

    # 通知管理员审核（异常只记日志，不阻断提交）
    try:
        from neurova.api.endpoints.notifications import notify_admins

        submission = item.get("submission") or {}
        submitter_id = str(submission.get("submitted_by") or current_user.get("user_id") or "")
        submitter_name = str(current_user.get("username") or submitter_id)
        notify_admins(
            title="知识库提交待审核",
            message=f"用户 {submitter_name} 提交「{item.get('title', '')}」到公共库，等待审核",
            notification_type="kb_review",
            data={
                "knowledge_id": knowledge_id,
                "title": item.get("title", ""),
                "submitter": submitter_id,
                "submitter_name": submitter_name,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("submit-public 通知管理员失败")
    return item_response(item)


@router.post("/{knowledge_id}/review-public", response_model=KnowledgeItem)
async def review_knowledge_public(
    request: Request,
    body: KnowledgeReviewRequest,
    knowledge_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """审批公共库提交（仅管理员）：通过→public，拒绝→维持 private；结果回执提交者"""
    repo = get_repository()
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可审批公共库提交")
    entry_or_404(repo, knowledge_id, current_user)
    try:
        item = repo.review_public_submission(
            current_user,
            knowledge_id,
            approve=bool(body.approve),
            reviewed_by=str(current_user.get("user_id", "")),
            note=body.note,
        )
    except (PermissionError, LookupError, ValueError) as exc:
        raise guard(exc)

    # 回执提交者（异常只记日志，不阻断审批）
    try:
        from neurova.api.endpoints.notifications import notify_user

        submission = item.get("submission") or {}
        submitter = str(submission.get("submitted_by") or "")
        if submitter:
            title = item.get("title", "")
            if body.approve:
                msg = f"你提交的「{title}」已通过审核，进入公共库"
            else:
                msg = f"你提交的「{title}」未通过审核" + (f"：{body.note}" if body.note else "")
            notify_user(
                submitter,
                title="知识库审核结果",
                message=msg,
                notification_type="kb_review_result",
                data={"knowledge_id": knowledge_id, "approve": bool(body.approve)},
            )
    except Exception:  # noqa: BLE001
        logger.exception("review-public 通知提交者失败")
    return item_response(item)
