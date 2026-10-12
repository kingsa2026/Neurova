# -*- coding: utf-8 -*-
"""运行时会话注册表的隔离判据（§6-118）。

要守的东西：`neurova.api.endpoints._app_state` 是 `api/app.py` 的 startup 写进去的
进程全局（含 `agents`），关停路径**不回收**。生产无所谓——进程随即就退；测试会话里
同一进程要连跑几百条用例，于是"下游用例自建 app 却读到上一个用例的运行时 agent"
就成了跨用例的隐形分支。本目录的 `conftest.py` 用 autouse 夹具做进出快照复原，
这两格就是钉住这件事：

- 第一格证明**漏的来源真实存在**（进了 lifespan 注册表就被填上）——否则第二格
  可能只是"没人写过所以没人还"的空转绿；
- 第二格证明**夹具真的还了**——把 `conftest.py` 删掉，这一格必须翻红。

两格按源码顺序跑（pytest 默认），第二格读的是"第一格跑完之后"的状态。
"""

from __future__ import annotations

from neurova.api import endpoints as ep

# 收集期取值：pytest 先收集全部再跑用例，所以这就是本场测试的"进入前"形态。
BASELINE_STATE = ep.get_app_state()


def _isolatedStore(tmp_path):
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

    return KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))


def test_lifespanBootPopulatesTheRuntimeRegistry(tmp_path, monkeypatch):
    """进一次真 lifespan ⇒ 注册表被填上（漏的来源，不是假想）。"""
    from neurova.cognitive_layers.knowledge_graph.manager import (
        reset_agent_knowledge_graph_managers,
    )
    from neurova.api.app import create_app
    from fastapi.testclient import TestClient

    reset_agent_knowledge_graph_managers()
    isolated = _isolatedStore(tmp_path)
    # 围栏比的是导入期的 PRODUCTION_STORAGE_DIR，默认路径当场会被拦住；
    # 注隔离实例只为让启动跑得下去，被测的是启动**留下的那条全局**。
    monkeypatch.setattr("neurova.knowledge.foundation.get_knowledge_fact_store",
                        lambda *a, **kw: isolated)
    monkeypatch.setattr("neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
                        lambda *a, **kw: isolated)
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NEUROVA_AGENT_WORKSPACES_DIR", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir(parents=True, exist_ok=True)

    try:
        with TestClient(create_app()):
            pass
    finally:
        isolated.close()

    state = ep.get_app_state()
    agents = (state or {}).get("agents") or {}
    assert agents, (
        "启动没把运行时 agent 写进注册表——那么本目录的隔离夹具就是在守一条不存在的漏，"
        "下一格的绿也是空转（真 create_app() 之后实测：%r）" % (state,))

    # 顺手把"注册表里有 agent 会改掉下游分支"这一跳钉住：知识导入路由解析运行面时
    # 第一优先读的就是这条全局（`_resolve_runtime_agents`）。
    from neurova.api.endpoints import knowledge_ingestion as kn

    assert kn._resolve_runtime_agents(None) == agents, (
        "注册表有 agent 却解析不出来——上一格的断言就失去了意义")


def testRegistryIsReclaimedForTheNextCase():
    """上一条用例进过 lifespan，这一条开头必须回到收集期形态（夹具真的还了）。"""
    assert ep.get_app_state() is BASELINE_STATE, (
        "运行时注册表被上一条用例留在了身后——下游那些自建 app 的用例会在 "
        "`_resolve_runtime_agents` 处走错分支（实测三格红，见 §6-118）。"
        "现值 agents=%r" % (sorted(((ep.get_app_state() or {}).get("agents") or {})),))
