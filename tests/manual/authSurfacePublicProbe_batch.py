# -*- coding: utf-8 -*-
"""live 抽样（§6-399 裁定 C）：对 A 生成的公开清单里**安全的 GET** 逐条真打，看有没有身份门。

口径：
- 只打 `GET`，且跳过名字里带 `chat/stream/run/invoke/execute/synthesize/chat` 的路径——
  抽样是为了验"无凭证不被身份门拦"，不是去触发业务副作用；
- 判定：**401/403 = 被身份门拦**（这与 A 的清单矛盾，红）；其余状态（200/400/404/422/500）
  都证明"没有身份门"（404 是资源不存在，不是门；500 另记，因为它不是鉴权问题）；
- 校准：先打一条已知受保护的 GET（`/api/v1/settings`）必须 401，证明"401 判据"不是空转。
- 数据根隔离：`isolatedDataRoot()`；不发任何出网请求（只打进程内 TestClient）。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/authSurfacePublicProbe_batch.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaAuthSample")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from scripts import generate_api_auth_surface as generator  # noqa: E402

SKIP_TOKENS = ("chat", "stream", "run", "invoke", "execute", "synthesize", "generate",
               "download", "export", "upload")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    app = create_app()
    rows = generator.collect(app)
    targets = []
    for row in rows:
        if row["guarded"] or row["method"] != "GET":
            continue
        if any(token in row["path"].lower() for token in SKIP_TOKENS):
            continue
        targets.append(row["path"])

    failures = []
    readings = 0
    with TestClient(app) as client:
        calibration = client.get("/api/v1/settings")
        print("[%s] 校准：已知受保护的 GET /api/v1/settings → %d（期望 401）"
              % ("PASS" if calibration.status_code == 401 else "FAIL", calibration.status_code))
        if calibration.status_code != 401:
            failures.append("calibration")

        for path in sorted(set(targets)):
            probe = path.replace("{agent_id}", "probe-agent").replace("{skill_id}", "probe-skill") \
                        .replace("{name}", "probe").replace("{key}", "probe") \
                        .replace("{id}", "probe").replace("{plugin_id}", "probe") \
                        .replace("{namespace}", "probe").replace("{user_id}", "probe") \
                        .replace("{session_id}", "probe").replace("{task_id}", "probe")
            if "{" in probe:
                print("[SKIP] 未替换的路径参数：%s" % path)
                continue
            response = client.get(probe)
            readings += 1
            blocked = response.status_code in (401, 403)
            print("[%s] %d %s%s" % ("FAIL" if blocked else "PASS", response.status_code, probe,
                                    "（被身份门拦，与公开清单矛盾）" if blocked else ""))
            if blocked:
                failures.append("%s -> %s" % (probe, response.status_code))

    print("")
    print("抽样 %d 条；失败 %d 条%s" % (readings, len(failures),
                                      ("：" + str(failures[:4])) if failures else ""))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
