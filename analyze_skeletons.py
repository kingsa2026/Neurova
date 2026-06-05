import pathlib, re
root = pathlib.Path(r'E:\项目\Neurova\neurova')
all_files = []
for p in root.rglob('*.py'):
    if '__pycache__' in str(p):
        continue
    text = p.read_text(encoding='utf-8', errors='ignore')
    stubs = len(re.findall(r'def\s+\w+\(\*args,\s*\*\*kwargs\):', text))
    todos = len(re.findall(r'Auto-restored from .pyc', text))
    total = stubs + todos
    if total:
        all_files.append((total, p.relative_to(root), stubs, todos))
all_files.sort(reverse=True)
print("TOTAL  STUB  TODO  path")
for total, path, stubs, todos in all_files:
    print(f"{total:5d} {stubs:4d} {todos:4d}  {path}")
print()
print(f"Grand total: {sum(f[0] for f in all_files)} placeholders in {len(all_files)} files")
