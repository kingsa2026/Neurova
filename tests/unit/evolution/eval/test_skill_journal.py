"""P2-11 候选即 commit — 技能正文 git 日志仓的红灯测试。

per-agent 独立 bare 仓（data/ 不受主仓跟踪，不能依赖主仓）；decide
approve 一 proposal 一 commit；git 缺失/失败诚实降级（返回 None 不阻断
审批主链）；本地操作、无远端配置（防误推）。
"""

import json

import pytest

from neurova.evolution.eval.skill_journal import SkillJournal


def _pending(tmp_path, pid="evo_x1", skill_id="s1"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "proposals.json").write_text(json.dumps([{
        "proposal_id": pid, "agent_id": "a1", "skill_id": skill_id,
        "artifact_type": "template", "baseline_text": "旧正文",
        "improved_text": "新正文v1", "status": "pending",
        "holdout_before": 0.2, "holdout_after": 0.9,
        "heldout_improvement": 0.05, "iterations_run": 2,
        "created_at": "", "decided_at": "",
    }]), encoding="utf-8")


class TestJournalUnit:
    def test_append_creates_commit(self, tmp_path):
        journal = SkillJournal(tmp_path / "journal.git")
        commit = journal.append(skill_id="s1", before="旧正文", after="新正文v1",
                                proposal_id="evo_x1",
                                evidence={"holdout_improvement": 0.7})
        assert commit
        items = journal.history("s1")
        assert len(items) == 1
        assert items[0]["proposal_id"] == "evo_x1"
        # 正文 blob 与 after 一致（cat-file 读回）
        assert items[0]["content"] == "新正文v1"

    def test_two_approves_two_commits_newest_first(self, tmp_path):
        journal = SkillJournal(tmp_path / "journal.git")
        journal.append(skill_id="s1", before="旧", after="v1",
                       proposal_id="evo_a", evidence={})
        journal.append(skill_id="s1", before="v1", after="v2",
                       proposal_id="evo_b", evidence={})
        items = journal.history("s1")
        assert [i["proposal_id"] for i in items] == ["evo_b", "evo_a"]

    def test_per_skill_isolation(self, tmp_path):
        journal = SkillJournal(tmp_path / "journal.git")
        journal.append(skill_id="s1", before="a", after="b",
                       proposal_id="evo_a", evidence={})
        journal.append(skill_id="s2", before="c", after="d",
                       proposal_id="evo_b", evidence={})
        assert [i["proposal_id"] for i in journal.history("s1")] == ["evo_a"]
        assert [i["proposal_id"] for i in journal.history("s2")] == ["evo_b"]

    def test_git_failure_degrades_honestly(self, tmp_path, monkeypatch):
        """git 调用失败 → append 返回 None 不抛异常（审批主链不受损）。"""
        journal = SkillJournal(tmp_path / "journal.git")

        def _boom(*args, **kwargs):
            raise RuntimeError("git not found")

        monkeypatch.setattr(journal, "_git", _boom)
        result = journal.append(skill_id="s1", before="a", after="b",
                                proposal_id="evo_a", evidence={})
        assert result is None
        assert journal.history("s1") == []

    def test_journal_is_bare_and_local(self, tmp_path):
        """bare 仓、无远端配置——防误推、防误挂主仓工作树。"""
        import subprocess

        journal = SkillJournal(tmp_path / "journal.git")
        journal.append(skill_id="s1", before="a", after="b",
                       proposal_id="evo_a", evidence={})
        cfg = subprocess.run(
            ["git", "--git-dir", str(tmp_path / "journal.git"), "config", "--local", "--list"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert "bare=true" in cfg.stdout.replace(" ", "")
        assert "remote." not in cfg.stdout


class TestDecideHook:
    @pytest.fixture
    def svc(self, tmp_path, monkeypatch):
        import neurova.skills.skill_service as ss
        from neurova.evolution.eval.service import SkillEvolutionService

        monkeypatch.setattr(
            ss.SkillService, "get_skill_info",
            lambda self, sid: {"manifest": {"config": {"context_template": "旧正文"}}},
        )
        monkeypatch.setattr(ss.SkillService, "update_auto_skill", lambda self, *a, **kw: True)
        _pending(tmp_path / "evo")
        return SkillEvolutionService("a1", base_dir=tmp_path / "evo")

    def test_approve_appends_journal(self, svc, tmp_path):
        ok = svc.decide("evo_x1", approve=True)
        assert ok
        items = SkillJournal(tmp_path / "evo" / "journal.git").history("s1")
        assert len(items) == 1
        assert items[0]["proposal_id"] == "evo_x1"
        assert items[0]["content"] == "新正文v1"
        assert items[0]["evidence"].get("holdout_after") == pytest.approx(0.9)

    def test_reject_appends_nothing(self, svc, tmp_path):
        assert svc.decide("evo_x1", approve=False)
        assert SkillJournal(tmp_path / "evo" / "journal.git").history("s1") == []
