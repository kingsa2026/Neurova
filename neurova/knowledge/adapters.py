"""
KBAdapter — 远程/本地知识库统一适配器（R-5/R-6）

统一接口契约:
    await adapter.search(query: str, limit: int) ->
        {"status": "success"|"failed", "results": [...], "error"?: str}

内置适配器:
    - LocalMemoryAdapter  ctx["memory_manager"].search（本地记忆库）
    - IflowKBAdapter      心流知识库（startSearch → pollSearch，平台 RESTful）
    - FeishuKBAdapter     飞书知识库（Wiki 空间 + 云文档搜索，tenant_access_token）
    - ImaKBAdapter        腾讯 ima 知识库（MCP-over-HTTP，JSON-RPC 2.0）
    - GenericRESTAdapter  通用 POST（api_url + Bearer + {query, dataset_id, top_k}）
                          自定义端点向后兼容走此适配器

安全:
    远程适配器 URL 一律经校验：仅 http/https、拒绝环回/私网/保留地址、
    DNS 解析后逐 IP 判定。ima MCP 为本机客户端服务，仅当显式 allow_local=True
    且主机为字面环回/私网地址时才放行（公网域名不经 allow_local 放行）。
"""

from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

IFLOW_DEFAULT_BASE_URL = "https://platform.iflow.cn"


def _validate_remote_url(url: str) -> bool:
    """远程知识库 URL 的 SSRF 校验。

    返回 False 表示拒绝（协议/主机不合规或解析失败）。
    """
    try:
        from urllib.parse import urlparse

        parsed = urlparse(str(url or ""))
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname or ""
        if not host:
            return False
        lowered = host.lower()
        if lowered == "localhost" or lowered.endswith(".localhost"):
            return False

        import ipaddress
        import socket

        candidates = []
        try:
            candidates.append(ipaddress.ip_address(lowered))
        except ValueError:
            pass
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            for info in socket.getaddrinfo(host, port):
                candidates.append(ipaddress.ip_address(info[4][0]))
        except Exception:
            if not candidates:
                return False  # 既不是合法 IP 又解析失败 → 拒绝
        for ip in candidates:
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            ):
                return False
        return True
    except Exception:
        return False


class KBAdapter:
    """知识库适配器基类。"""

    async def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        raise NotImplementedError


class LocalMemoryAdapter(KBAdapter):
    """本地记忆库（ctx 中的 memory_manager.search）。"""

    def __init__(self, memory_manager: Any) -> None:
        self._memory_manager = memory_manager

    async def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        if self._memory_manager is None:
            return {
                "status": "failed",
                "error": "本地知识库不可用：缺少 memory_manager",
                "results": [],
            }
        try:
            items = self._memory_manager.search(query=query, limit=limit)
            results = [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in (items or [])
            ]
            return {"status": "success", "results": results}
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "error": str(e), "results": []}


class GenericRESTAdapter(KBAdapter):
    """通用远程知识库 REST 适配器（自定义端点向后兼容）。

    约定: POST {api_url}
    headers: Authorization: Bearer <api_key>
    body: {"query", "dataset_id", "top_k"}
    响应: {"results": [...]}
    """

    def __init__(
        self,
        config: Dict[str, Any],
        http_post: Optional[Callable] = None,
        validate_url: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self._config = config or {}
        self._http_post = http_post or self._default_post
        self._validate_url = validate_url or _validate_remote_url

    @staticmethod
    def _default_post(url: str, payload: Dict, headers: Dict, timeout: float) -> Dict:
        import json as _json
        import urllib.request

        data = _json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            import json

            return json.loads(resp.read().decode("utf-8"))

    async def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        api_url = str(self._config.get("api_url", "") or "")
        if not api_url:
            return {"status": "failed", "error": "缺少 api_url", "results": []}
        if not self._validate_url(api_url):
            return {
                "status": "failed",
                "error": f"SSRF 校验未通过: {api_url}",
                "results": [],
            }

        headers: Dict[str, str] = {}
        api_key = str(self._config.get("api_key", "") or "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "query": query,
            "dataset_id": self._config.get("dataset_id"),
            "top_k": limit,
        }
        try:
            timeout = float(self._config.get("timeout", 30))
            data = self._http_post(api_url, payload, headers, timeout)
            results = data.get("results", []) if isinstance(data, dict) else []
            return {"status": "success", "results": results or []}
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "error": str(e), "results": []}


