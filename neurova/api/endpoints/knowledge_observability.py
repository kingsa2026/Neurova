# -*- coding: utf-8 -*-
"""默认关能力读数面（升级计划 §15.1「观测与开关」欠的服务端面）。

只做一件事：把 §13.1 那九项开关的**现值**一次报清楚，让前端的开关面板不再抄一张
静态表。九项的名册与解点在 `neurova.knowledge.defaultOffFlags`，本模块不读环境变量、
不解释语义，也不提供任何写入：

- 默认关是产品/成本/安全决定（§6「不打包全开」），不是断点；本页的职责是**可观测**，
  不是把开闸做成一个按钮；
- 因此本面只报开关态与归属模块，不回传任何环境变量的实际内容（判据⑤钉这一条）。

治理门：管理员可读，非管理员 403，未登录 401——服务器开关态不是公开面。
独立叶子：端点逻辑不塞 knowledge_ontology.py（尺寸纪律），挂载走 `knowledge.py` 聚合器。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from neurova.api.auth import get_current_user_or_service

router = APIRouter()


@router.get("/observability/default-off")
async def getDefaultOffReadings(
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """九项默认关开关的现值形读数（登录且管理员）。"""
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="默认关能力态是服务器配置面，仅管理员可读")

    from neurova.knowledge.defaultOffFlags import defaultOffReadings

    return {"code": 0, "message": "success", "data": {"items": defaultOffReadings()}}
