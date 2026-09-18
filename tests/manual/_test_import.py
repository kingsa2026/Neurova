import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Test if the original context_legacy.py can import
try:
    # Clear any cached modules
    for key in list(sys.modules.keys()):
        if 'neurova' in key:
            del sys.modules[key]
    
    from neurova.context_legacy import ContextBuilder
    print("context_legacy import OK:", ContextBuilder)
except Exception as e:
    print("context_legacy import FAIL:", e)
    import traceback
    traceback.print_exc()

# Test if neurova.core.base_module can be found via the pyc
try:
    from neurova.core.base_module import BaseModule
    print("base_module import OK:", BaseModule)
except Exception as e:
    print("base_module import FAIL:", e)