class IflowKBAdapter(KBAdapter):
    """心流（iflow）知识库适配器。

    协议对齐 flow-kb-sdk/happy-notes/scripts/iflow_common.py:
    - Bearer 认证（Authorization: Bearer <IFLOW_API_KEY>）
    - 检索: POST /api/v1/knowledge/startSearch → 轮询 GET searchList 直到 DONE
    - 默认 base_url: https://platform.iflow.cn
    """

    def __init__(
        self,
        config: Dict[str, Any],
        post_form: Optional[Callable] = None,
        get: Optional[Callable] = None,
        validate_url: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self._config = config or {}
        self.api_key = str(config.get("api_key", "") or "")
        self.base_url = str(config.get("base_url", "") or IFLOW_DEFAULT_BASE_URL).rstrip("/")
        self.dataset_id = config.get("dataset_id")
        self.poll_interval = float(config.get("poll_interval", 3))
        self.poll_max_wait = float(config.get("poll_max", 60))
        self._post_form = post_form or self._default_post_form
        self._get = get or self._default_get
        self._validate_url = validate_url or _validate_remote_url

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _default_post_form(self, path: str, data: Dict, timeout: float = 60.0) -> Dict:
        import json
        import urllib.request

        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers = {**self._headers(), "Content-Type": "application/json"}
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _default_get(self, path: str, timeout: float = 60.0) -> Dict:
        import json
        import urllib.request

        req = urllib.request.Request(
            f"{self.base_url}{path}", headers=self._headers(), method="GET"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    async def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        if not self.api_key:
            return {"status": "failed", "error": "缺少 api_key", "results": []}
        if not self._validate_url(self.base_url):
            return {
                "status": "failed",
                "error": f"SSRF 校验未通过: {self.base_url}",
                "results": [],
            }
        try:
            return await self._search_impl(query, limit)
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "error": str(e), "results": []}

    async def _search_impl(self, query: str, limit: int) -> Dict[str, Any]:
        import asyncio
        import time
        import urllib.parse

        search_type = str(self._config.get("search_type", "FAST_SEARCH"))
        source = str(self._config.get("source", "KB"))
        body: Dict[str, Any] = {
            "query": query,
            "searchType": search_type,
            "source": source,
        }
        if self.dataset_id:
            body["collectionId"] = self.dataset_id

        resp = self._post_form(
            "/api/v1/knowledge/startSearch", body, float(self._config.get("timeout", 60))
        )
        if not resp.get("success", False):
            return {
                "status": "failed",
                "error": str(resp.get("message") or "startSearch failed"),
                "results": [],
            }
        search_id = (resp.get("data") or {}).get("searchId")
        if not search_id:
            direct = (resp.get("data") or {}).get("results")
            if direct:
                return {"status": "success", "results": direct}
            return {"status": "failed", "error": "startSearch 未返回 searchId", "results": []}

        encoded = urllib.parse.quote(search_id)
        deadline = time.monotonic() + self.poll_max_wait
        while time.monotonic() < deadline:
            await asyncio.sleep(max(self.poll_interval, 0))
            status_resp = self._get(
                f"/api/v1/knowledge/searchList?searchId={encoded}&pageSize={max(limit, 20)}",
                float(self._config.get("timeout", 60)),
            )
            data = status_resp.get("data") or {}
            entries = data.get("list") or data.get("records") or []
            if entries:
                done = all(
                    str(e.get("status", "")).upper() in ("DONE", "FINISHED", "SUCCESS")
                    for e in entries
                )
                if done:
                    results: List[Dict] = []
                    for e in entries:
                        for r in e.get("results") or []:
                            results.append(r)
                    return {"status": "success", "results": results[:limit]}
        return {"status": "failed", "error": "检索轮询超时", "results": []}


class FeishuKBAdapter(KBAdapter):
    """飞书知识库适配器（对飞书开放平台官方 API）。

    认证: POST /open-apis/auth/v3/tenant_access_token/internal（app_id/app_secret），
    token 按 expire 秒缓存复用。

    检索: GET /open-apis/wiki/v2/spaces 列出知识空间（未指定 space_id 时），
    随后 POST /open-apis/suite/docs-api/search/doc 按 query 搜文档。

    配置:
      app_id / app_secret（必填）
      base_url（默认 https://open.feishu.cn）
      space_id（可选：限定单一知识空间，省略则检索全部空间）
    """

    DEFAULT_BASE_URL = "https://open.feishu.cn"

    def __init__(
        self,
        config: Dict[str, Any],
        raw_call: Optional[Callable] = None,
        validate_url: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self._config = config or {}
        self.app_id = str(config.get("app_id", "") or "")
        self.app_secret = str(config.get("app_secret", "") or "")
        self.base_url = str(config.get("base_url", "") or self.DEFAULT_BASE_URL).rstrip("/")
        self.space_id = config.get("space_id")
        self._raw_call = raw_call or self._default_raw_call
        self._validate_url = validate_url or _validate_remote_url
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def _default_raw_call(
        self, method: str, path: str, token: Optional[str] = None,
        json_body: Optional[Dict] = None, timeout: float = 30.0,
    ) -> tuple:
        import json as _json
        import urllib.request

        headers: Dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None
        if json_body is not None:
            data = _json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _json.loads(resp.read().decode("utf-8"))

    async def _ensure_token(self) -> Optional[str]:
        import time

        if self._token and time.time() < self._token_expires_at:
            return self._token
        if not self.app_id or not self.app_secret:
            return None
        status, body = self._raw_call(
            "POST",
            "/open-apis/auth/v3/tenant_access_token/internal",
            json_body={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=float(self._config.get("timeout", 30)),
        )
        token = (body or {}).get("tenant_access_token")
        if status != 200 or not token:
            return None
        self._token = token
        self._token_expires_at = time.time() + float((body or {}).get("expire", 7200))
        return token

    async def _list_spaces(self, token: str) -> List[Dict[str, Any]]:
        resp = self._raw_call(
            "GET",
            "/open-apis/wiki/v2/spaces?page_size=50",
            token=token,
            timeout=float(self._config.get("timeout", 30)),
        )
        items = ((resp[1] or {}) if resp else {}).get("items", [])
        return items or []

    async def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        if not self.app_id or not self.app_secret:
            return {
                "status": "failed",
                "error": "缺少 app_id/app_secret（飞书开放平台自建应用凭据）",
                "results": [],
            }
        if not self._validate_url(self.base_url):
            return {
                "status": "failed",
                "error": f"SSRF 校验未通过: {self.base_url}",
                "results": [],
            }
        try:
            return await self._search_impl(query, limit)
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "error": str(e), "results": []}

    async def _search_impl(self, query: str, limit: int) -> Dict[str, Any]:
        token = await self._ensure_token()
        if not token:
            return {"status": "failed", "error": "获取飞书 tenant_access_token 失败", "results": []}

        space_ids: List[str] = []
        if self.space_id:
            space_ids = [str(self.space_id)]
        else:
            spaces = await self._list_spaces(token)
            space_ids = [str(s.get("space_id")) for s in spaces if s.get("space_id")]

        results: List[Dict] = []
        for sid in space_ids:
            payload: Dict[str, Any] = {
                "query": query,
                "doc_types": ["doc", "docx", "sheet", "wiki"],
                "folder_tokens": [],
            }
            if sid:
                payload["space_id"] = sid
            status, body = self._raw_call(
                "POST",
                "/open-apis/suite/docs-api/search/doc",
                token=token,
                json_body=payload,
                timeout=float(self._config.get("timeout", 30)),
            )
            docs = ((body or {}) if body else {}).get("docs", []) or []
            for doc in docs:
                results.append(
                    {
                        "obj_token": doc.get("obj_token"),
                        "title": doc.get("title"),
                        "doc_type": doc.get("doc_type"),
                        "space_id": doc.get("space_id", sid),
                        "content": f"[飞书文档] {doc.get('title', '')}",
                        "source": "feishu",
                    }
                )
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

        return {"status": "success", "results": results}


class ImaKBAdapter(KBAdapter):
    """腾讯 ima 知识库适配器（MCP-over-HTTP，JSON-RPC 2.0）。

    背景: ima（AI 知识管家）未公开第三方 OpenAPI；桌面端内置 MCP 服务
    （设置 → 开发者 → MCP 服务，默认 http://localhost:9007/sse，附 Bearer Token）。
    流程: initialize → tools/list（确认 ima_search/search）→ tools/call(query)。

    配置:
      base_url（必填，ima MCP 地址）
      token（必填，ima 服务面板提供的凭证）
      allow_local（默认 False——本机 ima 服务属合法内网访问，需显式开启；
                  开启后仅放行字面环回/私网 IP 与 localhost，公网域名不放行）
    """

    DEFAULT_BASE_URL = "http://localhost:9007/sse"

    def __init__(
        self,
        config: Dict[str, Any],
        post_jsonrpc: Optional[Callable] = None,
        validate_url: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self._config = config or {}
        self.base_url = str(config.get("base_url", "") or self.DEFAULT_BASE_URL).rstrip("/")
        self.token = str(config.get("token", "") or "")
        self.allow_local = bool(config.get("allow_local", False))
        self._post_jsonrpc = post_jsonrpc or self._default_post_jsonrpc
        self._validate_url = validate_url or self._validate_target_url

    def _validate_target_url(self, url: str) -> bool:
        """URL 校验（默认安全：仅公开 http(s)）。

        allow_local=True 时仅放行：localhost 或字面环回/私网/链路本地 IP；
        域名（即使公网）不经 allow_local 放行——杜绝借 allow_local 绕边界。
        """
        import ipaddress
        from urllib.parse import urlparse

        try:
            parsed = urlparse(str(url or ""))
        except Exception:
            return False
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname or ""
        if not host:
            return False
        lowered = host.lower()
        if lowered == "localhost":
            return bool(self.allow_local)
        local_ip = None
        try:
            local_ip = ipaddress.ip_address(lowered)
        except ValueError:
            local_ip = None
        if self.allow_local and local_ip is not None:
            if local_ip.is_loopback or local_ip.is_private or local_ip.is_link_local:
                return True
            return False
        return _validate_remote_url(url)

    @staticmethod
    def _default_post_jsonrpc(
        url: str, payload: Dict, headers: Dict, timeout: float
    ) -> Dict:
        import json as _json
        import urllib.request

        data = _json.dumps(payload).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read().decode("utf-8"))

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _rpc(self, method: str, params: Optional[Dict] = None, req_id: int = 1) -> Any:
        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        resp = self._post_jsonrpc(
            self.base_url, payload, self._headers(), float(self._config.get("timeout", 30))
        )
        if isinstance(resp, dict) and "error" in resp:
            raise RuntimeError(str(resp["error"]))
        return (resp or {}).get("result", {})

    async def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        if not self.base_url:
            return {"status": "failed", "error": "缺少 base_url（ima MCP 服务地址）", "results": []}
        if not self.token:
            return {"status": "failed", "error": "缺少 token（ima MCP 服务凭证）", "results": []}
        if not self._validate_url(self.base_url):
            return {
                "status": "failed",
                "error": f"URL 校验未通过: {self.base_url}",
                "results": [],
            }
        try:
            return await self._search_impl(query, limit)
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "error": str(e), "results": []}

    async def _search_impl(self, query: str, limit: int) -> Dict[str, Any]:
        import json

        self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "neurova", "version": "1.0"},
            },
        )
        tools_info = self._rpc("tools/list")
        tool_names = {t.get("name") for t in (tools_info or {}).get("tools", [])}
        search_tool = (
            "ima_search"
            if "ima_search" in tool_names
            else ("search" if "search" in tool_names else None)
        )
        if not search_tool:
            return {"status": "failed", "error": "ima MCP 未提供检索工具", "results": []}

        args: Dict[str, Any] = {"query": query}
        base_id = self._config.get("knowledge_base_id")
        if base_id:
            args["knowledge_base_id"] = base_id
        call_result = self._rpc("tools/call", {"name": search_tool, "arguments": args})
        content = (call_result or {}).get("content", []) or []
        results: List[Dict] = []
        for chunk in content:
            text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    parsed = parsed.get("data") or parsed.get("results") or [parsed]
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict):
                            results.append(
                                {
                                    "title": item.get("title", ""),
                                    "content": item.get("content", ""),
                                    "knowledge_base": item.get("knowledge_base", ""),
                                    "url": item.get("url", ""),
                                    "source": "ima",
                                }
                            )
            except ValueError:
                results.append({"title": "", "content": text, "source": "ima"})
        return {"status": "success", "results": results[:limit]}


# ── 注册表 ───────────────────────────────────────────────────

_REMOTE_TYPES = {
    "iflow": IflowKBAdapter,
    "feishu": FeishuKBAdapter,
    "ima": ImaKBAdapter,
}
_GENERIC_TYPES = {"custom"}


def get_adapter(kb_type: str, config: Dict[str, Any], ctx: Optional[Dict] = None) -> KBAdapter:
    """按 kb_type 构造适配器。

    - local:   LocalMemoryAdapter(ctx["memory_manager"])
    - iflow:   IflowKBAdapter(config)
    - feishu:  FeishuKBAdapter(config)
    - ima:     ImaKBAdapter(config)
    - custom/未知（自填 api_url）: GenericRESTAdapter(config)
    """
    ctx = ctx or {}
    kb_type = str(kb_type or "local")
    if kb_type == "local":
        return LocalMemoryAdapter(ctx.get("memory_manager"))
    if kb_type in _REMOTE_TYPES:
        return _REMOTE_TYPES[kb_type](config)
    return GenericRESTAdapter(config)
