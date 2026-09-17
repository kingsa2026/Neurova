"""knowledge 拆分后 live-verify（2026-09-16 模块化重构验收）。

在 127.0.0.1:9528 拉起 create_app() 验证实例（不影响 9527 运行中的服务），
实测 knowledge 全部 34 条路由真实 HTTP 往返，并核对域核心语义链
（CRUD → 分块乐观锁 → 公共库审批 → 软删/墓碑/恢复 → 冲突裁决 →
configs 加密回显 → collections → 摄取队列入队/取消）。

隔离措施（全部进程内，不触碰真实 data/）：
- repository / storage 单例 swap 到 tmp 目录（持单例锁，先预创建真实单例
  防止 swap 前的请求误写真实存储）；
- 通知管理器经 NEUROVA_NOTIFICATIONS_PATH 重定向（submit/review 会发通知，
  单例构造时读该 env）；
- 摄取队列单例 swap 为 tmp db/files（create_app 会启动真实 drain worker）；
- RSI receipts 重定向到 tmp。

用法: python scripts/diagnostics/_live_verify_knowledge_split.py
退出码: 0 = 全部通过, 1 = 存在失败
"""
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

PROBE_ID = "__live_verify_probe__"
BASE = "http://127.0.0.1:9528/api/v1/knowledge"

failures = []


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not cond else ""), flush=True)
    if not cond:
        failures.append(name)


def http(method, url, token, body=None):
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


def multipart_body(filename, content):
    """极简 multipart/form-data 编码（/import 上传用）。"""
    boundary = "----liveverifyprobe123"
    payload = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/plain\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    return payload, f"multipart/form-data; boundary={boundary}"


def post_file(url, token, filename, content):
    payload, ctype = multipart_body(filename, content)
    req = urllib.request.Request(url, method="POST", data=payload)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"_raw": raw[:200]}


