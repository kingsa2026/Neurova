from __future__ import annotations

"""
知识管理接口 - Knowledge Endpoint

功能:
1. 获取知识库 (GET /api/v1/knowledge)
2. 搜索知识 (POST /api/v1/knowledge/search)
3. 添加知识 (POST /api/v1/knowledge)
4. 更新知识 (PUT /api/v1/knowledge/{id})
5. 删除知识 (DELETE /api/v1/knowledge/{id})
6. 导入文件 (POST /api/v1/knowledge/import) R-4: word/excel/ppt/pdf/html/txt/md
7. 导入远程网页 (POST /api/v1/knowledge/import-url) R-4（含 SSRF 防护）

R-4 修复: CRUD 接入 KnowledgeRepository（JSON 持久化），删除 memory_manager
探测与模拟数据兜底；无数据返回空列表。
"""

from neurova.core.logger import get_logger
import time
import urllib.parse
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request, UploadFile
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter()


class KnowledgeItem(BaseModel):
    """知识条目"""

    knowledge_id: str
    title: str
    content: str
    category: str = "general"
    tags: List[str] = []
    source: str = ""
    confidence: float = 0.5
    created_at: float = 0
    updated_at: float = 0


class KnowledgeCreate(BaseModel):
    """创建知识请求"""

    title: str = Field(..., description="标题")
    content: str = Field(..., description="内容")
    category: str = Field(default="general", description="分类")
    tags: List[str] = Field(default_factory=list, description="标签")
    source: str = Field(default="", description="来源")
    confidence: float = Field(default=0.5, ge=0, le=1, description="置信度")


class KnowledgeUpdate(BaseModel):
    """更新知识请求"""

    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    confidence: Optional[float] = None


class KnowledgeSearchRequest(BaseModel):
    """搜索知识请求"""

    query: str = Field(..., description="搜索查询")
    category: Optional[str] = None
    tags: List[str] = []
    limit: int = Field(default=10, ge=1, le=100)


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def _get_memory_manager(agent_id: str = "default"):
    """获取记忆管理器"""
    agent = _get_agent(agent_id)
    if not agent:
        return None
    return getattr(agent, "memory_manager", None)


def _get_repository(agent_id: str = "default"):
    """获取知识条目仓库（R-4: JSON 持久化）。测试可 monkeypatch 为独立实例。"""
    from neurova.knowledge.repository import get_knowledge_repository

    return get_knowledge_repository()


