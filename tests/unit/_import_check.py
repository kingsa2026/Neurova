import sys
print("Python version:", sys.version)
try:
    from neurova.tool_layers.tool_router import ToolRouter
    print("ToolRouter imported successfully")
except Exception as e:
    print("Import error:", e)
    import traceback
    traceback.print_exc()
