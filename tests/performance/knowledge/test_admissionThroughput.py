# -*- coding: utf-8 -*-
"""批量准入吞吐基线（升级计划 B7，实测先行：先有数，后有改）。

本文件是**基线记录**，不是优化验收：量的是当前 `admission.admit` 单条路径——
经 `productionAdmissionGate` 全装配（身份消解 → 本体裁决 → 逐字可核 → 冲突 →
置信 → 血缘）在临时库上连续写入 N 条合法三元组的吞吐（facts/s）。读数供后续
admitBatch 立项对比：计划 §5 B7 判据是"批量摊薄事务收益 ≥30% 才落 admitBatch"，
没有基线读数的瓶颈不动手。

口径（每一条都钉死，读数才可复现）：
- 临时 store（tmp_path 单文件库），tenantId=default，agentId 固定；
- subjectLabel 用 f-string 逐条递增：每条都是新主体，没有去重折回、
  没有同主体冲突升级——每条都走完整五段，含消解段随主体数增长的真实成本；
- 谓词用未登记的 `mentions`（validation.py 保守原则：未登记谓词五条免检），
  且没有以它为头的规则 ⇒ 前向链不点燃：基线量的是**准入**成本，不是推导成本；
- assertions 必带（生产闸拒绝匿名知识），evidenceText 不带 ⇒ 逐字可核闸不动作；
- 判分取墙钟：60s 上界是**量级爆炸护栏**（对实测基线留一个数量级以上的余量，
  只回答"有没有爆炸"，不回答"快慢 5%"——细粒度判分按本仓墙钟台账纪律
  必须取与机器无关的读数，那是 perf_gate 的职责，不在这里重复第二套）。
  CPU 读数随输出一并回报，仅作诊断，不参与断言。
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

#: 基线规模（计划 §5 B7 指定 N=200）
N = 200
#: 量级爆炸护栏（秒）：实测基线见本文件 docstring 下方输出记录，超此即回归爆炸
UPPER_BOUND_S = 60.0

#: 立项门槛（升级计划 §5 B7 原话："批量摊薄事务收益 ≥30% 才落 admitBatch"）
BATCH_GAIN_WAIVER_PCT = 30.0

pytestmark = [pytest.mark.timeout(120)]  # 全局 30s 不够量一次基线；慢测试单独放宽的既有惯例


@pytest.fixture()
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "throughput.db"))
    yield s
    s.close()


class TestAdmissionThroughputBaseline:
    def test_singleAdmitPathThroughputBaseline(self, store):
        gate = productionAdmissionGate(store, toolVersion="throughput-baseline")
        factIds: list = []

        wallStarted = time.perf_counter()
        cpuStarted = time.thread_time()
        for index in range(N):
            subject = f"吞吐基准主体{index:04d}"
            obj = f"客体{index:04d}"
            content = f"{subject} mentions {obj}"
            receipt = gate.admit(AdmissionRequest(
                agentId="throughput", tenantId="default",
                subjectLabel=subject, predicateTermId="mentions", objectTerm=obj,
                content=content,
                assertions=[{"actorType": "user", "actorId": "baseline",
                             "statementText": content}],
            ))
            factIds.append(receipt.factId)
        wallElapsed = time.perf_counter() - wallStarted
        cpuElapsed = time.thread_time() - cpuStarted
        throughput = N / wallElapsed

        # 合理性断言一：N 条全部成功且没有一条是折回旧行（每条主体唯一 ⇒ fact 唯一）
        assert all(factIds), "存在空 fact_id 的回执——写入没落地"
        assert len(set(factIds)) == N, "出现重复 fact_id——本基线口径要求逐条新主体"
        persisted = store._conn.execute(
            "SELECT COUNT(*) AS n FROM knowledge_facts"
            " WHERE tenant_id = 'default' AND agent_id = 'throughput'"
            " AND status = 'active' AND record_kind = 'triple'").fetchone()["n"]
        assert persisted == N, f"落库 {persisted} 条 != 断言写入 {N} 条"
        # 合理性断言二：量级护栏（宽松上界，防回归爆炸；快慢百分比不在此判）
        assert wallElapsed < UPPER_BOUND_S, (
            f"{N} 条准入耗时 {wallElapsed:.1f}s 超过量级护栏 {UPPER_BOUND_S}s——"
            "单条准入路径出现数量级退化"
        )
        print(
            f"\nadmission-throughput baseline: N={N} "
            f"elapsed={wallElapsed:.3f}s cpu={cpuElapsed:.3f}s "
            f"throughput={throughput:.1f} facts/s"
        )


def _requests(prefix: str, count: int = N) -> list:
    """同一批合法三元组，两种写法共用——差异只许在提交次数上。"""
    batch = []
    for index in range(count):
        subject = f"{prefix}主体{index:04d}"
        obj = f"客体{index:04d}"
        content = f"{subject} mentions {obj}"
        batch.append(AdmissionRequest(
            agentId="throughput", tenantId="default", subjectLabel=subject,
            predicateTermId="mentions", objectTerm=obj, content=content,
            assertions=[{"actorType": "user", "actorId": "decision",
                         "statementText": content}],
        ))
    return batch


class TestBatchAmortizationRealised:
    """B7 已立项后的收益判据：`admitBatch` 对逐条 `admit` 的摊薄必须站得住门槛。

    门槛沿用计划原话的 30%。它现在钉的不是"值不值得做"（那一句在立项当轮已用
    实测回答：同事务摊薄 +329%），而是**这条优化有没有被后来的改动做没**——
    `admitBatch` 一旦退化成逐条提交，收益掉回 0%，本判据当场红。

    反证口径（立项当轮踩过一次，记在这儿免得再踩）：判"批量"是否真批量，不能靠
    读代码——`sqlite3.Connection.__exit__` 走的是 C 层提交，覆写 Python 侧
    `commit()` 的那版探针两侧跑的是同一条路，量出来的 +0.3% 是噪声而不是结论。
    以 API 实测温差为准：逐条提交不可能快过整批一次提交，收益过门槛即证摊薄成立。
    """

    def _run(self, tmp_path, mode: str) -> float:
        store = KnowledgeFactStore(str(tmp_path / ("b-%s.db" % mode)))
        gate = productionAdmissionGate(store, toolVersion="b7-batch-decision")
        batch = _requests("摊薄基准")
        started = time.perf_counter()
        if mode == "perCommit":
            for request in batch:
                gate.admit(request)
        else:
            findings = gate.admitBatch(batch)
            assert all(f["ok"] for f in findings), (
                "批量档里有被拒的条目，两侧的写入量不可比：%s" % findings[:3]
            )
        elapsed = time.perf_counter() - started
        persisted = store._conn.execute(
            "SELECT COUNT(*) FROM knowledge_facts WHERE agent_id = 'throughput'"
        ).fetchone()[0]
        store.close()
        assert persisted == N, f"{mode} 态落库 {persisted} != {N}，两侧不可比"
        return N / elapsed

    def test_admitBatchGainStaysAboveWaiver(self, tmp_path):
        perCommit = self._run(tmp_path, "perCommit")
        batched = self._run(tmp_path, "batched")
        gainPct = (batched / perCommit - 1.0) * 100.0
        print(
            f"\nadmission batch-amortization (real API): perCommit={perCommit:.1f} facts/s "
            f"admitBatch={batched:.1f} facts/s gain={gainPct:+.1f}% "
            f"waiver={BATCH_GAIN_WAIVER_PCT:.0f}%"
        )
        assert gainPct >= BATCH_GAIN_WAIVER_PCT, (
            f"admitBatch 相对逐条 admit 只快 {gainPct:+.1f}%，低于 "
            f"{BATCH_GAIN_WAIVER_PCT:.0f}% 立项门槛——批量档没在摊薄提交，"
            "要么退化成了逐条落盘，要么事务作用域根本没生效"
        )
