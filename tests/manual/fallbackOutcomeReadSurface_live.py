# -*- coding: utf-8 -*-
"""H2-7 · ①的 live-verify：带病完成的读数必须能从 **HTTP 投影**里读出来，而不只躺在库里。

跑的真生产对象：真 `create_app()` + `TestClient`（真 lifespan）、真
`POST /projects/{pid}/script`、`POST /episodes/{eid}/storyboards`、`POST /episodes/{eid}/extract`、
`POST /episodes/{eid}/generate-videos`、真 `GET /projects/{pid}` 投影、真 `_spawn_run` 与 runs 台账、
真 `StudioStore`。只替 LLM 边界（`services.call_llm`）与服务商边界、auth 身份——
本层证的是「前端那一发 GET 拿到的字段形状，够不够它把带病条数说出来」。

判据（缺一条这条链就是断的）：

1. LLM 挂了的分集拆解 → 投影里那条 run 是 `done_with_fallback`，`detail_json` 解析后三个契约键
   （`fallback`/`fallback_failed`/`fallback_blocked`）齐备、成因文本非空；改前这里写的是干净的
   `done`，读侧只看状态字就永远看不见它（§6-78 J 条更正那一格）；
2. 分镜拆解整步失败 → 同上（改前落 `done` + `{"shots": 0}`，一镜没拆出来也算成功）；
3. 资产抽取失败 → 同上，且**不再**出现第二份成因键 `error`；
4. 一条缺首帧的批量视频 → 投影里 `fallback_blocked == 1`（条数是数出来的，不是文案里猜的）；
5. 对照：LLM 正常返回的分集 → `done`、两个带病计数为 0、`error` 为空（不能把成功写成带病）；
6. 全程不写仓内真实 `data/`（指纹前后一致）。

前端一层不在本脚本内自证：`describeRunOutcome` 取哪些键、警示条说什么话，由
`NeurUI/src/composables/__tests__/useStudioRun.test.ts` 与
`NeurUI/src/pages/aigc/__tests__/StudioProjectPage.test.ts` 钉；本脚本与它们之间的咬合由
`tests/unit/aigc_studio/test_runFallbackOutcomeSingleSource.py::TestFrontendReadsExactlyTheContractKeys`
（跨语言按键名对齐）保证。

一条命令复现（机器无关串）：
PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/fallbackOutcomeReadSurface_live.py

**改前对照**：把 `_settleRun` 里写三个契约键那两处撤掉、并把三个编排服务的收尾改回各自手写
`"status": RUN_DONE` 再跑本脚本——判据 1/2/3 会红在 `status='done'`，判据 4 会红在
`fallback_blocked` 缺键（见提交正文）。
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

DATA_ROOT = isolatedDataRoot()
REPO_DATA_DIR = PROJECT_ROOT / "data"
BASE = "/api/v1/studio"
USER = {"user_id": "u-live", "role": "admin"}
CONTRACT_KEYS = {"fallback", "fallback_failed", "fallback_blocked"}
TERMINAL = {"done", "done_with_fallback", "failed"}


def fingerprintDataDir():
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}:{st.st_size}:{st.st_mtime_ns}")
    digest = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest() if items else "empty"
    return digest, len(items)


def _awaitProjection(client, pid, rid, timeoutS=25.0):
    """轮真 GET：投影里没有这条 run、或它还没进终态就一直等。"""
    deadline = time.time() + timeoutS
    row = {}
    while time.time() < deadline:
        runs = client.get(f"{BASE}/projects/{pid}").json()["data"]["runs"]
        row = next((r for r in runs if r["id"] == rid), None) or {}
        if row.get("status") in TERMINAL:
            return row
        time.sleep(0.1)
    return row


def _degradedReadout(client, pid, rid, label, failures):
    """投影里那条 run 是否带着「可解析的带病读数」。"""
    row = _awaitProjection(client, pid, rid)
    if row.get("status") != "done_with_fallback":
        failures.append(f"{label}：投影状态写着 {row.get('status')!r}——带病完成被压平成成功")
        print(f"{label} 读数：{row}")
        return {}
    detail = json.loads(row.get("detail_json") or "{}")
    missing = CONTRACT_KEYS - set(detail)
    if missing:
        failures.append(f"{label}：投影 detail_json 缺契约键 {sorted(missing)}，前端无从取数")
    # 与 `_settleRun` 同一规则：要么数出条数，要么给出成因文本，两者皆空即读数只剩状态字
    told = (int(detail.get("fallback_failed") or 0) + int(detail.get("fallback_blocked") or 0)
            or bool(str(detail.get("fallback") or "").strip()))
    if not told:
        failures.append(f"{label}：既无带病计数也无成因文本，读侧无从知道它没跑完：{detail}")
    print(f"{label} 读数：status={row.get('status')!r} error={row.get('error')!r} "
          f"detail={row.get('detail_json')}")
    return detail


async def _boom(prompt: str, system: str) -> str:
    raise RuntimeError("上游模型 429 打不通")


async def _goodEpisodes(prompt: str, system: str) -> str:
    return json.dumps([{"number": 1, "title": "第一集", "content": "山上有座庙",
                        "synopsis": "开场"}], ensure_ascii=False)


def _fakeSubmit(creds, prompt, **kw):
    async def _v():
        return {"task_id": "rt-live", "poll_url": "", "raw": {}}

    return _v()


def main() -> int:
    from fastapi.testclient import TestClient

    from neurova.aigc_studio import services
    from neurova.aigc_studio.store import get_store
    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.llm.generators import protocols as proto_mod
    from neurova.llm.generators import runtime as gen_runtime
    from neurova.llm.generators.protocols import ProtocolCredentials

    failures = []
    before, nBefore = fingerprintDataDir()

    services.call_llm = _boom
    gen_runtime.resolve_generation_creds = (
        lambda hint, model, providerId, apiKey, baseUrl, defaultBase=None, **kw:
        ProtocolCredentials(api_key="k", base_url="https://x", model="m", protocol=hint))
    proto_mod.submit_video = _fakeSubmit

    store = get_store()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    with TestClient(app) as client:
        project = store.create_project(owner_user_id="u-live", title="带病读数面",
                                       aspect_ratio="9:16")
        pid = project["id"]

        # ① 分集拆解回退（改前压平成 done）
        rid1 = client.post(f"{BASE}/projects/{pid}/script",
                           json={"content": "三年之期已到" * 20}).json()["data"]["run_id"]
        _degradedReadout(client, pid, rid1, "① 分集回退", failures)

        # ② 分镜拆解整步失败（改前落 done + {"shots": 0}）
        eid = store.add_episode(pid, {"number": 1, "title": "e1", "content": "客厅夜"})["id"]
        rid2 = client.post(f"{BASE}/episodes/{eid}/storyboards", json={}).json()["data"]["run_id"]
        _degradedReadout(client, pid, rid2, "② 分镜整步失败", failures)

        # ③ 资产抽取失败：成因键收成一份
        rid3 = client.post(f"{BASE}/episodes/{eid}/extract", json={}).json()["data"]["run_id"]
        detail3 = _degradedReadout(client, pid, rid3, "③ 资产抽取失败", failures)
        if "error" in detail3:
            failures.append(f"③ 资产抽取：detail_json 仍有第二份成因键 error={detail3['error']!r}")

        # ④ 批量视频一条缺首帧：条数必须是数出来的
        eid2 = store.add_episode(pid, {"number": 2, "title": "e2", "content": "雪夜"})["id"]
        for n, hasFrame in {1: True, 2: False}.items():
            sb = store.add_storyboard(eid2, {"number": n, "video_prompt": f"镜{n}",
                                             "prompt": f"镜{n}", "duration": 3})
            if hasFrame:
                f = DATA_ROOT / f"live_frame{n}.png"
                f.write_bytes(b"IMG")
                store.update_storyboard(sb["id"], {"first_frame_path": str(f)})
        rid4 = client.post(f"{BASE}/episodes/{eid2}/generate-videos",
                           json={"provider": "wan", "model": "wan-x"}).json()["data"]["run_id"]
        detail4 = _degradedReadout(client, pid, rid4, "④ 批量视频被阻断", failures)
        if detail4.get("fallback_blocked") != 1:
            failures.append(f"④ 被阻断条数不是 1：{detail4.get('fallback_blocked')!r}")

        # ⑤ 对照：LLM 正常 → 干净 done，不写成带病
        services.call_llm = _goodEpisodes
        rid5 = client.post(f"{BASE}/projects/{pid}/script",
                           json={"content": "另一本书" * 30}).json()["data"]["run_id"]
        row5 = _awaitProjection(client, pid, rid5)
        detail5 = json.loads(row5.get("detail_json") or "{}")
        print(f"⑤ 正常对照读数：status={row5.get('status')!r} error={row5.get('error')!r} "
              f"detail={row5.get('detail_json')}")
        if row5.get("status") != "done" or (row5.get("error") or ""):
            failures.append(f"⑤ 成功却被写成 {row5.get('status')!r}/{row5.get('error')!r}")
        if detail5.get("fallback_blocked") != 0 or detail5.get("fallback_failed") != 0:
            failures.append(f"⑤ 成功行的带病计数非零：{detail5}")

    after, nAfter = fingerprintDataDir()
    print(f"仓内 data/ 指纹：before={before[:12]}({nBefore}) after={after[:12]}({nAfter})")
    if after != before:
        failures.append("仓内 data/ 被写动了")
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("H2-7 FALLBACK OUTCOME READ SURFACE LIVE VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
