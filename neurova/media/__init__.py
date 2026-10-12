"""
Media 包 - 媒体存储配置（只剩 `config.py`）

现役只剩 `MediaStorageConfigManager`：媒体存储路径与按 agent 分份的配置读写。它的九项能力
（扩展名白名单 / 日期归档 / sha256 校验位 / 加密 / 压缩 / 保留清理 / 缓存 TTL 与上限 / DB 后端 /
分 agent 配置）在 REST 端点自持那份里**没有对应实现**，且 `protected_tests.txt` 里
`test_runtime_landing_root.py::test_mediaConfigLandsUnderDataRoot` 真构造它断"配置目录不落 CWD"
——因此台账 §6-128 把它判为**需人裁**，不是可径退役的残留。

同包的 `manager.py`（第二份资产索引）已于 §6-139 退役：它生产零消费者，唯一长过端点那份的一格
是**产物 sha256 校验位**，已按甲方案并进入 `api/endpoints/media.py`（写侧随字节流算、索引存
`checksum`，`GET /{media_id}/metadata` 真读盘重算回 `checksum_ok`），连同索引写侧的锁一起补上。
"""

# media imports

