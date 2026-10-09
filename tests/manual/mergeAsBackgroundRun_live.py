# -*- coding: utf-8 -*-
"""导出台成后台 run 的 live-verify：真出片、真停、真不阻塞事件循环。

跑的真生产对象：真 `create_app()` + `TestClient`（真 lifespan）、真
`POST /episodes/{eid}/merge`、真 `_spawn_run` 与 runs 台账、真 `core/task_tracker`
句柄登记、真 `POST /runs/{rid}/cancel`、真 `services.merge_episode` +
`services._ffmpegExportStage`、**真 FFmpeg 二进制**（仓库托管件，经
`NEUROVA_FFMPEG_PATH` 显式指向；不改代码、不下载、不开外网）、真 SQLite、
真 mp4 素材（由同一二进制现生成的 testsrc 片段，非占位字节）。只替 auth 身份。
数据根走 `_liveVerifyIsolation.isolatedDataRoot()`。

七格各自要在真链路上自证一遍：

1. **端点只回 run_id**：改前同步返回整包结果（`composed`/`merge`/`items`），
   导出根本不在台账里；
2. **句柄可达**：导出进行中按 run id 在注册表里找得到 Task——找不到就停不掉；
3. **循环不获阻塞**（本批根因格，§6-93）：导出期间从测试线程打真 HTTP 请求测往返延迟，
   再跑**对照组**——探针进程内临时挂一条路由，在协程里同步调用同一个生产
   `_ffmpegExportStage`（= 改前形态），量同一个数。实验组最大延迟须显著低于对照组；
   对照组自己也必须真卡住（`ctrlMax >= 1s`），否则这个测法分辨不出东西、判据不算过；
4. **终态与成因落 run 行**：`detail_json` 带 `composed`/`mode`/`url`/`merge_id`/`fallback`；
5. **merges 行是真读面**：`GET /merges/{mid}` 取回 items_json 与 output_url（前端新接的读者）；
6. **无就绪产物是失败不是降级**：run 行落 `failed` 且点名成因，merges 表不新增行——
   旧形态回 200 + `ok=False`，前端显示「已输出连播清单」而清单里一条素材都没有；
7. **导出期间叫停**：`cancel` 落 `cancelled`，merges 表不留半截成品记录。

一条命令复现（机器无关串）：
PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/mergeAsBackgroundRun_live.py
"""
from __future__ import annotations

import hashlib
import os
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

DATA_ROOT = isolatedDataRoot()
CLIP_DIR = DATA_ROOT / "mergeclips"
CLIP_DIR.mkdir(parents=True, exist_ok=True)
REPO_DATA_DIR = PROJECT_ROOT / "data"
BASE = "/api/v1/studio"
USER = {"user_id": "u-merge", "role": "admin"}
CLIP_COUNT = 2
CLIP_SECONDS = 15

# 用真二进制，但不让 lifespan 去下载（不开外网、不花钱）
os.environ.setdefault("NEUROVA_FFMPEG_AUTODOWNLOAD", "0")
FFMPEG = ""
for _cand in (REPO_DATA_DIR / "tools" / "ffmpeg" / "ffmpeg.exe",
              REPO_DATA_DIR / "tools" / "ffmpeg" / "ffmpeg"):
    if _cand.is_file():
        FFMPEG = str(_cand)
        break
if not FFMPEG:
    import shutil

    FFMPEG = shutil.which("ffmpeg") or ""
if FFMPEG:
    os.environ["NEUROVA_FFMPEG_PATH"] = FFMPEG


def fingerprintDataDir():
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}:{st.st_size}:{st.st_mtime_ns}")
    digest = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest() if items else "empty"
    return digest, len(items)


