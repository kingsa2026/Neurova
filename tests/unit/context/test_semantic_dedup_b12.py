# -*- coding: utf-8 -*-
"""B12（billion-context 对照改进项）：语义去重阶段落地（带防漂移四件套）。

设计依据：docs/01-architecture/living_context_pool_design.md §5（多阶段去重
+ 防漂移）与本仓对照报告 B12 决策点。

契约：
1. 默认关（NEUROVA_DEDUP_SEMANTIC=1 显式开启）——语义去重有信息丢失与
   漂移风险，未灰度不得默认改写入行为；
2. 只在**写入期**生效，且只对**同 source** 的近重复（相似度 ≥ 0.95）判重；
3. 防漂移四件套：
   a. 豁免面——高优先级（≥90）/ USER_INPUT / SYSTEM_INSTRUCTION /
      DEVELOPER_INSTRUCTION 永不语义判重；
   b. 零丢失——被判重条目**仍写穿持久台账**（recall_evicted 可召回），
      只是不进常驻；
   c. 还原台账——每次判重记录（双方 hash/相似度/来源），可 restoreDedup
      一键还原入常驻；
   d. fail-open——向量面不可用（探针 None）一律放行（保守）。
4. 读数：retention_stats["dedup"] 面暴露检查数/判重数/还原数/台账规模。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool


def _drop(content: str, source=ContextSource.MEMORY, priority: int = 50) -> ContextInput:
    return ContextInput(source=source, content=content, priority=priority, tokens=50)


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


def _pool(tmp_path=None, **kw) -> ContextPool:
    """带持久台账的池（被判重条目的写穿与召回都要真库）。"""
    ledger = None
    if tmp_path is not None:
        from neurova.context.eviction_ledger_db import EvictionLedgerDB

        ledger = EvictionLedgerDB(
            db_path=str(tmp_path / "dedup-ledger.db"), user_id="u-b12", agent_id="a-b12"
        )
    return ContextPool(user_id="u-b12", agent_id="a-b12", ledger_db=ledger, **kw)


def _patch_probe(pool: ContextPool, similarity: float):
    """确定性探针替身：任意文本对都报给定相似度（打在池的探针缝上）。"""
    pool._semanticProbe = lambda a, b: similarity


class TestSemanticDedupDefaults:
    def test_default_off_admits_near_duplicate(self, monkeypatch, tmp_path):
        """默认关：近重复照常入池（行为与改前一致）。"""
        monkeypatch.delenv("NEUROVA_DEDUP_SEMANTIC", raising=False)
        pool = _pool(tmp_path)
        _patch_probe(pool, 0.99)
        pool.add_context(_drop("固件升级前必须先备份配置，操作步骤如下：一、二、三。"))
        pool.add_context(_drop("固件升级前必须先备份配置，操作步骤如下：一、二、三。呀。"))
        assert pool.resident_count() == 2, "默认关时不得语义判重"

    def test_enabled_dedups_same_source_near_duplicate(self, monkeypatch, tmp_path):
        """开启后：同 source 近重复不入常驻，但落持久台账（零丢失）。"""
        monkeypatch.setenv("NEUROVA_DEDUP_SEMANTIC", "1")
        pool = _pool(tmp_path)
        _patch_probe(pool, 0.97)
        first = _drop("固件升级前必须先备份配置，操作步骤如下：一、二、三。")
        second = _drop("固件升级前必须先备份配置，操作步骤如下：一、二、三。呀。")
        pool.add_context(first)
        pool.add_context(second)
        assert pool.resident_count() == 1, "近重复不得入常驻"
        # 零丢失：被判重条目仍可从持久台账召回
        recalled = pool.recall_evicted(query="呀")
        assert any("呀" in str(getattr(d, "content", "")) for d in recalled), (
            "被判重条目必须写穿台账（可召回）"
        )
        face = pool.get_retention_stats()["dedup"]
        assert face["semantic_dedup_total"] == 1
        assert face["restore_ledger_size"] == 1
        assert face["last_similarity"] == pytest.approx(0.97)


class TestDriftGuards:
    def test_high_priority_incoming_exempt(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_DEDUP_SEMANTIC", "1")
        pool = _pool(tmp_path)
        _patch_probe(pool, 0.99)
        pool.add_context(_drop("普通条目正文，足够长以参与语义判重。", priority=50))
        pool.add_context(_drop("普通条目正文，足够长以参与语义判重。变体。", priority=95))
        assert pool.resident_count() == 2, "高优先级（≥90）入池豁免"

    def test_user_input_source_exempt(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_DEDUP_SEMANTIC", "1")
        pool = _pool(tmp_path)
        _patch_probe(pool, 0.99)
        pool.add_context(_drop("用户说过的话原文，足够长以参与语义判重。", source=ContextSource.USER_INPUT))
        pool.add_context(_drop("用户说过的话原文，足够长以参与语义判重。变体。", source=ContextSource.USER_INPUT))
        assert pool.resident_count() == 2, "USER_INPUT 豁免"

    def test_cross_source_not_deduped(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_DEDUP_SEMANTIC", "1")
        pool = _pool(tmp_path)
        _patch_probe(pool, 0.99)
        pool.add_context(_drop("同一段长正文内容，足够长以参与语义判重。", source=ContextSource.MEMORY))
        pool.add_context(_drop("同一段长正文内容，足够长以参与语义判重。", source=ContextSource.EXPERIENCE))
        assert pool.resident_count() == 2, "跨 source 不判重"

    def test_below_threshold_admitted(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_DEDUP_SEMANTIC", "1")
        pool = _pool(tmp_path)
        _patch_probe(pool, 0.80)  # < 0.95
        pool.add_context(_drop("第一条长正文，足够长以参与语义判重。"))
        pool.add_context(_drop("第二条长正文，足够长以参与语义判重。"))
        assert pool.resident_count() == 2, "低于阈值不判重"

    def test_probe_unavailable_fail_open(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_DEDUP_SEMANTIC", "1")
        pool = _pool(tmp_path)
        pool._semanticProbe = lambda a, b: None  # 向量面不可用
        pool.add_context(_drop("长正文内容一，足够长以参与语义判重。"))
        pool.add_context(_drop("长正文内容二，足够长以参与语义判重。"))
        assert pool.resident_count() == 2, "探针不可用必须 fail-open"


class TestRestoreLedger:
    def test_restore_reinserts_deduped_drop(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_DEDUP_SEMANTIC", "1")
        pool = _pool(tmp_path)
        _patch_probe(pool, 0.97)
        first = _drop("固件升级前必须先备份配置，操作步骤如下：一、二、三。")
        second = _drop("固件升级前必须先备份配置，操作步骤如下：一、二、三。呀。")
        pool.add_context(first)
        pool.add_context(second)
        assert pool.resident_count() == 1

        dropped_hash = pool.get_retention_stats()["dedup"]["restore_ledger"][0]["dropped_hash"]
        ok = pool.restoreDedup(dropped_hash)
        assert ok is True
        assert pool.resident_count() == 2, "还原后应重回常驻"
        assert pool.get_retention_stats()["dedup"]["restores"] == 1

    def test_restore_unknown_hash_is_false(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_DEDUP_SEMANTIC", "1")
        pool = _pool(tmp_path)
        assert pool.restoreDedup("nonexistent") is False
