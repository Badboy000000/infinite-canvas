#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`tools/check_env_manifest.py` — 环境变量清单 + 分层校验(部署 PR-02 骨架层)。

**与 `tools/check_env.py` 的分工**:
- ``check_env.py``:**session preflight** · Obsidian 路径 / CodeGraph 索引 / tools 脚本
  是否就绪 · 面向 Agent 每次开工前
- ``check_env_manifest.py``:**部署 env manifest** · ``API/.env`` 变量分层清单 +
  每种部署模式(local_personal / intranet_team / public_team)的必填项校验 · 面向
  部署运维/CI/CD

**骨架层职责**:
- 提供分层清单 dataclass:``EnvVarSpec``(名 · 层 · 敏感度 · 各模式必填)
- 提供全量清单 ``ENV_MANIFEST``(读取自本文件常量 · 骨架期硬编码)
- 提供纯函数 ``validate_manifest(env_map, mode)`` · 返回缺失/警告清单
- CLI entry:``python tools/check_env_manifest.py --mode local_personal``
- **不做**:不写 ``API/.env.example`` · 不引入 vault · 不 fail-fast 阻断启动
  (阻断由生产 PR 承接;骨架 CLI 只返回 exit code)

**分层规则**(治理方案 M0 明示):
- ``core``:部署模式 / 绑定 / 公开域名
- ``security``:会话密钥 / CSRF / CORS 白名单
- ``storage``:数据目录 / MinIO endpoint(占位)
- ``providers.system``:系统级 Provider 密钥
- ``logging``:日志目录 / 级别 / 脱敏开关

**模式必填矩阵**:
- ``local_personal``:全部可选(默认宽松)
- ``intranet_team``:``PUBLIC_BASE_URL`` + 至少一个 Provider 密钥必填
- ``public_team``:上述 + session 密钥 + CORS 白名单 fail-fast

**退出码**:
- 0:通过
- 1:缺失必填项
- 2:参数错误

见 [[40 实施计划/部署与安全治理实施计划与PR清单]] PR-02。
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# stdout / stderr 编码兜底(Windows 中文控制台)
# ---------------------------------------------------------------------------

for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if isinstance(_stream, io.TextIOWrapper):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# ---------------------------------------------------------------------------
# 类型 & 常量
# ---------------------------------------------------------------------------

DeploymentMode = Literal["local_personal", "intranet_team", "public_team"]

VALID_MODES: Tuple[DeploymentMode, ...] = (
    "local_personal",
    "intranet_team",
    "public_team",
)

EnvLayer = Literal["core", "security", "storage", "providers.system", "logging"]

VALID_LAYERS: Tuple[EnvLayer, ...] = (
    "core",
    "security",
    "storage",
    "providers.system",
    "logging",
)


@dataclass(frozen=True)
class EnvVarSpec:
    """环境变量清单条目 · frozen。

    Attributes:
        name: 环境变量名(大写下划线)。
        layer: 分层。
        sensitive: 是否敏感(用于日志脱敏对齐)。
        required_in: 该变量在哪些模式下必填。
        description: 说明。
    """

    name: str
    layer: EnvLayer
    sensitive: bool
    required_in: Tuple[DeploymentMode, ...] = field(default_factory=tuple)
    description: str = ""


# ---------------------------------------------------------------------------
# 全量清单(骨架期硬编码 · 生产 PR 迁移至 Settings)
# ---------------------------------------------------------------------------

ENV_MANIFEST: Tuple[EnvVarSpec, ...] = (
    # core
    EnvVarSpec(
        name="IC_DEPLOYMENT_MODE",
        layer="core",
        sensitive=False,
        required_in=("intranet_team", "public_team"),
        description="部署模式 · local_personal / intranet_team / public_team",
    ),
    EnvVarSpec(
        name="PUBLIC_BASE_URL",
        layer="core",
        sensitive=False,
        required_in=("intranet_team", "public_team"),
        description="公开访问 URL(含协议)",
    ),
    EnvVarSpec(
        name="PUBLIC_MEDIA_BASE_URL",
        layer="core",
        sensitive=False,
        description="媒体资源公开 URL(可选)",
    ),
    # security
    EnvVarSpec(
        name="IC_SESSION_SECRET",
        layer="security",
        sensitive=True,
        required_in=("public_team",),
        description="会话签名密钥(public_team 必填)",
    ),
    EnvVarSpec(
        name="IC_CSRF_SECRET",
        layer="security",
        sensitive=True,
        required_in=("public_team",),
        description="CSRF token 密钥",
    ),
    EnvVarSpec(
        name="IC_CORS_ALLOWED_ORIGINS",
        layer="security",
        sensitive=False,
        required_in=("public_team",),
        description="CORS 白名单(逗号分隔 · public_team 空则 fail-fast)",
    ),
    # storage
    EnvVarSpec(
        name="OUTPUT_INPUT_DIR",
        layer="storage",
        sensitive=False,
        description="上传目录(读时求值)",
    ),
    EnvVarSpec(
        name="OUTPUT_OUTPUT_DIR",
        layer="storage",
        sensitive=False,
        description="生成结果目录",
    ),
    EnvVarSpec(
        name="LOCAL_UPLOAD_DIR",
        layer="storage",
        sensitive=False,
        description="LocalStorageAdapter 根目录",
    ),
    EnvVarSpec(
        name="IC_MINIO_ENDPOINT",
        layer="storage",
        sensitive=False,
        description="MinIO endpoint(占位 · 默认关闭)",
    ),
    # providers.system
    EnvVarSpec(
        name="COMFLY_API_KEY",
        layer="providers.system",
        sensitive=True,
        description="Comfly / APIMart 系统密钥",
    ),
    EnvVarSpec(
        name="MODELSCOPE_API_KEY",
        layer="providers.system",
        sensitive=True,
        description="ModelScope 系统密钥",
    ),
    EnvVarSpec(
        name="RUNNINGHUB_API_KEY",
        layer="providers.system",
        sensitive=True,
        description="RunningHub 系统密钥",
    ),
    EnvVarSpec(
        name="ARK_API_KEY",
        layer="providers.system",
        sensitive=True,
        description="火山引擎方舟系统密钥",
    ),
    EnvVarSpec(
        name="OPENAI_API_KEY",
        layer="providers.system",
        sensitive=True,
        description="OpenAI 系统密钥(CLI/API)",
    ),
    # logging
    EnvVarSpec(
        name="IC_LOG_LEVEL",
        layer="logging",
        sensitive=False,
        description="日志级别(默认 INFO)",
    ),
    EnvVarSpec(
        name="LOG_REDACTION_ENABLED",
        layer="logging",
        sensitive=False,
        description="日志脱敏中间件开关(默认 false)",
    ),
    EnvVarSpec(
        name="IC_LOG_DIR",
        layer="logging",
        sensitive=False,
        description="日志目录(可选)",
    ),
)


