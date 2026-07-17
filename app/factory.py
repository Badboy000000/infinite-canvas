"""FastAPI 应用工厂 facade。

PR-BE-01 契约：
- `create_app()` 返回当前仓库根 `main.py` 已经创建好的 FastAPI 实例的引用。
- 不在 import 时触发任何 `main` 的执行；`import main` 只发生在 `create_app()`
  被调用时（懒加载）。
- 不引入任何模块级副作用，避免与 `main.py` 现有 import 顺序发生耦合。

未来 PR（PR-BE-02/03/... ）会在此处逐步注册 middleware、include_router
以及 lifecycle hook。当前实现只做透明桥接。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 仅类型提示，运行时不 import
    from fastapi import FastAPI


def create_app() -> "FastAPI":
    """返回根 `main.py` 中已存在的 FastAPI 实例。

    M0 阶段严格 0 行为改动：仅做一次懒 import 并把已经组装好的 `app`
    对象返回给调用方。此处不得注册任何 middleware / router / handler ——
    那些能力由后续 PR 独立引入。
    """

    # 懒 import：避免形成 `main` -> `app.factory` -> `main` 的循环导入，
    # 也确保仅在被主动调用时才触发 main.py 的顶层副作用。
    import main  # noqa: WPS433 (允许函数内 import，出于循环导入防护)

    return main.app
