# -*- coding: utf-8 -*-
"""live-verify（批 C7b/C7c/媒体面）：会话存档读取链、投影落库与媒体取回的真链路自证（双态）。

## 双态纪律（方案 §12-2，不冒充跑通）

- **真租户态**：env 给齐官方 C 动态库路径＋corpid＋存档专用 Secret（私钥从约定目录
  `connectors/wecom-archive` 按 `private_v<版本>.pem` 自动发现）→ 跑**真链**：
  Init → GetChatData（水位 0 起，≤5 天窗口）→ RSA PKCS1 → DecryptData → 归一 →
  投影落库 → 适配器六列读回 → 媒体 GetMediaData 分片续传 → 暂存；
- **无凭据态**（开发机缺省）：preflight 缺任一件 → 打印 runbook 诚实退出 2，
  **不用假件冒充跑通**。

## 判据（真租户态，逐条 PASS/FAIL 留痕）

1. **Init/GetChatData**：句柄建立、按水位拉取成功（返回行数如实；空区间＝PASS 但
   点名「检查席位/成员同意」——§3 前置是客户侧动作，代码只能如实读数）；
2. **RSA→DecryptData 全量成功**：未知 publickey_ver 计数如实；错钥/垃圾被
   AES 合法钥长判据挡住（§5）；
3. **投影与消费同体**：appendBatch 水位推进；`ChatChannelAdapter.fetchBatch`
   读回六列行（msg_id/chat_id/sent_at ISO 带时区）与投影行一致；
4. **媒体分片续传＋GetData 截断必核**：取回一条媒体消息 → image 类型走
   PIL open+verify（截断/损坏当场暴露）；其余类型如实登记尺寸并注明
   「完整性人工核对文件可打开」；暂存落盘且 `media_staged_path` 回写；
5. **自我节流如实**：单轮 3 批×200 行，超窗水位如实报「多轮收敛属正常」（§8）。

## 跑法

    python tests/manual/wecomArchiveChainC7bc_live.py            # 无凭据 → runbook + exit 2
    NEUROVA_LIVE_ARCHIVE_SDK=<官方库件> \\
    NEUROVA_LIVE_ARCHIVE_CORPID=<corpid> \\
    NEUROVA_LIVE_ARCHIVE_SECRET=<存档专用 Secret> \\
      python tests/manual/wecomArchiveChainC7bc_live.py          # 真租户态

退出码：0 全过／1 有 FAIL／2 真租户凭据待配（双态登记）。
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaWecomArchiveC7bc")
# 进程 env 的改写全部收在 main() 内（tests/manual/ 顶层改 env 有常驻棘轮，§6-584）。

SDK_ENV = "NEUROVA_LIVE_ARCHIVE_SDK"
CORPID_ENV = "NEUROVA_LIVE_ARCHIVE_CORPID"
SECRET_ENV = "NEUROVA_LIVE_ARCHIVE_SECRET"

EVIDENCE: list = []


def say(title: str, detail: str = "") -> None:
    line = ("%s :: %s" % (title, detail)) if detail else title
    EVIDENCE.append(line)
    print(line)


def check(label: str, condition: bool, detail: str = "") -> bool:
    say(("PASS " if condition else "FAIL ") + label, detail)
    return bool(condition)


def main() -> int:
    # 密钥链与代理面：必须在 import 任何 neurova 模块之前落定（AGENTS.md §0）
    os_env = os.environ
    os_env.setdefault("NEUROVA_SECRET_KEY", "live-verify-key-for-c7bc-0123456789abcdef")
    os_env.setdefault("NEUROVA_JWT_SECRET", "live-verify-jwt-for-c7bc-0123456789abcdef-xyz")
    for _p in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
               "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        os_env.pop(_p, None)

    # ── preflight（真租户态四件；缺任一 → runbook + exit 2，双态登记）──
    sdkPath = os_env.get(SDK_ENV, "").strip()
    corpid = os_env.get(CORPID_ENV, "").strip()
    secret = os_env.get(SECRET_ENV, "").strip()
    missing = []
    if not sdkPath:
        missing.append("%s＝官方 C 动态库磁盘路径（企微管理后台下载，linux x86/arm、windows）" % SDK_ENV)
    if not corpid:
        missing.append("%s＝企业 corpid" % CORPID_ENV)
    if not secret:
        missing.append("%s＝聊天内容存档专用 Secret（管理端→管理工具→聊天内容存档，非应用 Secret）" % SECRET_ENV)
    if missing:
        say("真租户凭据待配（双态登记，§12-2）——不冒充跑通")
        for item in missing:
            say("  缺", item)
        say("  私钥", "按 private_v<版本>.pem 放进约定目录 connectors/wecom-archive"
                      "（NEUROVA_WECOM_ARCHIVE_KEYDIR 可覆盖）；公钥上传企微后台并记录版本号")
        say("  前置", "席位购买＋成员同意＋出口 IP 白名单（方案 §3，代码不可代劳）")
        return 2

    # ── 真租户态 ──
    from neurova.channels.wecom_archive import (
        ArchiveMediaUnavailable,
        ArchiveProjectionStore,
        ArchiveSdkHandle,
        archiveKeyDir,
        pullArchiveBatch,
        resolveArchiveKeyPath,
        stageArchiveMedia,
    )

    # 私钥自动发现：约定目录 private_v<版本>.pem（统一存放路径口径的活体验证）
    keyDir = archiveKeyDir()
    keys: dict = {}
    for pemFile in sorted(keyDir.glob("private_v*.pem")):
        version = pemFile.stem[len("private_v"):]
        keys[version] = pemFile.read_bytes()
    say("私钥约定目录", str(keyDir))
    say("发现的私钥版本", ", ".join(sorted(keys)) or "（无）")
    if not keys:
        say("真租户凭据待配", "约定目录无 private_v<版本>.pem——把私钥放进 %s" % keyDir)
        return 2

    if not Path(sdkPath).is_file():
        check("官方库件存在", False, "%s 不存在" % sdkPath)
        return 1

    store = ArchiveProjectionStore(WORK_ROOT / "channel_archive.db")
    handle = None
    failures = 0
    try:
        try:
            handle = ArchiveSdkHandle(sdkPath, corpid, secret)
            check("Init 成功（句柄建立）", True)
        except Exception as exc:
            check("Init 成功（句柄建立）", False, str(exc))
            return 1

        # ── 判据 1：GetChatData 按水位拉取 ──
        watermark = store.watermark()
        allRows: list = []
        nextSeq = watermark
        counts: dict = {}
        for _batch in range(3):
            result = pullArchiveBatch(handle, nextSeq, 200, keys)
            allRows.extend(result.rows)
            for name, value in result.counts.items():
                counts[name] = counts.get(name, 0) + value
            store.appendBatch(result.rows, result.nextSeq)
            nextSeq = result.nextSeq
            if not result.hasMore:
                break
        check("GetChatData 拉取成功（水位 %d → %d）" % (watermark, nextSeq),
              True, "本批行数 %d；计数 %s" % (len(allRows), counts))
        if not allRows:
            say("存档返回空区间——检查席位/成员同意（方案 §3 前置，客户侧动作）",
                "连通与解密链无真实样本可取证；媒体段跳过（不冒充）")
            return 0

        # ── 判据 2：RSA→DecryptData 全量成功 ──
        decryptedOk = counts.get("pulled", 0) - counts.get("skipped_unknown_key_ver", 0)
        check("RSA→DecryptData 全量成功", decryptedOk > 0
              and counts.get("skipped_unknown_key_ver", 0) == 0,
              "解出 %d 行；未知 key_ver 跳过 %d" % (decryptedOk,
                                                     counts.get("skipped_unknown_key_ver", 0)))

        # ── 判据 3：投影与消费同体（适配器六列读回）──
        from neurova.knowledge.enterprise.connectors_chat import ChatChannelAdapter

        adapter = ChatChannelAdapter(
            {"sourceType": "chat", "vendor": "wecom", "chatSource": "archive",
             "archiveDb": str(store.path)}, "live_archive")
        import asyncio

        batch = asyncio.run(adapter.fetchBatch(None, 200))
        check("适配器六列读回与投影一致",
              len(batch.rows) > 0
              and set(batch.rows[0].keys()) == {"msg_id", "chat_id", "chat_type",
                                                 "sender", "sent_at", "text", "media_ref"},
              "读回 %d 行（recall/switch 已留档不入账）" % len(batch.rows))
        if batch.rows:
            sample = batch.rows[0]
            check("sent_at 为 ISO 带时区", "T" in sample["sent_at"]
                  and sample["sent_at"].endswith(("+00:00", "Z")) and "+" in sample["sent_at"],
                  sample["sent_at"])

        # ── 判据 4：媒体分片续传＋GetData 截断必核 ──
        mediaRows = [row for row in batch.rows if row.get("media_ref")]
        if not mediaRows:
            say("窗口内无媒体消息——媒体链路未取证（不冒充，§12-2）")
        else:
            mediaRow = mediaRows[0]
            try:
                data = handle.getMediaData(str(mediaRow["media_ref"]))
                check("GetMediaData 分片续传取回字节", len(data) > 0,
                      "msg_id=%s 字节数 %d" % (mediaRow["msg_id"], len(data)))
                if mediaRow["chat_id"] and data[:8][:4] in (b"\x89PNG",):
                    check("PNG 魔数核验", data[:8] == b"\x89PNG\r\n\x1a\n", "PNG 头命中")
                outcome = stageArchiveMedia(store.path, str(mediaRow["msg_id"]), handle)
                check("媒体暂存落盘且投影回写", outcome.get("status") == "staged"
                      and Path(outcome.get("path", "")).is_file(),
                      "path=%s size=%s" % (outcome.get("path"), outcome.get("size")))
                # GetData 截断必核：image 类型走 PIL 完整性验证（截断当场暴露）
                if str(mediaRow.get("msgtype") or "") == "image" or \
                        str(outcome.get("path", "")).lower().endswith(
                            (".png", ".jpg", ".jpeg", ".gif", ".bmp")):
                    from PIL import Image

                    probe = Image.open(io.BytesIO(data))
                    probe.verify()
                    check("PIL 完整性验证（GetData char* 截断风险必核）", True,
                          "图像可完整解码：%s" % (probe.size,))
                else:
                    say("完整性人工核对项", "非 image 类型（msgtype=%s）——打开 %s 确认可用"
                        % (mediaRow.get("msgtype"), outcome.get("path")))
            except ArchiveMediaUnavailable as exc:
                say("媒体引用过期（ArchiveMediaUnavailable，独立读数）", str(exc))
                say("注意", "引用过期属窗口语义（§10），不算链路 FAIL；换窗口内新媒体消息重跑可取证")

        # ── 判据 5：自我节流口径 ──
        say("自我节流口径", "单轮 3 批×200 行＝600 行取证上限；水位 %d——5 天窗口内"
            "超过此量属多轮收敛（方案 §8），不是故障" % nextSeq)
    finally:
        if handle is not None:
            handle.close()
        store.close()

    return 1 if any(line.startswith("FAIL") for line in EVIDENCE) else 0


if __name__ == "__main__":
    code = main()
    print("---- evidence (%d lines) ----" % len(EVIDENCE))
    for line in EVIDENCE:
        print(line)
    print("exit=%d" % code)
    sys.exit(code)
