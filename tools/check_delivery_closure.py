#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Git 交付闭环检查脚本。

用途
====
本项目规则要求："PR 不因为代码写完 / 测试通过 / 文档写完就算合入 —— 必须
本地 commit 已推送到远程、可从记录的远程分支到达、且 PR 状态总账已回写 commit
hash"。历史上多次因为忘 push 或忘回写状态总账导致 PR 状态与代码事实不符。

本脚本把这条规则从"靠模型自觉"转成"物理护栏"：

1. 当前本地 HEAD 存在
2. HEAD 已推送到 ``origin/<current-branch>`` 且远程 = 本地
3. 工作树没有与当前 PR 相关的未提交改动（提示用户复核）

它**不**主动查询知识库里"PR 状态总账"的 commit hash 是否填了——因为这类文本
识别需要人工判断（PR 编号 / 专题等），交给交付时的 checklist 提示。

用法
====
- ``python tools/check_delivery_closure.py``：完整检查，dry-run 报告。
- ``python tools/check_delivery_closure.py --strict``：附加严格模式，若工作树
  有任何未 commit 改动直接 exit 1（默认只警告）。
- ``python tools/check_delivery_closure.py --branch <name>``：显式指定分支，
  绕过 ``git branch --show-current``（在 detached HEAD 或 CI 里有用）。

Exit code
=========
- 0：交付闭环条件全部满足
- 1：远程落后于本地 / detached HEAD / 未 push
- 2：不在 git 仓库或 git 命令失败
- 3：严格模式下工作树有未 commit 改动

Design
======
- 只做 read-only 检查：不 fetch、不 push、不改动仓库；确保脚本永远不会有
  副作用。
- 网络前提假定用户已经手动 ``git fetch`` 过；如果远程实际比本地新，本脚本
  会显示，但不会自动同步。
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path

for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if isinstance(_stream, io.TextIOWrapper):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def run_git(args: list[str]) -> tuple[int, str]:
    """在仓库根跑 git；返回 (returncode, stdout+stderr 文本)。"""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def check_in_repo() -> tuple[bool, str]:
    code, out = run_git(["rev-parse", "--is-inside-work-tree"])
    if code != 0:
        return False, out
    return out.strip() == "true", out


def current_head_sha() -> str | None:
    code, out = run_git(["rev-parse", "HEAD"])
    if code != 0:
        return None
    return out.strip()


def current_branch(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    code, out = run_git(["branch", "--show-current"])
    if code != 0 or not out.strip():
        # detached HEAD 时 --show-current 返回空
        return None
    return out.strip()


def remote_sha(branch: str) -> str | None:
    """获取 origin/<branch> 当前 sha（不 fetch）。"""
    code, out = run_git(["rev-parse", f"origin/{branch}"])
    if code != 0:
        return None
    return out.strip()


def working_tree_dirty() -> list[str]:
    code, out = run_git(["status", "--porcelain"])
    if code != 0:
        return []
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="检查当前 HEAD 是否已推送到远程 origin/<branch>。",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="严格模式：工作树有未 commit 改动直接 exit 3。",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="显式指定分支名，绕过自动检测（detached HEAD 或 CI 场景）。",
    )
    args = parser.parse_args()

    in_repo, out = check_in_repo()
    if not in_repo:
        print(f"[FAIL] 不在 git 工作树内：{out}", file=sys.stderr)
        return 2

    branch = current_branch(args.branch)
    if branch is None:
        print(
            "[FAIL] 处于 detached HEAD，无法确认对应远程分支。",
            file=sys.stderr,
        )
        print(
            "先切回具体分支：`git switch <branch>`，或用 --branch 显式指定。",
            file=sys.stderr,
        )
        return 1

    head = current_head_sha()
    if head is None:
        print("[FAIL] 无法获取当前 HEAD sha。", file=sys.stderr)
        return 2

    remote = remote_sha(branch)
    if remote is None:
        print(
            f"[FAIL] 找不到远程分支 origin/{branch}。",
            file=sys.stderr,
        )
        print(
            "首次推送：`git push -u origin " + branch + "`。",
            file=sys.stderr,
        )
        return 1

    print(f"分支：{branch}")
    print(f"本地 HEAD：{head[:12]}")
    print(f"origin/{branch}: {remote[:12]}")

    dirty = working_tree_dirty()
    if head != remote:
        # 需要判断是本地领先还是落后
        code, ahead = run_git(
            ["rev-list", "--count", f"origin/{branch}..HEAD"]
        )
        code2, behind = run_git(
            ["rev-list", "--count", f"HEAD..origin/{branch}"]
        )
        try:
            n_ahead = int(ahead)
        except ValueError:
            n_ahead = -1
        try:
            n_behind = int(behind)
        except ValueError:
            n_behind = -1

        if n_ahead > 0 and n_behind == 0:
            print(
                f"[FAIL] 本地领先 origin/{branch} {n_ahead} 个 commit —— "
                "尚未 push。",
                file=sys.stderr,
            )
            print(
                f"执行：`git push origin {branch}` 然后重跑本脚本。",
                file=sys.stderr,
            )
            return 1
        if n_behind > 0 and n_ahead == 0:
            print(
                f"[WARN] 本地落后 origin/{branch} {n_behind} 个 commit —— "
                f"可能需要先 pull。",
                file=sys.stderr,
            )
            return 1
        print(
            f"[FAIL] 本地与远程分叉：本地领先 {n_ahead} / 落后 {n_behind}。",
            file=sys.stderr,
        )
        return 1

    print(f"[OK] 本地 HEAD 已推送到 origin/{branch}。")

    if dirty:
        print("")
        print(f"[WARN] 工作树有 {len(dirty)} 项未 commit 的改动：")
        for line in dirty[:10]:
            print(f"   {line}")
        if len(dirty) > 10:
            print(f"   ... 共 {len(dirty)} 项")
        print(
            "\n交付前请确认：这些是本 PR 范围内、还是无关的用户改动。"
            "\n无关改动请单独 stash / 提交，不要混入 PR。"
        )
        if args.strict:
            print(
                "[FAIL] --strict 模式下不允许有未 commit 改动。",
                file=sys.stderr,
            )
            return 3

    print("")
    print("下一步（脚本无法自动验证，请人工确认）：")
    print(
        f"   - 知识库 PR 状态总账已记录 commit hash `{head[:12]}` 和分支 `{branch}`"
    )
    print(
        "   - 状态从 `submitted` / `in_progress` 更新为 `merged` / `completed`"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
