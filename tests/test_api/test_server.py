"""本地起一个最简 FastAPI 服务，手工探活用。

可运行脚本，不是测试模块：`python tests/test_api/test_server.py` 起服务。
路由函数名不得以 `test` 开头 —— 那种名字会被 pytest 当成用例名去收集，
而它按收集规则收不到（`def test` 不含下划线也不含驼峰），正是
`tests/unit/core/test_pytest_collection_hygiene.py` 点名的"看起来是用例却静默不跑"。
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="Test Server")

@app.get("/test")
def health():
    return {"status": "ok", "message": "测试服务器正常工作"}

if __name__ == "__main__":
    print("🚀 启动测试服务器在 http://0.0.0.0:9527")
    uvicorn.run(app, host="0.0.0.0", port=9527)
