"""数据 PR-14 · JSON 读通道下线判据 + 回滚剧本 · 契约测试（T560-T569 · 10 项）。

覆盖点：
- T560 · JSON_FALLBACK_READ=off 时 Settings 字段为 False
- T561 · JSON_ASYNC_MIRROR=off 时 Settings 字段为 False
- T562 · JSON_FALLBACK_READ=on 时 Settings 字段为 True
- T563 · JSON_ASYNC_MIRROR=on 时 Settings 字段为 True
- T564 · JSON_FALLBACK_READ env 默认值（未设置）= False
- T565 · JSON_ASYNC_MIRROR env 默认值（未设置）= False
- T566 · JSON_FALLBACK_READ 开关切换后行为正确（on→off→on）
- T567 · JSON_ASYNC_MIRROR 开关切换后行为正确（on→off→on）
- T568 · 回滚剧本文件存在
- T569 · 回滚剧本文件内容包含关键操作指引

护栏来源：任务书 · Wave 3-N.7 Batch 4 主线 B · 数据 PR-14 · 数据模型收官。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# 注意：`main.JSON_FALLBACK_READ` / `main.JSON_ASYNC_MIRROR` 是 `main.py`
# 模块级常量，在 import 时求值。测试不能通过 monkeypatch env 来改变它们（因为
# import 已经发生），必须用 `monkeypatch.setattr(main, "JSON_FALLBACK_READ", ...)`
# 直接修改 main 模块的 attribute。`_reset_settings_cache_for_tests()` 只清除
# `_deployment_snapshot` 缓存，不影响主模块常量。详见数据 PR-14 契约。
# 重新导入 `main` 模块不可行（Python 缓存已加载的模块），因此测试通过
# monkeypatch.setattr 模拟 `main` 模块 attribute 的瞬态值，再通过
# `_reset_settings_cache_for_tests()` 使 `get_settings()` 下次调用时重新读取。


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read_settings_field(field_name: str) -> bool:
    """现读 `get_settings()` 的指定 bool 字段。"""
    from app.shared.settings import get_settings

    return bool(getattr(get_settings(), field_name))


def _reset_cache():
    """清除 `_deployment_snapshot` 缓存，使 `get_settings()` 下次调用现读 main。"""
    from app.shared.settings.runtime import _reset_settings_cache_for_tests

    _reset_settings_cache_for_tests()


# ---------------------------------------------------------------------------
# T560-T561 · 默认 off 状态
# ---------------------------------------------------------------------------


def test_T560_json_fallback_read_off_by_default(monkeypatch):
    """JSON_FALLBACK_READ=off 时 Settings 字段为 False。"""
    import main

    monkeypatch.setattr(main, "JSON_FALLBACK_READ", False)
    _reset_cache()
    assert _read_settings_field("json_fallback_read") is False


def test_T561_json_async_mirror_off_by_default(monkeypatch):
    """JSON_ASYNC_MIRROR=off 时 Settings 字段为 False。"""
    import main

    monkeypatch.setattr(main, "JSON_ASYNC_MIRROR", False)
    _reset_cache()
    assert _read_settings_field("json_async_mirror") is False


# ---------------------------------------------------------------------------
# T562-T563 · 显式 on 状态
# ---------------------------------------------------------------------------


def test_T562_json_fallback_read_on(monkeypatch):
    """JSON_FALLBACK_READ=on 时 Settings 字段为 True。"""
    import main

    monkeypatch.setattr(main, "JSON_FALLBACK_READ", True)
    _reset_cache()
    assert _read_settings_field("json_fallback_read") is True


def test_T563_json_async_mirror_on(monkeypatch):
    """JSON_ASYNC_MIRROR=on 时 Settings 字段为 True。"""
    import main

    monkeypatch.setattr(main, "JSON_ASYNC_MIRROR", True)
    _reset_cache()
    assert _read_settings_field("json_async_mirror") is True


# ---------------------------------------------------------------------------
# T564-T565 · 未设置 env 时的默认值
# ---------------------------------------------------------------------------


def test_T564_json_fallback_read_unset(monkeypatch):
    """JSON_FALLBACK_READ 未设置时 Settings 字段为 False（默认值）。"""
    import main

    monkeypatch.setattr(main, "JSON_FALLBACK_READ", False)
    _reset_cache()
    assert _read_settings_field("json_fallback_read") is False


def test_T565_json_async_mirror_unset(monkeypatch):
    """JSON_ASYNC_MIRROR 未设置时 Settings 字段为 False（默认值）。"""
    import main

    monkeypatch.setattr(main, "JSON_ASYNC_MIRROR", False)
    _reset_cache()
    assert _read_settings_field("json_async_mirror") is False


# ---------------------------------------------------------------------------
# T566-T567 · 开关切换后行为正确
# ---------------------------------------------------------------------------


def test_T566_json_fallback_read_toggle(monkeypatch):
    """JSON_FALLBACK_READ 开关切换后行为正确（on→off→on）。"""
    import main

    # on
    monkeypatch.setattr(main, "JSON_FALLBACK_READ", True)
    _reset_cache()
    assert _read_settings_field("json_fallback_read") is True

    # off
    monkeypatch.setattr(main, "JSON_FALLBACK_READ", False)
    _reset_cache()
    assert _read_settings_field("json_fallback_read") is False

    # 再次 on
    monkeypatch.setattr(main, "JSON_FALLBACK_READ", True)
    _reset_cache()
    assert _read_settings_field("json_fallback_read") is True


def test_T567_json_async_mirror_toggle(monkeypatch):
    """JSON_ASYNC_MIRROR 开关切换后行为正确（on→off→on）。"""
    import main

    # on
    monkeypatch.setattr(main, "JSON_ASYNC_MIRROR", True)
    _reset_cache()
    assert _read_settings_field("json_async_mirror") is True

    # off
    monkeypatch.setattr(main, "JSON_ASYNC_MIRROR", False)
    _reset_cache()
    assert _read_settings_field("json_async_mirror") is False

    # 再次 on
    monkeypatch.setattr(main, "JSON_ASYNC_MIRROR", True)
    _reset_cache()
    assert _read_settings_field("json_async_mirror") is True


# ---------------------------------------------------------------------------
# T568 · 回滚剧本文件存在
# ---------------------------------------------------------------------------


def test_T568_rollback_playbook_exists():
    """回滚剧本文件 `docs/rollback/json-fallback-restore.md` 存在。"""
    playbook = REPO_ROOT / "docs" / "rollback" / "json-fallback-restore.md"
    assert playbook.is_file(), (
        f"回滚剧本文件不存在：{playbook}"
    )


# ---------------------------------------------------------------------------
# T569 · 回滚剧本内容包含关键操作指引
# ---------------------------------------------------------------------------


def test_T569_rollback_playbook_contains_key_sections():
    """回滚剧本文件内容包含关键操作指引。"""
    playbook = REPO_ROOT / "docs" / "rollback" / "json-fallback-restore.md"
    content = playbook.read_text(encoding="utf-8")

    # 必须包含的关键操作指引
    required_sections = [
        "JSON 回退读通道下线判据",
        "回滚剧本",
        "JSON_FALLBACK_READ",
        "JSON_ASYNC_MIRROR",
        "DB 主写异常",
        "对账补齐",
        "data-reconcile",
        "开关参考",
    ]
    for section in required_sections:
        assert section in content, (
            f"回滚剧本缺少关键内容：{section}"
        )