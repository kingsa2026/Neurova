# -*- coding: utf-8 -*-
"""H2-7 · ②的 live-verify：镜头面读的两列，真生产路上确实有值可读。

防的是「假接线」：前端加了渲染，但若 `injected_prompt` 在真链路上从来没被写过、或投影里
从来没带出，界面就永远空白——单测喂的是夹具，证不了这件事（同「端点存在 ≠ 被消费」那一族）。
这里跑真装配：真 `create_app()` + `TestClient`（真 lifespan）、真
`POST /episodes/{eid}/generate-images`（真 `generate_shot_images` → 真 `resolveShotContinuity`
→ 真写 `injected_prompt`）、真 `GET /episodes/{eid}` 投影（前端镜头卡的数据源）。
只替服务商凭证边界与 auth；图像提交**故意让它失败**——注入写在发请求之前（`services.py:468`），
这一层要证的正是"产物坏掉时读数仍然落账"。数据根走 `_liveVerifyIsolation.isolatedDataRoot()`。

判据：
1. 投影里 `injected_prompt` 非空，且含**场景定妆提示词 + 本镜氛围**（跨集连续性读数进提示词的实证）；
   角色那一档走的是参考图通道（`refs`，不进文本串），这里只把它当"过闸前置"用；
2. 含项目视觉风格，说明读到的是喂模型那串而非原始 `image_prompt`；
3. `title`（拆解/手动新增写入）随同一投影带出——镜头卡据此显示，改前该列零读者；
4. 服务商失败要诚实落到镜头行（`status='failed'`），否则读数假好；
5. 等 run 进终态**再**读投影：长任务挂在后台循环上，发完就读必然读到空值
   （第一版就栽在这里——那不是产品缺陷，是探针没等；形态与 §6-78 B 条同源）。
6. 仓内真实 `data/` 未被写动（指纹前后一致）。

一条命令复现（机器无关串）：
PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/injectedPromptFace_live.py
"""
from __future__ import annotations

import hashlib
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
CHAR_PROMPT = "character sheet, Lin Fan, black trench coat, cold key light"
SCENE_PROMPT = "wet living room at night, single lamp, long shadows"
ATMOSPHERE = "冷调夜雨"
TERMINAL = ("done", "done_with_fallback", "failed")


def fingerprintDataDir():
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}:{st.st_size}:{st.st_mtime_ns}")
    digest = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest() if items else "empty"
    return digest, len(items)


def _runStatus(client, pid, rid):
    runs = client.get(f"{BASE}/projects/{pid}").json()["data"]["runs"]
    return next((x["status"] for x in runs if x["id"] == rid), "")


def main() -> int:
    from fastapi.testclient import TestClient

    from neurova.aigc_studio.store import get_store
    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.llm.generators import runtime as gen_runtime

    failures = []
    before, nBefore = fingerprintDataDir()

    def boomCreds(hint, model, providerId, apiKey, baseUrl, defaultBase=None, **kw):
        raise RuntimeError("上游服务商不可用（本脚本故意让它失败）")

    gen_runtime.resolve_generation_creds = boomCreds

    store = get_store()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    with TestClient(app) as client:
        pid = store.create_project(owner_user_id="u-live", title="注入回看面",
                                   style="国风水墨", aspect_ratio="9:16")["id"]
        eid = store.add_episode(pid, {"number": 1, "title": "e1", "content": "客厅夜"})["id"]
        cid = store.add_character(pid, {"name": "林凡", "final_prompt": CHAR_PROMPT})["id"]
        # 角色必须已有定妆件——C1 的硬阻断闸会在参考件取不到时**直接拦下这一镜**，
        # 那种情况下 `injected_prompt` 根本不会写（本脚本第一版就红在这里：不是没接线，
        # 是夹具没过闸）。注意角色进的是**参考图通道**（`refs`，不在投影字段里），
        # 文本串里看不到它；进文本的是场景/氛围/道具那三档。
        ref = DATA_ROOT / "live_char_ref.png"
        ref.write_bytes(b"IMG")
        store.update_asset_row("characters", cid, {"image_path": str(ref)})
        sceneId = store.add_scene(pid, {"episode_id": eid, "location": "客厅", "time": "夜",
                                        "final_prompt": SCENE_PROMPT})["id"]
        sid = store.add_storyboard(eid, {"number": 1, "title": "雨夜对峙",
                                        "image_prompt": "a man pushes the door open",
                                        "atmosphere": ATMOSPHERE, "scene_id": sceneId,
                                        "characters": [{"name": "林凡", "id": cid}]})["id"]

        r = client.post(f"{BASE}/episodes/{eid}/generate-images",
                        json={"provider": "openai", "model": "gpt-image"})
        assert r.status_code == 200, r.text
        runId = r.json()["data"]["run_id"]

        deadline = time.time() + 25.0
        status = _runStatus(client, pid, runId)
        while time.time() < deadline and status not in TERMINAL:
            time.sleep(0.1)
            status = _runStatus(client, pid, runId)
        print(f"run 终态读数：{status!r}（{runId}）")
        if status not in TERMINAL:
            failures.append(f"run 没进终态（{status!r}），后面的读数都是未写就先读")

        rows = client.get(f"{BASE}/episodes/{eid}").json()["data"]["storyboards"]
        sb = next((x for x in rows if x["id"] == sid), {})
        injected = str(sb.get("injected_prompt") or "")
        print(f"注入读数：injected_prompt={injected!r}")
        print(f"镜头面读数：title={sb.get('title')!r} status={sb.get('status')!r} "
              f"error={sb.get('error')!r}")

        if not injected:
            failures.append("投影里 injected_prompt 为空——前端那格渲染的是夹具，真路上从没写过")
        if SCENE_PROMPT not in injected:
            failures.append(f"注入串不含场景定妆提示词（跨集连续性读数没进提示词）：{injected!r}")
        if ATMOSPHERE not in injected:
            failures.append(f"注入串不含本镜氛围（atmosphere 没进提示词）：{injected!r}")
        if "国风水墨" not in injected:
            failures.append(f"注入串不含项目视觉风格，读到的不是喂模型那串：{injected!r}")
        if injected and injected == sb.get("image_prompt"):
            failures.append("injected_prompt 与 image_prompt 相同——注入这一步没发生")
        if sb.get("title") != "雨夜对峙":
            failures.append(f"投影没带出镜头 title：{sb.get('title')!r}")
        if sb.get("status") != "failed":
            failures.append(f"服务商失败却把镜头标成 {sb.get('status')!r}——读数假好")

    after, nAfter = fingerprintDataDir()
    print(f"仓内 data/ 指纹：before={before[:12]}({nBefore}) after={after[:12]}({nAfter})")
    if after != before:
        failures.append("仓内 data/ 被写动了")
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("H2-7 INJECTED PROMPT FACE LIVE VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
