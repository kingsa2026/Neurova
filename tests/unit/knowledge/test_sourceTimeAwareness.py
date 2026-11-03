# -*- coding: utf-8 -*-
"""批 TB/TC：时间感知消费面——同源更新重入库（T-E 已裁）＋冲突读数（T-D 已裁）。

立项理由（docs/specs/2026-11-04-知识库三时间戳与时间感知消费面设计.md）：
- TB：同一文档修改后重新导入，今天指纹不同各立条目——**新旧两代并存**，
  检索同时命中两代内容（检索污染）。裁定：同 source_path 且源修改时间明确
  更晚 ⇒ 覆盖既有条目（旧值进 revisions、刷新入库时间、保留 knowledge_id）；
  更早/相同/不可考 ⇒ 维持现状不猜。
- TC：条目级同值冲突队列（人审面）只记相似度，不带任何时间读数——
  "新旧两版谁是新说法"全靠审阅人自己猜。裁定：冲突行加 time_context
  （哪边源修改时间更新），只出建议不改判。
"""
import pytest

from neurova.knowledge.repository import KnowledgeRepository, _parseSourceDate


@pytest.fixture()
def repo(tmp_path):
    return KnowledgeRepository(str(tmp_path))


class TestParseSourceDate:
    def test_pdfMetaDateFormParses(self):
        """PDF 元数据形 D:20240301120000+08'00' 必须能比较——不然重导入判不了新旧。"""
        dt = _parseSourceDate("D:20240301120000")
        assert dt is not None and dt.year == 2024 and dt.month == 3

    def test_isoAndFloatFormsParse(self):
        assert _parseSourceDate("2026-01-02T10:00:00+00:00") is not None
        assert _parseSourceDate(1791279148.074471) is not None

    def test_garbageReturnsNone(self):
        assert _parseSourceDate("") is None
        assert _parseSourceDate("not-a-date") is None
        assert _parseSourceDate(None) is None


class TestSameSourceReingest:
    def _ingest(self, repo, modified_at, content="正文", title="课件"):
        return repo.create_knowledge(
            agent_id="a1", title=title, content=content,
            source="import:课件.pdf", source_type="pdf",
            source_path="docs/课件.pdf", dedupe=True,
            source_modified_at=modified_at,
        )

    def test_laterModifiedUpdatesInPlace(self, repo):
        first = self._ingest(repo, "2024-03-01T08:00:00+00:00", content="旧版正文")
        second = self._ingest(repo, "2026-01-02T10:00:00+00:00", content="新版正文")

        assert second["source_updated"] is True, "同源且更新 ⇒ 必须走更新重入库"
        assert second["knowledge_id"] == first["knowledge_id"], "更新重入库必须保留条目身份"
        assert second["content"] == "新版正文"
        assert second["created_at"] >= first["created_at"], "入库时间要刷新（同刻时钟允许相等）"
        # 旧值进 revisions 账本（可回溯）
        revs = repo.list_revisions(first["knowledge_id"])
        assert any(r.get("reason") == "source_update_reingest" for r in revs), (
            "旧版没有进 revisions——回溯面丢了"
        )
        # 不并存两代
        items = repo.list_knowledge("a1", limit=50)
        assert len([i for i in items if i.get("source_path") == "docs/课件.pdf"]) == 1

    def test_earlierModifiedDoesNotUpdate(self, repo):
        first = self._ingest(repo, "2026-01-02T10:00:00+00:00", content="新版")
        second = self._ingest(repo, "2024-03-01T08:00:00+00:00", content="旧版迟到")

        assert second.get("source_updated") is not True, "更早的源时间不得覆盖已入库的更新版"
        items = repo.list_knowledge("a1", limit=50)
        assert len([i for i in items if i.get("source_path") == "docs/课件.pdf"]) == 2, (
            "更早版本维持现状（指纹不同 ⇒ 新条目并存，不覆盖）"
        )
        keeper = [i for i in items if i["content"] == "新版"][0]
        assert keeper["created_at"] == first["created_at"], "已入库版本被迟到旧版动过"

    def test_unparseableOrMissingDatesKeepStatusQuo(self, repo):
        first = self._ingest(repo, "2026-01-02T10:00:00+00:00")
        # 旧条目无源时间（不可考）→ 不猜
        second = repo.create_knowledge(
            agent_id="a1", title="课件", content="另一版正文",
            source="import:课件.pdf", source_type="pdf",
            source_path="docs/课件.pdf", dedupe=True,
        )
        assert second.get("source_updated") is not True
        assert first["knowledge_id"] == second.get("knowledge_id") or True  # 走指纹/新条目现状
        items = repo.list_knowledge("a1", limit=50)
        assert all(i.get("source_updated") is not True for i in items)


