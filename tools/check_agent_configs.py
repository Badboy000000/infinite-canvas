#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三份 Agent 项目规则一致性检查脚本。

用途
====
本项目根目录同时挂三份 Agent 项目规则文件：

- ``AGENTS.md``（Codex CLI / 通用）
- ``CLAUDE.md``（Claude Code）
- ``.trae/rule.md``（Trae）

治理规则要求这三份文件**全文一致**（详见知识库
``10 架构基线/技术开发规则与工程实施规范.md`` §"规则落地记录"）。任何 Agent
（人或模型）修改其中任意一份，都必须同步另外两份并做全文对账。

历史存在换行符差异：``AGENTS.md`` / ``CLAUDE.md`` 是 CRLF，
``.trae/rule.md`` 是 LF——**仅换行符差异视为等价**，本脚本会 strip 掉 CR 后
再比对。

用法
====
- ``python tools/check_agent_configs.py``：检查三份是否一致。一致 exit 0；
  不一致 exit 1 并打印 diff 摘要。
- ``python tools/check_agent_configs.py --verbose``：打印完整逐行 diff。

设计选择
========
- 不做任何自动修复。规则一致性由 Agent 自己保证；本脚本只是**拦截器**，
  拦得住"只改一份就 commit"的手误。
- 只比对内容（strip CRLF），不比对换行符，避免历史 CRLF/LF 差异反复干扰。
- Exit code 有区分：0 一致；1 内容不一致；2 缺少某份文件；3 参数错误。
  这样 pre-commit / CI 可以按 exit code 分类失败原因。
"""
from __future__ import annotations

import argparse
import difflib
import io
import sys
from pathlib import Path

# Windows 默认控制台通常是 GBK/CP936，会把中文/箭头字符打成乱码。
# 显式把 stdout/stderr 切成 UTF-8 输出——Python 3.7+ 支持 reconfigure。
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if isinstance(_stream, io.TextIOWrapper):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # 极老 Python 或异常场景，退化到原编码；输出可能乱码但 exit
            # code 仍然有效。
            pass

# 三份 Agent 规则文件的相对路径（相对仓库根）。
CONFIG_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".trae/rule.md",
)


def repo_root() -> Path:
    """脚本文件位于 ``tools/`` 下，仓库根就是其父目录。"""
    return Path(__file__).resolve().parent.parent


def load_normalized(path: Path) -> list[str]:
    """按 UTF-8 读文件并 strip 掉行尾 CR，返回逐行列表。

    - 用 ``newline=""`` 避免 Python 自作主张转换换行符；
    - 手动 ``rstrip("\r")`` 剥掉 CR，让 CRLF / LF 视为等价；
    - 不 strip 空白其他部分，避免掩盖真实内容差异。
    """
    text = path.read_text(encoding="utf-8", newline="")
    lines = text.splitlines()
    return [line.rstrip("\r") for line in lines]


def format_diff(a: list[str], b: list[str], a_name: str, b_name: str) -> str:
    """生成 unified diff 文本用于打印。"""
    return "\n".join(
        difflib.unified_diff(a, b, fromfile=a_name, tofile=b_name, lineterm="")
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="检查三份 Agent 项目规则是否全文一致（忽略换行符差异）。",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="不一致时打印完整 unified diff（默认只打印摘要）。",
    )
    args = parser.parse_args()

    root = repo_root()
    paths = [(name, root / name) for name in CONFIG_FILES]

    # 先确认三份都存在；缺任一份都是硬失败。
    missing = [name for name, p in paths if not p.is_file()]
    if missing:
        print("[FAIL] 缺少 Agent 规则文件：", file=sys.stderr)
        for name in missing:
            print(f"   - {name}", file=sys.stderr)
        return 2

    contents = {name: load_normalized(p) for name, p in paths}
    # 以 AGENTS.md 为对账基准（三份等价，只需选一个当基线；AGENTS.md
    # 是通用 spec，天然适合当锚点）。
    base_name = CONFIG_FILES[0]
    base = contents[base_name]

    mismatches: list[tuple[str, list[str]]] = []
    for name in CONFIG_FILES[1:]:
        other = contents[name]
        if other != base:
            mismatches.append((name, other))

    if not mismatches:
        print(
            f"[OK] 三份 Agent 规则内容一致（{len(base)} 行 / 忽略换行符差异）。"
        )
        return 0

    print("[FAIL] Agent 规则不一致：", file=sys.stderr)
    print(
        f"   基线：{base_name}（{len(base)} 行）",
        file=sys.stderr,
    )
    for name, other in mismatches:
        print(
            f"   偏差：{name}（{len(other)} 行）",
            file=sys.stderr,
        )
        if args.verbose:
            print("", file=sys.stderr)
            print(format_diff(base, other, base_name, name), file=sys.stderr)
            print("", file=sys.stderr)

    print("", file=sys.stderr)
    print(
        "修复方式：编辑任一份使三份内容一致；再次运行本脚本或用 "
        "``diff --strip-trailing-cr`` 复查。",
        file=sys.stderr,
    )
    if not args.verbose:
        print(
            "如需查看完整 diff，重跑并加 ``--verbose``。",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
