"""MCP HTTP 出网边界：URL 判定单源在 url_guard，TCP 连接固定到本次解析地址。"""

from __future__ import annotations

import os


def trustedHosts() -> set:
    raw = os.environ.get("NEUROVA_MCP_TRUST_HOSTS") or ""
    return {host.strip().lower() for host in raw.split(",") if host.strip()}


def resolveMcpEndpoint(endpoint: str):
    from neurova.security.url_guard import resolvePublicUrl

    resolution = resolvePublicUrl(endpoint, trusted_hosts=trustedHosts())
    if not resolution.addresses:
        raise ValueError(f"MCP endpoint 未解析出可连接地址: {endpoint}")
    if not resolution.directConnectable:
        raise ValueError("MCP endpoint 解析为 fake-ip，无法固定直连地址")
    return resolution


def pinnedMcpTransport(resolution):
    """保留请求 origin 与 TLS SNI，仅把 TCP 对端固定为已验证地址。"""
    import httpcore2
    import httpx2
    from httpcore2._backends.auto import AutoBackend

    class PinnedBackend(AutoBackend):
        async def connect_tcp(
            self, host, port, timeout=None, local_address=None, socket_options=None,
        ):
            if host != resolution.host:
                raise httpcore2.ConnectError(f"MCP 传输主机未固定: {host}")
            lastError = None
            for address in resolution.addresses:
                try:
                    return await super().connect_tcp(
                        address, port, timeout=timeout,
                        local_address=local_address, socket_options=socket_options,
                    )
                except Exception as exc:
                    lastError = exc
            raise lastError or httpcore2.ConnectError("MCP 目标没有可连接地址")

    class ResponseStream(httpx2.AsyncByteStream):
        def __init__(self, stream):
            self._stream = stream

        async def __aiter__(self):
            async for chunk in self._stream:
                yield chunk

        async def aclose(self):
            close = getattr(self._stream, "aclose", None)
            if close is not None:
                await close()

    class PinnedTransport(httpx2.AsyncBaseTransport):
        def __init__(self):
            self._pool = httpcore2.AsyncConnectionPool(network_backend=PinnedBackend())

        async def handle_async_request(self, request):
            coreRequest = httpcore2.Request(
                method=request.method,
                url=httpcore2.URL(
                    scheme=request.url.raw_scheme,
                    host=request.url.raw_host,
                    port=request.url.port,
                    target=request.url.raw_path,
                ),
                headers=request.headers.raw,
                content=request.stream,
                extensions=request.extensions,
            )
            response = await self._pool.handle_async_request(coreRequest)
            return httpx2.Response(
                response.status,
                headers=response.headers,
                stream=ResponseStream(response.stream),
                extensions=response.extensions,
                request=request,
            )

        async def aclose(self):
            await self._pool.aclose()

    return PinnedTransport()
