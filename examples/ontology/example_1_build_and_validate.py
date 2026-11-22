# -*- coding: utf-8 -*-
"""示例 1：建 3 个术语 + 注册 2 个形状 + 经唯一写咽喉落 3 条事实 + SHACL 校验报告。

离线可跑：不依赖网络 / LLM / API key；数据根用 tempfile 临时目录，跑完即清理。
运行：.venv/Scripts/python.exe examples/ontology/example_1_build_and_validate.py

预期输出（fact_id / subject_key 是每次运行不同的随机短哈希，下面用 … 缩略）：
----------------------------------------------------------------------
[1] 术语登记完成: device(概念) router(概念,父类=device) has_serial(关系)
[2] 形状注册完成: serial_format(pattern=SN-\\d+) concept_id_format(pattern=^[a-z])
[3] 咽喉写入成功: 路由器R1 is_a router          -> fact_id=fact_…
[3] 咽喉写入成功: 路由器R1 has_serial SN-001    -> fact_id=fact_…
[3] 咽喉写入成功: 交换机S1 is_a device          -> fact_id=fact_…
[4] 咽喉拒绝坏数据: 交换机S1 has_serial BAD-001
    原因: 本体校验未过：violation[shape:serial_format] 序列号必须是 SN-数字 形式…
[5] SHACL 运行时报告(现库, shadow): conforms=True, violations=0
[5] SHACL 运行时报告(坏候选 dry-run, shadow): conforms=False, violations=1
    - component=PatternConstraintComponent severity=Violation value=BAD-001
----------------------------------------------------------------------
预期输出摘要：3 术语 + 2 形状 + 3 事实经咽喉落库；第 4 条坏序列号被写前
校验拒绝；SHACL 报告现库 conform、坏候选被运行时校验点名。
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
from neurova.knowledge.ontology.shacl_runtime import validateShapesRuntime  # noqa: E402
from neurova.knowledge.ontology.shapes import ShapeRegistry  # noqa: E402
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry  # noqa: E402

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
                     "mediumRef": "example_1", "statementText": content}],
    ))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    workdir = tempfile.mkdtemp(prefix="ontology_example_1_")
    store = KnowledgeFactStore(str(Path(workdir) / "kb.db"))
    try:
        # ── [1] 建术语：两个概念（含层级）+ 一个关系 ──────────────────
        registry = OntologyTermRegistry(store)
        registry.register("device", "concept", label="设备",
                          definition="可联网的硬件设备")
        registry.register("router", "concept", label="路由器",
                          parentTermId="device",
                          definition="在网络间转发数据包的设备")
        registry.register("has_serial", "relation", label="有序列号",
                          domain=["device"], cardinality=1)
        print("[1] 术语登记完成: device(概念) router(概念,父类=device) "
              "has_serial(关系)")

        # ── [2] 注册 2 个用户形状（SHACL 语义 DSL：targetObjectsOf + pattern）──
        # 注：DSL 另支持 in/minCount/maxCount/class；其中 minCount/maxCount 在
        # 标准 SHACL 里只能挂在 PropertyShape 上，而本仓导出面把它发射成
        # NodeShape——pyshacl 会拒收。示例选 two pattern（NodeShape 合法），
        # 让运行时校验（pyshacl）与写前 DSL 校验同一批形状都能咬合。
        shapes = ShapeRegistry(store)
        shapes.register(TENANT, "serial_format", "relation", "pattern",
                        {"pattern": r"SN-\d+"}, targetTermId="has_serial",
                        severity="violation", message="序列号必须是 SN-数字 形式")
        shapes.register(TENANT, "concept_id_format", "relation", "pattern",
                        {"pattern": r"^[a-z][a-z0-9_]*$"}, targetTermId="is_a",
                        severity="violation", message="类型断言客体须是小写概念 id")
        print("[2] 形状注册完成: serial_format(pattern=SN-\\d+) "
              "concept_id_format(pattern=^[a-z])")

        # ── [3] 三条合法事实过唯一写咽喉（身份消解/本体校验/血缘/置信一段走完）
        gate = productionAdmissionGate(store, toolVersion="ontology_example")
        for subject, predicate, obj in (("路由器R1", "is_a", "router"),
                                        ("路由器R1", "has_serial", "SN-001"),
                                        ("交换机S1", "is_a", "device")):
            receipt = admit(gate, subject, predicate, obj)
            print("[3] 咽喉写入成功: %-18s %-11s %-8s -> fact_id=%s"
                  % (subject, predicate, obj, receipt.factId))

        # ── [4] 一条坏数据：形状 violation 在写前就被咽喉拒绝（零落盘）────
        # （换未写过序列号的交换机S1 当主体，让形状判据先于基数判据命中）
        try:
            admit(gate, "交换机S1", "has_serial", "BAD-001")
            print("[4] 意外：坏数据竟被放行（不应发生）")
        except ValueError as exc:
            print("[4] 咽喉拒绝坏数据: 交换机S1 has_serial BAD-001")
            print("    原因: %s" % str(exc).split("；")[0])

        # ── [5] SHACL 运行时校验报告（U1）：形状单源导出 + pyshacl 求值 ──
        report = validateShapesRuntime(store, TENANT, agentId=AGENT,
                                       mode="shadow")
        print("[5] SHACL 运行时报告(现库, shadow): conforms=%s, violations=%d"
              % (report["conforms"], len(report["violations"])))
        badCandidate = [{"subject_key": store.resolveSubjectKey(AGENT, "交换机S1"),
                         "predicate_term_id": "has_serial",
                         "object_term": "BAD-001", "fact_id": "candidate_1"}]
        dryRun = validateShapesRuntime(store, TENANT, agentId=AGENT,
                                       mode="shadow", extraFacts=badCandidate)
        print("[5] SHACL 运行时报告(坏候选 dry-run, shadow): conforms=%s, "
              "violations=%d" % (dryRun["conforms"], len(dryRun["violations"])))
        for item in dryRun["violations"]:
            print("    - component=%s severity=%s value=%s message=%s"
                  % (item["component"], item["severity"], item["value"],
                     item["message"]))
    finally:
        store.close()
        shutil.rmtree(workdir, ignore_errors=True)

    print("-" * 70)
    print("预期输出摘要：3 术语 + 2 形状 + 3 事实经咽喉落库；坏序列号被写前")
    print("校验拒绝（violation 零落盘）；SHACL 报告现库 conform、坏候选被点名。")


if __name__ == "__main__":
    main()
