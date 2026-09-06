"""认知三链路巡检 P2 防回归：EKB 中文相似度分词与阈值门。

根因：find_similar_experiences 用 str.split() 分词——中文整句成单 token，
子串匹配几乎必失配 keyword/topic 恒 0；而成功记录保底 0.1*1=0.1>0 过
similarity>0 阈值 → 任意查询恒"命中"3 条无关经验，[经验] 注入长期为噪声。
"""
import pytest

from neurova.skills.experience_knowledge_base import (
    ExperienceKnowledgeBase,
    ExperienceRecord,
)


@pytest.fixture
def ekb(tmp_path):
    db = ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))
    for text, agent in [
        ("怎么用Playwright抓取网页数据", "default"),
        ("Python FastAPI 如何定义路由", "default"),
        ("帮我查询北京明天的天气", "default"),
    ]:
        rec = ExperienceRecord(
            skill_name="chat",
            context={"user_input": text},
            result={"reply_excerpt": "r"},
            success=True,
        )
        db.add_experience_record(skill_name="chat", exp=rec, agent_id=agent)
    return db


def test_chinese_query_rankings_are_discriminative(ekb):
    """含实词重叠的查询应排在前，无关查询不得恒命中同批无关记录。"""
    # 相关查询：与"抓取网页"条目共享实词
    hits = ekb.find_similar_experiences(
        context={"user_input": "用Playwright抓取网页"}, limit=3, agent_id="default"
    )
    assert hits, "中文实词重叠应有命中"
    assert "抓取" in str(hits[0].get("context", {}).get("user_input", "")), (
        "相似度第一名应是含共享实词的记录（中文分词生效）"
    )


def test_unrelated_query_excludes_low_overlap_records(ekb):
    """查询与所有记录无实词重叠时，不应靠成功保底分把无关记录全带出来。"""
    hits = ekb.find_similar_experiences(
        context={"user_input": "量子色动力学的渐近自由"}, limit=3, agent_id="default"
    )
    assert not any(
        h.get("similarity_score", 0) > 0 and "天气" in str(h.get("context", {}).get("user_input", ""))
        for h in hits
    ), "零重叠记录不得凭 success 保底 0.1 分进入命中列表（噪声注入根因）"
