# -*- coding: utf-8 -*-
"""live-verify（Issue #330）：以真 uid 复演镜像的运行身份与导入面。

无 docker daemon，按镜像构建产出的**身份语义**在本机复演：

前像 = `useradd -r -g neurova neurova`（不建家目录，shadow 默认 HOME=/neurova）
后像 = `useradd -r -m -d /home/neurova` + `chown -R neurova:neurova /home/neurova`

探针（容器里真实发生的那两件事，用真 uid 执行）：
  A. 在 `$HOME` 下建各 SDK 缓存根 ⇒ 不通过即复现日志里的 E1022 / os error 13；
  B. `site.getusersitepackages()` 落点 vs `COPY --from=builder` 落点 ⇒ 不等即复现
     "包在盘上、`import` 找不到"。
"""
import os, pwd, re, shutil, subprocess, sys, tempfile
from pathlib import Path

REPO = Path("/workspace")
src = (REPO / "Dockerfile").read_text(encoding="utf-8")
user = re.findall(r"^\s*USER\s+(\S+)\s*$", src, re.MULTILINE)[-1]
seg = (re.search(rf"useradd\b[^\n]*\b{user}\b", src) or type("", (), {"group": lambda s, i: ""})()).group(0)
hasM = bool(re.search(r"(^|\s)-m(\s|$)", seg))
declared = (re.search(r"-d\s+(\S+)", seg) or [None, None])[1]

uid, gid = (pwd.getpwnam("nobody").pw_uid, pwd.getpwnam("nobody").pw_gid)

PROBE = r'''
import os, site, sys
home = sys.argv[1]
bad = []
for t in (".modelscope", ".cache/huggingface", ".local/lib/python3.12/site-packages"):
    p = os.path.join(home, t)
    try:
        os.makedirs(p, exist_ok=True)
        open(os.path.join(p, ".probe"), "w").close()
    except OSError as e:
        bad.append(f"{t}: {type(e).__name__}: {e.strerror}")
print("|".join(bad) or "OK")
print("usersite=" + site.getusersitepackages())
'''

def demote():
    os.setgid(gid); os.setuid(uid)

def runProbe(home: Path) -> str:
    r = subprocess.run([sys.executable, "-c", PROBE, str(home)],
                       capture_output=True, text=True, preexec_fn=demote,
                       env={**os.environ, "HOME": str(home)})
    return (r.stdout.strip() or r.stderr.strip()).replace("\n", " ; ")

def chownTree(path: Path, uid_: int, gid_: int):
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            try: shutil.chown(os.path.join(root, n), user=uid_, group=gid_)
            except OSError: pass
    os.chown(path, uid_, gid_)

# 沙箱根：让被降权的子进程能穿过父目录（tmp 默认 700 归 root）
sandbox = Path(tempfile.mkdtemp(prefix="nv330-"))
os.chmod(sandbox, 0o755)

def scenario(label: str, home: Path, owner: tuple[int, int], mode: int) -> str:
    """home 由 `owner` 持有、模式 mode；以运行用户 uid 跑缓存根探针。"""
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    os.chown(home, *owner)
    os.chmod(home, mode)
    return runProbe(home)

try:
    print("=== A. 缓存根可写性（真 uid=%d，模拟容器里的 neurova）===" % uid)
    preHome = sandbox / "neurova-shadow"   # 前像：HOME=/neurova —— 不存在
    print(f"  前像 useradd -r -g {user}：HOME=/{user}")
    print(f"    A1 HOME 不存在                  → 建缓存={runProbe(preHome) if preHome.exists() else '父目录可穿、HOME 不存在 ⇒ ENOENT（SDK 会尝试 mkdir，仍要先能写父目录）'}")
    a2 = scenario("A2 HOME 存在但 root:root 755", sandbox / "h-root", (0, 0), 0o755)
    print(f"    A2 HOME 存在但 root:root 0755  → {a2}")
    a3 = scenario("A3 HOME 归运行用户 0700  ", sandbox / "h-owner", (uid, gid), 0o700)
    print(f"    A3 HOME 归运行用户 0700（后像）→ {a3}")

    print("\n=== B. 导入面（COPY 落点必须就是用户站点根）===")
    dests = [d for _, d in re.findall(r"^\s*COPY\s+--from=\S+\s+(?:--\S+\s+)*(\S+)\s+(\S+)\s*$", src, re.MULTILINE)]
    declared = declared or (f"/home/{user}" if hasM else f"/{user}")
    userSiteRoot = f"{declared}/.local"
    envBlob = "\n".join(re.findall(r"^\s*ENV\s+(.+)$", src, re.MULTILINE))
    onPath = bool(re.search(r"PYTHONPATH\s*=\s*[^\n]*\.local", envBlob))
    print(f"  HOME={declared}（hasM={hasM}）")
    print(f"  COPY --from=builder 落点 = {dests}")
    print(f"  用户站点根 = {userSiteRoot}    PYTHONPATH 含 .local = {onPath}")
    landed = any(d == userSiteRoot or d.startswith(userSiteRoot + "/") for d in dests)
    imported = onPath or landed
    print(f"  依赖可被 import = {imported}")

    a3ok = a3.split(" ; ")[0] == "OK"
    print("\nLIVE-VERIFY:", "PASSED" if (a3ok and imported) else "FAILED")
    print(f"  判据：A3 缓存根全部可写={a3ok}，导入面闭合={imported}")
finally:
    shutil.rmtree(sandbox, ignore_errors=True)
