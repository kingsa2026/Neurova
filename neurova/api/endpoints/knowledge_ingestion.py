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

import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile

from neurova.api.auth import get_current_user_or_service
from neurova.core.logger import get_logger
from neurova.api.endpoints.knowledge_common import get_repository

logger = get_logger(__name__)

router = APIRouter()


def _build_item_dict(item: Dict[str, Any]) -> Dict[str, Any]:
    """导入响应投影：剔 chunks 正文冗余（块已含于 content），附 chunk_count。"""
    item = dict(item)
    chunks = item.pop("chunks", None) or []
    item["chunk_count"] = len(chunks) or 1
    return item


def _resolve_runtime_agents(request: Optional[Request]) -> Dict[str, Any]:
    """运行时 Agent 注册表解析（生产唯一事实源 + 测试回退）。

    生产链路：app.py 经 set_app_state 注入的 neurova.api.endpoints 模块级
    注册表（home.py _get_app_state 注释已明示：request.app.state 是
    Starlette State 对象，生产从不写入 agents）。回退读 request.app.state
    仅兼容测试自建 app 直接挂载的写法。
    """
    try:
        from neurova.api.endpoints import get_app_state

        agents = (get_app_state() or {}).get("agents")
        if agents:
            return agents
    except Exception:  # noqa: BLE001
        pass
    try:
        return getattr(getattr(getattr(request, "app", None), "state", None), "agents", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def _default_llm_call(request: Optional[Request], prefer_agent_id: Optional[str] = None):
    """从运行时 Agent 解析 LLM 调用器（prompt→文本）；不可用返回 None（跳过抽取）。

    根因修复（2026-09-05 知识图谱空图）：agent 从注册表解析（此前读
    request.app.state.agents——生产恒空，抽取恒被跳过）；AgentLLMClient.chat
    是 async，经 mem_core.run_async_safely 同步桥接（BE-CORE-001 同款，
    此前同步调用拿到 coroutine 后 content 恒空）。

    prefer_agent_id：优先用知识所属 Agent 的 llm_client（per-agent 模型配置）；
    其模型不可用（AgentLLMClient 错误契约返回 "[LLM Error]" 文本或抛异常）时
    逐个回退其他活跃 Agent——抽取是后台增强任务，不应因单个 Agent 配置坏而死亡。
    """
    try:
        agents = _resolve_runtime_agents(request)
        candidates: List[Any] = []
        if prefer_agent_id and prefer_agent_id in agents:
            candidates.append(agents[prefer_agent_id])
        for aid, agent in agents.items():
            if prefer_agent_id and aid == prefer_agent_id:
                continue
            candidates.append(agent)
        clients = [c for c in (getattr(a, "llm_client", None) for a in candidates) if c is not None]
        if not clients:
            return None

        def _call(prompt: str):
            from neurova.mem_core import run_async_safely

            last = ""
            for client in clients:
                try:
                    resp = run_async_safely(
                        client.chat([{"role": "user", "content": prompt}])
                    )
                except Exception as exc:  # noqa: BLE001 - 换下一个候选
                    logger.warning("graph_bridge: LLM 调用异常，尝试下一个候选: %s", exc)
                    continue
                content = getattr(resp, "content", "") or ""
                if content.startswith("[LLM Error]"):
                    last = content
                    logger.warning("graph_bridge: 候选 LLM 返回错误，尝试下一个: %s", content[:120])
                    continue
                return content
            return last

        return _call
    except Exception as e:  # noqa: BLE001
        logger.debug("graph_bridge LLM 解析失败: %s", e)
    return None


def _try_extract_to_graph(
    items: List[Dict[str, Any]], request: Request, agent_id: Optional[str] = None
) -> None:
    """导入后触发"知识条目→图谱节点"抽取（批次 3）。失败逐条吞掉，不阻断导入。"""
    from neurova.cognitive_layers.knowledge_graph.manager import (
        get_agent_knowledge_graph_manager,
        get_knowledge_graph_manager,
    )
    from neurova.knowledge.graph_bridge import extract_knowledge_to_graph
    from neurova.knowledge.repository import get_knowledge_repository

    llm_call = _default_llm_call(request, prefer_agent_id=agent_id)
    if llm_call is None:
        logger.info("[知识导入] 未解析到可用 LLM，跳过 %s 条的图谱抽取", len(items))
        return
    repo = get_knowledge_repository()
    # per-agent 隔离：写入所属 agent 的图谱（agent_id 缺失时退全局，仅测试路径）
    if agent_id:
        try:
            graph = get_agent_knowledge_graph_manager(agent_id)
        except ValueError:
            graph = get_knowledge_graph_manager()
    else:
        graph = get_knowledge_graph_manager()
    for entry in items:
        try:
            extract_knowledge_to_graph(entry, repo=repo, llm_call=llm_call, graph_manager=graph)
        except Exception as e:  # noqa: BLE001
            logger.warning("[知识导入] 图谱抽取失败（已跳过）: %s", e)


@router.post("/import")
async def import_knowledge_file(
    file: UploadFile,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
    agent_id: str = Query(default="default", description="Agent ID"),
    sync: bool = Query(default=True, description="true=同步导入（现行为）；false=入队后台处理，返回 task_id（P1-#9）"),
):
    """导入知识文件（txt/md/docx/xlsx/pptx/pdf/html/csv）。

    R-4: 复用 attachment_parser 抽取文本，抽取成功则创建知识条目
    （归属当前用户、默认私有）。批次 3：导入后触发图谱抽取。
    P1-#9：sync=false 走持久化摄取队列（落文件+入队即返 task_id，崩溃可重跑；
    异步路径不做图谱抽取，结果标 skipped_async）。
    """
    filename = file.filename or "imported"
    data = await file.read()
    if not sync:
        from neurova.knowledge.ingest_queue import get_ingress_queue

        task = get_ingress_queue().enqueue_upload(
            filename=filename, data=data, agent_id=agent_id,
            user_id=str(current_user.get("user_id") or ""),
        )
        return {"code": 0, "message": "Queued", "data": {"task_id": task["task_id"], "status": task.get("status"), "replayed": task.get("replayed", False)}}
    items, extract_status = _import_file_data(data, filename, agent_id, current_user)
    if not items:
        # 2026-09-06 修复：抽取失败显式化——此前以成功语义静默返回空列表，
        # 前端一律提示"导入成功"，用户无从知晓 .ppt 旧格式/超 2MB/纯图片页
        # 实际未入库（"提示成功但列表没有"的根因）。
        return {
            "code": 1,
            "message": f"extract_failed:{extract_status}",
            "data": {"items": [], "status": extract_status},
        }
    _try_extract_to_graph(items, request, agent_id=agent_id)
    return {"code": 0, "message": "Import completed", "data": {"items": items}}


def _import_file_data(
    data: bytes, filename: str, agent_id: str, user: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], str]:
    from neurova.attachment_parser import extract_attachment_text
    from neurova.knowledge.splitter import split_with_meta  # noqa: F401 - 分块单源引用保持

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    file_type = _guess_type(ext)
    text, status = extract_attachment_text(data, filename, file_type)
    if not text:
        logger.info("[知识导入] %s 未抽取文本 (%s)", filename, status)
        return [], status

    repo = get_repository()
    title = _title_from_filename(filename)
    # P0-2 分块：摄取即分块（段落→句→硬切降级），检索命中可溯源到块。
    # P1#6：子块进索引细命中，父块作 LLM 上下文回传
    from neurova.knowledge.splitter import build_entry_chunks

    _children, _parents = build_entry_chunks(text)
    item = repo.create_knowledge(
        agent_id=agent_id,
        title=title,
        content=text,
        category="import",
        tags=[],
        source="import:" + filename,
        confidence=0.7,
        visibility="private",
        owner_user_id=str((user or {}).get("user_id", "") or "default"),
        chunks=_children,
        parents=_parents,
        # P0-3 闭环审查修 D：批量导入不进同值冲突队列——同名文件批量导入
        # （课件/周报）会瞬间产生 N-1 条 pending 刷屏待审；导入条目已有
        # source 字段独立溯源，冲突检测留给交互式单条创建路径
        detect_conflict=False,
    )
    return [_build_item_dict(item)], status


