"""Bypass neurova.knowledge.__init__ which has broken transitive imports."""
import importlib.util
import sys
from pathlib import Path

_STORAGE_PATH = Path(__file__).resolve().parents[2] / "neurova" / "knowledge" / "storage.py"
_spec = importlib.util.spec_from_file_location("neurova.knowledge.storage", _STORAGE_PATH)
_mod = importlib.util.module_from_spec(_spec)
_pkg = sys.modules.setdefault("neurova.knowledge", type(sys)("neurova.knowledge"))
_pkg.__path__ = [str(_STORAGE_PATH.parent)]
sys.modules["neurova.knowledge.storage"] = _mod
_spec.loader.exec_module(_mod)
# 挂到父包属性：monkeypatch.setattr("neurova.knowledge.xxx") 需要
# neurova.knowledge 可经 getattr 链解析（sys.modules 注册不等于属性挂载）
import neurova as _neurova

_neurova.knowledge = _pkg
