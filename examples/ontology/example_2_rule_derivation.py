# -*- coding: utf-8 -*-
"""示例 2：注册传递规则 → 写 2 条事实 → 前向链推出结论 → 解释生成 → 撤销前提 → 精确撤销验证。

离线可跑：不依赖网络 / LLM / API key；数据根用 tempfile 临时目录，跑完即清理。
运行：.venv/Scripts/python.exe examples/ontology/example_2_rule_derivation.py

预期输出（fact_id 是每次运行不同的随机短哈希，下面用 … 缩略）：
----------------------------------------------------------------------
[1] 规则登记完成: part_of_transitive  X part_of Y, Y part_of Z => X part_of Z
[2] 事实写入: 螺丝A part_of 主板M  -> fact_id=fact_…
[2] 事实写入: 主板M part_of 整机X  -> fact_id=fact_…
[3] 前向链推出: fact_id=fact_… content=螺丝A part_of 整机X（由规则 part_of_transitive 推出）
[4] 解释生成:
    结论 螺丝A part_of 整机X 由规则 part_of_transitive 从前提 主板M part_of 整机X、螺丝A part_of 主板M 推出
[5] 撤销前提: 主板M part_of 整机X (fact_id=fact_…)
[6] 精确撤销验证:
    推导结论 螺丝A part_of 整机X 状态 = retracted（随前提精确退场）
    未涉事实 螺丝A part_of 主板M   状态 = active（不受波及）
    检索读面剩余事实数 = 1（推导结论已出池）
----------------------------------------------------------------------
预期输出摘要：规则注册后前向链自动推出传递结论；解释生成给出中文推导链；
撤销一条前提后，只有依赖它的推导结论被精确撤销，其余事实不受波及。

（运行时另有一行 logging INFO「事实撤回 …」走 stderr，属正常噪声，不影响判读。）
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
from neurova.knowledge.ontology.derivation_ledger import DerivationLedger  # noqa: E402
from neurova.knowledge.ontology.explanation import explainDerivation  # noqa: E402
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine  # noqa: E402
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
                     "mediumRef": "example_2", "statementText": content}],
    ))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    workdir = tempfile.mkdtemp(prefix="ontology_example_2_")
    store = KnowledgeFactStore(str(Path(workdir) / "kb.db"))
    try:
        # ── [1] 登记关系术语 + 显式注册一条传递规则（relay 形状）─────────
        registry = OntologyTermRegistry(store)
        registry.register("part_of", "relation", label="属于",
                          definition="部件与其上级装配件的组成关系")
        engine = ForwardChainingEngine(store)
        engine.registerRule(
            "part_of_transitive", "part_of",
            [{"atom": "part_of", "subject": "X", "object": "Y"},
             {"atom": "part_of", "subject": "Y", "object": "Z"}],
            headSubjectVar="X")
        print("[1] 规则登记完成: part_of_transitive  "
              "X part_of Y, Y part_of Z => X part_of Z")

        # ── [2] 两条前提事实过唯一写咽喉（每次写入后闸内自动点燃相关规则）──
        gate = productionAdmissionGate(store, toolVersion="ontology_example")
        r1 = admit(gate, "螺丝A", "part_of", "主板M")
        print("[2] 事实写入: 螺丝A part_of 主板M  -> fact_id=%s" % r1.factId)
        r2 = admit(gate, "主板M", "part_of", "整机X")
        print("[2] 事实写入: 主板M part_of 整机X  -> fact_id=%s" % r2.factId)

        # ── [3] 前向链推出的结论（推导事实也经咽喉入库，账本记前提边）────
        ledger = DerivationLedger(store)
        derivedIds = ledger.derivedFactIds()
        derivedId = derivedIds[0]
        derived = store.fact(derivedId)
        print("[3] 前向链推出: fact_id=%s content=%s"
              % (derivedId, derived["content"]))

        # ── [4] 解释生成：沿推导账本回溯这条结论怎么来的（中文模板）──────
        explanation = explainDerivation(store, derivedId)
        print("[4] 解释生成:")
        print("    %s" % explanation["text"])

        # ── [5] 撤销一条前提：行不删，只出候选（可撤销不可遗忘）──────────
        store.retract(r2.factId, reason="示例：撤销前提")
        print("[5] 撤销前提: 主板M part_of 整机X (fact_id=%s)" % r2.factId)

        # ── [6] 精确撤销验证：只有依赖该前提的推导退场，其余事实不动 ──────
        derivedAfter = store.fact(derivedId)
        untouched = store.fact(r1.factId)
        remaining = store.searchableFacts(agentId=AGENT, tenantId=TENANT)
        print("[6] 精确撤销验证:")
        print("    推导结论 螺丝A part_of 整机X 状态 = %s（随前提精确退场）"
              % derivedAfter["status"])
        print("    未涉事实 螺丝A part_of 主板M   状态 = %s（不受波及）"
              % untouched["status"])
        print("    检索读面剩余事实数 = %d（推导结论已出池）" % len(remaining))
    finally:
        store.close()
        shutil.rmtree(workdir, ignore_errors=True)

    print("-" * 70)
    print("预期输出摘要：规则注册后前向链自动推出传递结论；解释生成给出中文")
    print("推导链；撤销一条前提后，仅依赖它的推导结论被精确撤销，其余不动。")


if __name__ == "__main__":
    main()
