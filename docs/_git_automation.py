"""
Neurova GitHub Automation Script
Runs on remote server to handle git operations and releases.
"""
import subprocess
import os
import sys
import json
import re

REPO_URL = "https://github.com/kingsa2026/Neurova.git"
WORK_DIR = "/workspace/neurova-repo"

def run(cmd, cwd=None, check=True):
    """Run a shell command and return output."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        cwd=cwd or WORK_DIR
    )
    if result.returncode != 0 and check:
        print(f"ERROR running: {cmd}")
        print(f"STDERR: {result.stderr}")
    return result.stdout.strip(), result.stderr.strip(), result.returncode

def setup_repo():
    """Clone or update the repo."""
    if not os.path.exists(WORK_DIR):
        print(f"Cloning repo to {WORK_DIR}...")
        os.makedirs(os.path.dirname(WORK_DIR), exist_ok=True)
        out, err, rc = run(f"git clone {REPO_URL} {WORK_DIR}", cwd="/workspace")
        if rc != 0:
            print(f"Clone failed: {err}")
            return False
        print(out or "Clone successful")
    else:
        print("Repo exists, fetching...")
        os.chdir(WORK_DIR)
        run("git fetch origin")
        run("git checkout fix/pyc-import-recovery 2>/dev/null || git checkout main")
    return True

def get_current_version():
    """Get the latest version from git tags."""
    out, _, _ = run("git tag --sort=-v:refname | grep -E '^v?[0-9]+\\.[0-9]+\\.[0-9]+$' | head -5", check=False)
    if not out:
        return "0.0.0"
    tags = out.strip().split('\n')
    for tag in tags:
        tag = tag.strip().lstrip('v')
        if re.match(r'^\d+\.\d+\.\d+$', tag):
            return tag
    return "0.0.0"

def bump_version(current_version):
    """Increment the patch version: 0.0.1 -> 0.0.2"""
    parts = current_version.split('.')
    parts[-1] = str(int(parts[-1]) + 1)
    return '.'.join(parts)

def get_changes():
    """Get list of changed files."""
    out, _, _ = run("git status --porcelain")
    if not out:
        return []
    changes = []
    for line in out.split('\n'):
        line = line.strip()
        if line:
            changes.append(line)
    return changes

def get_diff_summary():
    """Get a summary of changes."""
    out, _, _ = run("git diff --stat HEAD")
    return out

def get_untracked_files():
    """Get untracked files."""
    out, _, _ = run("git ls-files --others --exclude-standard")
    return out.split('\n') if out else []

def commit_and_push(new_version):
    """Stage all changes, commit and push."""
    changes = get_changes()
    untracked = get_untracked_files()
    
    if not changes and not any(u.strip() for u in untracked):
        print("No changes to commit")
        return False
    
    print(f"Changes detected:")
    for c in changes:
        print(f"  {c}")
    for u in untracked:
        if u.strip():
            print(f"  ?? {u}")
    
    # Stage all changes
    run("git add -A")
    
    # Create commit message
    commit_msg = f"v{new_version}: Automated release - {len(changes)} changes"
    out, err, rc = run(f'git commit -m "{commit_msg}"')
    if rc != 0:
        print(f"Commit failed or nothing to commit: {err}")
        return False
    
    print(f"Committed successfully")
    
    # Push
    branch, _, _ = run("git rev-parse --abbrev-ref HEAD")
    print(f"Pushing to origin/{branch}...")
    out, err, rc = run(f"git push origin {branch}")
    print(out or err)
    
    return rc == 0

def create_release(new_version):
    """Create a GitHub release tag and push."""
    tag = f"v{new_version}"
    
    # Create tag
    out, err, rc = run(f"git tag -a {tag} -m 'Release {tag}'")
    if rc != 0:
        print(f"Tag creation warning: {err}")
    
    # Push tag
    out, err, rc = run(f"git push origin {tag}")
    print(f"Tag push: {out or err}")
    
    # Show release info
    log, _, _ = run("git log -1 --pretty=format:'%h - %s'")
    
    print(f"\n{'='*60}")
    print(f"Release {tag} created and pushed!")
    print(f"Latest commit: {log}")
    print(f"{'='*60}")
    
    return tag

def main():
    print("=" * 60)
    print("Neurova GitHub Automation")
    print("=" * 60)
    
    # Setup repo
    if not setup_repo():
        print("Failed to setup repo")
        sys.exit(1)
    
    os.chdir(WORK_DIR)
    
    # Show current branch and latest commits
    branch, _, _ = run("git rev-parse --abbrev-ref HEAD")
    log, _, _ = run("git log --oneline -5")
    print(f"Branch: {branch}")
    print(f"Recent commits:\n{log}")
    
    # Get current version
    current = get_current_version()
    print(f"\nCurrent latest version: v{current}")
    
    # Check changes
    diff_summary = get_diff_summary()
    changes = get_changes()
    print(f"\nWorking tree changes: {len(changes)}")
    if changes:
        for c in changes[:20]:
            print(f"  {c}")
        if len(changes) > 20:
            print(f"  ... and {len(changes) - 20} more")
    
    if not changes:
        untracked = get_untracked_files()
        if not any(u.strip() for u in untracked):
            print("\nNo changes detected. Nothing to commit.")
            return
    
    # Bump version
    new_version = bump_version(current)
    print(f"\nNew version: v{new_version}")
    
    # Commit and push
    if commit_and_push(new_version):
        # Create release
        create_release(new_version)
    
    # Final status
    log, _, _ = run("git log --oneline -3")
    print(f"\nFinal commits:\n{log}")
    print("\nDone!")

if __name__ == "__main__":
    main()
