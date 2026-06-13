"""
心流知识库 (iflow) 适配器

基于 iflow API 封装，参考 happy-notes SDK 的核心逻辑
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx

from neurova.knowledge.config import get_knowledge_config

logger = logging.getLogger(__name__)


class ContentType(str, Enum):
    """内容类型"""

    TEXT = "text"
    MARKDOWN = "markdown"
    HTML = "html"
    PDF = "pdf"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    CODE = "code"
    JSON = "json"
    CSV = "csv"
    URL = "url"


@dataclass
class KnowledgeItem:
    """知识项"""

    item_id: str = field(default_factory=lambda: f"item_{int(time.time() * 1000)}")
    title: str = ""
    content: str = ""
    content_type: ContentType = ContentType.TEXT
    source: str = ""
    author: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "item_id": self.item_id,
            "title": self.title,
            "content": self.content,
            "content_type": self.content_type.value,
            "source": self.source,
            "author": self.author,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeItem":
        """从字典创建"""
        return cls(
            item_id=data.get("item_id", f"item_{int(time.time() * 1000)}"),
            title=data.get("title", ""),
            content=data.get("content", ""),
            content_type=ContentType(data.get("content_type", "text")),
            source=data.get("source", ""),
            author=data.get("author", ""),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


@dataclass
class Collection:
    """知识库集合"""

    collection_id: str = ""
    name: str = ""
    description: str = ""
    owner_id: str = ""
    document_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "collection_id": self.collection_id,
            "name": self.name,
            "description": self.description,
            "owner_id": self.owner_id,
            "document_count": self.document_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Collection":
        """从字典创建"""
        return cls(
            collection_id=data.get("collection_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            owner_id=data.get("owner_id", ""),
            document_count=data.get("document_count", 0),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Document:
    """文档"""

    document_id: str = ""
    collection_id: str = ""
    title: str = ""
    content: str = ""
    content_type: ContentType = ContentType.TEXT
    url: Optional[str] = None
    file_path: Optional[str] = None
    file_size: int = 0
    author: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "document_id": self.document_id,
            "collection_id": self.collection_id,
            "title": self.title,
            "content": self.content,
            "content_type": self.content_type.value,
            "url": self.url,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "author": self.author,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Document":
        """从字典创建"""
        return cls(
            document_id=data.get("document_id", ""),
            collection_id=data.get("collection_id", ""),
            title=data.get("title", ""),
            content=data.get("content", ""),
            content_type=ContentType(data.get("content_type", "text")),
            url=data.get("url"),
            file_path=data.get("file_path"),
            file_size=data.get("file_size", 0),
            author=data.get("author", ""),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


@dataclass
class SearchResult:
    """搜索结果"""

    result_id: str = ""
    document_id: str = ""
    collection_id: str = ""
    title: str = ""
    content: str = ""
    score: float = 0.0
    highlights: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "result_id": self.result_id,
            "document_id": self.document_id,
            "collection_id": self.collection_id,
            "title": self.title,
            "content": self.content,
            "score": self.score,
            "highlights": self.highlights,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SearchResult":
        """从字典创建"""
        return cls(
            result_id=data.get("result_id", ""),
            document_id=data.get("document_id", ""),
            collection_id=data.get("collection_id", ""),
            title=data.get("title", ""),
            content=data.get("content", ""),
            score=data.get("score", 0.0),
            highlights=data.get("highlights", []),
            metadata=data.get("metadata", {}),
        )


class FlowKBClient:
    """
    心流知识库客户端

    封装 iflow API 调用
    """

    def __init__(self, api_key: str, api_base: str = "https://api.iflow.com"):
        """
        初始化客户端

        Args:
            api_key: API 密钥
            api_base: API 基础 URL
        """
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")

        # HTTP 客户端
        self._client: Optional[httpx.AsyncClient] = None

        # 默认集合ID
        self._default_collection_id: Optional[str] = None

        logger.info("FlowKBClient initialized: %s", api_base)

    @property
    def headers(self) -> Dict[str, str]:
        """请求头"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Neurova/1.0",
        }

    def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.api_base, headers=self.headers, timeout=30.0)
        return self._client

    async def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """
        发送 HTTP 请求

        Args:
            method: HTTP 方法
            path: 请求路径
            **kwargs: 其他参数

        Returns:
            响应数据
        """
        client = self._get_client()

        try:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error: %s - %s", e.response.status_code, e.response.text)
            raise
        except Exception as e:
            logger.error("Request failed: %s", e)
            raise

    async def close(self) -> None:
        """关闭客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def create_collection(
        self, name: str, description: str = "", metadata: Optional[Dict[str, Any]] = None
    ) -> Collection:
        """
        创建知识库集合

        Args:
            name: 集合名称
            description: 集合描述
            metadata: 元数据

        Returns:
            创建的集合
        """
        data = {"name": name, "description": description, "metadata": metadata or {}}

        result = await self._request("POST", "/collections", json=data)
        return Collection.from_dict(result)

    async def list_collections(self, limit: int = 100, offset: int = 0) -> List[Collection]:
        """
        列出知识库集合

        Args:
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            集合列表
        """
        params = {"limit": limit, "offset": offset}
        result = await self._request("GET", "/collections", params=params)

        collections = []
        for item in result.get("collections", []):
            collections.append(Collection.from_dict(item))

        return collections

    async def get_collection(self, collection_id: str) -> Optional[Collection]:
        """
        获取知识库集合

        Args:
            collection_id: 集合ID

        Returns:
            集合对象
        """
        try:
            result = await self._request("GET", f"/collections/{collection_id}")
            return Collection.from_dict(result)
        except Exception as e:
            logger.error("Failed to get collection %s: %s", collection_id, e)
            return None

    async def update_collection(self, collection_id: str, updates: Dict[str, Any]) -> Optional[Collection]:
        """
        更新知识库集合

        Args:
            collection_id: 集合ID
            updates: 更新内容

        Returns:
            更新后的集合
        """
        try:
            result = await self._request("PUT", f"/collections/{collection_id}", json=updates)
            return Collection.from_dict(result)
        except Exception as e:
            logger.error("Failed to update collection %s: %s", collection_id, e)
            return None

    async def delete_collection(self, collection_id: str) -> bool:
        """
        删除知识库集合

        Args:
            collection_id: 集合ID

        Returns:
            是否删除成功
        """
        try:
            await self._request("DELETE", f"/collections/{collection_id}")
            return True
        except Exception as e:
            logger.error("Failed to delete collection %s: %s", collection_id, e)
            return False

    async def upload_document(self, collection_id: str, document: Document) -> Optional[Document]:
        """
        上传文档

        Args:
            collection_id: 集合ID
            document: 文档对象

        Returns:
            上传后的文档
        """
        data = document.to_dict()
        data["collection_id"] = collection_id

        try:
            result = await self._request("POST", f"/collections/{collection_id}/documents", json=data)
            return Document.from_dict(result)
        except Exception as e:
            logger.error("Failed to upload document: %s", e)
            return None

    async def import_url(self, collection_id: str, url: str, title: Optional[str] = None) -> Optional[Document]:
        """
        从URL导入文档

        Args:
            collection_id: 集合ID
            url: 文档URL
            title: 文档标题

        Returns:
            导入的文档
        """
        data = {"url": url, "title": title or url}

        try:
            result = await self._request("POST", f"/collections/{collection_id}/import", json=data)
            return Document.from_dict(result)
        except Exception as e:
            logger.error("Failed to import URL: %s", e)
            return None

    async def list_documents(self, collection_id: str, limit: int = 100, offset: int = 0) -> List[Document]:
        """
        列出文档

        Args:
            collection_id: 集合ID
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            文档列表
        """
        params = {"limit": limit, "offset": offset}
        result = await self._request("GET", f"/collections/{collection_id}/documents", params=params)

        documents = []
        for item in result.get("documents", []):
            documents.append(Document.from_dict(item))

        return documents

    async def delete_document(self, collection_id: str, document_id: str) -> bool:
        """
        删除文档

        Args:
            collection_id: 集合ID
            document_id: 文档ID

        Returns:
            是否删除成功
        """
        try:
            await self._request("DELETE", f"/collections/{collection_id}/documents/{document_id}")
            return True
        except Exception as e:
            logger.error("Failed to delete document: %s", e)
            return False

    async def search(
        self, collection_id: str, query: str, limit: int = 10, filters: Optional[Dict[str, Any]] = None
    ) -> List[SearchResult]:
        """
        搜索文档

        Args:
            collection_id: 集合ID
            query: 搜索查询
            limit: 返回数量限制
            filters: 过滤器

        Returns:
            搜索结果列表
        """
        data = {"query": query, "limit": limit, "filters": filters or {}}

        try:
            result = await self._request("POST", f"/collections/{collection_id}/search", json=data)

            results = []
            for item in result.get("results", []):
                results.append(SearchResult.from_dict(item))

            return results
        except Exception as e:
            logger.error("Search failed: %s", e)
            return []

    async def start_web_search(self, query: str, max_results: int = 10) -> Optional[str]:
        """
        启动网络搜索

        Args:
            query: 搜索查询
            max_results: 最大结果数

        Returns:
            搜索任务ID
        """
        data = {"query": query, "max_results": max_results}

        try:
            result = await self._request("POST", "/web-search", json=data)
            return result.get("task_id")
        except Exception as e:
            logger.error("Failed to start web search: %s", e)
            return None

    async def get_web_search_result(self, task_id: str) -> Optional[List[SearchResult]]:
        """
        获取网络搜索结果

        Args:
            task_id: 搜索任务ID

        Returns:
            搜索结果列表
        """
        try:
            result = await self._request("GET", f"/web-search/{task_id}")

            if result.get("status") != "completed":
                return None

            results = []
            for item in result.get("results", []):
                results.append(SearchResult.from_dict(item))

            return results
        except Exception as e:
            logger.error("Failed to get web search result: %s", e)
            return None


class FlowKBAdapter:
    """
    心流知识库适配器

    封装 FlowKBClient，提供更高级的接口
    """

    def __init__(self, api_key: str, api_base: str = "https://api.iflow.com"):
        """
        初始化适配器

        Args:
            api_key: API 密钥
            api_base: API 基础 URL
        """
        self.client = FlowKBClient(api_key=api_key, api_base=api_base)
        self._default_collection_id: Optional[str] = None
        self._initialized = False

        logger.info("FlowKBAdapter initialized")

    async def initialize(self) -> bool:
        """
        初始化适配器

        Returns:
            是否初始化成功
        """
        try:
            # 获取或创建默认集合
            collections = await self.client.list_collections(limit=1)
            if collections:
                self._default_collection_id = collections[0].collection_id
            else:
                # 创建默认集合
                collection = await self.client.create_collection(name="默认知识库", description="Neurova 默认知识库")
                if collection:
                    self._default_collection_id = collection.collection_id

            self._initialized = True
            logger.info("FlowKBAdapter initialized successfully")
            return True

        except Exception as e:
            logger.error("Failed to initialize FlowKBAdapter: %s", e)
            return False

    async def close(self) -> None:
        """关闭适配器"""
        await self.client.close()
        self._initialized = False

    async def create_knowledge_base(
        self, name: str, description: str = "", metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Collection]:
        """
        创建知识库

        Args:
            name: 知识库名称
            description: 知识库描述
            metadata: 元数据

        Returns:
            创建的知识库
        """
        return await self.client.create_collection(name, description, metadata)

    async def list_knowledge_bases(self, limit: int = 100, offset: int = 0) -> List[Collection]:
        """
        列出知识库

        Args:
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            知识库列表
        """
        return await self.client.list_collections(limit, offset)

    async def get_knowledge_base(self, collection_id: str) -> Optional[Collection]:
        """
        获取知识库

        Args:
            collection_id: 集合ID

        Returns:
            知识库对象
        """
        return await self.client.get_collection(collection_id)

    async def delete_knowledge_base(self, collection_id: str) -> bool:
        """
        删除知识库

        Args:
            collection_id: 集合ID

        Returns:
            是否删除成功
        """
        return await self.client.delete_collection(collection_id)

    async def add_document(
        self,
        collection_id: Optional[str] = None,
        title: str = "",
        content: str = "",
        content_type: ContentType = ContentType.TEXT,
        source: str = "",
        author: str = "",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Document]:
        """
        添加文档

        Args:
            collection_id: 集合ID
            title: 文档标题
            content: 文档内容
            content_type: 内容类型
            source: 来源
            author: 作者
            tags: 标签
            metadata: 元数据

        Returns:
            添加的文档
        """
        if collection_id is None:
            collection_id = self._default_collection_id

        if not collection_id:
            logger.error("No collection ID specified")
            return None

        document = Document(
            title=title,
            content=content,
            content_type=content_type,
            source=source,
            author=author,
            tags=tags or [],
            metadata=metadata or {},
        )

        return await self.client.upload_document(collection_id, document)

    async def list_documents(
        self, collection_id: Optional[str] = None, limit: int = 100, offset: int = 0
    ) -> List[Document]:
        """
        列出文档

        Args:
            collection_id: 集合ID
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            文档列表
        """
        if collection_id is None:
            collection_id = self._default_collection_id

        if not collection_id:
            return []

        return await self.client.list_documents(collection_id, limit, offset)

    async def delete_document(self, collection_id: Optional[str] = None, document_id: str = "") -> bool:
        """
        删除文档

        Args:
            collection_id: 集合ID
            document_id: 文档ID

        Returns:
            是否删除成功
        """
        if collection_id is None:
            collection_id = self._default_collection_id

        if not collection_id:
            return False

        return await self.client.delete_document(collection_id, document_id)

    async def search(
        self,
        collection_id: Optional[str] = None,
        query: str = "",
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """
        搜索文档

        Args:
            collection_id: 集合ID
            query: 搜索查询
            limit: 返回数量限制
            filters: 过滤器

        Returns:
            搜索结果列表
        """
        if collection_id is None:
            collection_id = self._default_collection_id

        if not collection_id:
            return []

        return await self.client.search(collection_id, query, limit, filters)

    async def search_multi_collection(
        self, collection_ids: List[str], query: str, limit: int = 10
    ) -> List[SearchResult]:
        """
        多集合搜索

        Args:
            collection_ids: 集合ID列表
            query: 搜索查询
            limit: 返回数量限制

        Returns:
            搜索结果列表
        """
        all_results = []

        for collection_id in collection_ids:
            try:
                results = await self.client.search(collection_id, query, limit)
                all_results.extend(results)
            except Exception as e:
                logger.error("Search failed for collection %s: %s", collection_id, e)

        # 按分数排序
        all_results.sort(key=lambda x: x.score, reverse=True)

        return all_results[:limit]

    async def web_search(self, query: str, max_results: int = 10) -> List[SearchResult]:
        """
        网络搜索

        Args:
            query: 搜索查询
            max_results: 最大结果数

        Returns:
            搜索结果列表
        """
        # 启动搜索
        task_id = await self.client.start_web_search(query, max_results)
        if not task_id:
            return []

        # 等待结果
        for _ in range(30):  # 最多等待30秒
            results = await self.client.get_web_search_result(task_id)
            if results:
                return results
            await asyncio.sleep(1)

        logger.warning("Web search timeout")
        return []

    def set_default_collection(self, collection_id: str) -> None:
        """设置默认集合"""
        self._default_collection_id = collection_id

    @property
    def default_collection_id(self) -> Optional[str]:
        """获取默认集合ID"""
        return self._default_collection_id


# 全局实例
_flow_kb_adapter: Optional[FlowKBAdapter] = None


async def get_flow_kb_adapter() -> Optional[FlowKBAdapter]:
    """
    获取心流知识库适配器单例

    Returns:
        FlowKBAdapter 实例
    """
    global _flow_kb_adapter

    if _flow_kb_adapter is None:
        config = get_knowledge_config()

        # 从配置中获取API密钥
        api_key = config.metadata.get("flow_kb_api_key", "")
        api_base = config.metadata.get("flow_kb_api_base", "https://api.iflow.com")

        if not api_key:
            logger.warning("FlowKB API key not configured")
            return None

        _flow_kb_adapter = FlowKBAdapter(api_key=api_key, api_base=api_base)

        # 初始化
        success = await _flow_kb_adapter.initialize()
        if not success:
            logger.error("Failed to initialize FlowKBAdapter")
            _flow_kb_adapter = None
            return None

    return _flow_kb_adapter


async def close_flow_kb_adapter() -> None:
    """关闭心流知识库适配器"""
    global _flow_kb_adapter

    if _flow_kb_adapter:
        await _flow_kb_adapter.close()
        _flow_kb_adapter = None