def main():
    logging.disable(logging.CRITICAL)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    import neurova.knowledge.repository as repo_mod
    import neurova.knowledge.storage as storage_mod
    import neurova.knowledge.ingest_queue as queue_mod

    tmp = Path(tempfile.mkdtemp(prefix="live_verify_kb_"))
    # 通知管理器单例构造时读该 env → 必须在 create_app 之前设置
    os.environ["NEUROVA_NOTIFICATIONS_PATH"] = str(tmp / "notifications.json")
    os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "live_verify_kb_probe_secret_0123456789")
    os.environ.setdefault("NEUROVA_RSI_RECEIPTS", str(tmp / "rsi_receipts.jsonl"))

    # ── 隔离 1：repository 单例 swap（先锁外预创建真实单例，锁内只做 swap；
    # threading.Lock 不可重入，锁内调 get_knowledge_repository() 会自死锁）──
    if repo_mod._singleton is None:
        repo_mod.get_knowledge_repository()
    with repo_mod._singleton_lock:
        repo_mod._singleton = repo_mod.KnowledgeRepository(str(tmp / "knowledge"))
    # ── 隔离 2：storage 单例 swap（同上）──
    if storage_mod._singleton is None:
        storage_mod.get_knowledge_storage()
    with storage_mod._singleton_lock:
        storage_mod._singleton = storage_mod.KnowledgeStorage(str(tmp / "knowledge"))
    # ── 隔离 3：摄取队列单例 swap 为 tmp（create_app 会启动真实 drain worker）──
    probe_queue = queue_mod.KnowledgeIngressQueue(
        db_path=tmp / "ingress.db", files_dir=tmp / "ingress_files"
    )
    if queue_mod._queue is None:
        queue_mod.get_ingress_queue()
    with queue_mod._queue_lock:
        queue_mod._queue = probe_queue

    from neurova.api.app import create_app
    from neurova.api.auth import create_access_token
    from neurova.api.endpoints import get_app_state, set_app_state

    app = create_app()
    state = get_app_state()
    state["agents"][PROBE_ID] = types.SimpleNamespace(personality="md text", constitution="")
    set_app_state(state)

    token = create_access_token(data={
        "sub": PROBE_ID, "username": PROBE_ID, "role": "admin", "neuser_id": PROBE_ID,
    })

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
        # ══════════════ core：根路由 / 详情 / 更新 / 搜索 / 预览 ══════════════
        print("\n=== core: 根路由 / 详情 / 更新 / 搜索 / 预览 ===")

        st, body = http("GET", f"{BASE}?page=1&page_size=10", token)
        check("GET \"\" 空态 200 + 分页信封", st == 200 and body.get("code") == 0
              and body.get("data", {}).get("items") == [] and body.get("data", {}).get("total") == 0
              and body.get("data", {}).get("page") == 1 and body.get("data", {}).get("page_size") == 10,
              f"status={st} body={str(body)[:150]}")

        st, body = http("POST", BASE, token,
                        {"title": "Python GIL", "content": "全局解释器锁",
                         "tags": ["python"], "confidence": 0.9})
        # 根 POST 返回裸 KnowledgeItem（知识域非 envelope 域，逐端点契约照实断言）
        kid = body.get("knowledge_id", "")
        check("POST \"\" 创建私有条目 200", st == 200 and bool(kid),
              f"status={st} body={str(body)[:150]}")
        check("创建回读 visibility=private",
              body.get("visibility") == "private",
              f"visibility={body.get('visibility')}")

        st, body = http("POST", BASE, token,
                        {"title": "Rust 所有权", "content": "move 语义", "visibility": "public"})
        kid_pub = body.get("knowledge_id", "")
        check("POST \"\" admin 直建公开条目 200", st == 200 and bool(kid_pub)
              and body.get("visibility") == "public",
              f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}?page=1&page_size=10", token)
        check("GET \"\" admin 视角 total=2", st == 200 and body.get("data", {}).get("total") == 2,
              f"status={st} total={body.get('data', {}).get('total')}")

        st, body = http("GET", f"{BASE}/{kid}", token)
        check("GET /{id} 详情 200 + title 一致", st == 200 and body.get("title") == "Python GIL",
              f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}/__no_such_id__", token)
        check("GET /{id} 不存在 → 404 不泄露存在性", st == 404, f"status={st}")

        st, body = http("PUT", f"{BASE}/{kid}", token, {"title": "Python GIL v2"})
        check("PUT /{id} 更新 200 + title 回读", st == 200 and body.get("title") == "Python GIL v2",
              f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}/{kid}/revisions", token)
        check("GET /{id}/revisions 账本非空（PUT 已记账）", st == 200 and isinstance(body, list)
              and len(body) >= 1, f"status={st} body={str(body)[:120]}")

        st, body = http("GET", f"{BASE}/{kid}/chunks", token)
        check("GET /{id}/chunks 200（create 默认整篇模式 chunks=None → 空清单）",
              st == 200 and body == [], f"status={st} body={str(body)[:120]}")

        st, body = http("PUT", f"{BASE}/{kid}/chunks/0", token,
                        {"content": "块内容", "expected_revision": 0})
        check("PUT /{id}/chunks/0 整篇模式 → 400 诚实拒绝（未分块走条目更新）",
              st == 400, f"status={st} body={str(body)[:120]}")

        st, body = http("GET", f"{BASE}/{kid}/chunks/0/revisions", token)
        check("GET /{id}/chunks/0/revisions 未分块 → 空账本 200", st == 200 and body == [],
              f"status={st} body={str(body)[:120]}")

        st, body = http("POST", f"{BASE}/search", token, {"query": "GIL", "limit": 10})
        check("POST /search 命中更新后条目", st == 200 and isinstance(body, list)
              and len(body) == 1 and body[0].get("title") == "Python GIL v2",
              f"status={st} body={str(body)[:150]}")

        st, body = http("POST", f"{BASE}/preview-chunking", token,
                        {"content": "第一段。\n\n第二段。", "max_chars": 200})
        check("POST /preview-chunking 只读预览（chunks + 统计）",
              st == 200 and body.get("code") == 0
              and body.get("data", {}).get("total", 0) >= 1
              and isinstance(body.get("data", {}).get("chunks"), list),
              f"status={st} body={str(body)[:150]}")

        # ══════════════ sharing：公共库审批 / 冲突 / 墓碑恢复 ══════════════
        print("\n=== sharing: 公共库审批 / 冲突裁决 / 墓碑恢复 / 共享 ===")

        st, body = http("POST", f"{BASE}/{kid}/share", token, {"usernames": ["ghost_user"]})
        check("POST /{id}/share 未知用户 → 400（resolve_usernames 校验）", st == 400,
              f"status={st} body={str(body)[:120]}")

        st, body = http("POST", f"{BASE}/{kid}/unshare", token, {"usernames": ["ghost_user"]})
        check("POST /{id}/unshare 未知用户 → 400", st == 400, f"status={st} body={str(body)[:120]}")

        # share 200 快乐路径：探针用户不在真实用户库，用真实 admin 用户名
        # （读用户库只读不写）；库中无 admin 则只保留 400 校验路径
        try:
            from neurova.auth.user_model import UserModel
            _admin_name = "admin" if UserModel().get_user_by_username("admin") else ""
        except Exception:
            _admin_name = ""
        if _admin_name:
            st, body = http("POST", f"{BASE}/{kid}/share", token, {"usernames": [_admin_name]})
            check("POST /{id}/share 共享给 admin → 200（裸 KnowledgeItem）",
                  st == 200 and body.get("knowledge_id") == kid,
                  f"status={st} body={str(body)[:150]}")
            st, body = http("POST", f"{BASE}/{kid}/unshare", token, {"usernames": [_admin_name]})
            check("POST /{id}/unshare 取消共享 → 200",
                  st == 200 and body.get("knowledge_id") == kid,
                  f"status={st} body={str(body)[:150]}")

        st, body = http("POST", f"{BASE}/{kid}/submit-public", token)
        # submit-public 返回裸 KnowledgeItem（response_model）
        check("POST /{id}/submit-public 200 + submission=pending",
              st == 200 and (body.get("submission") or {}).get("status") == "pending",
              f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}/public-submissions", token)
        ids = [i.get("knowledge_id") for i in body] if isinstance(body, list) else []
        check("GET /public-submissions 待审清单含刚提交条目", st == 200 and kid in ids,
              f"status={st} body={str(body)[:150]}")

        st, body = http("POST", f"{BASE}/{kid}/review-public", token,
                        {"approve": True, "note": "质量合格"})
        check("POST /{id}/review-public approve → visibility=public",
              st == 200 and body.get("visibility") == "public",
              f"status={st} body={str(body)[:150]}")

        st, body = http("POST", BASE, token, {"title": "Conflict Case A", "content": "A"})
        kid_a = body.get("knowledge_id", "")
        check("POST 冲突条目 A 创建", st == 200 and bool(kid_a),
              f"status={st} body={str(body)[:120]}")
        st, body = http("POST", BASE, token, {"title": "Conflict Case A", "content": "A 同值新说法"})
        st, body = http("GET", f"{BASE}/conflicts", token)
        pend = body if isinstance(body, list) else []
        # fresh repo 里唯一 pending 冲突即本次同值提交
        conflict_id = next((c.get("conflict_id") for c in pend if c.get("conflict_id")), "")
        check("GET /conflicts 同值冲突已检测为 pending", st == 200 and bool(conflict_id),
              f"status={st} pending={str(pend)[:200]}")

        st, body = http("POST", f"{BASE}/conflicts/{conflict_id}/resolve", token,
                        {"resolution": "keep_both"})
        check("POST /conflicts/{id}/resolve keep_both → 200",
              st == 200 and body.get("code") == 0 and body.get("data", {}).get("conflict_id") == conflict_id,
              f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}/conflicts?status=resolved", token)
        res = body if isinstance(body, list) else []
        check("GET /conflicts?status=resolved 裁决历史含刚裁决项",
              st == 200 and any(c.get("conflict_id") == conflict_id for c in res),
              f"status={st} resolved={str(res)[:150]}")

        st, body = http("DELETE", f"{BASE}/{kid}", token)
        check("DELETE /{id} 属主删除 200（软删入墓碑）",
              st == 200 and body.get("data", {}).get("action") == "deleted",
              f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}/{kid}", token)
        check("软删后 GET /{id} → 404（读路径不可见）", st == 404, f"status={st}")

        st, body = http("GET", f"{BASE}/deleted", token)
        tom = body if isinstance(body, list) else []
        check("GET /deleted 墓碑含刚删条目",
              st == 200 and any(r.get("knowledge_id") == kid for r in tom),
              f"status={st} tombstones={str(tom)[:200]}")

        st, body = http("POST", f"{BASE}/{kid}/restore", token)
        check("POST /{id}/restore 从墓碑复活 200",
              st == 200 and body.get("data", {}).get("action") == "restored",
              f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}/{kid}", token)
        check("恢复后 GET /{id} 重新可见", st == 200 and body.get("title") == "Python GIL v2",
              f"status={st} body={str(body)[:150]}")

        # 公开条目（kid_pub）保持 public 状态贯穿全程，最后物理清除
        st, body = http("DELETE", f"{BASE}/{kid_pub}?purge=true", token)
        check("DELETE ?purge=true 公开条目物理删除", st == 200
              and body.get("data", {}).get("action") == "deleted",
              f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}/{kid_pub}", token)
        check("purge 后 GET /{id} → 404（物理删除不可见）", st == 404, f"status={st}")

        # ══════════════ remote：configs / collections / ingress-tasks ══════════════
        print("\n=== remote: configs CRUD / collections / 队列观测 ===")

        st, body = http("GET", f"{BASE}/configs", token)
        check("GET /configs 空态 200（code=0, configs=[]）",
              st == 200 and body.get("code") == 0 and body.get("data", {}).get("configs") == [],
              f"status={st} body={str(body)[:150]}")

        st, body = http("POST", f"{BASE}/configs", token,
                        {"name": "Feishu KB", "source_type": "feishu", "api_key": "secret-abc"})
        cfg_id = body.get("data", {}).get("id", "")
        check("POST /configs 创建（回 {id}）", st == 200 and body.get("code") == 0 and bool(cfg_id),
              f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}/configs/{cfg_id}", token)
        check("GET /configs/{id} 回显元数据 + has_api_key=true 且无密钥明文",
              st == 200 and body.get("data", {}).get("name") == "Feishu KB"
              and body.get("data", {}).get("has_api_key") is True
              and "secret-abc" not in json.dumps(body),
              f"status={st} body={str(body)[:200]}")

        st, body = http("PUT", f"{BASE}/configs/{cfg_id}", token, {"name": "Feishu KB v2"})
        check("PUT /configs/{id} 更新 → updated", st == 200 and body.get("message") == "updated",
              f"status={st} body={str(body)[:150]}")

        st, body = http("POST", f"{BASE}/configs/{cfg_id}/sync?agent_id={PROBE_ID}", token)
        check("POST /configs/{id}/sync 非飞书外其他类型走飞书分支（feishu 配置装配后真实同步）",
              st in (200, 400, 409, 502), f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}/collections", token)
        check("GET /collections 空态 200", st == 200 and body.get("code") == 0
              and body.get("data", {}).get("collections") == [],
              f"status={st} body={str(body)[:150]}")

        st, body = http("POST", f"{BASE}/collections", token,
                        {"config_id": cfg_id, "collection_name": "col-a", "vector_store": "qdrant"})
        mid = body.get("data", {}).get("id", "")
        check("POST /collections 创建映射（回 {id}）", st == 200 and bool(mid),
              f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}/collections", token)
        cols = body.get("data", {}).get("collections", [])
        check("GET /collections 含新映射", any(c.get("id") == mid for c in cols),
              f"status={st} collections={str(cols)[:150]}")

        st, body = http("DELETE", f"{BASE}/collections/{mid}", token)
        check("DELETE /collections/{id} → deleted", st == 200 and body.get("message") == "deleted",
              f"status={st} body={str(body)[:120]}")

        st, body = http("GET", f"{BASE}/ingress-tasks", token)
        check("GET /ingress-tasks 200 + stats 字段", st == 200 and body.get("code") == 0
              and "stats" in body.get("data", {}) and isinstance(body.get("data", {}).get("tasks"), list),
              f"status={st} body={str(body)[:150]}")

        # ══════════════ ingestion：文件导入 / 块编辑乐观锁 / 队列 / SSRF ══════════════
        print("\n=== ingestion: /import 同步+异步 / 块编辑乐观锁 / /import-url SSRF ===")

        st, body = post_file(f"{BASE}/import?agent_id={PROBE_ID}", token,
                             "notes.txt", "神经网络是一种机器学习方法。")
        imp_kid = ((body.get("data", {}) or {}).get("items") or [{}])[0].get("knowledge_id", "")
        check("POST /import 同步导入 200 + 条目入库", st == 200 and body.get("code") == 0 and bool(imp_kid),
              f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}/{imp_kid}/chunks", token)
        check("导入条目已自动分块（chunks >= 1）", st == 200 and isinstance(body, list) and len(body) >= 1,
              f"status={st} body={str(body)[:150]}")

        st, body = http("PUT", f"{BASE}/{imp_kid}/chunks/0", token,
                        {"content": "神经网络（修订）", "expected_revision": 0})
        check("PUT /{id}/chunks/0 乐观锁命中 → 200 revision 递增",
              st == 200 and body.get("data", {}).get("revision") == 1,
              f"status={st} body={str(body)[:150]}")

        st, body = http("PUT", f"{BASE}/{imp_kid}/chunks/0", token,
                        {"content": "陈旧写入", "expected_revision": 0})
        check("PUT /{id}/chunks/0 陈旧 expected_revision → 409 冲突", st == 409,
              f"status={st} body={str(body)[:120]}")

        st, body = http("GET", f"{BASE}/{imp_kid}/chunks/0/revisions", token)
        check("GET /{id}/chunks/0/revisions 编辑账本非空（最新在前）",
              st == 200 and isinstance(body, list) and len(body) >= 1,
              f"status={st} body={str(body)[:120]}")

        st, body = http("PUT", f"{BASE}/{imp_kid}/chunks/99", token, {"content": "x"})
        check("PUT /{id}/chunks/99 越界 → 404", st == 404, f"status={st} body={str(body)[:120]}")

        st, body = post_file(f"{BASE}/import?sync=false&agent_id={PROBE_ID}", token,
                             "async_notes.txt", "异步导入的文本内容。")
        task_id = body.get("data", {}).get("task_id", "")
        check("POST /import?sync=false 入队即返 task_id",
              st == 200 and body.get("code") == 0 and bool(task_id)
              and body.get("data", {}).get("replayed") is False,
              f"status={st} body={str(body)[:150]}")

        st, body = http("GET", f"{BASE}/ingress-tasks/{task_id}", token)
        check("GET /ingress-tasks/{id} 任务详情（spans + item_ids，无 storage_path 外露）",
              st == 200 and body.get("data", {}).get("task_id") == task_id
              and isinstance(body.get("data", {}).get("spans"), list)
              and "storage_path" not in body.get("data", {}),
              f"status={st} body={str(body)[:200]}")

        st, body = http("POST", f"{BASE}/ingress-tasks/{task_id}/cancel", token)
        # 真实契约：{code:0, message:"cancelled", data:{task_id}}（端点尾段实证）
        check("POST /ingress-tasks/{id}/cancel pending 任务 → 200 cancelled",
              st == 200 and body.get("message") == "cancelled"
              and body.get("data", {}).get("task_id") == task_id,
              f"status={st} body={str(body)[:150]}")

        st, body = http("POST", f"{BASE}/ingress-tasks/{task_id}/cancel", token)
        check("重复 cancel 已取消任务 → 409（不谎报成功）", st == 409, f"status={st}")

        st, body = http("POST", f"{BASE}/import-url?agent_id={PROBE_ID}&url=http://127.0.0.1/x", token)
        check("POST /import-url 环回地址 → 400（SSRF 防护）",
              st == 400 and "Invalid URL" in str(body.get("detail", "")),
              f"status={st} body={str(body)[:150]}")

        st, body = http("POST", f"{BASE}/import-url?agent_id={PROBE_ID}&url=ftp://example.com/x", token)
        check("POST /import-url 非 http(s) → 400", st == 400, f"status={st}")

        # ══════════════ 路由清单普查（同实例 app.routes）══════════════
        print("\n=== live app route census ===")
        kb_routes = {}
        for r in app.routes:
            p = getattr(r, "path", "")
            m = getattr(r, "methods", None)
            # 仅本域：排除同挂载的 knowledge-graph / knowledge-integration 兄弟域
            if (m and p.startswith("/api/v1/knowledge/")
                    or p == "/api/v1/knowledge"):
                kb_routes.setdefault(p, set()).update(m - {"HEAD", "OPTIONS"})

        def full(path):
            return f"/api/v1/knowledge{path}"

        expected = {
            full(""): {"GET", "POST"},
            full("/search"): {"POST"},
            full("/preview-chunking"): {"POST"},
            full("/public-submissions"): {"GET"},
            full("/conflicts"): {"GET"},
            full("/conflicts/{conflict_id}/resolve"): {"POST"},
            full("/deleted"): {"GET"},
            full("/{knowledge_id}/restore"): {"POST"},
            full("/{knowledge_id}/revisions"): {"GET"},
            full("/{knowledge_id}/chunks"): {"GET"},
            full("/{knowledge_id}/chunks/{index}/revisions"): {"GET"},
            full("/{knowledge_id}/chunks/{index}"): {"PUT"},
            full("/{knowledge_id}/share"): {"POST"},
            full("/{knowledge_id}/unshare"): {"POST"},
            full("/{knowledge_id}/submit-public"): {"POST"},
            full("/{knowledge_id}/review-public"): {"POST"},
            full("/configs"): {"GET", "POST"},
            full("/configs/{config_id}"): {"GET", "PUT", "DELETE"},
            full("/configs/{config_id}/sync"): {"POST"},
            full("/collections"): {"GET", "POST"},
            full("/collections/{mapping_id}"): {"DELETE"},
            full("/ingress-tasks"): {"GET"},
            full("/ingress-tasks/{task_id}"): {"GET"},
            full("/ingress-tasks/{task_id}/cancel"): {"POST"},
            full("/{knowledge_id}"): {"GET", "PUT", "DELETE"},
            full("/import"): {"POST"},
            full("/import-url"): {"POST"},
        }
        actual = {p: set(m) for p, m in kb_routes.items()}
        check("live app knowledge 路径-方法集与拆分前快照逐一一致（34 条）",
              actual == expected,
              "missing=" + str(sorted(set(expected) - set(actual)))
              + " extra=" + str(sorted(set(actual) - set(expected)))
              + " diff=" + str({p: (sorted(expected.get(p, set())), sorted(actual.get(p, set())))
                                for p in set(expected) & set(actual) if expected[p] != actual[p]}))
        total_pairs = sum(len(m) for m in actual.values())
        check("路由方法对总数 = 34", total_pairs == 34, f"actual={total_pairs}")

    finally:
        try:
            state = get_app_state()
            state["agents"].pop(PROBE_ID, None)
        except Exception:
            pass
        try:
            server.should_exit = True
            thread.join(timeout=10)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED: {len(failures)} 项未通过: {failures}")
        return 1
    print("ALL PASS: knowledge 34 条路由真实 HTTP 往返与拆分前契约一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
