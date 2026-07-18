#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Infinite Canvas 环境前置检查脚本。

用途
====
把 Agent 上线一次会话前的关键前置条件从"配置文件里的一段话"变成"一条命令
的输出"：

- Obsidian 知识库路径是否可达、必读入口是否存在
- 本仓库 CodeGraph 索引是否已建 (``.codegraph/``)
- ``codegraph`` CLI 是否在 PATH
- Node / fnm 环境是否可用

模型不再需要在 CLAUDE.md 里读一大段"知识库在这里、CodeGraph 长这样"的说明
才能开工；跑一次本脚本，输出就是当前会话的**实时环境快照**。

用法
====
- ``python tools/check_env.py``：完整检查，全部通过 exit 0，否则 exit 1。
- ``python tools/check_env.py --quiet``：只在有问题时打印。

Exit code
=========
- 0：全部前置条件满足
- 1：有一项以上不满足（stderr 有详情）
"""
from __future__ import annotations

import argparse
import io
import shutil
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


OBSIDIAN_ROOT = Path("E:/个人知识库/Infinite Canvas 二开与架构治理项目知识库")
OBSIDIAN_ENTRY = OBSIDIAN_ROOT / "Infinite Canvas 二开与架构治理项目知识库 Index.md"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def check_obsidian() -> tuple[bool, str]:
    if not OBSIDIAN_ROOT.is_dir():
        return False, f"知识库目录不存在：{OBSIDIAN_ROOT}"
    if not OBSIDIAN_ENTRY.is_file():
        return False, f"知识库入口缺失：{OBSIDIAN_ENTRY.name}"
    return True, f"{OBSIDIAN_ROOT}（入口: {OBSIDIAN_ENTRY.name}）"


def check_codegraph_index() -> tuple[bool, str]:
    idx = repo_root() / ".codegraph"
    db = idx / "codegraph.db"
    if not idx.is_dir():
        return False, "本项目未建 CodeGraph 索引（.codegraph/ 缺失）"
    if not db.is_file():
        return False, "索引目录存在但 codegraph.db 缺失，可能索引损坏"
    size_mb = db.stat().st_size / (1024 * 1024)
    return True, f".codegraph/codegraph.db ({size_mb:.1f} MB)"


def check_codegraph_cli() -> tuple[bool, str]:
    exe = shutil.which("codegraph")
    if not exe:
        return False, "PATH 中找不到 `codegraph` 命令"
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        version = result.stdout.strip() or result.stderr.strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"调用 codegraph 失败：{exc}"
    return True, f"{exe}（v{version}）"


def check_node_env() -> tuple[bool, str]:
    node = shutil.which("node")
    if not node:
        return False, "PATH 中找不到 `node`"
    try:
        result = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        version = result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"调用 node 失败：{exc}"
    fnm = shutil.which("fnm")
    fnm_note = " + fnm" if fnm else ""
    return True, f"{node} ({version}){fnm_note}"


def check_tools_dir() -> tuple[bool, str]:
    """本 tools/ 目录应有的关键脚本都在。"""
    required = [
        "check_agent_configs.py",
        "sync_agent_configs.py",
        "cleanup_test_artifacts.py",
        "check_delivery_closure.py",
    ]
    tools = repo_root() / "tools"
    missing = [name for name in required if not (tools / name).is_file()]
    if missing:
        return False, "tools/ 缺少：" + ", ".join(missing)
    return True, f"tools/ 关键脚本齐全 ({len(required)} 个)"


CHECKS = [
    ("Obsidian 知识库", check_obsidian),
    ("CodeGraph 索引", check_codegraph_index),
    ("CodeGraph CLI", check_codegraph_cli),
    ("Node / fnm 环境", check_node_env),
    ("tools/ 目录", check_tools_dir),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="检查 Infinite Canvas 项目会话前置条件。",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="只在有问题时打印。",
    )
    args = parser.parse_args()

    all_ok = True
    lines: list[str] = []
    for name, fn in CHECKS:
        ok, detail = fn()
        marker = "[OK]  " if ok else "[FAIL]"
        lines.append(f"{marker} {name}: {detail}")
        if not ok:
            all_ok = False

    if all_ok and args.quiet:
        return 0

    for line in lines:
        stream = sys.stdout if line.startswith("[OK]") else sys.stderr
        print(line, file=stream)

    if all_ok:
        print("")
        print("[OK] 所有会话前置条件满足。")
        return 0

    print("", file=sys.stderr)
    print("请解决上述 [FAIL] 项后再继续。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
