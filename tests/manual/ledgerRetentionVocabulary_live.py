# -*- coding: utf-8 -*-
"""H2-2 · E 条的 live-verify：真 app 起来后，产物保留清理真的认得「成功件」。

跑的真生产对象：真 `create_app()` + `TestClient`（走真 lifespan 的启动/关闭钩子，
`app.py:1153-1158` 那格 `start_retention_bootstrap()` 就是被证的对象）、
真 `POST /api/v1/generation/image`（写侧：成功件直落终态词值）、
真 `persist_media`（全仓唯一产物落盘点）、真 `GenerationTaskLedger`（真 JSON 落盘）、
真 `StudioStore`（真 SQLite，保护面数据源）、真 `GET /api/v1/generation/tasks`（投影面）。
只替两处服务商边界：`protocols.generate_image` 与端点的凭据解析；auth 依赖用
`dependency_overrides` 只替身份（不改业务判定）。

判据（缺一条这条链就是断的）：

1. **成功件被认成终态并清掉**：一条 `succeeded` + 有 `local_path` + 超期 + 无引用的产物，
   经过真 lifespan 的那一轮后**文件已删**——改前 `_TERMINAL=("done","failed")` 认不出
   账本里的 `succeeded`，这一格是 0 删除（§6-78 E 条）；
2. **被 Studio 引用的产物保留**：另一条同为 `succeeded` + 超期，但镜头行 `video_path`
   指着它 → 必须还在（保护面真读真库）；
3. **账本行永不删**，两条都还能查到，且状态仍是单源终态集合里的值；
4. **投影面诚实**：`GET /generation/tasks` 对被删的那条报 `file_missing=true` 且 `url=""`
   （历史面板显示「已过期」），对保留的那条报 `file_missing=false` 且给可访问 url；
5. 全程不写仓内真实 `data/`（指纹前后一致）。

一条命令复现（机器无关串——写死开发机绝对路径会给常驻守卫
`TestNoHardcodedDevMachinePaths` 新增 offender）：
PYTHONPATH="$(git rev-parse --show-toplevel)" NEUROVA_LIVE_WAIT=14 \\
    .venv/Scripts/python.exe tests/manual/ledgerRetentionVocabulary_live.py

**改前对照**：把本脚本原样复制到 HEAD 基线工作树再跑，判据 1 会红在
`deleted=0 / 两个文件都还在`——那正是这条缺陷的读数，不是脚本写错。
"""
from __future__ import annotations

import base64
import hashlib
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

DATA_ROOT = isolatedDataRoot()
REPO_DATA_DIR = PROJECT_ROOT / "data"
OWNER = "u-live"
DAYS = 1
AGE_S = (DAYS + 2) * 86400.0
WAIT_S = float(os.environ.get("NEUROVA_LIVE_WAIT", "14"))


def fingerprintDataDir():
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}:{st.st_size}:{st.st_mtime_ns}")
    digest = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest() if items else "empty"
    return digest, len(items)