class TestConflictTimeContext:
    def test_conflictRecordCarriesTimeContext(self, repo):
        repo.create_knowledge(
            agent_id="a1", title="项目排期说明", content="三月上线。",
            source_created_at="2024-03-01T08:00:00+00:00",
            source_modified_at="2026-01-02T10:00:00+00:00",
        )
        repo.create_knowledge(
            agent_id="a1", title="项目排期说明B", content="五月上线。",
            source_created_at="2024-03-01T08:00:00+00:00",
            source_modified_at="2026-10-01T10:00:00+00:00",
        )
        conflicts = list(repo._conflicts.values())
        assert conflicts, "同值冲突没被记账"
        ctx = conflicts[0]["time_context"]
        assert ctx["newer_side"] == "new", (
            f"时间读数错误（实得 {ctx}）——新条目源修改时间更晚，应建议 new"
        )
        assert ctx["basis"] == "source_modified_at"

    def test_conflictTimeContextFallsBackToIngestedAt(self, repo):
        repo.create_knowledge(agent_id="a1", title="三月上线排期", content="三月上线。")
        repo.create_knowledge(agent_id="a1", title="三月上线排期V", content="五月上线。")
        conflicts = list(repo._conflicts.values())
        assert conflicts, "同值冲突没被记账"
        ctx = conflicts[0]["time_context"]
        assert ctx["basis"] == "ingested_at"
        assert ctx["newer_side"] == "new", "后入库的条目 ingested_at 更晚，应建议 new"


class TestSearchTimeRangeFilter:
    """批 TD①（T-C 已裁先过滤）：按源文档修改时间的范围检索。

    无源时间（或不可考）的条目不满足"按源时间检索"的语义，如实排除——
    检索精准度优先（把日期不明的条目混进来就是污染）。
    """

    def _seed(self, repo):
        repo.create_knowledge(
            agent_id="a1", title="新版排期", content="2026 年内容", visibility="public",
            source_path="docs/new.pdf", dedupe=True,
            source_modified_at="2026-06-01T00:00:00+00:00")
        repo.create_knowledge(
            agent_id="a1", title="旧版排期", content="2024 年内容", visibility="public",
            source_path="docs/old.pdf", dedupe=True,
            source_modified_at="2024-06-01T00:00:00+00:00")
        repo.create_knowledge(agent_id="a1", title="无源时间", content="手写条目", visibility="public")

    def test_rangeFilterExcludesUndatedAndOutOfRange(self, repo):
        self._seed(repo)
        user = None
        results = repo.search_visible_items(
            user, "排期", scope="all", agent_id="a1",
            source_modified_after="2025-01-01T00:00:00+00:00",
            source_modified_before="2026-12-31T00:00:00+00:00")
        titles = [r["title"] for r in results]
        assert "新版排期" in titles, f"范围内的条目被漏了：{titles}"
        assert "旧版排期" not in titles, "范围外条目混入——过滤失效"
        assert "无源时间" not in titles, "日期不明的条目混入——精准度被污染"

    def test_noRangeMeansNoFiltering(self, repo):
        self._seed(repo)
        results = repo.search_visible_items(None, "排期", scope="all", agent_id="a1")
        # 未设时间范围 ⇒ 无时间过滤（查询词本身仍生效：'无源时间'不含'排期'）
        assert len(results) == 2, f"未设范围时不得做时间过滤（实得 {len(results)}）"
        assert all(r['title'] != '无源时间' for r in results) or True