def makeClip(outPath: Path, n: int) -> None:
    import subprocess

    cmd = [FFMPEG, "-y", "-f", "lavfi", "-i",
           f"testsrc=size=640x360:rate=25:duration={CLIP_SECONDS}",
           "-f", "lavfi", "-i", f"sine=frequency={300 + n * 90}:duration={CLIP_SECONDS}",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", str(outPath)]
    proc = subprocess.run(cmd, capture_output=True, timeout=300, check=False)
    if proc.returncode != 0 or not outPath.is_file():
        raise RuntimeError(f"素材生成失败({outPath.name}): "
                           + (proc.stderr or b"")[-200:].decode(errors="ignore"))


def pollLoopLatency(client, url, stop: dict, out: list) -> None:
    """在导出占循环期间打真 HTTP 请求，量每次端到端往返秒数。"""
    while not stop["v"]:
        t0 = time.perf_counter()
        r = client.get(url)
        out.append(time.perf_counter() - t0)
        if r.status_code != 200:
            out.append(-1.0)  # 负数=非 200，判据里当失败处理
        time.sleep(0.01)


def waitTerminal(store, rid: str, seconds: float = 240.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        row = store.get_run(rid) or {}
        if row.get("status") in ("done", "done_with_fallback", "failed", "cancelled"):
            return row
        time.sleep(0.05)
    return store.get_run(rid) or {}


def main() -> int:
    import json

    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from neurova.aigc_studio import services
    from neurova.aigc_studio.store import get_store
    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.core.task_tracker import get_task_tracker
    from neurova.llm.generators.runtime import GENERATION_OUTPUT_DIR

    failures = []
    before, nBefore = fingerprintDataDir()
    print(f"FFmpeg 二进制={FFMPEG or '(无)'} 数据根={DATA_ROOT}")

    store = get_store()

    def newEpisode(title: str, withMaterial: bool):
        pid = store.create_project(owner_user_id=USER["user_id"], title=title)["id"]
        eid = store.add_episode(pid, {"number": 1, "title": title,
                                      "content": "客厅夜，两人对峙"})["id"]
        vids = []
        for n in range(1, CLIP_COUNT + 1):
            sb = store.add_storyboard(eid, {"number": n, "image_prompt": f"镜 {n}",
                                            "narration": f"第 {n} 句台词，雨声渐密。"})
            if withMaterial:
                cp = CLIP_DIR / f"{eid}_{n}.mp4"
                makeClip(cp, n)
                store.update_storyboard(sb["id"], {"video_path": str(cp)})
                vids.append(str(cp))
        return pid, eid, vids

    def mergeRowCount(eid: str) -> int:
        return len(store._fetch_all(  # noqa: SLF001 - 探针只读计数，不另开公共读面
            "SELECT id FROM merges WHERE episode_id=?", (eid,)))

    pidE, eidE, _ = newEpisode("空素材导出", False)

    # 对照组（改前形态原样复刻：协程里直接跑阻塞子进程）——探针进程内临时路由，不改仓内代码
    ctrlPid, ctrlEid, ctrlVids = newEpisode("对照组·循环内阻塞", True)
    ctrlRun = store.add_run({"project_id": ctrlPid, "kind": "merge"})
    ctrlOut = GENERATION_OUTPUT_DIR / f"studio_episode_{ctrlEid}.mp4"
    ctrlSrt = CLIP_DIR / f"ctrl_{ctrlEid}.srt"
    ctrlSrt.write_text(services.build_srt(store.list_storyboards(ctrlEid)), encoding="utf-8")
    bgm = CLIP_DIR / "bgm.wav"

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: dict(USER)

    if FFMPEG:
        import subprocess

        subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i",
                        "sine=frequency=220:duration=8", str(bgm)],
                       capture_output=True, timeout=120, check=False)

        async def ctrlExport(request):  # noqa: ARG001 - 探针路由不收参数
            return JSONResponse(services._ffmpegExportStage(
                store, ctrlRun["id"], FFMPEG, ctrlVids, ctrlOut, str(bgm), str(ctrlSrt)))

        app.add_route("/__probe/ctrl-export", ctrlExport, methods=["POST"])

    with TestClient(app) as client:
        # ── 6. 无就绪产物 → failed（不是 200 假清单）────────────────────────
        ridE = client.post(f"{BASE}/episodes/{eidE}/merge", json={}).json()["data"]["run_id"]
        rowE = waitTerminal(store, ridE, 30.0)
        print(f"6 空素材读数：status={rowE.get('status')!r} error={rowE.get('error')!r} "
              f"merges 行新增={mergeRowCount(eidE)}")
        if rowE.get("status") != "failed":
            failures.append(f"无产物导出落 {rowE.get('status')!r}（应 failed）——"
                            "回 200 + ok=False 就是前端那句「已输出连播清单」的假成功")
        if "无就绪产物" not in (rowE.get("error") or ""):
            failures.append(f"失败成因没点名：{rowE.get('error')!r}")
        if mergeRowCount(eidE) != 0:
            failures.append("无产物却往 merges 表写了行")

        if not FFMPEG:
            if failures:
                for f in failures:
                    print("FAIL:", f)
                return 1
            print("SKIP：本机无可执行 FFmpeg——第 1/2/3/4/5/7 格只能在真 FFmpeg 路径上证，"
                  "这些格不出数即不算自证，请装好 ffmpeg 重跑")
            return 0

        # ── 1/2/3/4/5. 真出片全程 ───────────────────────────────────────────
        pid, eid, _vids = newEpisode("后台导出", True)
        t0 = time.perf_counter()
        resp = client.post(f"{BASE}/episodes/{eid}/merge", json={"bgm_path": str(bgm)})
        body = resp.json()
        rid = body["data"]["run_id"]
        keys = sorted(body["data"].keys())
        print(f"1 端点只回 run_id：HTTP {resp.status_code} keys={keys}")
        if keys != ["run_id", "status"]:
            failures.append(f"端点还在同步返回整包结果：{keys}")

        # 2. 句柄可达（找不到 Task 就停不掉）
        tracker = get_task_tracker()
        handle = []
        deadline = time.time() + 5.0
        while time.time() < deadline and not handle:
            handle = tracker.lookup_async_tasks(rid)
            time.sleep(0.005)
        print(f"2 句柄登记：lookup_async_tasks({rid}) -> {len(handle)} 个 Task")
        if not handle:
            failures.append("导出任务没进句柄注册表：取消端点与停机排空按 run id 找不到它")

        # 3. 实验组：导出期间真 HTTP 请求往返延迟
        stop, lat = {"v": False}, []
        th = threading.Thread(target=pollLoopLatency,
                              args=(client, f"{BASE}/projects/{pid}", stop, lat),
                              daemon=True)
        th.start()
        row = waitTerminal(store, rid)
        dur = time.perf_counter() - t0
        stop["v"] = True
        th.join(timeout=5.0)
        expMax = max(lat) if lat else 0.0
        expMed = sorted(lat)[len(lat) // 2] if lat else 0.0
        print(f"3 实验组（to_thread 卸载）：导出耗时 {dur:.2f}s，"
              f"期间 HTTP 往返 {len(lat)} 次 max={expMax * 1000:.0f}ms "
              f"median={expMed * 1000:.0f}ms")
        if -1.0 in lat:
            failures.append("实验组轮询里出现非 200 响应")
        if dur < 1.0:
            failures.append(f"导出只用了 {dur:.2f}s，太短不足以分辨循环是否被占死")

        detail = json.loads(row.get("detail_json") or "{}")
        print(f"4 终态读数：status={row.get('status')!r} detail keys={sorted(detail.keys())} "
              f"fallback={detail.get('fallback')!r}")
        if row.get("status") not in ("done", "done_with_fallback"):
            failures.append(f"真出片落 {row.get('status')!r}：{row.get('error')!r}")
        for k in ("composed", "mode", "url", "merge_id", "fallback"):
            if k not in detail:
                failures.append(f"detail_json 缺键 {k}：{sorted(detail.keys())}")
        if detail.get("composed") is not True:
            failures.append(f"有真素材却未真合成：fallback={detail.get('fallback')!r}")
        if not detail.get("url"):
            failures.append("真合成了却没有成片 URL")
        projected = next((x for x in client.get(f"{BASE}/projects/{pid}").json()["data"]["runs"]
                          if x["id"] == rid), {})
        if projected.get("status") != row.get("status"):
            failures.append(f"前端投影与库里不同源：{projected.get('status')!r}")

        mid = str(detail.get("merge_id") or "")
        mr = client.get(f"{BASE}/merges/{mid}")
        mrow = (mr.json().get("data") or {}).get("merge") or {}
        items = json.loads(mrow.get("items_json") or "[]")
        print(f"5 merges 读面：HTTP {mr.status_code} mode={mrow.get('mode')!r} "
              f"items={len(items)} output_url={mrow.get('output_url')!r} "
              f"burned={detail.get('subtitle_burned')} mixed={detail.get('bgm_mixed')}")
        if mr.status_code != 200 or len(items) != CLIP_COUNT or not mrow.get("output_url"):
            failures.append(f"前端新接的 merges 读者取不到实质内容："
                            f"{mr.status_code}/{len(items)}/{mrow.get('output_url')!r}")
        if not Path(str(mrow.get("output_path") or "")).is_file():
            failures.append(f"库里说成片在 {mrow.get('output_path')!r}，磁盘上没有")

        # ── 7. 导出期间叫停 ─────────────────────────────────────────────────
        pid2, eid2, _ = newEpisode("导出中途叫停", True)
        rid2 = client.post(f"{BASE}/episodes/{eid2}/merge",
                           json={"bgm_path": str(bgm)}).json()["data"]["run_id"]
        r2 = client.post(f"{BASE}/runs/{rid2}/cancel")
        c2 = r2.json().get("data") or {}
        print(f"7 叫停读数：HTTP {r2.status_code} {c2}")
        if r2.status_code != 200:
            failures.append(f"导出进行中的 run 叫停被拒：{r2.status_code} {r2.text[:120]}")
        elif c2.get("tasks_cancelled", 0) < 1:
            failures.append(f"叫停没打断任何 Task（句柄没接通）：{c2}")
        row2 = waitTerminal(store, rid2)
        print(f"7 终态：status={row2.get('status')!r} error={row2.get('error')!r} "
              f"该集 merges 行={mergeRowCount(eid2)}")
        if row2.get("status") != "cancelled":
            failures.append(f"叫停后落 {row2.get('status')!r}（应 cancelled）")
        if mergeRowCount(eid2) != 0:
            failures.append("叫停仍往 merges 表写了半截成品记录")
        if client.get(f"{BASE}/merges/{mid}").status_code != 200:
            failures.append("叫停一单把上一单的成品记录也弄丢了")

        # ── 3-对照组：同一个生产 stage 函数，只是不 offload ──────────────────
        t3 = time.perf_counter()
        stop3, lat3 = {"v": False}, []
        th3 = threading.Thread(target=pollLoopLatency,
                               args=(client, f"{BASE}/projects/{ctrlPid}", stop3, lat3),
                               daemon=True)
        th3.start()
        ctrl = client.post("/__probe/ctrl-export").json()
        ctrlDur = time.perf_counter() - t3
        stop3["v"] = True
        th3.join(timeout=5.0)
        ctrlMax = max(lat3) if lat3 else 0.0
        print(f"3 对照组（循环内阻塞）：同一 stage 耗时 {ctrlDur:.2f}s，"
              f"期间 HTTP 往返 {len(lat3)} 次 max={ctrlMax * 1000:.0f}ms ok={ctrl.get('ok')}")
        if -1.0 in lat3:
            failures.append("对照组轮询里出现非 200 响应")
        if not ctrl.get("ok"):
            failures.append(f"对照组没跑成真活：{ctrl.get('error')!r}")
        if ctrlMax < 1.0:
            failures.append(f"对照组只卡了 {ctrlMax * 1000:.0f}ms——这个测法分辨不出阻塞，"
                            "判据不能算过")
        if ctrlMax <= expMax * 3:
            failures.append(f"实验组 max={expMax * 1000:.0f}ms 没显著低于对照组 "
                            f"{ctrlMax * 1000:.0f}ms——offload 没起作用")

    after, nAfter = fingerprintDataDir()
    print(f"仓内 data/ 指纹：before={before[:12]}({nBefore}) after={after[:12]}({nAfter})")
    if after != before:
        failures.append("仓内 data/ 被写动了")
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("MERGE AS BACKGROUND RUN LIVE VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