@router.get("", response_model=List[KnowledgeItem])
async def get_knowledge(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    category: Optional[str] = Query(default=None, description="分类筛选"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取知识库（r-repo 持久化；无数据返回空列表，不返回模拟数据）"""
    repo = _get_repository(agent_id)
    items = repo.list_knowledge(agent_id, category=category, limit=limit, offset=offset)

    return [
        KnowledgeItem(
            knowledge_id=item["knowledge_id"],
            title=item["title"],
            content=item["content"],
            category=item.get("category", "general"),
            tags=item.get("tags") or [],
            source=item.get("source", ""),
            confidence=item.get("confidence", 0.5),
            created_at=item.get("created_at", 0),
            updated_at=item.get("updated_at", 0),
        )
        for item in items
    ]


@router.post("/search", response_model=List[KnowledgeItem])
async def search_knowledge(
    request: Request,
    body: KnowledgeSearchRequest,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """搜索知识（标题+内容包含匹配）"""
    repo = _get_repository(agent_id)
    results = repo.search_knowledge(
        agent_id=agent_id,
        query=body.query,
        category=body.category,
        tags=body.tags,
        limit=body.limit,
    )
    return [
        KnowledgeItem(
            knowledge_id=item["knowledge_id"],
            title=item["title"],
            content=item["content"],
            category=item.get("category", "general"),
            tags=item.get("tags") or [],
            source=item.get("source", ""),
            confidence=item.get("confidence", 0.5),
            created_at=item.get("created_at", 0),
            updated_at=item.get("updated_at", 0),
        )
        for item in results
    ]


@router.post("", response_model=KnowledgeItem)
async def create_knowledge(
    request: Request,
    body: KnowledgeCreate,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """添加知识"""
    _get_request_id(request)

    repo = _get_repository(agent_id)
    item = repo.create_knowledge(
        agent_id=agent_id,
        title=body.title,
        content=body.content,
        category=body.category,
        tags=body.tags,
        source=body.source,
        confidence=body.confidence,
    )

    return KnowledgeItem(
        knowledge_id=item["knowledge_id"],
        title=item["title"],
        content=item["content"],
        category=item["category"],
        tags=item["tags"],
        source=item["source"],
        confidence=item["confidence"],
        created_at=item["created_at"],
        updated_at=item["updated_at"],
    )


@router.get("/{knowledge_id}", response_model=KnowledgeItem)
async def get_knowledge_item(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取单个知识详情"""
    repo = _get_repository(agent_id)
    item = repo.get_item(agent_id, knowledge_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Knowledge '{knowledge_id}' not found")

    return KnowledgeItem(
        knowledge_id=item["knowledge_id"],
        title=item["title"],
        content=item["content"],
        category=item.get("category", "general"),
        tags=item.get("tags") or [],
        source=item.get("source", ""),
        confidence=item.get("confidence", 0.5),
        created_at=item.get("created_at", 0),
        updated_at=item.get("updated_at", 0),
    )


@router.put("/{knowledge_id}", response_model=KnowledgeItem)
async def update_knowledge(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    body: KnowledgeUpdate = KnowledgeUpdate(),
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """更新知识"""
    _get_request_id(request)

    repo = _get_repository(agent_id)
    if not repo.update_knowledge(agent_id, knowledge_id, body.dict(exclude_unset=True)):
        raise HTTPException(status_code=404, detail=f"Knowledge '{knowledge_id}' not found")

    # 返回更新后的知识
    return await get_knowledge_item(request, knowledge_id, agent_id)


@router.delete("/{knowledge_id}")
async def delete_knowledge(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """删除知识"""
    request_id = _get_request_id(request)

    repo = _get_repository(agent_id)
    if not repo.delete_knowledge(agent_id, knowledge_id):
        raise HTTPException(status_code=404, detail=f"Knowledge '{knowledge_id}' not found")

    return {
        "code": 0,
        "message": f"Knowledge '{knowledge_id}' deleted",
        "data": {"knowledge_id": knowledge_id},
        "request_id": request_id,
    }


# ══════════════════════════════════════════════════════════════
# R-4: 多格式导入（文件 + 远程网页）
# ══════════════════════════════════════════════════════════════

def _build_item_dict(item: Dict[str, Any]) -> Dict[str, Any]:
    return dict(item)


@router.post("/import")
async def import_knowledge_file(
    file: UploadFile,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """导入知识文件（txt/md/docx/xlsx/pptx/pdf/html/csv）。

    R-4: 复用 attachment_parser 抽取文本，抽取成功则创建知识条目。
    """
    filename = file.filename or "imported"
    data = await file.read()
    items = _import_file_data(data, filename, agent_id)
    return {"code": 0, "message": "Import completed", "data": {"items": items}}


def _import_file_data(data: bytes, filename: str, agent_id: str) -> List[Dict[str, Any]]:
    from neurova.attachment_parser import extract_attachment_text

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    file_type = _guess_type(ext)
    text, status = extract_attachment_text(data, filename, file_type)
    if not text:
        logger.info("[知识导入] %s 未抽取文本 (%s)", filename, status)
        return []

    repo = _get_repository(agent_id)
    title = _title_from_filename(filename)
    item = repo.create_knowledge(
        agent_id=agent_id,
        title=title,
        content=text,
        category="import",
        tags=[],
        source=f"import:{filename}",
        confidence=0.7,
    )
    return [_build_item_dict(item)]


def _guess_type(ext: str) -> str:
    if ext in ("txt", "md", "rst"):
        return "text"
    if ext in ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv", "html", "htm"):
        return "document"
    return "file"


def _title_from_filename(filename: str) -> str:
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    return base.strip() or "Imported Knowledge"


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
    agent_id: str = Query(default="default", description="Agent ID"),
    url: str = Query(..., description="远程网页 URL"),
):
    """导入远程网页（抽取正文存为知识条目）"""
    if not _validate_import_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL: only public http(s) allowed")

    try:
        data = _fetch_url(url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Fetch failed: {e}")

    items = _import_file_data(data, _title_from_url(url), agent_id)
    return {"code": 0, "message": "URL import completed", "data": {"items": items}}


def _title_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip("/") or "root"
    name = path.rsplit("/", 1)[-1]
    return name[:64] or parsed.netloc or "Web Page"