def main() -> int:
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.api.endpoints import generation as gen_ep
    from neurova.aigc_studio.store import get_store
    from neurova.llm.generators import protocols, task_ledger as tl
    from neurova.llm.generators.runtime import GENERATION_OUTPUT_DIR

    failures: list[str] = []
    before, nBefore = fingerprintDataDir()

    # 保留开关走真 env（`retention_days()` 调用时读，lifespan 据此决定是否排队）
    os.environ["NEUROVA_GENERATION_RETENTION_DAYS"] = str(DAYS)

    led = tl.get_generation_task_ledger()
    outDir = Path(GENERATION_OUTPUT_DIR)
    outDir.mkdir(parents=True, exist_ok=True)
    payload = base64.b64encode(b"PNGPAYLOAD" * 24).decode()

    async def fakeGenerateImage(creds, prompt, size="1024x1024", n=1,
                                ref_images=None, seed=None, strength=None, **kw):
        return {"images": [f"data:image/png;base64,{payload}"], "ignored_params": []}

    class _Creds:
        model = "live-probe"
        base_url = "https://example.invalid"

    # 只替两处服务商边界：出图与凭据解析。落盘、账本、清理、投影全是真实现。
    protocols.generate_image = fakeGenerateImage
    gen_ep._resolve_generation_creds = lambda *a, **k: _Creds()

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"user_id": OWNER, "role": "admin"}
    written: dict[str, str] = {}
    with TestClient(app) as client:
        # ① 真端点写侧：两条成功件（真 `persist_media` 落盘、真账本记 `succeeded`）
        for tag in ("keep", "purge"):
            r = client.post("/api/v1/generation/image",
                            json={"prompt": f"live-{tag}", "model": "live-probe",
                                  "width": 512, "height": 512, "num_images": 1})
            assert r.status_code == 200, r.text
            path = r.json()["data"]["images"][0]["path"]
            assert Path(path).is_file(), path
            written[tag] = path

        rows = {rec.local_path: rec for rec in led.list() if rec.local_path in written.values()}
        assert set(rows) == set(written.values()), (
            f"账本没记上两条成功件：{sorted(rows)} vs {sorted(written.values())}")
        for tag, rec in sorted(rows.items()):
            assert rec.status in tl.TASK_TERMINAL_STATUSES, rec.status

        # ② 保护面：Studio 真库里一条镜头指着 keep
        store = get_store()
        pid = store.create_project(OWNER, title="E 条活体")["id"]
        ep = store.add_episode(pid, {"number": 1, "title": "e1"})
        sb = store.add_storyboard(ep["id"], {"order": 1, "prompt": "p"})
        store.update_storyboard(sb["id"], {"video_status": "done",
                                           "video_path": written["keep"]})

        # ③ 超期：按账本自己的字段回填（真值真格式，不造第二份状态）
        now = time.time()
        for rec in rows.values():
            rec.updated_at = now - AGE_S
            rec.submitted_at = now - AGE_S
            led.add(rec)

        keptPath = Path(written["keep"])
        purgedPath = Path(written["purge"])

        # ④ 真 lifespan：bootstrap 排队 → 一轮真清理
        deadline = time.time() + WAIT_S
        while time.time() < deadline and purgedPath.exists():
            time.sleep(0.5)

        r = client.get("/api/v1/generation/tasks")
        assert r.status_code == 200, r.text
        tasks = {t["task_id"]: t for t in r.json()["data"]["tasks"]}

    readings = []
    if purgedPath.exists():
        readings.append(f"成功件没被清掉（{purgedPath.name} 仍在盘）——"
                        "读侧认不出写侧的词值，清理逻辑整轮空转")
    if not keptPath.exists():
        readings.append(f"被 Studio 引用的产物被删了（{keptPath.name}）——保护面失效")
    for rec in rows.values():
        if led.get(rec.task_id) is None:
            readings.append(f"账本行被删（{rec.prompt}）")
        elif led.get(rec.task_id).status not in tl.TASK_TERMINAL_STATUSES:
            readings.append(f"{rec.prompt} 的状态不在单源终态集合")
    byTag = {rec.prompt.replace("live-", ""): rec for rec in rows.values()}
    for tag, expectMissing in (("keep", False), ("purge", True)):
        rec = byTag[tag]
        row = tasks.get(rec.task_id)
        if row is None:
            readings.append(f"{tag} 条没出现在 /generation/tasks")
            continue
        if bool(row["file_missing"]) is not expectMissing:
            readings.append(f"{tag} 投影 file_missing={row['file_missing']}，期望 {expectMissing}")
        if expectMissing and row["url"].startswith("/api/v1/generation/files/"):
            readings.append(f"{tag} 已过期却仍回本地产物链接（文件已删，必 404）")
        if not expectMissing and not row["url"].startswith("/api/v1/generation/files/"):
            readings.append(f"{tag} 产物在盘却不给可访问的本地链接：{row['url'][:60]!r}")

    after, nAfter = fingerprintDataDir()
    keepRow = tasks.get(byTag["keep"].task_id, {})
    purgeRow = tasks.get(byTag["purge"].task_id, {})
    print(f"清理读数：kept={'在盘' if keptPath.exists() else '已删'} "
          f"purged={'在盘' if purgedPath.exists() else '已删'} "
          f"账本行={len(led.list())} 条 保留天数={DAYS} 回填龄={AGE_S / 86400:.1f} 天")
    print(f"投影读数：kept file_missing={keepRow.get('file_missing')} url={bool(keepRow.get('url'))} / "
          f"purged file_missing={purgeRow.get('file_missing')} url={bool(purgeRow.get('url'))}")
    print(f"仓内 data/ 指纹：before={before[:12]}({nBefore}) after={after[:12]}({nAfter})")
    if after != before:
        failures.append("仓内 data/ 被写动了")
    failures += readings
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("H2-2 E-LEDGER RETENTION VOCABULARY LIVE VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
