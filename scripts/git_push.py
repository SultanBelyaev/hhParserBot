#!/usr/bin/env python3
"""Commit and push to GitHub using GITHUB_TOKEN from .env (never commit the token)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    env_path = ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        values[key.strip()] = val
    return values


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=check)


def api_request(token: str, method: str, url: str, data: dict | None = None) -> dict:
    body = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "hh-parser-git-push",
    }
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {exc.code}: {raw}") from exc


def ensure_repo(token: str, repo: str) -> str:
    """Return clone URL without embedding token."""
    if "/" not in repo:
        raise RuntimeError("GITHUB_REPO должен быть в формате username/hh-parser")
    owner, name = repo.split("/", 1)
    try:
        api_request(token, "GET", f"https://api.github.com/repos/{owner}/{name}")
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise
        api_request(
            token,
            "POST",
            "https://api.github.com/user/repos",
            {"name": name, "private": True, "description": "HH.ru auto-apply parser"},
        )
    return f"https://github.com/{owner}/{name}.git"


def main() -> int:
    env = load_env()
    token = env.get("GITHUB_TOKEN", "").strip()
    repo = env.get("GITHUB_REPO", "").strip()

    if not token:
        print("Добавьте в .env:\nGITHUB_TOKEN=ghp_...\nGITHUB_REPO=ваш_логин/hh-parser", file=sys.stderr)
        return 1
    if not repo:
        print("Добавьте в .env:\nGITHUB_REPO=ваш_логин/hh-parser", file=sys.stderr)
        return 1

    message = " ".join(sys.argv[1:]).strip() or "Update project"

    status = run(["git", "status", "--porcelain"], check=False)
    if status.stdout.strip():
        run(["git", "add", "-A"])
        commit = run(["git", "commit", "-m", message], check=False)
        if commit.returncode != 0 and "nothing to commit" not in (commit.stderr + commit.stdout):
            print(commit.stderr or commit.stdout, file=sys.stderr)
            return commit.returncode

    clone_url = ensure_repo(token, repo)
    remote = run(["git", "remote", "get-url", "origin"], check=False)
    if remote.returncode != 0:
        run(["git", "remote", "add", "origin", clone_url])
    else:
        run(["git", "remote", "set-url", "origin", clone_url])

    push_url = clone_url.replace("https://", f"https://x-access-token:{token}@")
    push = run(["git", "push", "-u", push_url, "HEAD:main"], check=False)
    if push.returncode != 0:
        push = run(["git", "push", "-u", push_url, "HEAD:master"], check=False)
    if push.returncode != 0:
        print(push.stderr or push.stdout, file=sys.stderr)
        return push.returncode

    run(["git", "remote", "set-url", "origin", clone_url])
    run(["git", "branch", "--set-upstream-to", "origin/main", "main"], check=False)

    print(f"Pushed to https://github.com/{repo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
