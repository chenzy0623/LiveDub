"""github.com 的 443 端口被墙时，用 api.github.com 走 Git Data API 把本地提交推上去。

等价于 `git push`，只是传输走 REST：
    blobs → tree → commit → 更新 refs/heads/main

改动文件的判定不依赖 merge-base（本地和远端可能没有共同祖先历史，
因为远端提交也是用这个脚本生成的）。改用「内容寻址比对」：
远端 tree（recursive）与本地 `git ls-tree -r HEAD` 的 blob sha 逐项对比。

用法：
    python tools/push_via_api.py            # 推送 HEAD
    python tools/push_via_api.py --dry-run  # 只打印要传的文件
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = "chenzy0623/LiveDub"
API = "https://api.github.com"
ROOT = Path(__file__).resolve().parent.parent
BRANCH = "main"


def token() -> str:
    return subprocess.check_output(["gh", "auth", "token"], text=True).strip()


TOK = token()


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOK}")
    req.add_header("Accept", "application/vnd.github+json")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def git(*args: str) -> str:
    out = subprocess.check_output(["git", *args], cwd=ROOT)
    return out.decode("utf-8", "replace").strip()


def remote_tree(tree_sha: str) -> dict[str, tuple[str, str]]:
    """远端 tree → {path: (sha, mode)}。"""
    data = call("GET", f"/repos/{REPO}/git/trees/{tree_sha}?recursive=1")
    out: dict[str, tuple[str, str]] = {}
    for item in data.get("tree", []):
        if item.get("type") == "blob":
            out[item["path"]] = (item["sha"], item.get("mode", "100644"))
    return out


def local_tree(rev: str = "HEAD") -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for line in git("ls-tree", "-r", rev).splitlines():
        meta, path = line.split("\t", 1)
        mode, _kind, sha = meta.split()
        out[path] = (sha, mode)
    return out


def main() -> int:
    dry = "--dry-run" in sys.argv
    local = git("rev-parse", "HEAD")
    ref = call("GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}")
    remote = ref["object"]["sha"]
    if local == remote:
        print("✓ 远端已是最新，无需推送")
        return 0

    rtree = remote_tree(call("GET", f"/repos/{REPO}/git/commits/{remote}")["tree"]["sha"])
    ltree = local_tree(local)

    tree: list[dict] = []
    count = 0
    for path, (sha, mode) in sorted(ltree.items()):
        old = rtree.get(path)
        if old is None:
            action = "+"
        elif old[0] != sha or old[1] != mode:
            action = "M"
        else:
            continue
        count += 1
        if not dry:
            data = (ROOT / path).read_bytes()
            blob = call("POST", f"/repos/{REPO}/git/blobs",
                        {"content": base64.b64encode(data).decode(), "encoding": "base64"})
            tree.append({"path": path, "mode": mode if mode in ("100644", "100755") else "100644",
                         "type": "blob", "sha": blob["sha"]})
            print(f"  {action} {path} ({len(data)} B)")
        else:
            print(f"  {action} {path}")

    for path in sorted(set(rtree) - set(ltree)):
        count += 1
        tree.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
        print(f"  - {path}")

    if count == 0:
        print("内容一致，无需推送")
        return 0
    if dry:
        print(f"（dry-run）共 {count} 个文件待推送，取消")
        return 0

    base_tree = call("GET", f"/repos/{REPO}/git/commits/{remote}")["tree"]["sha"]
    new_tree = call("POST", f"/repos/{REPO}/git/trees",
                    {"base_tree": base_tree, "tree": tree})["sha"]
    message = git("log", "-1", "--pretty=%B", local)
    commit = call("POST", f"/repos/{REPO}/git/commits",
                  {"message": message, "tree": new_tree, "parents": [remote]})
    call("PATCH", f"/repos/{REPO}/git/refs/heads/{BRANCH}",
         {"sha": commit["sha"], "force": False})
    subprocess.run(["git", "update-ref", f"refs/remotes/origin/{BRANCH}", commit["sha"]],
                   cwd=ROOT, check=False)
    print(f"✓ 已推送 {len(tree)} 个文件，远端 {BRANCH} = {commit['sha'][:7]}")
    print(f"  https://github.com/{REPO}/commit/{commit['sha']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
