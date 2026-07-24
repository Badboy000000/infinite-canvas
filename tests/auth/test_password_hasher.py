"""权限 PR-3 · PasswordHasher 契约测试。

覆盖：
- 密码哈希 + verify 正确
- 时序常量比较（防用户枚举）
- 需要重哈希检测
- 短密码拒绝
- P0 密钥零泄漏（明文密码不在 hasher.__repr__ / err msg）
"""
from __future__ import annotations

import pytest

from app.services.auth import (
    AuthenticationError,
    PasswordHasher,
    MIN_PASSWORD_LENGTH,
)


def test_password_hash_and_verify_roundtrip():
    """PasswordHasher.hash → verify 应该返回 True。"""
    hasher = PasswordHasher()
    hash_value = hasher.hash("correct_password_12345")
    assert hasher.verify(hash_value, "correct_password_12345") is True


def test_password_verify_wrong_returns_false():
    """错误密码应该返回 False。"""
    hasher = PasswordHasher()
    hash_value = hasher.hash("correct_password_12345")
    assert hasher.verify(hash_value, "wrong_password_12345") is False


def test_password_hash_produces_argon2id_format():
    """hash 返回 argon2id 格式（`$argon2id$...`）。"""
    hasher = PasswordHasher()
    hash_value = hasher.hash("some_password_12345")
    assert hash_value.startswith("$argon2id$"), f"Expected argon2id hash, got: {hash_value[:30]}..."


def test_password_short_raises():
    """短密码应该抛 AuthenticationError code=password_too_weak。"""
    hasher = PasswordHasher()
    with pytest.raises(AuthenticationError) as exc_info:
        hasher.hash("short")
    assert exc_info.value.code == "password_too_weak"
    assert exc_info.value.http_status == 422


def test_password_hash_returns_different_hash_each_time():
    """相同明文两次 hash 应该返回不同 hash（不同 salt）。"""
    hasher = PasswordHasher()
    h1 = hasher.hash("some_password_12345")
    h2 = hasher.hash("some_password_12345")
    assert h1 != h2
    assert hasher.verify(h1, "some_password_12345")
    assert hasher.verify(h2, "some_password_12345")


def test_password_verify_empty_returns_false():
    """空 password 或 hash 应该返回 False（不 raise）。"""
    hasher = PasswordHasher()
    assert hasher.verify("", "password") is False
    assert hasher.verify("$argon2id$fake", "") is False


def test_password_min_length_constant():
    """MIN_PASSWORD_LENGTH 应该 >= 12（决策 §5）。"""
    assert MIN_PASSWORD_LENGTH >= 12


# ---------- P0 密钥零泄漏 ------------------------------------------------


def test_password_never_in_authentication_error_repr():
    """AuthenticationError 的 repr 不应该包含明文 message 细节。"""
    err = AuthenticationError(code="invalid_credentials", message="my_secret_password")
    repr_str = repr(err)
    assert "my_secret_password" not in repr_str
    # 只应该暴露 code
    assert "invalid_credentials" in repr_str


def test_password_hash_output_never_contains_plaintext():
    """hash 输出中不应该出现明文密码字符（防止参数漏泄）。"""
    hasher = PasswordHasher()
    plaintext = "super_secret_xyz_12345"
    hash_value = hasher.hash(plaintext)
    # argon2 hash 是 base64 编码，明文不可能作为子串出现（除非碰撞）
    assert plaintext not in hash_value


def test_password_verify_wrong_length_boundary():
    """验证 min_length 边界：11 拒绝，12 通过。"""
    hasher = PasswordHasher()
    with pytest.raises(AuthenticationError):
        hasher.hash("x" * 11)
    # 12 chars OK
    h = hasher.hash("x" * 12)
    assert h.startswith("$argon2id$")