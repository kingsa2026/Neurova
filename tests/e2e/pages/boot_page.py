# -*- coding: utf-8 -*-
"""后端 boot 冒烟的 page object（对照批 C12）。

把 `test_backend_boot.py` 的探活/文档面断言收成可复用封装：
- `waitHealth`：轮询 /health 直到 200（预算内）；
- `expectApiDocsRemoved`：/docs /redoc /openapi.json 钉死 404 的断言面。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Tuple

from .base import BasePage, resolveBaseUrl

PROJECT_ROOT = str(Path(__file__).resolve().parents[3])

#: 文档面钉死 404 的路径清单（与 test_backend_boot 的契约一致）
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class BootPage(BasePage):
    """后端 boot 冒烟页面对象（API 级）。"""

    def __init__(self, port: int = 9527, timeout: float = 5.0):
        super().__init__(base_url=resolveBaseUrl(port), timeout=timeout)
        self.port = port

    def getHealth(self) -> Tuple[int, Dict]:
        return self.get("/health")

    def waitHealth(self, seconds: float = 90.0) -> bool:
        """预算内轮询 /health 直到 200。"""
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                status, _ = self.getHealth()
                if status == 200:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def expectApiDocsRemoved(self) -> List[Tuple[str, int]]:
        """文档面钉死 404；返回 [(path, status)]（应全为 404）。"""
        return [(path, self.get(path)[0]) for path in DOCS_PATHS]
