# -*- coding: utf-8 -*-
"""创作专区业务编排（R3）：剧本→资产→分镜→批量首帧/视频→旁白→合并。

对齐 huobao-drama 阶段模型（功能自研）；生成通道全部复用批次0/1 单源
（llm.generators.protocols + runtime + task_ledger + recovery 循环）：
- 图像：generate_image + @角色参考图注入 + 风格/画幅项目锁注入
- 视频：submit_video 提交 → 账本 batch_key=episode 关联 → 恢复循环收口本地化
- 合并：有 FFmpeg 真拼接；无则 slideshow manifest（诚实降级，与 drama 节点同策略）
所有 LLM/生成函数支持注入 fake llm（网络零依赖单测）。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from neurova.aigc_studio.llm import (
    EXTRACTOR, PROMPT_GENERATOR, SCRIPT_REWRITER, STORYBOARD_BREAKER,
    call_llm, extract_json,
)
from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 图像服务商 → 实测协议 hint（与 drama_nodes._SCENE_PROTOCOLS 对齐的本地小表）
_PROVIDER_HINTS = {
    "openai": "openai_compat",
    "wanx": "dashscope",
    "dashscope": "dashscope",
    "ark": "ark",
    "seedream": "ark",
}


def _aspect_token(aspect: str) -> str:
    return str(aspect or "9:16").split()[0]


# ── Phase 01：剧本拆解 ────────────────────────────────────────────────────


async def split_script(store, pid: str, novel_text: str,
                       llm: Optional[Callable[[str, str], Awaitable[str]]] = None,
                       model: Optional[str] = None) -> List[Dict[str, Any]]:
    """小说/故事 → 分集剧本（LLM；坏输出回退原文单集，不中断）。"""
    llm = llm or call_llm
    run = store.add_run({"project_id": pid, "kind": "script",
                         "detail_json": json.dumps({"chars": len(novel_text or "")})})
    prompt = (
        "请把下面的小说拆解为分集拍摄脚本（按剧情自然分集）。\n\n"
        f"原文：\n{novel_text[:12000]}"
    )
    fallback_reason = ""
    try:
        raw = await llm(prompt, SCRIPT_REWRITER)
        parsed = extract_json(raw, "array")
    except Exception as e:  # noqa: BLE001
        logger.warning("剧本拆解 LLM 失败，回退原文单集: %s", e)
        parsed, fallback_reason = None, str(e)[:200]
    eps: List[Dict[str, Any]] = []
    if isinstance(parsed, list) and parsed:
        for i, item in enumerate(parsed, 1):
            if not isinstance(item, dict):
                continue
            eps.append(store.add_episode(pid, {
                "number": int(item.get("number") or i),
                "title": str(item.get("title") or f"第{i}集"),
                "content": str(item.get("content") or ""),
                "synopsis": str(item.get("synopsis") or ""),
            }))
    if not eps:
        eps.append(store.add_episode(pid, {
            "number": 1, "title": "第1集", "content": novel_text or "",
            "synopsis": "", "status": "draft",
        }))
        fallback_reason = fallback_reason or "LLM 输出不可解析"
    store.update_run(run["id"], {
        "status": "done",
        "detail_json": json.dumps({"episodes": len(eps), "fallback": fallback_reason},
                                  ensure_ascii=False),
    })
    return eps


# ── Phase 02：资产抽取（去重）─────────────────────────────────────────────


async def extract_assets(store, pid: str, eid: str,
                         llm: Optional[Callable[[str, str], Awaitable[str]]] = None,
                         ) -> Dict[str, Any]:
    """剧本 → 角色/场景/道具抽取；同名人跳过（huobao 去重语义）。"""
    llm = llm or call_llm
    ep = store.get_episode(eid) or {}
    run = store.add_run({"project_id": pid, "kind": "extract"})
    prompt = f"剧本（第{ep.get('number', 1)}集《{ep.get('title', '')}》）：\n{str(ep.get('content') or '')[:8000]}"
    added = {"characters_added": 0, "scenes_added": 0, "props_added": 0,
             "characters_skipped": 0, "scenes_skipped": 0, "props_skipped": 0}
    parsed = None
    err = ""
    try:
        parsed = extract_json(await llm(prompt, EXTRACTOR), "object")
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
    parsed = parsed if isinstance(parsed, dict) else {}

    existing_c = {c["name"] for c in store.list_characters(pid)}
    for item in parsed.get("characters") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        if str(item["name"]) in existing_c:
            added["characters_skipped"] += 1
            continue
        existing_c.add(str(item["name"]))
        store.add_character(pid, {
            "name": str(item["name"]), "role": str(item.get("role") or ""),
            "description": str(item.get("description") or ""),
            "appearance": str(item.get("appearance") or ""),
            "styling": str(item.get("styling") or ""),
            "personality": str(item.get("personality") or ""),
            "final_prompt": str(item.get("final_prompt") or item.get("prompt") or ""),
        })
        added["characters_added"] += 1
    existing_s = {f"{s['location']}|{s['time']}" for s in store.list_scenes(pid)}
    for item in parsed.get("scenes") or []:
        if not isinstance(item, dict) or not (item.get("location") or item.get("prompt")):
            continue
        key = f"{item.get('location', '')}|{item.get('time', '')}"
        if key in existing_s:
            added["scenes_skipped"] += 1
            continue
        existing_s.add(key)
        store.add_scene(pid, {
            "episode_id": eid, "location": str(item.get("location") or ""),
            "time": str(item.get("time") or ""), "prompt": str(item.get("prompt") or ""),
            "lighting": str(item.get("lighting") or ""),
        })
        added["scenes_added"] += 1
    existing_p = {p["name"] for p in store.list_props(pid)}
    for item in parsed.get("props") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        if str(item["name"]) in existing_p:
            added["props_skipped"] += 1
            continue
        existing_p.add(str(item["name"]))
        store.add_prop(pid, {"name": str(item["name"]),
                             "description": str(item.get("description") or "")})
        added["props_added"] += 1

    store.update_run(run["id"], {
        "status": "done" if not err else "done_with_fallback",
        "detail_json": json.dumps({**added, "error": err}, ensure_ascii=False),
    })
    return added


# ── Phase 03：分镜拆解 ────────────────────────────────────────────────────


async def break_storyboards(store, pid: str, eid: str, force: bool = False,
                            llm: Optional[Callable[[str, str], Awaitable[str]]] = None,
                            ) -> List[Dict[str, Any]]:
    """分集剧本 → 分镜镜头（含角色/道具名→资产 id 映射，供 @mention 参考注入）。"""
    llm = llm or call_llm
    if store.list_storyboards(eid) and not force:
        return store.list_storyboards(eid)
    ep = store.get_episode(eid) or {}
    run = store.add_run({"project_id": pid, "kind": "storyboard"})
    chars = {c["name"]: c for c in store.list_characters(pid)}
    props = {p["name"]: p for p in store.list_props(pid)}
    prompt = (
        f"为第{ep.get('number', 1)}集《{ep.get('title', '')}》拆出分镜。"
        f"可用角色：{list(chars)}；可用场景：{[s['location'] for s in store.list_scenes(pid)]}。"
        f"\n剧本：\n{str(ep.get('content') or '')[:8000]}"
    )
    shots: List[Dict[str, Any]] = []
    try:
        parsed = extract_json(await llm(prompt, STORYBOARD_BREAKER), "array")
    except Exception as e:  # noqa: BLE001
        logger.warning("分镜拆解 LLM 失败: %s", e)
        parsed = None
    if isinstance(parsed, list):
        for i, item in enumerate(parsed, 1):
            if not isinstance(item, dict):
                continue
            char_ids = [{"name": n, "id": chars[n]["id"]}
                        for n in (item.get("characters") or []) if n in chars]
            prop_ids = [{"name": n, "id": props[n]["id"]}
                        for n in (item.get("props") or []) if n in props]
            shots.append(store.add_storyboard(eid, {
                "number": int(item.get("number") or i),
                "title": str(item.get("title") or ""),
                "description": str(item.get("description") or ""),
                "image_prompt": str(item.get("image_prompt") or ""),
                "video_prompt": str(item.get("video_prompt") or ""),
                "narration": str(item.get("narration") or ""),
                "camera": str(item.get("camera") or ""),
                "movement": str(item.get("movement") or ""),
                "atmosphere": str(item.get("atmosphere") or ""),
                "bgm_prompt": str(item.get("bgm_prompt") or ""),
                "sound_effect": str(item.get("sound_effect") or ""),
                "duration": float(item.get("duration") or 3),
                "characters": char_ids, "props": prop_ids,
                "status": "pending",
            }))
    store.update_run(run["id"], {
        "status": "done", "detail_json": json.dumps({"shots": len(shots)})})
    return shots


# ── 批量生成：首帧图 / 视频 / 旁白 ─────────────────────────────────────────


def _resolve_creds(hint: str, model: str, provider_id: Any):
    from neurova.llm.generators.runtime import resolve_generation_creds

    return resolve_generation_creds(hint, model or "", provider_id or None, None, None,
                                    "https://api.openai.com/v1")


def _inject_style(prompt: str, project: Dict[str, Any]) -> str:
    """火宝式项目锁：风格 + 画幅注入每镜提示词。"""
    parts = [prompt]
    style = str(project.get("style") or "").strip()
    if style:
        parts.append(style)
    parts.append(f"{_aspect_token(str(project.get('aspect_ratio') or ''))} aspect ratio")
    return ", ".join(p for p in parts if p)


async def generate_shot_images(store, pid: str, eid: str,
                               provider: str = "openai", model: str = "",
                               shot_ids: Optional[List[str]] = None) -> Dict[str, int]:
    """逐镜首帧（@角色参考图注入 + 风格/画幅项目锁；单镜失败诚实标注不中断）。

    shot_ids：仅重跑指定镜头（Phase03 单镜重试）；None = 整集。
    """
    from neurova.llm.generators.protocols import generate_image
    from neurova.llm.generators.runtime import (
        GENERATION_OUTPUT_DIR, GenerationCredsError, persist_media,
    )

    project = store.get_project(pid, "admin", is_admin=True) or {}
    hint = _PROVIDER_HINTS.get(str(provider or "").lower(), "openai_compat")
    stats = {"done": 0, "failed": 0, "skipped_no_prompt": 0}
    chars = {c["id"]: c for c in store.list_characters(pid)}
    for sb in store.list_storyboards(eid):
        if shot_ids and sb["id"] not in shot_ids:
            continue
        base_prompt = sb.get("image_prompt") or sb.get("description") or ""
        if not base_prompt.strip():
            stats["failed"] += 1
            stats["skipped_no_prompt"] += 1
            store.update_storyboard(sb["id"], {
                "status": "failed", "error": "无画面提示词（image_prompt/description 均为空）"})
            continue
        injected = _inject_style(base_prompt, project)
        refs = [chars[c["id"]]["image_path"]
                for c in (json.loads(sb.get("characters_json") or "[]"))
                if c.get("id") in chars and chars[c["id"]].get("image_path")]
        store.update_storyboard(sb["id"], {"injected_prompt": injected})
        try:
            creds = _resolve_creds(hint, model, None)
            result = await generate_image(
                creds, injected, size="1024x1024", n=1,
                ref_images=refs)
            remote = [u for u in (result.get("images") or []) if u]
            if not remote:
                raise RuntimeError("协议未返回图像")
            path = await persist_media(remote[0], "image", f"studio_{sb['id']}", 0)
            store.update_storyboard(sb["id"], {
                "first_frame_path": path, "status": "image_ready", "error": ""})
            stats["done"] += 1
        except Exception as e:  # noqa: BLE001 — 单镜失败隔离
            logger.warning("分镜首帧失败(%s): %s", sb["id"], e)
            store.update_storyboard(sb["id"], {
                "status": "failed", "error": str(e)[:200]})
            stats["failed"] += 1
    _record_usage("image", stats.get("done", 0), stats.get("failed", 0),
                  project.get("owner_user_id", ""))
    return stats


def _record_usage(kind: str, ok: int, failed: int, user_id: str) -> None:
    """L4：Studio 批量生成聚合入账 AIGC 用量（写失败静默）。"""
    try:
        from neurova.core.aigc_usage import get_aigc_usage

        usage = get_aigc_usage()
        if ok:
            usage.record(kind=kind, user_id=user_id, status="success", items=ok)
        if failed:
            usage.record(kind=kind, user_id=user_id, status="failed", items=0)
    except Exception:  # noqa: BLE001
        pass


async def generate_shot_videos(store, pid: str, eid: str, provider: str = "wan",
                               model: str = "", resolution: str = "1080p",
                               duration: int = 5, owner_user_id: str = "",
                               shot_ids: Optional[List[str]] = None) -> Dict[str, int]:
    """逐镜 i2v 提交（首帧为参考）→ 账本 batch_key=episode 关联 → 恢复循环收口。"""
    from neurova.llm.generators.protocols import submit_video
    from neurova.llm.generators.task_ledger import TaskRecord, get_generation_task_ledger

    hint = {"wan": "wan", "seedance": "seedance2", "veo": "veo"}.get(
        str(provider or "").lower(), "wan")
    default_base = ("https://dashscope.aliyuncs.com/api/v1" if hint == "wan"
                    else "https://ark.cn-beijing.volces.com" if hint == "seedance2"
                    else "https://generativelanguage.googleapis.com/v1beta")
    stats = {"submitted": 0, "skipped": 0, "failed": 0}
    for sb in store.list_storyboards(eid):
        if shot_ids and sb["id"] not in shot_ids:
            continue
        vprompt = (sb.get("video_prompt") or sb.get("description") or "").strip()
        frame = sb.get("first_frame_path") or ""
        if not vprompt:
            stats["skipped"] += 1
            continue
        if sb.get("video_status") == "running":
            stats["skipped"] += 1
            continue
        try:
            creds = _resolve_creds(hint, model, None)
            from neurova.llm.generators.protocols import ProtocolCredentials

            creds = ProtocolCredentials(
                api_key=creds.api_key, base_url=creds.base_url or default_base,
                model=creds.model, protocol=hint)
            submitted = await submit_video(
                creds, vprompt, duration=int(sb.get("duration") or duration),
                resolution=resolution,
                ref_images=[frame] if frame and Path(frame).is_file() else [],
                # A1：镜头尾帧（存在才透传；WAN 无通道进 ignored_params，
                # Seedance first+last 插值）
                last_frame=(sb.get("end_frame_path") or None))
            remote_id = str(submitted.get("task_id") or "")
            if not remote_id:
                raise RuntimeError("提交未返回 task_id")
            record = get_generation_task_ledger().add(TaskRecord(
                kind="video", provider_id="", protocol=hint, model=creds.model,
                base_url=creds.base_url, status="submitted", remote_task_id=remote_id,
                poll_url=str(submitted.get("poll_url") or ""),
                prompt=vprompt[:500], owner_user_id=owner_user_id,
                source="workflow", batch_key=eid, project_id=pid,
                ignored_params=",".join(submitted.get("ignored_params") or []),
            ))
            store.update_storyboard(sb["id"], {
                "video_status": "running", "ledger_task_id": record.task_id,
                "error": ""})
            stats["submitted"] += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("分镜视频提交失败(%s): %s", sb["id"], e)
            store.update_storyboard(sb["id"], {
                "video_status": "failed", "error": str(e)[:200]})
            stats["failed"] += 1
    _record_usage("video", stats.get("submitted", 0), stats.get("failed", 0), "")
    return stats


async def generate_asset_images(store, pid: str, provider: str = "ark",
                                ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """资产定妆图（同角色复用 seed_value 保一致性；单资产失败可重试）。"""
    from neurova.llm.generators.protocols import generate_image
    from neurova.llm.generators.runtime import persist_media

    project = store.get_project(pid, "admin", is_admin=True) or {}
    hint = _PROVIDER_HINTS.get(str(provider or "").lower(), "openai_compat")
    stats = {"done": 0, "failed": 0}
    for c in store.list_characters(pid):
        if ids and c["id"] not in ids:
            continue
        prompt = (c.get("final_prompt") or
                  f"character sheet, {c.get('appearance') or c.get('name')}, "
                  f"{c.get('styling') or ''}").strip()
        try:
            creds = _resolve_creds(hint, "", None)
            import zlib
            # 稳定 seed：同一资产恒定（跨进程可复现），支撑 huobao 式定妆一致性
            seed = zlib.crc32(c["id"].encode("utf-8")) % (10 ** 8)
            result = await generate_image(creds, _inject_style(prompt, project),
                                          size="1024x1024", n=1, seed=seed)
            remote = [u for u in (result.get("images") or []) if u]
            if not remote:
                raise RuntimeError("未返回图像")
            path = await persist_media(remote[0], "image", f"asset_{c['id']}", 0)
            store.update_asset_row("characters", c["id"], {
                "image_path": path, "seed_value": str(seed), "status": "ready"})
            store.add_asset({"project_id": pid, "kind": "character",
                             "name": c["name"], "ref_path": path,
                             "meta": {"asset_id": c["id"], "seed": seed}})
            stats["done"] += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("资产定妆失败(%s): %s", c["id"], e)
            store.update_asset_row("characters", c["id"], {
                "status": "failed"})
            stats["failed"] += 1
    return stats


async def synthesize_narration(store, pid: str, eid: str, voice: str = "default") -> Dict[str, int]:
    """逐镜旁白 TTS（VoiceEngine/TTSManager 双通道，产物落 data/generations）。"""
    stats = {"done": 0, "failed": 0, "skipped": 0}
    for sb in store.list_storyboards(eid):
        text = (sb.get("narration") or "").strip()
        if not text:
            stats["skipped"] += 1
            continue
        try:
            path = await _synthesize_to_file(text, voice)
            store.update_storyboard(sb["id"], {"audio_path": path})
            stats["done"] += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("旁白合成失败(%s): %s", sb["id"], e)
            stats["failed"] += 1
    return stats


async def _synthesize_to_file(text: str, voice: str) -> str:
    from neurova.api.endpoints import get_app_state
    from neurova.llm.generators.runtime import persist_bytes

    state = get_app_state() or {}
    engine = (state.get("voice_engines") or {}).get("tts")
    audio = None
    if engine and engine.is_available():
        result = await engine.process(input_data=text, operation="synthesize",
                                      voice=voice, speed=1.0)
        if getattr(result, "error", None):
            raise RuntimeError(str(result.error))
        audio = getattr(result, "audio_data", None)
    else:
        mgr = state.get("tts_manager")
        if not mgr or not mgr.is_initialized:
            raise RuntimeError("TTS 引擎未就绪")
        audio = await mgr.synthesize(text, voice=voice)
    if not audio:
        raise RuntimeError("合成失败")
    import uuid as _uuid
    return await persist_bytes(audio, "wav", _uuid.uuid4().hex[:16], 0)


# ── Phase 04：合并导出 ────────────────────────────────────────────────────


def _fmt_srt_ts(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    h, rem = divmod(millis, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(shots: List[Dict[str, Any]]) -> str:
    lines = []
    start = 0.0
    for i, sb in enumerate(shots, 1):
        text = str(sb.get("narration") or sb.get("description") or "").strip()
        if not text:
            continue
        end = start + max(2.0, float(sb.get("duration") or 3))
        lines += [str(i), f"{_fmt_srt_ts(start)} --> {_fmt_srt_ts(end)}", text, ""]
        start = end
    return "\n".join(lines)


async def merge_episode(store, pid: str, eid: str) -> Dict[str, Any]:
    """制片导出：FFmpeg 真拼接（有二进制且镜头有视频）→ mp4；否则连播清单 manifest。"""
    from neurova.core.ffmpeg import resolve_ffmpeg_path
    from neurova.llm.generators.runtime import (
        GENERATION_OUTPUT_DIR, local_url_for, persist_bytes,
    )

    shots = store.list_storyboards(eid)
    # 字幕文件先落（两种模式都需要）
    srt = build_srt(shots)
    subtitle_path = ""
    if srt:
        subtitle_path = await persist_bytes(srt.encode("utf-8"), "srt", f"studio_{eid}_srt", 0)
        store.update_episode(eid, {"subtitle_path": subtitle_path})

    items = [{
        "index": i + 1,
        "shot": sb.get("number"),
        "image": local_url_for(sb["first_frame_path"]) if sb.get("first_frame_path") else "",
        "video": local_url_for(sb["video_path"]) if sb.get("video_path") else "",
        "audio": local_url_for(sb["audio_path"]) if sb.get("audio_path") else "",
        "text": sb.get("narration") or sb.get("description") or "",
    } for i, sb in enumerate(shots)]

    videos = [sb.get("video_path") for sb in shots if sb.get("video_path")
              and Path(sb["video_path"]).is_file()]
    ffmpeg = resolve_ffmpeg_path()
    if ffmpeg and len(videos) >= 1:
        try:
            import subprocess
            import tempfile

            out_path = GENERATION_OUTPUT_DIR / f"studio_episode_{eid}.mp4"
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                             encoding="utf-8") as lf:
                for v in videos:
                    lf.write("file '" + str(v).replace("'", "'\\''") + "'\n")
                list_file = lf.name
            cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_file,
                   "-c", "copy", str(out_path)]
            proc = subprocess.run(cmd, capture_output=True, timeout=600, check=False)
            Path(list_file).unlink(missing_ok=True)
            if proc.returncode == 0 and out_path.is_file():
                merge = store.add_merge({
                    "project_id": pid, "episode_id": eid, "mode": "ffmpeg_concat",
                    "status": "done", "output_path": str(out_path),
                    "output_url": local_url_for(str(out_path)), "items": items,
                })
                store.update_episode(eid, {"video_path": str(out_path),
                                           "status": "exported"})
                return {"ok": True, "composed": True, "mode": "ffmpeg_concat",
                        "url": merge["output_url"], "merge": merge, "items": items}
            err = f"FFmpeg 失败: {(proc.stderr or b'')[-200:].decode(errors='ignore')}"
        except Exception as e:  # noqa: BLE001
            err = f"FFmpeg 异常: {str(e)[:200]}"
        logger.warning("%s（降级连播清单）", err)

    has_material = any(videos) or any(
        sb.get("first_frame_path") or sb.get("audio_path") for sb in shots)
    if not has_material:
        merge = store.add_merge({
            "project_id": pid, "episode_id": eid, "mode": "none",
            "status": "failed", "error": "无就绪产物（镜头未生成图/音/视频）",
            "items": items})
        return {"ok": False, "composed": False, "mode": "none",
                "error": "无就绪产物（镜头未生成图/音/视频）",
                "merge": merge, "items": items}

    merge = store.add_merge({
        "project_id": pid, "episode_id": eid, "mode": "slideshow_manifest",
        "status": "manifest", "error": "" if ffmpeg else "本机无 FFmpeg，输出连播清单",
        "items": items})
    return {"ok": True, "composed": False, "mode": "slideshow_manifest",
            "merge": merge, "items": items,
            "error": ""}
