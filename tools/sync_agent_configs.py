#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 docs/agent-protocol/base.md 生成三份 Agent 项目规则文件。

用途
====
本项目根目录挂三份 Agent 项目规则（``AGENTS.md`` / ``CLAUDE.md`` /
``.trae/rule.md``）必须全文一致。为了避免"改一份忘同步另外两份"的手误，
本脚本把 **唯一来源** 定在 ``docs/agent-protocol/base.md``，从它生成三份。

工作流约定
==========
- **修改 Agent 项目规则时，只编辑 ``docs/agent-protocol/base.md``。**
- 编辑完执行 ``python tools/sync_agent_configs.py --apply`` 重新生成三份。
- 生成后执行 ``python tools/check_agent_configs.py`` 复核（pre-commit 也会跑）。

用法
====
- ``python tools/sync_agent_configs.py``：dry-run，展示三份将被覆盖的差异。
- ``python tools/sync_agent_configs.py --apply``：实际写入三份文件。
- ``python tools/sync_agent_configs.py --check``：仅验证三份是否与 base 一致，
  不写入；用于 pre-commit / CI，不一致就 exit 1。

换行符
======
- ``AGENTS.md`` / ``CLAUDE.md`` 历史使用 **CRLF**（Windows Notepad / VS Code
  默认），保留不动。
- ``.trae/rule.md`` 历史使用 **LF**，保留不动。
- 内容层面（``check_agent_configs.py`` 校验的部分）三份完全一致。

Exit code
=========
- ``0``：dry-run / check 通过；或 apply 成功。
- ``1``：check 模式下发现某份文件与 base 不一致。
- ``2``：base.md 不存在或无法读取。
"""
from __future__ import annotations

import argparse
import difflib
import io
import sys
from pathlib import Path

# Windows 控制台 UTF-8 兜底，避免中文乱码。
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if isinstance(_stream, io.TextIOWrapper):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


BASE_PATH = Path("docs/agent-protocol/base.md")

# 三份目标文件的相对路径及各自的换行符风格。
# 保留历史风格；如果未来想统一为 LF，也只需要在这里改一处。
TARGETS: tuple[tuple[str, str], ...] = (
    ("AGENTS.md", "\r\n"),
    ("CLAUDE.md", "\r\n"),
    (".trae/rule.md", "\n"),
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def read_base(base_path: Path) -> str:
    """按 LF 语义读取 base 内容并规范化换行符。"""
    # ``Path.read_text(newline=...)`` 直到 Python 3.14 才支持，为兼容 3.11 / 3.12 / 3.13
    # 改走 ``open`` + ``.read()``。
    with base_path.open(encoding="utf-8", newline="") as handle:
        raw = handle.read()
    # 允许 base 存放为任意换行符，内部一律按 LF 处理。
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def _read_text_binary_safe(path: Path) -> str:
    """跨 Python 版本读取保留原换行符的文本内容（与 read_base 同理由）。"""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def render(content_lf: str, line_sep: str) -> str:
    """把 LF 内容渲染成目标换行符。"""
    if line_sep == "\n":
        return content_lf
    return content_lf.replace("\n", line_sep)


def diff_summary(current: str, expected: str, name: str) -> str:
    """打印文件将被覆盖的行数变化摘要。"""
    a = current.splitlines()
    b = expected.splitlines()
    # 只用统计层面的摘要，避免 dry-run 时把大量 diff 淹没终端。
    added = sum(1 for line in b if line not in a)
    removed = sum(1 for line in a if line not in b)
    return f"   {name}: 当前 {len(a)} 行 → 目标 {len(b)} 行 (+{added} / -{removed})"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从 docs/agent-protocol/base.md 生成三份 Agent 项目规则。",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--apply",
        action="store_true",
        help="实际写入三份文件（默认只做 dry-run）。",
    )
    group.add_argument(
        "--check",
        action="store_true",
        help="校验三份是否已与 base 一致；不写入，用于 pre-commit / CI。",
    )
    args = parser.parse_args()

    root = repo_root()
    base_path = root / BASE_PATH
    if not base_path.is_file():
        print(f"[FAIL] 找不到 base 文件：{base_path}", file=sys.stderr)
        print(
            "先创建 docs/agent-protocol/base.md 作为规则的唯一来源。",
            file=sys.stderr,
        )
        return 2

    base_lf = read_base(base_path)

    # 逐一计算每份目标文件的期望内容。
    plan: list[tuple[Path, str, str]] = []
    for rel, line_sep in TARGETS:
        target = root / rel
        expected = render(base_lf, line_sep)
        plan.append((target, expected, rel))

    if args.check:
        # 校验模式：三份必须已经与 base 一致（内容 + 换行符风格）。
        drifted: list[str] = []
        for target, expected, rel in plan:
            if not target.is_file():
                drifted.append(f"{rel}（文件不存在）")
                continue
            current = _read_text_binary_safe(target)
            if current != expected:
                drifted.append(rel)
        if drifted:
            print(
                "[FAIL] 以下文件与 docs/agent-protocol/base.md 不一致：",
                file=sys.stderr,
            )
            for name in drifted:
                print(f"   - {name}", file=sys.stderr)
            print(
                "\n修复方式：``python tools/sync_agent_configs.py --apply``。",
                file=sys.stderr,
            )
            return 1
        print(
            f"[OK] 三份 Agent 规则均与 base 一致（{base_lf.count(chr(10))} 行）。"
        )
        return 0

    # dry-run / apply 共用的差异展示：
    print(f"Base 源：{BASE_PATH}（{base_lf.count(chr(10))} 行）")
    for target, expected, rel in plan:
        if target.is_file():
            current = _read_text_binary_safe(target)
            if current == expected:
                print(f"   {rel}: 已是最新，无变化")
                continue
            print(diff_summary(current, expected, rel))
        else:
            print(f"   {rel}: 将新建（{expected.count(chr(10))} 行）")

    if not args.apply:
        print("\n(dry-run) 未写入。加 --apply 才实际写盘。")
        return 0

    # apply 模式：实际写入。
    for target, expected, rel in plan:
        target.parent.mkdir(parents=True, exist_ok=True)
        # newline='' 让 Python 不再插手换行符；expected 里已包含正确的
        # \r\n 或 \n。
        target.write_text(expected, encoding="utf-8", newline="")
        print(f"[written] {rel}")

    print("\n[OK] 三份 Agent 规则已从 base 重新生成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
