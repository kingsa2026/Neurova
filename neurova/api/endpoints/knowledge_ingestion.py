"""知识导入端点（R-4 多格式文件导入 + 远程网页导入含 SSRF 防护）与图谱抽取桥接。

2026-09-16 自 knowledge.py 拆出；路径与响应契约不变。
外部消费方（knowledge_graph_api / knowledge/ingest_worker）经 knowledge
聚合器 re-export 引用 _default_llm_call / _import_file_data / _fetch_url，
签名与语义不变。

依赖方向（架构约束，2026-09-16 拆分后冻结；全图见 knowledge.py 头部）：
    本模块 ──▶ knowledge_common（repository 解析等）
              ──▶ neurova.knowledge.graph_bridge（图谱抽取桥，函数内懒导入）
    禁止：本模块 import 兄弟叶子（core/sharing/remote），也禁止 import
    聚合器 knowledge.py（成环）；共享需求下沉 knowledge_common。
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile

from neurova.api.auth import get_current_user_or_service
from neurova.core.logger import get_logger
from neurova.knowledge.document_pipeline import resolveSourceDates
from neurova.knowledge.url_guard import validate_public_http_url
from neurova.api.endpoints.knowledge_common import get_repository

logger = get_logger(__name__)

router = APIRouter()

# 抽取三件套下沉共享层（endpoints 分层守卫不变量 2：叶子之间零交叉）。
# 本模块的 /import 路由与 knowledge_core 的 PUT 更新路径共用同一份实装，
# 名字经本地绑定取得——patch 本模块属性仍能改到路由实际调用的那个对象。
from neurova.api.endpoints.knowledge_common import (  # noqa: E402,F401
    ENV_EVENT_SUMMARY, ENV_EXTRACT_ON_UPDATE, _EVENT_SUMMARY_PROMPT,
    _default_llm_call, _resolve_runtime_agents, _try_extract_to_graph,
    extract_after_update, extract_event_summary,
)

#: 条目更新后 facts 重抽的门控（SAG 对比候选 C2）：LLM 成本随更新量走，
#: 默认 off＝旧行为；开闸时复用导入抽取同一条管线，增量 admit 不删旧 facts。

def _build_item_dict(item: Dict[str, Any]) -> Dict[str, Any]:
    """导入响应投影：剔 chunks 正文冗余（块已含于 content），附 chunk_count。"""
    item = dict(item)
    chunks = item.pop("chunks", None) or []
    item["chunk_count"] = len(chunks) or 1
    return item



@router.post("/import")
async def import_knowledge_file(
    file: UploadFile,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
    agent_id: str = Query(default="default", description="Agent ID"),
    sync: bool = Query(default=True, description="true=同步导入（现行为）；false=入队后台处理，返回 task_id（P1-#9）"),
    ocr: str = Query(default="auto", description="auto=仅对无文字层页面 OCR；on=强制 OCR；off=禁用"),
    engine: str = Query(default="", pattern="^(structured|legacy)?$",
                        description="structured=页码/标题/OCR 流水线；legacy=旧单段抽取（回退）；空=读 NEUROVA_KB_DOC_PIPELINE"),
    source_path: str = Query(default="", description="客户端可提供的真实路径；缺省用文件名（裸文件名不触发同源更新）"),
):
    """导入知识文件（txt/md/docx/xlsx/pptx/pdf/html/csv）。

    R-4: 复用 attachment_parser 抽取文本，抽取成功则创建知识条目
    （归属当前用户、默认私有）。批次 3：导入后触发图谱抽取。
    P1-#9：sync=false 走持久化摄取队列（落文件+入队即返 task_id，崩溃可重跑；
    异步路径不做图谱抽取，结果标 skipped_async）。
    """
    filename = file.filename or "imported"
    # 直接调用（测试/内部）时未传该参会是 FastAPI Query 默认对象，不能当字符串用。
    sourcePath = source_path if isinstance(source_path, str) else ""
    data = await file.read()
    if not sync:
        from neurova.knowledge.ingest_queue import get_ingress_queue

        task = get_ingress_queue().enqueue_upload(
            filename=filename, data=data, agent_id=agent_id,
            user_id=str(current_user.get("user_id") or ""),
        )
        return {"code": 0, "message": "Queued", "data": {"task_id": task["task_id"], "status": task.get("status"), "replayed": task.get("replayed", False)}}
    items, extract_status = _import_file_data(
        data, filename, agent_id, current_user, ocr_mode=ocr,
        engine_mode=engine, source_path=sourcePath,
    )
    if not items:
        # 2026-09-06 修复：抽取失败显式化——此前以成功语义静默返回空列表，
        # 前端一律提示"导入成功"，用户无从知晓 .ppt 旧格式/超 2MB/纯图片页
        # 实际未入库（"提示成功但列表没有"的根因）。
        return {
            "code": 1,
            "message": f"extract_failed:{extract_status}",
            "data": {"items": [], "status": extract_status},
        }
    _try_extract_to_graph(
        items, request, agent_id=agent_id,
        tenant_id=str(current_user.get("tenant_id") or "default"),
    )
    # C5：事件摘要生成（NEUROVA_KB_EVENT_SUMMARY 门控默认 off，关闸零开销）。
    tenantId = str(current_user.get("tenant_id") or "default")
    for entry in items:
        extract_event_summary(entry, request, agent_id=agent_id, tenant_id=tenantId)
    return {"code": 0, "message": "Import completed", "data": {"items": items}}


def _import_file_data(
    data: bytes, filename: str, agent_id: str, user: Dict[str, Any],
    ocr_mode: str = "auto", engine_mode: str = "", source_path: str = "",
) -> Tuple[List[Dict[str, Any]], str]:
    engine_mode = engine_mode or os.environ.get(
        "NEUROVA_KB_DOC_PIPELINE", "structured"
    )
    from neurova.knowledge.document_pipeline import DocumentParseError, parse_document

    try:
        parsed = parse_document(
            data, filename, source_path=source_path or filename, ocr_mode=ocr_mode,
            engine_mode=engine_mode,
        )
    except DocumentParseError as exc:
        logger.info("[知识导入] %s 未抽取文本 (%s)", filename, exc.reason)
        return [], exc.reason
    except Exception as exc:  # noqa: BLE001 - 解析失败按抽取失败上报
        logger.warning("[知识导入] %s 解析异常: %s", filename, exc)
        return [], "parse_failed:%s" % type(exc).__name__

    repo = get_repository()
    srcCreated, srcModified = resolveSourceDates(
        parsed.metadata, ingest_time=str(parsed.ingest_time or ""))
    # 元数据缺失时 modified 是用入库时刻顶替的回退钟，不能当"源修改时间"
    # 去触发 TB 覆盖（P2-5）。
    srcModifiedEstimated = not str(parsed.metadata.get("modified_at") or "").strip()
    title = str(parsed.metadata.get("title") or _title_from_filename(filename))
    item = repo.create_knowledge(
        agent_id=agent_id,
        title=title,
        content=parsed.content,
        category="import",
        tags=[],
        source="import:" + filename,
        confidence=0.7,
        visibility="private",
        owner_user_id=str((user or {}).get("user_id", "") or "default"),
        tenant_id=str((user or {}).get("tenant_id") or "default"),
        chunks=parsed.chunks,
        parents=parsed.parents,
        # P0-3 闭环审查修 D：批量导入不进同值冲突队列——同名文件批量导入
        # （课件/周报）会瞬间产生 N-1 条 pending 刷屏待审；导入条目已有
        # source 字段独立溯源，冲突检测留给交互式单条创建路径
        detect_conflict=False,
        source_type=parsed.source_type,
        source_path=parsed.source_path,
        ingest_time=parsed.ingest_time,
        author=str(parsed.metadata.get("author") or ""),
        page_count=parsed.metadata.get("page_count"),
        ocr_used=bool(parsed.metadata.get("ocr_used")),
        ocr_engine=str(parsed.metadata.get("ocr_engine") or ""),
        ocr_confidence_avg=parsed.metadata.get("ocr_confidence_avg"),
        document_id=parsed.doc_id,
        dedupe=True,
        source_created_at=srcCreated,
        source_modified_at=srcModified,
        source_modified_estimated=srcModifiedEstimated,
    )
    return [_build_item_dict(item)], parsed.source_type


def _title_from_filename(filename: str) -> str:
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    return base.strip() or "Imported Knowledge"


def _title_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip("/") or "root"
    name = path.rsplit("/", 1)[-1]
    return name[:64] or parsed.netloc or "Web Page"


def _filename_for_url(url: str) -> str:
    """网页抓取的解析文件名：真实扩展名优先，无扩展名补 .html。

    parse_document 按文件名扩展分派；URL 末段常是 `article` 这种无扩展名形态，
    直接用标题（无扩展）会判 unsupported_format——线上 /import-url 因此对
    大多数网页恒失败。source_path 仍用真实 URL（P2-5）。
    """
    parsed = urllib.parse.urlparse(url)
    name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if name and "." in name:
        return name
    return _title_from_url(url) + ".html"


def _fetch_url(url: str) -> bytes:
    """抓取远程网页（测试可 monkeypatch）。校验通过后由 urllib 拉取。"""
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Neurova-KB/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read(1024 * 1024)  # 最多 1MB


@router.post("/import-url")
async def import_knowledge_url(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
    agent_id: str = Query(default="default", description="Agent ID"),
    url: str = Query(..., description="远程网页 URL"),
    sync: bool = Query(default=True, description="true=同步导入；false=入队后台处理（P1-#9）"),
):
    """导入远程网页（抽取正文存为知识条目，归属当前用户、默认私有）"""
    if not validate_public_http_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL: only public http(s) allowed")

    if not sync:
        # SSRF 校验已在上方（安全门不后置）；抓取挪到 worker 执行。
        from neurova.knowledge.ingest_queue import get_ingress_queue

        task = get_ingress_queue().enqueue_url(
            url=url, title_hint=_title_from_url(url), agent_id=agent_id,
            user_id=str(current_user.get("user_id") or ""),
        )
        return {"code": 0, "message": "Queued", "data": {"task_id": task["task_id"], "status": task.get("status"), "replayed": task.get("replayed", False)}}

    try:
        data = _fetch_url(url)
    except Exception as e:
        raise HTTPException(status_code=502, detail="Fetch failed: %s" % e)

    # P1-#9 顺带修复预存 bug：原实现 `items = _import_file_data(...)` 未解包，
    # items 实为 (list, status) 元组——抽取失败仍返回 code=0 谎报成功，且
    # data.items 形状是 [条目列表, 状态串]（前端消费 items[0] 才碰巧对）。
    # 与 /import 对齐：解包 + 失败显式 code=1。
    items, extract_status = _import_file_data(
        data, _filename_for_url(url), agent_id, current_user, source_path=url,
    )
    if not items:
        return {
            "code": 1,
            "message": f"extract_failed:{extract_status}",
            "data": {"items": [], "status": extract_status},
        }
    _try_extract_to_graph(
        items, request, agent_id=agent_id,
        tenant_id=str(current_user.get("tenant_id") or "default"),
    )
    # C5：事件摘要生成（门控同 /import；关闸零开销）。
    urlTenantId = str(current_user.get("tenant_id") or "default")
    for entry in items:
        extract_event_summary(entry, request, agent_id=agent_id, tenant_id=urlTenantId)
    return {"code": 0, "message": "URL import completed", "data": {"items": items}}
