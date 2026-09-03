import sys
sys.path.insert(0, '.')

try:
    from neurova.api.endpoints import settings
    print("settings module imported successfully")
    print(f"router: {settings.router}")
except Exception as e:
    print(f"Error importing settings: {e}")
    import traceback
    traceback.print_exc()

try:
    from neurova.api.endpoints import sandbox
    print("sandbox module imported successfully")
    print(f"router: {sandbox.router}")
except Exception as e:
    print(f"Error importing sandbox: {e}")
    import traceback
    traceback.print_exc()

try:
    from neurova.api.endpoints import benchmark
    print("benchmark module imported successfully")
    print(f"router: {benchmark.router}")
except Exception as e:
    print(f"Error importing benchmark: {e}")
    import traceback
    traceback.print_exc()