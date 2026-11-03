"""跨进程分片失效：另一进程写了／擦了，本进程下一次取数必须看见（§6-504，取向＝读盘版本号）。

病灶（§6-476 仍开①登记的那条边界）：`vector_index._load_user` 只在 uid 不在 `_cache` 时读盘，
此后同进程再不重读。单进程内这没问题；**多进程部署下**（后端一个进程、CLI/worker 另一个进程），
另一个进程改了分片文件——包括 `dropEntry` 的当场擦除——本进程的 `records` 与 ANN handle
照样命中旧缓存。违规内容在盘上已经被擦掉了，读侧却还能检索到它。

修法按 §6-501 裁定的取向落地：写入方在分片旁落一个**极小的版本文件**（`计数 空格 内容指纹`），
取数方在命中缓存之前先读它比对；对不上（或读不出来）就重读分片。分片内容本身一个字没改口径，
`_recordVersions` 也仍然只有一份——盘上的计数直接接管它，ANN handle 因此自动作废重建。

为什么不用 mtime：同秒内的两次改动 mtime 可以完全一样，时钟回拨还会把新判成旧；
为什么不只认计数：两个进程都读到 N、都写 N+1，只认计数就会把第二个进程的改动读成"没变"——
所以版本文件带内容指纹，**任何真实内容变化都必然换指纹**，与写者的调度无关。

判据面全部走**在役入口**（两个索引实例共享一个分片目录，就是两个进程），
不 reference 任何新符号：实现怎么改都行，读数必须一样。
"""

import json
from pathlib import Path

import pytest

from neurova.knowledge.vector_index import KnowledgeVectorIndex

USER = {"user_id": "7", "username": "k", "role": "user", "neuser_id": "7"}


class _StubEngine:
    """确定性 embedding 桩：固定词表 one-hot（与 integration 那族同一形状，不引真实 ONNX）。"""

    VOCAB = ["quantum", "rust", "async", "cookie"]

    def encode(self, text):
        t = (text or "").lower()
        return [1.0 if w in t else 0.0 for w in self.VOCAB]


class _StubRepo:
    """知识仓库的最小面：索引只调 `visible_items(user)`。"""

    def __init__(self, entries):
        self._entries = list(entries)

    def visible_items(self, user):
        return [dict(e) for e in self._entries]


def _entry(kid, title, content):
    return {"knowledge_id": kid, "title": title, "content": content}


@pytest.fixture()
def shardDir(tmp_path):
    # storage_fence 不许写生产目录，测试落点一律走 tmp_path
    return str(tmp_path / "kb" / "vec")


def _index(shardDir):
    return KnowledgeVectorIndex(shardDir, engine=_StubEngine(), annBackend=None)


def test_anotherProcessWriteShowsUpOnNextRead(shardDir):
    """A 读过一次后 B 写入新条目 ⇒ A 下一次检索必须看得见（今天看不见＝本格红）。"""
    a, b = _index(shardDir), _index(shardDir)
    a.ensure_indexed(_StubRepo([_entry("k1", "Quantum", "quantum explained")]), USER)
    assert [h["id"] for h in a.search("quantum", USER)] == ["k1"], "前置：A 已把分片读进缓存"

    b.ensure_indexed(_StubRepo([
        _entry("k1", "Quantum", "quantum explained"),
        _entry("k2", "Rust", "rust async guide"),
    ]), USER)

    hits = a.search("rust", USER)
    assert [h["id"] for h in hits] == ["k2"], (
        f"另一进程写入的条目在 A 这边不可见（缓存不失效）：{hits}")


def test_anotherProcessEraseIsNotStillSearchable(shardDir):
    """擦除的即时性：B 把条目从盘上擦掉 ⇒ A 不得再把它作为命中返回。"""
    a, b = _index(shardDir), _index(shardDir)
    repo = _StubRepo([_entry("k1", "Quantum", "quantum explained")])
    a.ensure_indexed(repo, USER)
    assert a.search("quantum", USER), "前置：A 已检索得到"

    erased = b.dropEntry("k1")
    assert erased["files"] >= 1, f"盘上没擦掉：{erased}"

    assert a.search("quantum", USER) == [], (
        "分片文件里的正文副本已被擦除，A 仍按旧缓存返回命中——违规内容清理在跨进程下不成立")


def test_unchangedShardIsNotReparsed(shardDir, monkeypatch):
    """便宜的比对要真便宜：分片没变时，第二次数只读版本文件，不再解析分片 JSON。

    反向钉的是"用重读全盘换正确性"这种修法——那会把 §6-473/§6-476 一路省下来的
    增量同步收益整段吃掉（docstring 里 ANN 版本那段就是为了不做全量扫描）。
    """
    from neurova.knowledge import vector_index as vi

    counter = {"loads": 0}
    realLoads = json.loads

    class _CountingJson:
        loads = staticmethod(lambda s: counter.__setitem__("loads", counter["loads"] + 1) or realLoads(s))
        dumps = staticmethod(json.dumps)

    writer = _index(shardDir)
    writer.ensure_indexed(_StubRepo([_entry("k1", "Quantum", "quantum explained")]), USER)

    # 换一个没读过这份分片的实例来打基准：`ensure_indexed` 自己会写盘但不解析旧文件，
    # 在写者身上数"第一次读盘"会把基准数成 0（我第一版就踩在这里）。
    monkeypatch.setattr(vi, "json", _CountingJson)
    reader = _index(shardDir)
    reader.search("quantum", USER)
    first = counter["loads"]
    reader.search("quantum", USER)
    second = counter["loads"]

    assert first >= 1, (
        "冷启动取数连分片 JSON 都没解析——本格失去了基准（不是『优化到位』）")
    assert second == first, (
        f"分片一个字没变，第二次数仍解析了 {second - first} 次 JSON ⇒ 版本比对没起作用")


def test_shardWithoutVersionFileIsNeverServedFromCache(shardDir):
    """读不出版本文件＝**不知道**，不许当成"没变"。

    存量分片（这功能落地之前写的）没有版本文件；若把"读不到"当成"版本相等"，
    那些分片就永远命中旧缓存——正病换个形态留下。
    """
    a, b = _index(shardDir), _index(shardDir)
    a.ensure_indexed(_StubRepo([_entry("k1", "Quantum", "quantum explained")]), USER)

    root = Path(shardDir)
    for sidecar in list(root.glob("*.revision")):
        sidecar.unlink()

    b.ensure_indexed(_StubRepo([_entry("k2", "Rust", "rust async guide")]), USER)
    for sidecar in list(root.glob("*.revision")):
        sidecar.unlink()

    hits = a.search("rust", USER)
    assert [h["id"] for h in hits] == ["k2"], (
        f"版本文件缺失时被当成『没变』，A 仍在吃旧缓存：{hits}")
