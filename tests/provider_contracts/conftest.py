"""Provider 契约测试 conftest · fixture 装载 + `{{API_KEY}}` 占位符替换 + 协议目录发现。

提供:
- `resolve_fixture(protocol, name)` — 从 `tests/provider_contracts/<protocol>/` 读 JSON fixture
- `placeholder_substitute(obj, api_key)` — 替换 `{{API_KEY}}` / `{{BASE_URL}}` 占位符
- `protocol_dirs` — 自动发现协议目录

见 [[40 实施计划/Provider 适配体系治理实施计划与PR清单]] PR-04。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

FIXTURES_ROOT = Path(__file__).resolve().parent


def resolve_fixture(protocol: str, name: str) -> Optional[dict]:
    """从 `tests/provider_contracts/<protocol>/` 读 JSON fixture。

    Args:
        protocol: 协议目录名(如 `openai`)。
        name: 文件名(不含 `.json` 后缀)。

    Returns:
        dict(JSON 解析后);文件不存在时返回 None。
    """
    path = FIXTURES_ROOT / protocol / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_fixture_text(protocol: str, name: str) -> Optional[str]:
    """读取 fixture 原始文本(用于测试占位符替换)。"""
    path = FIXTURES_ROOT / protocol / f"{name}.json"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def placeholder_substitute(obj: Any, api_key: str = "sk-test-key", base_url: str = "https://test.api.example.com") -> Any:
    """递归替换对象中的 `{{API_KEY}}` / `{{BASE_URL}}` 占位符。

    Args:
        obj: 任意 JSON 可序列化对象。
        api_key: 替换值(默认 sk-test-key)。
        base_url: 替换值(默认测试 URL)。

    Returns:
        替换后的对象。
    """
    if isinstance(obj, str):
        return obj.replace("{{API_KEY}}", api_key).replace("{{BASE_URL}}", base_url)
    if isinstance(obj, dict):
        return {k: placeholder_substitute(v, api_key, base_url) for k, v in obj.items()}
    if isinstance(obj, list):
        return [placeholder_substitute(v, api_key, base_url) for v in obj]
    return obj


def list_protocol_dirs() -> list[str]:
    """自动发现协议目录(排除 __pycache__ 等)。"""
    return sorted(
        p.name for p in FIXTURES_ROOT.iterdir()
        if p.is_dir() and not p.name.startswith("_") and not p.name.startswith(".")
    )


@pytest.fixture
def provider_test_api_key() -> str:
    return "sk-test-fixture-key"


@pytest.fixture
def provider_test_base_url() -> str:
    return "https://openai-test.example.com/v1"


@pytest.fixture
def discover_protocols() -> list[str]:
    return list_protocol_dirs()


__all__ = [
    "FIXTURES_ROOT",
    "resolve_fixture",
    "read_fixture_text",
    "placeholder_substitute",
    "list_protocol_dirs",
]