def _guess_type(ext: str) -> str:
    if ext in ("txt", "md", "rst", "json", "yaml", "yml", "toml", "log"):
        return "text"
    if ext in ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv", "html", "htm",
               "rtf", "odt", "ods", "odp", "xml"):
        return "document"
    return "file"


def _title_from_filename(filename: str) -> str:
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    return base.strip() or "Imported Knowledge"


def _title_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip("/") or "root"
    name = path.rsplit("/", 1)[-1]
    return name[:64] or parsed.netloc or "Web Page"


# ── 远程网页导入（SSRF 防护） ─────────────────────────────────

def _validate_import_url(url: str) -> bool:
    """校验导入 URL 安全（R-4 SSRF 防护）：
    - 仅 http/https
    - 拒绝 localhost/环回/私有/保留地址（解析后 IP 判断）
    Allowlist 语义：不合规 → False。
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname or ""
    if not host:
        return False

    # 主机名快速拒绝：localhost / 内部域名后缀
    lowered = host.lower()
    if lowered in ("localhost",) or lowered.endswith(".localhost"):
        return False

    import ipaddress

    # 直接 IP 字面量
    try:
        ip = ipaddress.ip_address(lowered)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
    except ValueError:
        pass

    # 域名：解析后逐个 IP 检查（DNS rebinding 场景下至少列出全部分析结果）
    import socket

    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except Exception:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


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
    if not _validate_import_url(url):
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
    items, extract_status = _import_file_data(data, _title_from_url(url), agent_id, current_user)
    if not items:
        return {
            "code": 1,
            "message": f"extract_failed:{extract_status}",
            "data": {"items": [], "status": extract_status},
        }
    _try_extract_to_graph(items, request, agent_id=agent_id)
    return {"code": 0, "message": "URL import completed", "data": {"items": items}}
