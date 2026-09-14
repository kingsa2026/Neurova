# -*- coding: utf-8 -*-
"""创作专区 API（R3）：/api/v1/studio/*。

权限与隔离口径对齐 neurflow（路由级登录 + 属主判定 deny 与不存在同构 404，
admin 全量）。长耗时编排（LLM 拆解/批量生成）后台执行并落 runs 审计，
立即返回 run_id；镜头进度经 GET episode 详情轮询（video 完成状态由
task_ledger/recovery 循环收口后回读回填）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from neurova.aigc_studio import services
from neurova.aigc_studio.llm import call_llm  # noqa: F401 — 测试可 monkeypatch services 层
from neurova.aigc_studio.store import get_store
from neurova.api.deps import get_current_user
from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)])

_tasks: set = set()  # 后台任务强引用（与 neurflow _background_tasks 同法）


def _uid(user: Dict[str, Any]) -> str:
    return str(user.get("user_id") or "")


def _is_admin(user: Dict[str, Any]) -> bool:
    return user.get("role") == "admin"


def _owned_project(store, pid: str, user: Dict[str, Any]) -> Dict[str, Any]:
    project = store.get_project(pid, _uid(user), _is_admin(user))
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _episode_with_project(store, eid: str, user: Dict[str, Any]):
    ep = store.get_episode(eid)
    if ep is None:
        raise HTTPException(status_code=404, detail="分集不存在")
    project = _owned_project(store, ep["project_id"], user)
    return project, ep


# ── projects ───────────────────────────────────────────────────────────────


@router.get("/projects")
async def list_projects(current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    return {"code": 0, "data": {"projects": store.list_projects(_uid(current_user), _is_admin(current_user))}}


@router.post("/projects")
async def create_project(body: Dict[str, Any] = Body(...),
                         current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    title = str(body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title 必填")
    project = store.create_project(
        owner_user_id=_uid(current_user), title=title,
        description=str(body.get("description") or ""),
        genre=str(body.get("genre") or "都市逆袭"),
        style=str(body.get("style") or "cinematic"),
        aspect_ratio=str(body.get("aspect_ratio") or "9:16"),
        total_episodes=int(body.get("total_episodes") or 1),
    )
    return {"code": 0, "data": {"project": project}}


@router.get("/projects/{pid}")
async def get_project(pid: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    project = _owned_project(store, pid, current_user)
    episodes = store.list_episodes(pid)
    for ep in episodes:
        shots = store.list_storyboards(ep["id"])
        ep["shot_count"] = len(shots)
        ep["shots_ready"] = sum(1 for s in shots if s["status"] in ("image_ready", "video_ready"))
    return {"code": 0, "data": {
        "project": project,
        "episodes": episodes,
        "characters": store.list_characters(pid),
        "scenes": store.list_scenes(pid),
        "props": store.list_props(pid),
        "runs": store.list_runs(pid)[:20],
    }}


@router.put("/projects/{pid}")
async def update_project(pid: str, body: Dict[str, Any] = Body(...),
                         current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    _owned_project(store, pid, current_user)
    fields = {k: v for k, v in body.items()
              if k in ("title", "description", "genre", "style", "aspect_ratio", "status")}
    store.update_project(pid, _uid(current_user), fields, _is_admin(current_user))
    return {"code": 0, "data": {"project": store.get_project(pid, _uid(current_user), _is_admin(current_user))}}


@router.delete("/projects/{pid}")
async def delete_project(pid: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    _owned_project(store, pid, current_user)
    store.soft_delete(pid, _uid(current_user), _is_admin(current_user))
    return {"code": 0, "data": {"deleted": True}}


# ── 长任务：script / extract / storyboard-break / 批量生成 / 旁白（后台+runs）──


def _spawn_run(store, pid: str, kind: str, work) -> Dict[str, Any]:
    run = store.add_run({"project_id": pid, "kind": kind})

    async def _wrapper():
        try:
            result = await work()
            import json as _json
            store.update_run(run["id"], {"status": "done", "detail_json": _json.dumps(
                result if isinstance(result, (dict, list)) else {"result": str(result)},
                ensure_ascii=False, default=str)})
        except Exception as e:  # noqa: BLE001
            logger.exception("studio 后台任务失败(%s)", kind)
            store.update_run(run["id"], {"status": "failed", "error": str(e)[:500]})

    task = asyncio.create_task(_wrapper())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"code": 0, "data": {"run_id": run["id"], "status": "started"}}


@router.post("/projects/{pid}/script")
async def split_script(pid: str, body: Dict[str, Any] = Body(...),
                       current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    _owned_project(store, pid, current_user)
    content = str(body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content 必填")
    model = body.get("model")

    return _spawn_run(store, pid, "script",
                      lambda: services.split_script(store, pid, content, model=model))


@router.post("/episodes/{eid}/extract")
async def extract_assets(eid: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    project, ep = _episode_with_project(store, eid, current_user)
    return _spawn_run(store, project["id"], "extract",
                      lambda: services.extract_assets(store, project["id"], eid))


@router.post("/episodes/{eid}/storyboards")
async def break_storyboards(eid: str, body: Optional[Dict[str, Any]] = Body(default=None),
                            current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    project, _ep = _episode_with_project(store, eid, current_user)
    force = bool((body or {}).get("force"))
    return _spawn_run(store, project["id"], "storyboard",
                      lambda: services.break_storyboards(store, project["id"], eid, force=force))


@router.post("/episodes/{eid}/generate-images")
async def generate_images(eid: str, body: Optional[Dict[str, Any]] = Body(default=None),
                          current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    project, _ep = _episode_with_project(store, eid, current_user)
    provider = str((body or {}).get("provider") or "openai")
    model = str((body or {}).get("model") or "")
    provider_id = str((body or {}).get("provider_id") or "")
    return _spawn_run(store, project["id"], "images",
                      lambda: services.generate_shot_images(store, project["id"], eid,
                                                            provider=provider, model=model,
                                                            provider_id=provider_id))


@router.post("/episodes/{eid}/generate-videos")
async def generate_videos(eid: str, body: Optional[Dict[str, Any]] = Body(default=None),
                          current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    project, _ep = _episode_with_project(store, eid, current_user)
    b = body or {}
    return _spawn_run(store, project["id"], "videos",
                      lambda: services.generate_shot_videos(
                          store, project["id"], eid,
                          provider=str(b.get("provider") or "wan"),
                          model=str(b.get("model") or ""),
                          provider_id=str(b.get("provider_id") or ""),
                          resolution=str(b.get("resolution") or "1080p"),
                          duration=int(b.get("duration") or 5),
                          owner_user_id=_uid(current_user)))


@router.post("/episodes/{eid}/narration")
async def narration(eid: str, body: Optional[Dict[str, Any]] = Body(default=None),
                    current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    project, _ep = _episode_with_project(store, eid, current_user)
    voice = str((body or {}).get("voice") or "default")
    return _spawn_run(store, project["id"], "narration",
                      lambda: services.synthesize_narration(store, project["id"], eid, voice=voice))


@router.post("/projects/{pid}/assets/images")
async def asset_images(pid: str, body: Optional[Dict[str, Any]] = Body(default=None),
                       current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    _owned_project(store, pid, current_user)
    b = body or {}
    provider = str(b.get("provider") or "ark")
    ids = [str(i) for i in (b.get("ids") or [])] or None
    return _spawn_run(store, pid, "asset_images",
                      lambda: services.generate_asset_images(
                          store, pid, provider=provider, ids=ids,
                          model=str(b.get("model") or ""),
                          provider_id=str(b.get("provider_id") or "")))


# ── episodes / storyboards 读与编辑 ───────────────────────────────────────


def _backfill_video_status(store, eid: str) -> List[Dict[str, Any]]:
    """从任务账本回填镜头视频状态（recovery 循环收口 ledger → 此处只读投影）。"""
    from neurova.llm.generators.task_ledger import get_generation_task_ledger
    from neurova.llm.generators.runtime import local_url_for

    led = get_generation_task_ledger()
    shots = store.list_storyboards(eid)
    for sb in shots:
        if sb.get("video_status") == "running" and sb.get("ledger_task_id"):
            task = led.get(sb["ledger_task_id"])
            if task is None:
                continue
            if task.status == "succeeded":
                path = task.local_path or ""
                store.update_storyboard(sb["id"], {
                    "video_status": "done", "video_path": path,
                    "status": "video_ready" if path else sb["status"], "error": ""})
                sb["video_status"] = "done"
                sb["video_path"] = path
            elif task.status == "failed":
                store.update_storyboard(sb["id"], {
                    "video_status": "failed", "error": task.error[:200]})
                sb["video_status"] = "failed"
    return shots


@router.get("/episodes/{eid}")
async def get_episode(eid: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    _project, ep = _episode_with_project(store, eid, current_user)
    shots = _backfill_video_status(store, eid)
    return {"code": 0, "data": {"episode": ep, "storyboards": shots}}


@router.put("/episodes/{eid}")
async def update_episode(eid: str, body: Dict[str, Any] = Body(...),
                         current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    _project, _ep = _episode_with_project(store, eid, current_user)
    fields = {k: v for k, v in body.items()
              if k in ("title", "content", "synopsis", "status", "duration")}
    store.update_episode(eid, fields)
    return {"code": 0, "data": {"episode": store.get_episode(eid)}}


@router.post("/episodes/{eid}/storyboards/manual")
async def add_storyboard_manual(eid: str, body: Dict[str, Any] = Body(...),
                                current_user: Dict[str, Any] = Depends(get_current_user)):
    """手动新增镜头：LLM 拆解失败/不可用（如欠费）时工作台不被阻塞——
    分镜是数据行，拆解只是填充方式之一。"""
    store = get_store()
    _project, ep = _episode_with_project(store, eid, current_user)
    keep = ("number", "title", "description", "image_prompt", "video_prompt",
            "narration", "camera", "movement", "atmosphere", "bgm_prompt",
            "sound_effect", "duration", "characters", "props", "scene_id",
            "first_frame_path", "end_frame_path")
    row = {k: v for k, v in body.items() if k in keep}
    if not any(str(row.get(k) or "").strip() for k in ("description", "image_prompt", "video_prompt")):
        raise HTTPException(status_code=400, detail="镜头至少需要 description/image_prompt/video_prompt 之一")
    if "number" not in row:
        row["number"] = len(store.list_storyboards(eid)) + 1
    sb = store.add_storyboard(eid, row)
    return {"code": 0, "data": {"storyboard": sb}}


@router.put("/storyboards/{sid}")
async def update_storyboard(sid: str, body: Dict[str, Any] = Body(...),
                            current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    sb = store.get_storyboard(sid)
    if sb is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    _episode_with_project(store, sb["episode_id"], current_user)
    fields = {k: v for k, v in body.items() if k in (
        "title", "description", "image_prompt", "video_prompt", "narration",
        "camera", "movement", "atmosphere", "bgm_prompt", "sound_effect",
        "duration", "characters", "props", "first_frame_path", "end_frame_path")}
    store.update_storyboard(sid, fields)
    return {"code": 0, "data": {"storyboard": store.get_storyboard(sid)}}


@router.post("/storyboards/{sid}/retry")
async def retry_storyboard(sid: str, body: Optional[Dict[str, Any]] = Body(default=None),
                           current_user: Dict[str, Any] = Depends(get_current_user)):
    """单镜重试（huobao 批量失败一键重试语义）：stage=image|video。"""
    store = get_store()
    sb = store.get_storyboard(sid)
    if sb is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    project, _ep = _episode_with_project(store, sb["episode_id"], current_user)
    b = body or {}
    stage = str(b.get("stage") or "image")
    provider = str(b.get("provider") or ("openai" if stage == "image" else "wan"))
    model = str(b.get("model") or "")
    provider_id = str(b.get("provider_id") or "")

    if stage == "video":
        work = lambda: services.generate_shot_videos(  # noqa: E731
            store, project["id"], sb["episode_id"], provider=provider, model=model,
            provider_id=provider_id, owner_user_id=_uid(current_user), shot_ids=[sid])
    else:
        work = lambda: services.generate_shot_images(  # noqa: E731
            store, project["id"], sb["episode_id"], provider=provider, model=model,
            provider_id=provider_id, shot_ids=[sid])
    return _spawn_run(store, project["id"], f"retry_{stage}", work)


# ── merge / assets ────────────────────────────────────────────────────────


@router.post("/episodes/{eid}/merge")
async def merge(eid: str, body: Optional[Dict[str, Any]] = Body(default=None),
                current_user: Dict[str, Any] = Depends(get_current_user)):
    """合并导出同步执行（本地 FFmpeg 拼接或连播清单，秒级）。

    body.bgm_path（A3）：用户已上传的 BGM 音频本地路径，参与二级混音。"""
    store = get_store()
    project, _ep = _episode_with_project(store, eid, current_user)
    res = await services.merge_episode(store, project["id"], eid,
                                       bgm_path=str((body or {}).get("bgm_path") or ""))
    code = 0 if res.get("ok") else -1
    return {"code": code, "data": res}


@router.get("/merges/{mid}")
async def get_merge(mid: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    store = get_store()
    merge_row = store.get_merge(mid)
    if not merge_row:
        raise HTTPException(status_code=404, detail="合成记录不存在")
    _owned_project(store, merge_row["project_id"], current_user)
    return {"code": 0, "data": {"merge": merge_row}}


@router.put("/assets/{table}/{asset_id}")
async def update_asset(table: str, asset_id: str, body: Dict[str, Any] = Body(...),
                       current_user: Dict[str, Any] = Depends(get_current_user)):
    if table not in ("characters", "scenes", "props"):
        raise HTTPException(status_code=400, detail="非法资产表")
    store = get_store()
    row = store.get_asset_row(table, asset_id)
    if not row:
        raise HTTPException(status_code=404, detail="资产不存在")
    _owned_project(store, row["project_id"], current_user)
    keep = {"description", "appearance", "styling", "personality", "final_prompt",
            "prompt", "lighting", "name", "role", "image_path"}
    store.update_asset_row(table, asset_id, {k: v for k, v in body.items() if k in keep})
    return {"code": 0, "data": {"asset": store.get_asset_row(table, asset_id)}}
