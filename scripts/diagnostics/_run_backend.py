"""临时脚本：仅启动本地后端（9527），供手工调试时单独拉起服务。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn
from neurova.api.app import create_app

app = create_app()
uvicorn.run(app, host="127.0.0.1", port=9527, log_level="info")
