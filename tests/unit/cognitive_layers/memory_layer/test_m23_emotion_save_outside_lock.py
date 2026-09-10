"""M-23 回归测试：set_emotion 不在持锁状态下做 DB IO。

根因：modules/emotion_module.py set_emotion 在 `with self._lock:` 内调用
`self._save_to_db`（sqlite 写持锁），阻塞 get_emotion 等并发读。

修复后契约：锁内只更新内存态（保护计数 + _memory_emotions），
退出锁后落盘；落盘仍发生（持久化语义不变）。
"""

import pytest

from neurova.cognitive_layers.memory_layer.modules.emotion_module import (
    EmotionModule,
    EmotionState,
    EmotionType,
)


@pytest.fixture()
def module(tmp_path):
    db_dir = tmp_path / "m23"
    db_dir.mkdir()
    mod = EmotionModule(db_path=str(db_dir / "emotion.db"))
    mod.init()
    yield mod
    mod.shutdown()


def test_set_emotion_saves_outside_lock(module):
    calls = []

    orig_save = module._save_to_db

    def spy(memory_id, emotion):
        # RLock 同线程可重入，用 _is_owned() 检测落盘瞬间是否持锁
        calls.append(module._lock._is_owned())
        return orig_save(memory_id, emotion)

    module._save_to_db = spy

    emotion = EmotionState(
        primary_emotion=EmotionType.JOY, intensity=0.8, valence=0.7, arousal=0.6
    )
    module.set_emotion("mem-1", emotion)

    assert calls == [False], "set_emotion 在持锁状态下做 DB IO（M-23 未修复）"
    # 内存态已更新
    assert module.get_emotion("mem-1") is emotion
    # 落盘仍发生：重开连接可读到持久化行
    import sqlite3, json

    conn = sqlite3.connect(str(module._db_path))
    try:
        row = conn.execute(
            "SELECT emotion_data FROM memory_emotions WHERE memory_id = ?", ("mem-1",)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "锁外落盘未发生，持久化语义被破坏"
    assert json.loads(row[0])["primary_emotion"] == "joy"
