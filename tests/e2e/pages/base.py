# -*- coding: utf-8 -*-
"""e2e page object 基类（QwenPaw 对照批 C12）。

- `shouldSkipReal`/`shouldSkipMock`：双档跳过语义（真后端档需
  `NEUROVA_E2E_REAL=1` 显式开启；mock 档恒跑）；
- `resolveBaseUrl`：环境变量优先，缺省按端口拼本机地址；
- `BasePage`：urllib 薄封装（get/post 返回 (status, json)），供各
  page/client 子类复用——不引第三方 HTTP 依赖。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple


def shouldSkipReal(realEnvValue: str) -> Tuple[bool, str]:
    """真后端档的跳过判定：`NEUROVA_E2E_REAL` 未开即诚实跳过（点名原因）。"""
    if str(realEnvValue or "").strip() == "1":
        return False, ""
    return True, "真后端档未开启：设置 NEUROVA_E2E_REAL=1 后运行（避免无后端时的假失败）"


def shouldSkipMock(mockEnvValue: str) -> Tuple[bool, str]:
    """mock 档恒跑（不依赖真后端；参数留作与 real 对称的信号位）。"""
    return False, ""


def resolveBaseUrl(port: int = 9527) -> str:
    """e2e 目标地址：`NEUROVA_E2E_BASE_URL` 优先（CI/远端后端），缺省本机端口。"""
    explicit = os.environ.get("NEUROVA_E2E_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    return f"http://127.0.0.1:{port}"


class BasePage:
    """API 级 page object 基类：统一超时、鉴权头与 (status, json) 返回形态。"""

    def __init__(self, base_url: str, timeout: float = 10.0,
                 headers: Optional[Dict[str, str]] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.extra_headers = dict(headers or {})

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, str]] = None) -> Tuple[int, Any]:
        url = f"{self.base_url}{path}"
        merged = {**self.extra_headers, **(headers or {})}
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        if data is not None:
            merged.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, headers=merged, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, self._decode(resp)
        except urllib.error.HTTPError as e:
            return e.code, self._decode(e)

    @staticmethod
    def _decode(resp) -> Any:
        raw = resp.read()
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return raw.decode("utf-8", "replace")

    def get(self, path: str, headers: Optional[Dict[str, str]] = None) -> Tuple[int, Any]:
        return self._request("GET", path, headers=headers)

    def post(self, path: str, payload: Optional[Dict[str, Any]] = None,
             headers: Optional[Dict[str, str]] = None) -> Tuple[int, Any]:
        return self._request("POST", path, payload=payload, headers=headers)
