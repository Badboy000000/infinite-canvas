"""`app.security.pillow_guard` — Pillow 图片处理限额(部署 PR-05 骨架层)。

**定位**:纯函数 + frozen dataclass 决策对象 · env flag 默认关闭 · 与旧行为等价。

**骨架契约**:
- ``PillowGuardPolicy``:max_pixels / max_bytes_estimate / max_dimension · frozen
- ``PillowDecision``:结果 frozen dataclass(``accepted`` / ``reason`` / ``estimated_bytes``)
- ``PillowReason``:拒绝原因 Literal 枚举
- ``estimate_pixel_bytes(width, height, channels)``:纯函数 · 内存占用估算
- ``check_image_dimensions(w, h, channels, policy)``:主入口 · 不接触 Pillow / PIL
- ``is_pillow_guard_enforce_enabled()``:env flag ``PILLOW_GUARD_ENFORCE`` 判据

**默认策略**(治理方案 M1 明示):
- max_pixels: 40_000_000(约 6300²)
- max_dimension: 15_000(单边)
- max_bytes_estimate: 512 MB(内存预估上限)
- channels 默认按 4(RGBA)估算

**不做**:
- **不 import PIL / Pillow**(骨架层禁止;纯尺寸计算)
- 不设置 ``Image.MAX_IMAGE_PIXELS``(生产切换归后续 PR)
- 不实现 ``safe_open_image`` / ``safe_thumbnail``(骨架只暴露决策纯函数)
- 不替换 ``main.py`` 中的 ``Image.open`` 调用点

**为什么骨架不 import PIL**:PIL/Pillow 是 optional 依赖(仓库既有,但骨架层
保持"纯 Python 尺寸计算"接口 · 不改进程依赖面)· 生产 PR 在 middleware /
装饰器层封装 PIL 调用。

见 [[40 实施计划/部署与安全治理实施计划与PR清单]] PR-05。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Optional


# ---------------------------------------------------------------------------
# env flag
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes", "on", "TRUE"})

PILLOW_GUARD_ENFORCE_ENV = "PILLOW_GUARD_ENFORCE"


def is_pillow_guard_enforce_enabled() -> bool:
    """``PILLOW_GUARD_ENFORCE`` 是否已开启(默认 false)。"""
    return os.environ.get(PILLOW_GUARD_ENFORCE_ENV, "").strip() in _TRUTHY


# ---------------------------------------------------------------------------
# Reason 枚举 & 决策对象
# ---------------------------------------------------------------------------

PillowReason = Literal[
    "accepted",
    "oversize_pixels",
    "oversize_dimension",
    "oversize_estimate_bytes",
    "invalid_dimension",
]


@dataclass(frozen=True)
class PillowDecision:
    """Pillow 护栏决策 · frozen。"""

    accepted: bool
    reason: PillowReason
    width: Optional[int] = None
    height: Optional[int] = None
    channels: Optional[int] = None
    total_pixels: Optional[int] = None
    estimated_bytes: Optional[int] = None
    limit_bytes: Optional[int] = None


# ---------------------------------------------------------------------------
# 策略 dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PillowGuardPolicy:
    """Pillow 护栏策略 · frozen。默认对齐治理方案 M1 明示阈值。"""

    max_pixels: int = 40_000_000
    max_dimension: int = 15_000
    max_bytes_estimate: int = 512 * 1024 * 1024
    default_channels: int = 4  # RGBA


DEFAULT_PILLOW_POLICY = PillowGuardPolicy()


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


def estimate_pixel_bytes(width: int, height: int, channels: int = 4) -> int:
    """估算 Pillow 解码后内存占用(字节)· 按 W × H × C × 1(uint8)。

    Args:
        width: 图像宽(像素)。
        height: 图像高(像素)。
        channels: 通道数(缺省 4 · RGBA)。

    Returns:
        字节数;负数或 0 参数会返回 0。
    """
    if width <= 0 or height <= 0 or channels <= 0:
        return 0
    return int(width) * int(height) * int(channels)


def check_image_dimensions(
    *,
    width: int,
    height: int,
    channels: Optional[int] = None,
    policy: PillowGuardPolicy = DEFAULT_PILLOW_POLICY,
) -> PillowDecision:
    """Pillow 护栏主检查 · 纯函数 · 无 IO / 不接触 PIL。

    检查顺序:
        1. 参数非法(<=0)→ ``invalid_dimension``
        2. 单边超限 → ``oversize_dimension``
        3. 总像素超限 → ``oversize_pixels``
        4. 预估内存超限 → ``oversize_estimate_bytes``
        5. 均通过 → ``accepted``

    Args:
        width: 图像宽。
        height: 图像高。
        channels: 通道数(缺省 policy.default_channels)。
        policy: 策略;缺省 ``DEFAULT_PILLOW_POLICY``。

    Returns:
        ``PillowDecision``。
    """
    if width <= 0 or height <= 0:
        return PillowDecision(
            accepted=False,
            reason="invalid_dimension",
            width=width,
            height=height,
        )

    ch = channels if channels is not None else policy.default_channels
    if ch <= 0:
        return PillowDecision(
            accepted=False,
            reason="invalid_dimension",
            width=width,
            height=height,
            channels=ch,
        )

    if width > policy.max_dimension or height > policy.max_dimension:
        return PillowDecision(
            accepted=False,
            reason="oversize_dimension",
            width=width,
            height=height,
            channels=ch,
        )

    pixels = width * height
    if pixels > policy.max_pixels:
        return PillowDecision(
            accepted=False,
            reason="oversize_pixels",
            width=width,
            height=height,
            channels=ch,
            total_pixels=pixels,
        )

    estimated = estimate_pixel_bytes(width, height, ch)
    if estimated > policy.max_bytes_estimate:
        return PillowDecision(
            accepted=False,
            reason="oversize_estimate_bytes",
            width=width,
            height=height,
            channels=ch,
            total_pixels=pixels,
            estimated_bytes=estimated,
            limit_bytes=policy.max_bytes_estimate,
        )

    return PillowDecision(
        accepted=True,
        reason="accepted",
        width=width,
        height=height,
        channels=ch,
        total_pixels=pixels,
        estimated_bytes=estimated,
        limit_bytes=policy.max_bytes_estimate,
    )


__all__ = [
    "PILLOW_GUARD_ENFORCE_ENV",
    "PillowGuardPolicy",
    "PillowDecision",
    "PillowReason",
    "DEFAULT_PILLOW_POLICY",
    "estimate_pixel_bytes",
    "check_image_dimensions",
    "is_pillow_guard_enforce_enabled",
]
