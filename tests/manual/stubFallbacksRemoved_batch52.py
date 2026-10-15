# -*- coding: utf-8 -*-
"""live-verify（批 52，§6-228）：八处同名 class/def 桩拆掉之后，真链路给得出真货。

判据档数形状（AST 里 handler 有没有定义同名 class/def）；这一支要在**真导入 + 真调用**上读数：

1. `provider_manager` 的六个名字逐个与真身 **`is` 同一对象**（桩那侧必然不是——桩是本地另定义的一份）；
2. 密钥那条腿是**真加解密**：`encrypt_api_key(x) != x` 且解回原值；若本机未装 pycryptodome，
   真身按设计抛 `RuntimeError`（fail-fast）——那也是读数，桩那侧的形态是**原样透传**，两者必须能分开；
3. `get_preset_registry()` 给得出真注册表（桩那侧 `return None`，下一句就是 AttributeError）；
4. `router` 的三枚函数与 `RequestType` 同样 `is` 真身，且 `LLM_ROUTER_AVAILABLE` 已不存在
   （全仓现读：只写不读，留着就是 §2 那条"只写不读的配置"）；
5. `post_chat_pipeline.ReflectionType is growth_log.ReflectionType`；
6. 真 `create_app()` 装配完好（摘掉八段兜底不许打断启动链路）；
7. **反向校准**：同一把尺（判据自己的 `stubViolations`）打在 HEAD 的仓外工作树上必须报出 8 处，本树报空。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/stubFallbacksRemoved_batch52.py`
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402  (必须先于 neurova 导入)

REPO = Path(__file__).resolve().parents[2]
WORK_ROOT = isolatedDataRoot(prefix="neurovaStubB52")
failures: list = []


def read(idx: str, desc: str, fn) -> None:
    try:
        print("[%s] PASS %s  ← %s" % (idx, desc, fn()))
    except AssertionError as exc:
        failures.append("%s %s：%s" % (idx, desc, exc))
        print("[%s] FAIL %s：%s" % (idx, desc, exc))


def _identityWithRealModules() -> str:
    pm = importlib.import_module("neurova.llm.provider_manager")
    pairs = {
        "Module": ("neurova.core.module_system", "Module"),
        "LogLevel": ("neurova.core.log_level", "LogLevel"),
        "get_logger": ("neurova.core.logger", "get_logger"),
        "LLMPresetRegistry": ("neurova.llm.presets", "LLMPresetRegistry"),
        "ModelPreset": ("neurova.llm.presets", "ModelPreset"),
        "get_preset_registry": ("neurova.llm.presets", "get_preset_registry"),
        "SecretStore": ("neurova.llm.providers.secret_store", "SecretStore"),
        "encrypt_api_key": ("neurova.llm.providers.secret_store", "encrypt_api_key"),
        "decrypt_api_key": ("neurova.llm.providers.secret_store", "decrypt_api_key"),
        "ConnectionResult": ("neurova.llm.providers.types", "ConnectionResult"),
        "ProbeResult": ("neurova.llm.providers.types", "ProbeResult"),
        "PydanticModelInfo": ("neurova.llm.providers.types", "ModelInfo"),
        "ProviderCapability": ("neurova.llm.providers.types", "ProviderCapability"),
        "ProviderType": ("neurova.llm.providers.types", "ProviderType"),
    }
    wrong = []
    for local, (modName, attr) in pairs.items():
        real = getattr(importlib.import_module(modName), attr)
        if getattr(pm, local, None) is not real:
            wrong.append((local, getattr(getattr(pm, local, None), "__module__", "缺失")))
    assert not wrong, f"这些名字不是真身：{wrong}"
    return "%d 个名字全部 is 真身" % len(pairs)


def _secretLegIsReal() -> str:
    pm = importlib.import_module("neurova.llm.provider_manager")
    plain = "sk-test-项目-12345"
    try:
        cipher = pm.encrypt_api_key(plain)
    except RuntimeError as exc:      # 真身的 fail-fast 形态（未装 pycryptodome）
        return f"真身按设计 fail-fast：RuntimeError({str(exc)[:48]})；桩那侧的形态是原样 return key"
    assert cipher != plain, "encrypt_api_key 原样返回——那正是被拆掉的透传桩的形状"
    assert pm.decrypt_api_key(cipher) == plain, "解密回不来"
    return "密文≠明文（长度 %d→%d），解回原值" % (len(plain), len(cipher))


def _presetRegistryIsReal() -> str:
    pm = importlib.import_module("neurova.llm.provider_manager")
    reg = pm.get_preset_registry()
    assert reg is not None, "get_preset_registry() 给了 None——桩那侧就是这形状"
    presets = reg.list_presets()
    assert hasattr(presets, "__iter__"), f"list_presets 读数异常：{type(presets)}"
    return "注册表=%s，预设条数=%d" % (type(reg).__name__, len(list(presets)))


def _routerLegsAreReal() -> str:
    router = importlib.import_module("neurova.router")
    real = importlib.import_module("neurova.llm.llm_router")
    wrong = [n for n in ("RequestType", "detect_request_type", "get_llm_router",
                         "select_model_for_request") if getattr(router, n) is not getattr(real, n)]
    assert not wrong, f"router 给的不是 llm_router 真身：{wrong}"
    assert not hasattr(router, "LLM_ROUTER_AVAILABLE"), "只写不读的可用性开关还挂着"
    got = router.detect_request_type("随便一段文本")
    assert got is real.RequestType.CHAT, f"detect_request_type 读数异常：{got!r}"
    return "四名 is 真身，LLM_ROUTER_AVAILABLE 已摘，detect('…')=%s" % got.value


def _reflectionTypeIsOneSource() -> str:
    pcp = importlib.import_module("neurova.post_chat_pipeline")
    growth = importlib.import_module("neurova.cognitive_layers.meta_cognition_layer.growth_log")
    assert pcp.ReflectionType is growth.ReflectionType, (
        "两份 ReflectionType 并存：%s vs %s" % (pcp.ReflectionType.__members__,
                                                growth.ReflectionType.__members__))
    return "成员=%s（同一对象）" % sorted(pcp.ReflectionType.__members__)


def _appStillAssembles() -> str:
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app

    app = create_app()
    included = [r for r in app.routes if type(r).__name__ == "_IncludedRouter"]
    assert len(included) >= 60, f"挂载面塌了：{len(included)}"
    client = TestClient(app)
    assert client.get("/health").status_code == 200, "/health 该 200"
    assert client.get("/api/v1/_no_such_b52").status_code == 404, "校准面该 404"
    return "路由挂载=%d 只，/health→200，校准→404" % len(included)


CODE = (
    "import sys, json\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import importlib.util\n"
    "spec = importlib.util.spec_from_file_location('j', sys.argv[1] + "
    "'/tests/unit/test_noFirstPartyImportPlaceholder.py')\n"
    "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
    "import os\n"
    "hits = {}\n"
    "for rel in m._trackedPyFiles():\n"
    "    p = os.path.join(sys.argv[1], rel)\n"
    "    if not os.path.isfile(p): continue\n"
    "    for v in m.stubViolations(open(p, encoding='utf-8', errors='replace').read(), rel):\n"
    "        hits[v[0]] = hits.get(v[0], 0) + 1\n"
    "print(json.dumps(hits, ensure_ascii=False))\n")


def _headSideCalibration() -> str:
    base = Path(tempfile.mkdtemp(prefix="neurovaB52Head-"))
    wt = base / "head"
    subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach", str(wt), "HEAD"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        judge = "tests/unit/test_noFirstPartyImportPlaceholder.py"
        shutil.copyfile(REPO / judge, wt / judge)
        shutil.copyfile(REPO / "tests/ast_scan.py", wt / "tests/ast_scan.py")
        p = subprocess.run([sys.executable, "-c", CODE, str(wt)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", cwd=str(wt),
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        got = json.loads(p.stdout.strip().splitlines()[-1])
        assert sum(got.values()) == 8 and len(got) == 3, (
            f"HEAD 侧应报 8 处／3 档，实得 {got}；stderr 尾={p.stderr[-200:]}")
        here = subprocess.run([sys.executable, "-c", CODE, str(REPO)], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", cwd=str(REPO),
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        mine = json.loads(here.stdout.strip().splitlines()[-1])
        assert not mine, f"本树仍有同名桩：{mine}"
        return "HEAD=%d 处／%d 档（%s）｜本树=0" % (sum(got.values()), len(got), sorted(got))
    finally:
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(wt)],
                       capture_output=True)
        subprocess.run(["git", "-C", str(REPO), "worktree", "prune"], capture_output=True)
        shutil.rmtree(base, ignore_errors=True)


read("1", "provider_manager 的 14 个名字逐个 is 真身", _identityWithRealModules)
read("2", "密钥那条腿是真加解密（或真 fail-fast），不是透传", _secretLegIsReal)
read("3", "get_preset_registry 给得出真注册表", _presetRegistryIsReal)
read("4", "router 三函数与 RequestType 是真身，可用性开关已摘", _routerLegsAreReal)
read("5", "post_chat_pipeline 的 ReflectionType 单源", _reflectionTypeIsOneSource)
read("6", "真 create_app() 装配完好", _appStillAssembles)
read("7", "反向校准：HEAD 报 8 处／3 档、本树报空", _headSideCalibration)

print("\n总计：7 项，失败 %d 项 ｜ 隔离工作根=%s" % (len(failures), WORK_ROOT))
for f in failures:
    print("  - " + f)
sys.exit(1 if failures else 0)
