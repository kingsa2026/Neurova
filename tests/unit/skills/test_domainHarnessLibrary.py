"""N8：域级 harness 视图只读扩展既有技能库。"""

from neurova.skills.skill_service import (
    SkillService,
    domainHarnessesFrom,
    searchDomainHarnessesFrom,
    skillDomainOf,
)


def _info(domain="legal", version="1.1.0", body="BODY", revisions=None):
    return {
        "name": "peer",
        "version": version,
        "description": "peer skill",
        "manifest": {
            "config": {
                "category": domain,
                "context_template": body,
                "revisions": revisions or [],
            }
        },
    }


def test_skill_domain_prefers_category_then_tags():
    assert skillDomainOf(_info("legal")) == "legal"
    assert skillDomainOf({"manifest": {"tags": ["finance"]}}) == "finance"
    assert skillDomainOf({}) == "general"


def test_domain_harnesses_only_adopted_and_excludes_current():
    infos = [
        ("peer", _info("legal", version="1.2.0", body="PEER")),
        ("base", _info("legal", version="1.0.0", body="BASE")),
        ("other", _info("finance", version="1.2.0", body="OTHER")),
    ]
    got = domainHarnessesFrom(infos, "legal", exclude_skill_id="peer")
    assert got == []

    got = domainHarnessesFrom(infos, "legal")
    assert [item["skill_id"] for item in got] == ["peer"]
    assert got[0]["context_template"] == "PEER"


def test_cross_domain_search_ranks_and_filters():
    legal = _info("legal", version="1.2.0", body="合同审查 harness")
    finance = _info("finance", version="1.3.0", body="财报分析 harness")
    infos = [("legal-skill", legal), ("finance-skill", finance)]

    hits = searchDomainHarnessesFrom(infos, "财报")
    assert [item["skill_id"] for item in hits] == ["finance-skill"]
    assert hits[0]["score"] > 0

    legal_only = searchDomainHarnessesFrom(infos, "harness", domain="legal")
    assert [item["skill_id"] for item in legal_only] == ["legal-skill"]

    empty = searchDomainHarnessesFrom(infos, "")
    assert {item["skill_id"] for item in empty} == {"legal-skill", "finance-skill"}


def test_service_exposes_domain_view(tmp_path):
    svc = SkillService(agent_id="n8", skills_dir=str(tmp_path / "skills"))
    svc._skills["peer"] = _info("legal", version="1.2.0", body="PEER")

    assert svc.skillDomain("peer") == "legal"
    got = svc.listDomainHarnesses("legal")
    assert got and got[0]["skill_id"] == "peer"
