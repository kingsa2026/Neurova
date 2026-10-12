# -*- coding: utf-8 -*-
"""批次 K3 第 1 步：对**真实库**跑一次检索台架并冻结基线，取聚合读数。

与其余活体脚本不同，这里**故意不做数据根隔离**——N3 那格的原话是
"台架建了三张表、建了 REST 读面，却从未对真数据跑过一次"（`data/knowledge/` 里连
`knowledge_evaluation.db` 这个文件都不存在）。要把它变成有据可查，就必须真跑在真库上。

写盘面有两处，且都要说清：① 评测库 `knowledge_evaluation.db`（本脚本新建，cases/runs/
findings 三表）；② `knowledge_facts.db` 的**库文件**会变——但**行不动**。第一版这里写的
是"全程只读"，被 md5 指纹当场推翻：打开底座连接即重放迁移链，本批之前落的 v13
（给断言表加 `erased_at`）在真库上重放，`user_version` 从 12 走到 13、列新增，
而 facts/subjects/assertions/activities/narratives 行数逐格核对与跑前一致。
首跑顺带证成一件 K2 的事：**迁移在既有真库上重放不炸**（§8.0 那格工单 011 就是炸在这里）。

读数只报**聚合量**，不导出查询串：真库 36 条条目全是 `visibility=private`、
属主 `user_id=1`，标题就是用户自己的知识内容，把它们写进仓内文件等于把私有语料
交出去。合成夹具（第 2 步）才是能入库、能给别人跑、会红的那一份。

身份不是可选参数：条目是私有的，换一个 user 就是在测另一份语料——
所以 `run()` 把 `context.user` 随读数一起落库，本脚本也必须显式用真属主跑。

跑法（仓库根）：

    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe -m tests.manual.retrievalBaselineLive
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    from neurova.knowledge.evaluation import get_retrieval_benchmark
    from neurova.knowledge.repository import get_knowledge_repository

    repo = get_knowledge_repository()
    bench = get_retrieval_benchmark()

    items = [it for entries in repo._items.values() for it in entries]
    owners = sorted({str(it.get("owner_user_id") or "") for it in items})
    print("语料：条目 %d 条，属主集合 %s，可见性 %s" % (
        len(items), owners,
        sorted({str(it.get("visibility") or "") for it in items})))
    if not items:
        print("FAIL 真库没有条目，跑出来的读数无依据")
        return 2

    if bench.caseCount() == 0:
        seeded = bench.seedFromRepository(repo, minCases=30)
        print("自动标注产例 %d 条（三种口径轮转，同 query 去重）" % seeded)
    else:
        print("评测集已存在 %d 例，不重复播种" % bench.caseCount())

    # 真属主：private 条目对别的 user 不可见，换身份测的是另一份语料
    report = bench.run(repo, user={"user_id": owners[0]}, agentId="default",
                       topK=5, note="首次真库基线（K3 / N3）")
    print("本次 run：%s measure_state=%s" % (report["run_id"], report["measure_state"]))
    if bench.baseline() is None:
        bench.freezeBaseline(report, note="K3 首冻：台架自此对真数据有一次实证")

    snapshot = bench.baselineSnapshot()
    # 只打聚合量；unhit_queries 是用户私有标题，不落屏也不入库
    readings = dict(snapshot.get("readings") or {})
    readings["unhit_count"] = len(snapshot.get("unhit_queries") or [])
    print(json.dumps({
        "measure_state": snapshot.get("measure_state"),
        "frozen_at": snapshot.get("frozen_at"),
        "case_count": snapshot.get("case_count"),
        "top_k": snapshot.get("top_k"),
        "context": snapshot.get("context"),
        "readings": readings,
        "labeling_breakdown": snapshot.get("labeling_breakdown"),
    }, ensure_ascii=False, indent=2))

    # 态名照抄生产字面：`retrieval_benchmark.py:315` 落 "measured"，`:186/:284` 落
    # "unevidenced"，仓内没有这份枚举的常量。第一版这里自推成 "evidenced"，
    # 于是基线明明冻结成功、脚本却自己报 FAIL——判据比产品窄是脚本 bug，不是产品缺陷。
    if snapshot.get("measure_state") != "measured":
        print("FAIL 基线不是 measured 态（现值 %r），读数不可引用"
              % snapshot.get("measure_state"))
        return 1
    print("BASELINE-FROZEN 真库基线已冻结，台架自此有一条可读的实证 run（run_id=%s）"
          % snapshot.get("run_id"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
