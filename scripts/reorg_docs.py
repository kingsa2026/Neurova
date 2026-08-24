#!/usr/bin/env python
"""
Neurova 文档单一事实源 —— 安全重组脚本

功能：
  将 docs/ 下 139 个扁平 .md 文件按主题移入已有子目录（bug/ memory/ architecture/
  research/ reports/ 等），并识别冗余簇。

安全设计：
  - 默认 --dry-run，只打印计划，不改动任何文件。
  - 用 git mv（若仓库已初始化）保留历史；否则用 os.rename。
  - 目标已存在同名文件则跳过并报警（绝不覆盖）。
  - 删除冗余簇前必须显式 --apply --purge，且只删除白名单内的文件。

用法：
  python scripts/reorg_docs.py --dry-run        # 预览
  python scripts/reorg_docs.py --apply          # 执行移动（不删文件）
  python scripts/reorg_docs.py --apply --purge  # 执行移动 + 删除白名单冗余
"""
import os, re, argparse, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")

# 导航文件：必须留在 docs/ 根，禁止移动
PROTECTED = {"INDEX.md", "REORG_PLAN.md", "README.md"}

# 主题 -> 目标子目录（子目录不存在则自动创建）
RULES = [
    (r"bug|fix|修复", "bug"),
    (r"memory|记忆", "memory"),
    (r"graph|图谱|knowledge", "architecture"),
    (r"architecture|架构|design", "architecture"),
    (r"voice|tts|audio|语音", "voice"),
    (r"plugin|skill|技能", "plugins-skills"),
    (r"harmony|鸿蒙", "harmony"),
    (r"ui|frontend|前端|页面", "web"),
    (r"comparison|vs_|对标|analysis", "research"),
    (r"report|报告|summary|总结", "reports"),
]

# 冗余白名单：仅在 --purge 时删除（保留权威 + 必要参考）
PURGE_WHITELIST = {
    "memory-system-upgrade-summary.md",
    "neurova-memory-system-upgrade-technical.md",
    "memory-nerf-upgrade-plan.md",
    "nerf-memory-system-analysis.md",
    "nerf-frontend-adaptation-summary.md",
}

def classify(name: str):
    low = name.lower()
    for pat, sub in RULES:
        if re.search(pat, low):
            return sub
    return "misc"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="执行移动（默认仅预览）")
    ap.add_argument("--purge", action="store_true", help="同时删除白名单冗余（需 --apply）")
    args = ap.parse_args()
    dry = not args.apply

    moves, purges, skips = [], [], []
    flat = sorted(f for f in os.listdir(DOCS) if f.endswith(".md") and os.path.isfile(os.path.join(DOCS, f)))

    for f in flat:
        if f in PROTECTED:
            skips.append((f, "导航文件，保留在 docs/"))
            continue
        sub = classify(f)
        # 权威文档显式归位
        if f == "NEUROVA_CogArch_2.0.md":
            sub = "architecture"
        elif f in ("API_REFERENCE.md", "API_CALLING_SPECIFICATION.md"):
            sub = "api"
        elif f in ("HARMONYOS_DESIGN.md",):
            sub = "harmony"
        dest_dir = os.path.join(DOCS, sub)
        dest = os.path.join(dest_dir, f)
        if os.path.exists(dest):
            skips.append((f, "目标已存在"))
            continue
        moves.append((f, sub))

    # 冗余文件
    for f in flat:
        if f in PURGE_WHITELIST:
            purges.append(f)

    print(f"[dry-run={dry}] docs/ 扁平文件: {len(flat)}")
    print(f"  计划移动: {len(moves)}  跳过: {len(skips)}  待删冗余: {len(purges)}")
    if dry:
        for f, sub in moves:
            print(f"  MOVE  {f}  ->  {sub}/")
        for f in purges:
            print(f"  PURGE {f}")
        for f, r in skips:
            print(f"  SKIP  {f}  ({r})")
        return

    # 执行
    for f, sub in moves:
        dest_dir = os.path.join(DOCS, sub)
        os.makedirs(dest_dir, exist_ok=True)
        src, dest = os.path.join(DOCS, f), os.path.join(dest_dir, f)
        try:
            if os.path.exists(os.path.join(ROOT, ".git")):
                import subprocess
                subprocess.run(["git", "mv", src, dest], check=True, cwd=ROOT)
            else:
                shutil.move(src, dest)
            print(f"  moved {f} -> {sub}/")
        except Exception as e:
            print(f"  ERR   {f}: {e}")

    if args.purge:
        for f in purges:
            p = os.path.join(DOCS, f)
            if os.path.exists(p):
                os.remove(p)
                print(f"  deleted {f}")

if __name__ == "__main__":
    main()
