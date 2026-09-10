"""M-19 / M-20 回归测试：肌肉记忆落盘纪律与加载容错。

M-19 根因：record_usage 在 `with self._lock:` 内经 _update_existing_item /
新建路径调用 `_save_all()`（文件 IO 持锁），而 forget 在锁外调用 —— 落盘
位置不一致，持锁写盘会阻塞 match 等高频读路径。
修复后契约：锁内只改状态，退出锁后统一经公开薄包装 `save_all()` 落盘。

M-20 根因：_load_level 一句 dict comprehension 解析整文件，单条坏记录
`except: return {}` → 整层清零（后续 _save_all 落盘即真实丢数据）。
修复后契约：逐条 try/except，坏条目 warning 跳过，好条目保留；
整文件损坏（JSON 解析失败）仍整体放弃并告警。
"""

import json
import threading

import pytest

from neurova.cognitive_layers.memory_layer.muscle_memory import (
    MuscleMemory,
    MuscleMemoryItem,
)


@pytest.fixture()
def mm_dir(tmp_path):
    d = tmp_path / "muscle"
    d.mkdir()
    return d


class TestM19SaveOutsideLock:
    def test_record_usage_saves_outside_lock(self, mm_dir):
        mm = MuscleMemory(storage_path=str(mm_dir))
        violations = []
        orig_save = mm._save_all

        def spy():
            # RLock 同线程可重入，_is_owned() 才能检测当前线程持锁（与
            # test_lock_coverage_m060709.py 的确定性锁契约同口径）
            if mm._lock._is_owned():
                violations.append("save_all called while holding lock")
            return orig_save()

        mm._save_all = spy
        mm.record_usage("toolA", "hello world", {"p": 1}, success=True)
        assert not violations, "record_usage 在持锁状态下落盘（M-19 未修复）"

    def test_public_save_all_wrapper_exists(self, mm_dir):
        mm = MuscleMemory(storage_path=str(mm_dir))
        assert hasattr(type(mm), "save_all"), "缺少公开 save_all() 薄包装"
        mm.record_usage("toolB", "kw one", {}, success=True)
        mm.save_all()  # 应可独立调用
        assert (mm_dir / "muscle_l3.json").exists()

    def test_state_still_persisted_after_usage(self, mm_dir):
        mm = MuscleMemory(storage_path=str(mm_dir))
        mm.record_usage("toolC", "kw two", {}, success=True)
        data = json.loads((mm_dir / "muscle_l3.json").read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["tool_name"] == "toolC"


class TestM20LoadLevelPerItemTolerance:
    def _write(self, mm_dir, payload, name="muscle_l3.json"):
        (mm_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def test_bad_item_skipped_good_item_kept(self, mm_dir):
        good = MuscleMemoryItem(
            id="good1", tool_name="t", query_fingerprint="kw"
        ).to_dict()
        self._write(
            mm_dir,
            [
                good,
                {"id": "bad-missing-fields"},  # 缺 tool_name → from_dict KeyError
                {
                    "id": "bad-level",
                    "tool_name": "x",
                    "query_fingerprint": "y",
                    "level": "bogus-level",  # MemoryLevel 枚举解析失败
                },
            ],
        )
        mm = MuscleMemory(storage_path=str(mm_dir))
        assert "good1" in mm._l3, "单条坏记录导致整层清零（M-20 未修复）"
        assert "bad-missing-fields" not in mm._l3
        assert "bad-level" not in mm._l3

    def test_whole_file_corruption_still_warns_and_yields_empty(self, mm_dir):
        (mm_dir / "muscle_l1.json").write_text("{corrupt json", encoding="utf-8")
        mm = MuscleMemory(storage_path=str(mm_dir))
        assert mm._l1 == {}
