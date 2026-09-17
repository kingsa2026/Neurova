"""
知识管理接口 - Knowledge Endpoint（聚合器）

2026-09-16 模块化拆分：本文件原 1338 行单文件多域端点，按域拆为
  - knowledge_common.py     共享层（模型 / repository 解析 / 可见性校验 / 异常守卫）
  - knowledge_core.py       CRUD / 搜索 / 分块预览 / 块级编辑
  - knowledge_sharing.py    share/unshare / 公共库审批 / 墓碑 / 同值冲突
  - knowledge_remote.py     远程知识库配置托管（configs/collections）+ 摄取队列观测
  - knowledge_ingestion.py  /import 文件 + /import-url 网页（SSRF 防护）+ 图谱抽取桥接
拆分是纯结构迁移：全部 34 条路由路径与响应契约不变（有序快照与遮蔽守护见
test_knowledge_route_order.py）。本文件挂载子 router 并保留兼容 re-export
（knowledge_graph_api / ingest_worker / 测试经 knowledge.<name> 引用私有符号）。

依赖方向（架构约束，2026-09-16 拆分后冻结）：

    neurova.api.endpoints.__init__ 注册表 ("neurova.api.endpoints.knowledge", "/v1/knowledge")
      │  include_router(prefix="/api/v1/knowledge")
      ▼
    本文件 knowledge.py（聚合器：只做组装，无端点处理函数）
      │  include_router × 5 + 根路由 add_api_route("") + 兼容 re-export
      ├─▶ knowledge_core       CRUD / 搜索 / 分块预览 / 块级编辑 + detail_router(参数路由)
      ├─▶ knowledge_sharing    share / 公共库审批 / 墓碑恢复 / 同值冲突
      ├─▶ knowledge_remote     configs / collections / ingress-tasks
      └─▶ knowledge_ingestion  /import 文件 / /import-url 网页（SSRF）/ 图谱抽取桥
                │  每个叶子只依赖共享叶子（叶子之间零交叉，已实证）
                ▼
      knowledge_common（模型 / repository 解析 / 可见性守卫 / 用户名解析）
                │  函数内懒导入
                ▼
      neurova.knowledge.repository / storage（下层域）

约束（改动前先读）：
1. 单向无环：聚合器 ─▶ 叶子 ─▶ knowledge_common；禁止任何反向边（叶子不得
   import 聚合器，聚合器不得 import 叶子之外的同域模块）。
2. 叶子之间禁止互相 import（含函数内懒导入）——共享需求一律下沉 knowledge_common。
3. 本文件不得承载业务逻辑或端点处理函数：根路由 GET ""/POST "" 的处理函数在
   knowledge_core，本文件仅 add_api_route 挂载（FastAPI 禁止嵌套 include 时
   prefix 与 path 双空）。
4. 叶子新增共享项加到 knowledge_common，不要在叶子间直接互调。

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

from __future__ import annotations

from fastapi import APIRouter, Depends, Request  # noqa: F401 - re-export 兼容面（原文件导出）
from typing import Dict, List  # noqa: F401

from neurova.core.logger import get_logger

from neurova.api.endpoints.knowledge_core import router as _core_router
from neurova.api.endpoints.knowledge_core import detail_router as _core_detail_router
from neurova.api.endpoints.knowledge_ingestion import router as _ingestion_router
from neurova.api.endpoints.knowledge_remote import router as _remote_router
from neurova.api.endpoints.knowledge_sharing import router as _sharing_router

logger = get_logger(__name__)

router = APIRouter()

# 根路由 GET ""/POST ""：FastAPI 禁止嵌套 include 时 prefix 与 path 双空，
# 由聚合器以原文件的注册方式直接挂载（处理函数与模型在 knowledge_core）。
# 原文件中根路由最先注册，顺序契约照旧。
from neurova.api.endpoints.knowledge_core import (  # noqa: E402,F401
    KnowledgeItem as _KnowledgeItem,
    create_knowledge as _create_knowledge,
    get_knowledge as _get_knowledge,
)

router.add_api_route(
    "",
    _get_knowledge,
    methods=["GET"],
)
router.add_api_route(
    "",
    _create_knowledge,
    methods=["POST"],
    response_model=_KnowledgeItem,
)

# ---------------------------------------------------------------------------
# 路由注册顺序契约（守护见 test_knowledge_route_order.py）：
# 单段参数 GET /{knowledge_id} 会遮蔽其后注册的单段字面 GET（/configs
# /collections /public-submissions /deleted /ingress-tasks 等）。
# 故全部字面前缀子 router 必须先 include，detail_router 最后。
# ---------------------------------------------------------------------------
router.include_router(_core_router)
router.include_router(_sharing_router)
router.include_router(_remote_router)
router.include_router(_ingestion_router)
router.include_router(_core_detail_router)

# ---------------------------------------------------------------------------
# 兼容 re-export（2026-09-16 拆分前这些名字定义在本文件；外部消费方
# knowledge_graph_api._default_llm_call / knowledge.ingest_worker._fetch_url /
# _import_file_data、tests 经 knowledge.<name> 或 from knowledge import <fn>
# 直接调端点处理函数——拆分前原文件的模块级函数面即外部契约，照单全收）。
# 共享层真身在 knowledge_common / knowledge_ingestion / knowledge_sharing，
# patch 请打叶子模块。
# ---------------------------------------------------------------------------
from neurova.api.endpoints.knowledge_common import (  # noqa: E402,F401
    KnowledgeCreate,
    KnowledgeItem,
    KnowledgeReviewRequest,
    KnowledgeSearchRequest,
    KnowledgeShareRequest,
    KnowledgeUpdate,
    entry_or_403 as _entry_or_403,
    entry_or_404 as _entry_or_404,
    get_agent as _get_agent,
    get_memory_manager as _get_memory_manager,
    get_repository as _get_repository,
    get_request_id as _get_request_id,
    guard as _guard,
    item_response as _item_response,
    resolve_usernames as _resolve_usernames,
)
from neurova.api.endpoints.knowledge_core import (  # noqa: E402,F401
    create_knowledge,
    delete_knowledge,
    get_knowledge,
    get_knowledge_item,
    list_chunk_revisions,
    list_knowledge_chunks,
    list_knowledge_revisions,
    preview_chunking,
    search_knowledge,
    update_knowledge,
    update_knowledge_chunk,
)
from neurova.api.endpoints.knowledge_ingestion import (  # noqa: E402,F401
    _build_item_dict,
    _default_llm_call,
    _fetch_url,
    _guess_type,
    _import_file_data,
    _resolve_runtime_agents,
    _title_from_filename,
    _title_from_url,
    _try_extract_to_graph,
    import_knowledge_file,
    import_knowledge_url,
    _validate_import_url,
)
from neurova.api.endpoints.knowledge_remote import (  # noqa: E402,F401
    _get_kb_storage,
    cancel_ingress_task,
    create_kb_collection,
    create_kb_config,
    delete_kb_collection,
    delete_kb_config,
    get_ingress_task,
    get_kb_config,
    list_ingress_tasks,
    list_kb_collections,
    list_kb_configs,
    sync_kb_config,
    update_kb_config,
)
from neurova.api.endpoints.knowledge_sharing import (  # noqa: E402,F401
    ConflictResolutionRequest,
    list_conflicts,
    list_deleted_knowledge,
    list_public_submissions,
    resolve_conflict,
    restore_knowledge,
    review_knowledge_public,
    share_knowledge,
    submit_knowledge_to_public,
    unshare_knowledge,
)
