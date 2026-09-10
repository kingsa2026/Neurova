"""C-15 回归测试：AdaptiveToolWeights.update_weight 的落盘必须在锁外执行。

缺陷：update_weight 在外层 RLock 持有期间经 _maybe_persist → save() 同步
write_text 落盘，磁盘 IO 期间所有权重读路径被串行阻塞（save() 自身
"锁内快照、锁外写"的注释只对直接调用 save 的路径成立）。
"""

import threading

from neurova.evolution.closed_loop import AdaptiveToolWeights


def test_update_weight_persists_outside_lock(tmp_path):
    weights = AdaptiveToolWeights()
    weights.attach_persistence(tmp_path / "weights.json", save_interval=0)

    observed = {}
    original_save = weights.save

    def probe_save(path=None):
        # 落盘瞬间从另一线程尝试拿锁：锁外落盘 → 立即成功；
        # 锁内落盘（缺陷行为）→ 1s 内拿不到
        def try_lock():
            acquired = weights._lock.acquire(timeout=1.0)
            if acquired:
                weights._lock.release()
            observed["other_thread_acquired_during_save"] = acquired

        t = threading.Thread(target=try_lock, daemon=True)
        t.start()
        t.join(timeout=2.0)
        return original_save(path)

    weights.save = probe_save  # _maybe_persist 经 self.save() 命中探针

    weights.update_weight("tool_a", True, latency=0.1)

    assert observed.get("other_thread_acquired_during_save") is True


def test_update_weight_still_persists_and_reloadable(tmp_path):
    weights = AdaptiveToolWeights()
    weights.attach_persistence(tmp_path / "weights.json", save_interval=0)

    weights.update_weight("tool_a", True)
    weights.update_weight("tool_a", False)

    assert (tmp_path / "weights.json").exists()

    reloaded = AdaptiveToolWeights()
    assert reloaded.load(tmp_path / "weights.json") is True
    entry = reloaded.get_weight("tool_a")
    assert entry is not None
    assert entry.success_count == 1
    assert entry.failure_count == 1
