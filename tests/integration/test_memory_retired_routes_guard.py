"""已退役的内存端点必须真的不可达（防止"删了实现、留着 500 的空壳"）

这五条路由的共同形态：**后端没有实现，前端只有封装、组件侧零消费**。

- `GET /memory/questions/pending`、`POST /memory/questions/ask`、`GET /memory/questions/stats`
  —— `MemoryManager` 上三个方法一个都不存在（运行时 `hasattr` 逐条探明），
  而"问题队列"这个功能的现役实现在 `/api/v1/growth/questions`（走
  `agent.question_queue_manager`），本组是它的第二份实现且从未接通；
- `GET /memory/eki/reinforce` —— 调 `manager.eki_get_reinforcement_recommendations`，
  不存在；manager 上语义相邻的 `eki_recommend_reinforcement` 是"给传入的 id 打分"，
  与"推荐哪些记忆需要强化"不是同一件事，不能改名冒充接通；
- `POST /memory/meta/skills/generate` —— 调 `manager.meta_generate_skill`，不存在；
  而整个 `/meta/skills*` 面在 manager 侧是"最近元认知事件"的别名视图，不含技能生成。

处置口径由维护者拍板为**退役**（AGENTS.md §2：写出无人读的字段、注册无消费者的模块
属断点，必须接线或删除；无人消费即删），不是把 500 改写成 501 后继续挂着一条
无人调用的路由。

判据取行为而非形状：五条路径必须 404。删除前它们红在 500（AttributeError 被
折成 5001），删除后红转绿。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.endpoints.memory import router as memoryRouter
from neurova.api.error_handlers import register_error_handlers

ANON = {"user_id": "default", "username": "default", "role": "user", "neuser_id": "default"}

RETIRED = [
    ("get", "/api/v1/memory/questions/pending"),
    ("post", "/api/v1/memory/questions/ask"),
    ("get", "/api/v1/memory/questions/stats"),
    ("get", "/api/v1/memory/eki/reinforce"),
    ("post", "/api/v1/memory/meta/skills/generate"),
]


@pytest.fixture
def client():
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(memoryRouter, prefix="/api/v1/memory")
    testClient = TestClient(app)
    testClient.app.dependency_overrides[auth_mod.get_current_user_or_default] = lambda: ANON
    return testClient


@pytest.mark.parametrize("method,path", RETIRED)
def test_retiredRouteIsUnreachable(client, method: str, path: str):
    r = getattr(client, method)(path)

    assert r.status_code == 404, (
        f"{method.upper()} {path} 应已退役（404），实得 {r.status_code}: {r.text}"
    )


def test_retiredPathsAreNotRegisteredAnywhere():
    """路由表里不得留悬空登记——防止"实现删了、@router 还挂在别处"的半退役形态"""
    registered = {
        (route.path, tuple(sorted(getattr(route, "methods", []) or [])))
        for route in memoryRouter.routes
    }
    leftovers = []
    for method, path in RETIRED:
        tail = path.split("/api/v1/memory", 1)[1]
        if any(routePath == tail for routePath, _ in registered):
            leftovers.append(f"{method.upper()} {path}")

    assert leftovers == [], "以下已退役路由仍挂在 router 上：\n" + "\n".join(leftovers)


def test_questionsModuleIsRetired():
    """同批退役专用叶子模块与聚合器里的导入（修复教义第 7 条：接线与退役同批完成）"""
    import importlib

    assert not importlib.util.find_spec("neurova.api.endpoints.memory.questions"), (
        "questions 模块仍在：其端点已退役，模块与其在 memory/__init__.py 的导入应同批删除"
    )

    source = (
        importlib.import_module("neurova.api.endpoints.memory").__file__
    )
    with open(source, encoding="utf-8") as fh:
        aggregator = fh.read()
    assert "from . import questions" not in aggregator, "聚合器仍在导入已退役模块"
