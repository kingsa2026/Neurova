"""人工 golden set 回归门：常见/冲突/过期/权限四类查询。

用例是手工标注（labeling_method=manual），不是 seedFromRepository 的标题直取。
门禁直接跑真 hybrid（禁用向量模型，避免单测加载 ONNX），读数不达标即红。
"""
import json
from pathlib import Path

from neurova.knowledge.evaluation.retrieval_benchmark import RetrievalBenchmark
from neurova.knowledge.hybrid import hybrid_search_knowledge
from neurova.knowledge.repository import KnowledgeRepository

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
OWNER = {"user_id": "1", "role": "admin"}
BOB = {"user_id": "2", "role": "user"}


def _seed(repo):
    def add(kid, title, content, **kw):
        repo.create_knowledge(
            "default", knowledge_id=kid, title=title, content=content,
            visibility=kw.pop("visibility", "public"), owner_user_id="1",
            detect_conflict=False, **kw,
        )

    add("g-common", "量子计算入门", "量子计算 基础 入门")
    add("g-conflict-old", "项目代号 旧值", "项目代号 旧值 Alpha")
    add("g-conflict-new", "项目代号 新值", "项目代号 新值 Beta")
    add("g-active-policy", "过期政策 当前版本", "过期政策 当前版本 仍有效")
    add(
        "g-expired-policy", "过期政策 旧版本", "过期政策 旧版本",
        valid_until="2000-01-01T00:00:00+00:00",
    )
    add("g-public-budget", "预算 公开", "预算 公开")
    add("g-private-budget", "预算 私密", "预算 私密", visibility="private")


def _load_cases(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["cases"]


def _run_suite(tmp_path, repo, user, fixture_name, top_k=5):
    bench = RetrievalBenchmark(str(tmp_path / (Path(fixture_name).stem + ".db")))
    cases = _load_cases(fixture_name)
    for case in cases:
        bench.addCase(
            case["query"], case["expected_ids"], domain=case["domain"],
            createdBy="golden", labelingMethod="manual",
        )

    def search_fn(query):
        return hybrid_search_knowledge(
            repo, user, query, limit=top_k, vector_index=None
        )

    report = bench.run(repo, user=user, topK=top_k, searchFn=search_fn)
    return bench, cases, report


def test_golden_suite_common_conflict_expired(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    _seed(repo)

    bench, cases, report = _run_suite(
        tmp_path, repo, OWNER, "knowledge_golden_cases.json"
    )

    assert report["measure_state"] == "measured"
    assert report["case_count"] == len(cases) == 3
    assert bench.labelingBreakdown() == {"manual": 3}
    assert report["recall_at_k"] >= 0.9, report
    assert report["mrr"] >= 0.8, report
    assert report["unhit_rate"] == 0.0, report

    expired_findings = [
        f for f in bench.findings(report["run_id"]) if f["query"] == "过期政策"
    ]
    assert expired_findings
    assert "g-expired-policy" not in expired_findings[0]["hit_ids"]

    bench.freezeBaseline(report)
    report2 = bench.run(
        repo, user=OWNER, topK=5,
        searchFn=lambda q: hybrid_search_knowledge(
            repo, OWNER, q, limit=5, vector_index=None
        ),
    )
    verdict = bench.compareAgainstBaseline(report2)
    assert verdict["verdict"] == "pass", verdict


def test_golden_permission_suite_does_not_leak_private(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    _seed(repo)

    bench, cases, report = _run_suite(
        tmp_path, repo, BOB, "knowledge_golden_permission_cases.json"
    )

    assert report["measure_state"] == "measured"
    assert report["case_count"] == len(cases) == 1
    assert report["unhit_rate"] == 0.0, report
    findings = bench.findings(report["run_id"])
    assert findings
    assert "g-private-budget" not in findings[0]["hit_ids"]
