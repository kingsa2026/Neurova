# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-13 批 36，§6-188）：市场「装过什么」这本账今天真的有读者了。

判据档（`tests/unit/skills/test_marketInstalledStateIsReadBack.py`）在 tmp_path 里搭场景；
这一支要证的是**跨实例与跨 HTTP 面**的读回闭环——写侧自证不是目标，"下一个进程还看得见"才是：

1. 真 `MarketImporter` 走一次本地种子安装 ⇒ 内存读数含该技能（写侧本来就有）；
2. **同一目录新建第二个实例**（＝重启）⇒ `list_installed()` 读回同一条，版本号逐字等于盘上那份；
3. 经真 `create_app()` 的 `GET /api/v1/marketplace/installed`：单例重建后仍列出它 ⇒ 面板读数不再失忆；
4. 卸载 ⇒ 第三个实例不再列它（读侧不许把已删的读成现役）；
5. 坏记账件 ⇒ 不采信 + **出声** + 盘上字节一个字符没动（读侧不毁证据）；
6. 目录名 ≠ 文件自报 `skill_id` ⇒ 键取目录名（记账与删除同源）；
7. `SkillsMPAdapter.install`：回 False 且目标目录零字节（不再 `return True` 空装）；
8. 反向校准（证明 7 不是"把安装一关了之"）：`SkillsShAdapter` 递真 zip 字节 ⇒ 回 True 且 SKILL.md 落盘。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/marketInstalledStateReadBack_batch36.py`
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaMarketB36")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.skills import market_adapters as MA  # noqa: E402
from neurova.skills.market_importer import MarketImporter  # noqa: E402

failures: list[str] = []
BASE = "/api/v1/marketplace"
SKILL_ID = "web-search"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def main() -> int:
    import os

    os.environ["NEUROVA_JWT_SECRET_KEY"] = "live_b36_secret_key_for_p0_fixes_0123"

    cache = WORK_ROOT / "market-cache"
    cache.mkdir(parents=True, exist_ok=True)

    # ── 1-2：真安装 → 跨实例读回 ──
    importer = MarketImporter(skills_dir=cache)
    task = importer.import_skill(skill_id=SKILL_ID, version=None, force=False)
    mem = {item["skill_id"] for item in importer.list_installed()}
    check("[1] 本地种子安装后内存读数含该技能（写侧本来就有，先自证）", SKILL_ID in mem,
          f"status={getattr(task.status, 'name', task.status)} mem={sorted(mem)}")

    revived = MarketImporter(skills_dir=cache)
    readBack = {item["skill_id"]: item["version"] for item in revived.list_installed()}
    diskVersion = json.loads((cache / SKILL_ID / "skill.json").read_text(encoding="utf-8")).get("version")
    check("[2] 第二个实例（＝重启）从盘上读回同一条（键=目录名）", SKILL_ID in readBack,
          f"readBack={readBack}")
    check("[2b] 读回的版本号逐字等于盘上那份（不替它编）",
          str(readBack.get(SKILL_ID)) == str(diskVersion),
          f"读回={readBack.get(SKILL_ID)!r} 盘上={diskVersion!r}")

    # ── 3：真 HTTP 面（单例重建 = 新进程的等价） ──
    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.skills import market_importer as MI

    MI.reset_market_importer()
    MI._market_importer = MarketImporter(skills_dir=cache)

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "live-b36", "username": "live-b36", "role": "user", "neuser_id": "live-b36"}
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get(f"{BASE}/installed")
        listed = {row.get("skill_id") for row in (resp.json() or [])} if resp.status_code == 200 else set()
        check("[3] GET /marketplace/installed 在单例重建后仍列出已装（面板不再失忆）",
              resp.status_code == 200 and SKILL_ID in listed,
              f"status={resp.status_code} listed={sorted(listed)[:4]}")

    # ── 4：卸载后不得被盘上残留读回来 ──
    check("[4a] 卸载面认得出它（读侧接通后 uninstall 不再回 False）",
          MarketImporter(skills_dir=cache).uninstall_skill(SKILL_ID) is True)
    check("[4b] 卸载后第三个实例不再列它",
          SKILL_ID not in {i["skill_id"] for i in MarketImporter(skills_dir=cache).list_installed()})

    # ── 5：坏记账件——不采信、出声、不改写 ──
    broken = cache / "broken--pkg"
    broken.mkdir(parents=True, exist_ok=True)
    raw = "{ 这不是合法 json"
    (broken / "skill.json").write_text(raw, encoding="utf-8")
    seen: list[str] = []
    import logging

    class _Spy(logging.Handler):
        def emit(self, record):
            if "读不懂" in record.getMessage():
                seen.append(record.getMessage())

    root = logging.getLogger("neurova.skills.market_importer")
    spy = _Spy(level=logging.WARNING)
    root.addHandler(spy)
    try:
        items = {i["skill_id"] for i in MarketImporter(skills_dir=cache).list_installed()}
    finally:
        root.removeHandler(spy)
    check("[5] 坏记账件不采信、且出声点名（不把'读不懂'读成'没装'了事）",
          "broken--pkg" not in items and len(seen) == 1, f"items={sorted(items)} 出声={len(seen)} 条")
    check("[5b] 读侧没动盘上那个坏文件（不毁证据）",
          (broken / "skill.json").read_text(encoding="utf-8") == raw)

    # ── 6：键取目录名而不是文件自报 ──
    ghost = cache / "dir--name"
    ghost.mkdir(parents=True, exist_ok=True)
    (ghost / "skill.json").write_text(json.dumps({"skill_id": "claims--other", "version": "2.0.0"}),
                                      encoding="utf-8")
    keys = {i["skill_id"] for i in MarketImporter(skills_dir=cache).list_installed()}
    check("[6] 目录名≠自报 skill_id 时采信目录名（记账与删除同源）",
          "dir--name" in keys and "claims--other" not in keys, f"keys={sorted(keys)}")

    # ── 7：空装不再谎报 ──
    out = WORK_ROOT / "mp-out"
    out.mkdir(parents=True, exist_ok=True)
    verdict = MA.SkillsMPAdapter().install(
        MA.SkillInfo(name="mp--demo", source="skillsmp",
                     download_url="https://skillsmp.invalid/mp--demo.zip"), str(out))
    check("[7] SkillsMP 的 install 不再回 True 而零落字节",
          verdict is False and not any(out.iterdir()),
          f"verdict={verdict} 目录内={sorted(p.name for p in out.iterdir())}")

    # ── 8：反向校准——真下载的适配器仍要装得动 ──
    payload = io.BytesIO()
    with __import__("zipfile").ZipFile(payload, "w", __import__("zipfile").ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", "---\nname: sh--demo\n---\n\n# 活体 SH 正文\n")
    blob = payload.getvalue()
    out2 = WORK_ROOT / "sh-out"
    out2.mkdir(parents=True, exist_ok=True)
    def _fakeDownload(self, url, dest):
        Path(dest).write_bytes(blob)
        return True

    MA.SkillsShAdapter._download_file = _fakeDownload
    verdict2 = MA.SkillsShAdapter().install(
        MA.SkillInfo(name="sh--demo", source="skills.sh",
                     download_url="https://skills.sh/sh--demo.zip"), str(out2))
    check("[8] 反向校准：真取到字节的适配器仍回 True 且 SKILL.md 落盘（不是把安装一关了之）",
          verdict2 is True and (out2 / "SKILL.md").is_file()
          and "# 活体 SH 正文" in (out2 / "SKILL.md").read_text(encoding="utf-8"),
          f"verdict={verdict2}")

    print(f"\n读数 {8 + 2} 项，失败 {len(failures)} 项: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
