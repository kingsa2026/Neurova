"""growth 拆分后 live-verify（2026-09-16 模块化重构验收）。

在 127.0.0.1:9528 拉起 create_app() 验证实例（不影响 9527 上的运行中服务），
实测 personality（4 路由）/ constitution（6 路由）真实 HTTP 往返 + JSON 落盘，
并核对 envelope 契约（{code, message, data, request_id}）。

隔离措施：
- 独立 probe agent（SimpleNamespace 桩）注入 _app_state，不触碰真实 agent 数据；
- 落盘只写 data/{personality,constitution}/__live_verify_probe__.json，结束清理。

用法: python scripts/diagnostics/_live_verify_growth_split.py
退出码: 0 = 全部通过, 1 = 存在失败
"""
import json
import logging
import os
import sys
import threading
import time
import types
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

PROBE_ID = "__live_verify_probe__"
BASE = f"http://127.0.0.1:9528/api/v1/growth"
PERSONALITY_FILE = Path("data/personality") / f"{PROBE_ID}.json"
CONSTITUTION_FILE = Path("data/constitution") / f"{PROBE_ID}.json"

failures = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def http(method: str, url: str, token: str, body=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    try:
        with urllib.request.urlopen(req, data, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"_raw": raw[:200]}


def main() -> int:
    logging.disable(logging.CRITICAL)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.environ.setdefault("NEUROVA_RSI_RECEIPTS", "data/evolution/rsi_receipts.jsonl")

    from neurova.api.app import create_app
    from neurova.api.auth import create_access_token
    from neurova.api.endpoints import set_app_state, get_app_state

    app = create_app()
    state = get_app_state()
    state["agents"][PROBE_ID] = types.SimpleNamespace(personality="md text", constitution="")
    set_app_state(state)

    token = create_access_token(data={"sub": "live_verify_probe", "username": "probe", "role": "admin", "neuser_id": "live_verify_probe"})

    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=9528, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    if not server.started:
        print("FATAL: verification server failed to start")
        return 1

    try:
        # ---------------- personality ----------------
        print("\n=== personality routes ===")

        st, body = http("GET", f"{BASE}/personality?agent_id={PROBE_ID}", token)
        check("GET /personality 200 + envelope", st == 200 and body.get("code") == 0
              and "message" in body and "data" in body and "request_id" in body,
              f"status={st} keys={sorted(body.keys()) if isinstance(body, dict) else body}")
        check("GET 空态 traits={}", body.get("data", {}).get("traits") == {}, f"traits={body.get('data', {}).get('traits')}")

        st, body = http("GET", f"{BASE}/personality/traits?agent_id={PROBE_ID}", token)
        check("GET /personality/traits 200 + envelope", st == 200 and body.get("code") == 0
              and set(body.keys()) == {"code", "message", "data", "request_id"},
              f"status={st} keys={sorted(body.keys()) if isinstance(body, dict) else body}")

        put_traits = {"openness": 0.7, "conscientiousness": 0.6, "extraversion": 0.5,
                      "agreeableness": 0.8, "neuroticism": 0.3, "creativity": 0.65}
        st, body = http("PUT", f"{BASE}/personality?agent_id={PROBE_ID}", token, {"traits": put_traits})
        check("PUT /personality 200 + envelope", st == 200 and body.get("code") == 0
              and set(body.keys()) == {"code", "message", "data", "request_id"},
              f"status={st} body={str(body)[:150]}")
        check("PUT 回读 envelope.data.traits 与写入一致",
              body.get("data", {}).get("traits") == put_traits,
              f"readback={body.get('data', {}).get('traits')}")

        on_disk = json.loads(PERSONALITY_FILE.read_text(encoding="utf-8"))
        check("PUT 落盘 JSON（tmp+replace 原子写）", on_disk.get("traits") == put_traits,
              f"disk={on_disk}")

        st, body = http("POST", f"{BASE}/personality/evolve?agent_id={PROBE_ID}", token, {})
        check("POST /personality/evolve 501 诚实未实现", st == 501, f"status={st}")

        # ---------------- constitution ----------------
        print("\n=== constitution routes ===")

        st, body = http("GET", f"{BASE}/constitution?agent_id={PROBE_ID}", token)
        check("GET /constitution 200 + envelope", st == 200 and body.get("code") == 0
              and set(body.keys()) == {"code", "message", "data", "request_id"},
              f"status={st} keys={sorted(body.keys()) if isinstance(body, dict) else body}")
        check("GET overview 空态 rules=[]", body.get("data", {}).get("constitution") == [],
              f"rules={body.get('data', {}).get('constitution')}")

        st, body = http("POST", f"{BASE}/constitution/rules?agent_id={PROBE_ID}", token,
                        {"content": "不得虚构事实", "priority": 1})
        check("POST rules 200 + envelope", st == 200 and body.get("code") == 0
              and set(body.keys()) == {"code", "message", "data", "request_id"},
              f"status={st} body={str(body)[:150]}")
        rule_id = body.get("data", {}).get("rule_id", "")
        check("POST 返回 rule_id", bool(rule_id), f"rule_id={rule_id!r}")

        st, body = http("GET", f"{BASE}/constitution/rules?agent_id={PROBE_ID}", token)
        rules = body.get("data", [])
        check("GET rules 200 + envelope.data 列表含新规则",
              st == 200 and isinstance(rules, list) and len(rules) == 1
              and rules[0]["content"] == "不得虚构事实",
              f"status={st} rules={str(rules)[:150]}")

        st, body = http("PUT", f"{BASE}/constitution/rules/{rule_id}?agent_id={PROBE_ID}", token,
                        {"content": "v2", "priority": 5})
        check("PUT rule 200 + envelope", st == 200 and body.get("code") == 0
              and body.get("data", {}).get("content") == "v2" and body.get("data", {}).get("priority") == 5,
              f"status={st} body={str(body)[:150]}")

        on_disk = json.loads(CONSTITUTION_FILE.read_text(encoding="utf-8"))
        check("PUT 落盘（新进程视角直读）", on_disk and on_disk[0]["content"] == "v2" and on_disk[0]["priority"] == 5,
              f"disk={on_disk}")

        st, body = http("PUT", f"{BASE}/constitution/rules/{rule_id}?agent_id={PROBE_ID}", token,
                        {"enabled": False})
        check("toggle 只传 enabled：content/priority 不被覆写",
              st == 200 and body.get("data", {}).get("enabled") is False
              and body.get("data", {}).get("content") == "v2" and body.get("data", {}).get("priority") == 5,
              f"status={st} body={str(body)[:150]}")

        st, body = http("DELETE", f"{BASE}/constitution/rules/{rule_id}?agent_id={PROBE_ID}", token)
        check("DELETE rule 200 + envelope", st == 200 and body.get("code") == 0
              and body.get("data", {}).get("rule_id") == rule_id,
              f"status={st} body={str(body)[:150]}")

        st, body = http("DELETE", f"{BASE}/constitution/rules/{rule_id}?agent_id={PROBE_ID}", token)
        check("DELETE 幂等性：删不存在 id → 404（真读盘判定）", st == 404, f"status={st}")

        # 整表更新放在删除之后（它会整体覆写规则列表，先删会误伤 delete 用例）
        st, body = http("PUT", f"{BASE}/constitution?agent_id={PROBE_ID}", token, [{"content": "整表更新", "priority": 9}])
        check("PUT /constitution 整表更新 + envelope", st == 200 and body.get("code") == 0
              and body.get("data", {}).get("constitution") == [{"content": "整表更新", "priority": 9}],
              f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}/constitution?agent_id={PROBE_ID}", token)
        check("GET overview 读持久源", st == 200 and
              [r["content"] for r in body.get("data", {}).get("constitution", [])] == ["整表更新"],
              f"body={str(body)[:150]}")

        # ---------------- 路由清单普查 ----------------
        print("\n=== live app route census ===")
        # create_app 生产加固禁用 docs/openapi（404）→ 直接普查同实例 app.routes，
        # 该实例正是上面应答 HTTP 请求的实例，等价于 openapi 反映的注册面。
        growth_routes = {}
        for r in app.routes:
            p = getattr(r, "path", "")
            m = getattr(r, "methods", None)
            if m and "/growth" in p:
                growth_routes.setdefault(p, set()).update(m - {"HEAD", "OPTIONS"})
        personality_constitution = {
            p: sorted(m) for p, m in growth_routes.items()
            if "/personality" in p or "/constitution" in p
        }
        expected = {
            "/api/v1/growth/personality": ["GET", "PUT"],
            "/api/v1/growth/personality/traits": ["GET"],
            "/api/v1/growth/personality/evolve": ["POST"],
            "/api/v1/growth/constitution": ["GET", "PUT"],
            "/api/v1/growth/constitution/rules": ["GET", "POST"],
            "/api/v1/growth/constitution/rules/{rule_id}": ["DELETE", "PUT"],
        }
        check("live app personality/constitution 路径-方法与拆分前一致",
              personality_constitution == expected,
              f"actual={json.dumps(personality_constitution, ensure_ascii=False)}")
        print(f"  growth 域路由路径总数: {len(growth_routes)} (含 overview/capabilities/reflection/questions/proactive/motivation)")

    finally:
        PERSONALITY_FILE.unlink(missing_ok=True)
        CONSTITUTION_FILE.unlink(missing_ok=True)
        try:
            state = get_app_state()
            state["agents"].pop(PROBE_ID, None)
            server.should_exit = True
            thread.join(timeout=10)
        except Exception:
            pass

    print()
    if failures:
        print(f"FAILED: {len(failures)} 项未通过: {failures}")
        return 1
    print("ALL PASS: personality/constitution 全部路由真实 HTTP 往返与拆分前契约一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