# ---------------------------------------------------------------------------
# 校验结果
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManifestValidationResult:
    """校验结果 · frozen。

    Attributes:
        mode: 校验时使用的部署模式。
        missing_required: 缺失的必填变量名列表。
        empty_optional: 空值的可选变量名列表(仅报告 · 不影响 exit code)。
        warnings: 其他警告(如 `intranet_team` 无任一 provider 密钥)。
        by_layer: 按 layer 分组的变量清单(全量)。
    """

    mode: DeploymentMode
    missing_required: Tuple[str, ...]
    empty_optional: Tuple[str, ...]
    warnings: Tuple[str, ...]
    by_layer: Mapping[str, Tuple[str, ...]]

    @property
    def ok(self) -> bool:
        return not self.missing_required


# ---------------------------------------------------------------------------
# 校验函数
# ---------------------------------------------------------------------------


def validate_manifest(
    env_map: Mapping[str, str],
    mode: DeploymentMode = "local_personal",
) -> ManifestValidationResult:
    """按分层清单 + 模式校验 · 纯函数。

    Args:
        env_map: 环境变量映射(通常传 ``os.environ``)。
        mode: 部署模式;默认 ``local_personal``。

    Returns:
        ``ManifestValidationResult``。
    """
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode: {mode!r} · expected one of {VALID_MODES}")

    missing: List[str] = []
    empty_optional: List[str] = []
    warnings: List[str] = []
    by_layer: Dict[str, List[str]] = {layer: [] for layer in VALID_LAYERS}

    provider_keys_present = False

    for spec in ENV_MANIFEST:
        by_layer[spec.layer].append(spec.name)
        raw = env_map.get(spec.name, "").strip()

        if mode in spec.required_in and not raw:
            missing.append(spec.name)
        elif not raw and not spec.required_in:
            empty_optional.append(spec.name)

        # provider 密钥有 ≥1 命中即算 OK
        if spec.layer == "providers.system" and raw:
            provider_keys_present = True

    # intranet_team / public_team 至少要有一个 Provider 密钥
    if mode in ("intranet_team", "public_team") and not provider_keys_present:
        warnings.append(
            "no provider system credentials configured · at least one "
            "of [COMFLY_API_KEY / MODELSCOPE_API_KEY / RUNNINGHUB_API_KEY / "
            "ARK_API_KEY / OPENAI_API_KEY] recommended for team modes",
        )

    return ManifestValidationResult(
        mode=mode,
        missing_required=tuple(missing),
        empty_optional=tuple(empty_optional),
        warnings=tuple(warnings),
        by_layer={k: tuple(v) for k, v in by_layer.items()},
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_result(result: ManifestValidationResult, verbose: bool) -> None:
    print(f"[env-manifest] mode = {result.mode}")
    print(f"[env-manifest] ok   = {result.ok}")
    if result.missing_required:
        print("[env-manifest] missing required:")
        for name in result.missing_required:
            print(f"  - {name}")
    if verbose:
        for layer, names in result.by_layer.items():
            if not names:
                continue
            print(f"[env-manifest] layer [{layer}]: {', '.join(names)}")
        if result.empty_optional:
            print(f"[env-manifest] empty optional: {', '.join(result.empty_optional)}")
    for w in result.warnings:
        print(f"[env-manifest] warning: {w}", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Infinite Canvas 环境变量清单校验",
    )
    parser.add_argument(
        "--mode",
        choices=list(VALID_MODES),
        default=os.environ.get("IC_DEPLOYMENT_MODE", "local_personal"),
        help="部署模式(默认读 IC_DEPLOYMENT_MODE · fallback local_personal)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="打印每层清单与可选变量",
    )
    args = parser.parse_args(argv)

    try:
        result = validate_manifest(dict(os.environ), mode=args.mode)
    except ValueError as exc:
        print(f"[env-manifest] error: {exc}", file=sys.stderr)
        return 2

    _print_result(result, verbose=args.verbose)
    return 0 if result.ok else 1


__all__ = [
    "DeploymentMode",
    "EnvLayer",
    "EnvVarSpec",
    "ENV_MANIFEST",
    "VALID_MODES",
    "VALID_LAYERS",
    "ManifestValidationResult",
    "validate_manifest",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
