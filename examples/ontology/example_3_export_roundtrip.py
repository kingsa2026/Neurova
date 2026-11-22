# -*- coding: utf-8 -*-
"""示例 3：全库 Turtle 导出 → 自家解析器往返 → 逐字节一致断言。

离线可跑：不依赖网络 / LLM / API key；数据根用 tempfile 临时目录，跑完即清理。
运行：.venv/Scripts/python.exe examples/ontology/example_3_export_roundtrip.py

预期输出（三元组计数随种子数据固定；fact/subject 哈希每次不同，不进断言）：
----------------------------------------------------------------------
[1] 种子数据: 术语 2 条(device/router) + 规则 1 条(dev_rel) + 事实 3 条
[2] 全库 Turtle 导出: 一次导出 3 段(terms/rules/facts)共 N 行, 解析出 M 个三元组
[3] 自家解析往返: parseTurtle 读回 M 个三元组，关键三元组全部命中
    - (kbg:device, kbg:kind, "concept"@zh)
    - (kbg:router, kbg:parentTermId, kbg:device)
    - (kbg:<subj_…>, kbg:mentions, "端口P1"@zh)
[4] 逐字节一致断言: 第二次导出与第一次逐字节相同 -> True
    回读解析两次结果一致 -> True
----------------------------------------------------------------------
预期输出摘要：serializeAll 全库导出是确定性的——同库两次输出逐字节一致，
且导出文本能被自家 parseTurtle 无损读回（往返判据）。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

# 让脚本从仓库任意工作目录都能跑：把项目根加进 sys.path（与既有示例同款）。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from neurova.knowledge.foundation.admission import (  # noqa: E402
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore  # noqa: E402
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine  # noqa: E402
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry  # noqa: E402
from neurova.knowledge.ontology.turtle import (  # noqa: E402
    iri,
    literal,
    parseTurtle,
    serializeAll,
)

AGENT = "default"
TENANT = "default"


def admit(gate, subject, predicate, obj):
    """经生产装配咽喉写一条三元组。assertions 必带——咽喉不接受匿名知识。"""
    content = "%s %s %s" % (subject, predicate, obj)
    return gate.admit(AdmissionRequest(
        agentId=AGENT, tenantId=TENANT,
        subjectLabel=subject, predicateTermId=predicate, objectTerm=obj,
        content=content,
        assertions=[{"actorType": "pipeline", "actorId": "ontology_example",
                     "mediumRef": "example_3", "statementText": content}],
    ))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    workdir = tempfile.mkdtemp(prefix="ontology_example_3_")
    store = KnowledgeFactStore(str(Path(workdir) / "kb.db"))
    try:
        # ── [1] 种子数据：术语层级 + 一条规则 + 三条事实 ─────────────────
        registry = OntologyTermRegistry(store)
        registry.register("device", "concept", label="设备")
        registry.register("router", "concept", label="路由器",
                          parentTermId="device")
        registry.register("mentions", "relation", label="提及")
        ForwardChainingEngine(store).registerRule(
            "dev_rel", "mentions",
            [{"atom": "mentions", "subject": "X", "object": "Y"}])
        gate = productionAdmissionGate(store, toolVersion="ontology_example")
        admit(gate, "路由器R1", "is_a", "router")
        admit(gate, "路由器R1", "mentions", "端口P1")
        admit(gate, "交换机S1", "is_a", "device")
        print("[1] 种子数据: 术语 3 条(device/router/mentions) + 规则 1 条"
              "(dev_rel) + 事实 3 条")

        # ── [2] 全库 Turtle 导出（terms/rules/facts 三段一个文档）────────
        text1 = serializeAll(store)
        triples1 = parseTurtle(text1)
        print("[2] 全库 Turtle 导出: %d 行, 解析出 %d 个三元组"
              % (len(text1.splitlines()), len(triples1)))

        # ── [3] 自家解析往返：导出的文本能被自己的解析器读回 ─────────────
        routerKey = store.resolveSubjectKey(AGENT, "路由器R1")
        expected = {
            (iri("device"), "kbg:kind", literal("concept")),
            (iri("router"), "kbg:parentTermId", iri("device")),
            (iri(routerKey), "kbg:mentions", literal("端口P1")),
        }
        missing = expected - set(triples1)
        print("[3] 自家解析往返: 关键三元组 %s"
              % ("全部命中" if not missing else "缺失 %s" % (missing,)))
        for triple in sorted(expected):
            print("    - %s" % (triple,))

        # ── [4] 逐字节一致断言：同库两次导出逐字节相同（确定性判据）──────
        text2 = serializeAll(store)
        triples2 = parseTurtle(text2)
        print("[4] 逐字节一致断言: 第二次导出与第一次逐字节相同 -> %s"
              % (text1 == text2))
        print("    回读解析两次结果一致 -> %s" % (triples1 == triples2))
        assert text1 == text2, "同库两次导出必须逐字节一致"
        assert triples1 == triples2, "解析回读必须稳定"
    finally:
        store.close()
        shutil.rmtree(workdir, ignore_errors=True)

    print("-" * 70)
    print("预期输出摘要：serializeAll 全库导出是确定性的——同库两次输出逐字节")
    print("一致，且导出文本能被自家 parseTurtle 无损读回（往返判据）。")


if __name__ == "__main__":
    main()
