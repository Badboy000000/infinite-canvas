"""AuditService 骨架（权限 PR-7 · Wave 3-N.8 Batch 4）。

**定位**：结构化审计日志写入服务 · 与 observability(app.task.observability)
共用 whitelist frozenset 强制 P0 密钥零泄漏防线 · 与 GenerationHistory 分离
(与任务模型 M1 GenerationHistory 分离决策一致)。

**当前 PR skeleton 交付**：
- `AuditService.append(event)` API · JSONL 追加写 · 稳定字段序列化。
- `AuditEvent` frozen dataclass · 白名单字段 · 未列字段自动过滤。
- `_ALLOWED_AUDIT_FIELDS` frozenset(17 字段) · 与治理方案 §审计事件对齐。
- 默认写入 `data/identity/audit_logs.jsonl`(权限 PR-0 已创建 0 字节空文件)。
- 默认关闭 flag `AUDIT_SERVICE_WRITE_ENABLED`(等价旧行为 · 不写盘)。

**GM-16 pre-flight**：`AuditService` / `AuditEvent` / `AuditAction` /
`_ALLOWED_AUDIT_FIELDS` 全部为新公共符号 · greenfield。

**未来演进**(Wave 3-N.9+ 承接):
- PermissionService `check()` 调用点自动 emit audit event
- `/api/me/capabilities` GET 记 read 事件
- 高风险接口(`/api/providers` PUT · `/api/canvases` DELETE)记 write 事件
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Literal, Mapping, Optional

__all__ = [
    "AuditAction",
    "AuditEvent",
    "AuditService",
    "DEFAULT_AUDIT_LOG_PATH",
    "is_audit_write_enabled",
    "_ALLOWED_AUDIT_FIELDS",
]

# ---------------------------------------------------------------------------
# 白名单 · 与 observability whitelist 独立(审计有 audit-specific 字段)
# ---------------------------------------------------------------------------

_ALLOWED_AUDIT_FIELDS: FrozenSet[str] = frozenset(
    {
        # 事件标识
        "event_id",
        "timestamp",
        "action",
        "outcome",
        # 请求上下文
        "request_id",
        "user_id",
        "principal_kind",
        "session_id",
        "workspace_id",
        "project_id",
        # 资源
        "resource_type",
        "resource_id",
        # 决策
        "role",
        "permission",
        "reason",
        # 观测
        "ip",
        "user_agent",
    }
)
"""17 字段审计白名单 · P0 密钥零泄漏防线 · 未列字段自动 drop 不 raise。

严格禁止:api_key / password / token / secret / auth_header 类字段。
与 [[30 治理方案/用户团队权限治理方案]] §审计事件章节对齐 · 未来扩展需 KB + code
同步 · 走独立 PR 增补。
"""

AuditAction = Literal[
    "auth.login",
    "auth.logout",
    "auth.session_expired",
    "permission.check_allowed",
    "permission.check_denied",
    "capability.read",
    "resource.read",
    "resource.write",
    "resource.delete",
    "provider.update",
    "system.rate_limit_exceeded",
    "system.audit_service_started",
]
"""12 种 audit action 枚举 · 覆盖认证 / 授权 / 资源 / 系统四大类。"""

AuditOutcome = Literal["success", "denied", "error"]


# ---------------------------------------------------------------------------
# AuditEvent · frozen dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditEvent:
    """审计事件(frozen · JSON 可序列化)。

    - `event_id` / `timestamp` 由 caller 提供或使用 factory · 保证测试可复现。
    - `action` 必填 · 严格来自 AuditAction 枚举。
    - `outcome` 必填 · success / denied / error 三态。
    - `context` 是可选 dict · 白名单字段自动过滤 · 未列字段 drop 不 raise。
    """

    event_id: str
    timestamp: str
    action: AuditAction
    outcome: AuditOutcome
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转 dict(应用白名单过滤) · JSON 可直接序列化。

        白名单过滤规则:
        - `event_id` / `timestamp` / `action` / `outcome` 4 顶层字段无条件保留
        - `context` 内字段过 `_ALLOWED_AUDIT_FIELDS` 白名单 · 未列字段 drop
        - 未列字段 drop 不 raise(与 observability 白名单一致行为)
        """
        payload: Dict[str, Any] = {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "action": self.action,
            "outcome": self.outcome,
        }
        for key, value in self.context.items():
            if key in _ALLOWED_AUDIT_FIELDS:
                payload[key] = value
        return payload


# ---------------------------------------------------------------------------
# 环境 flag(默认关闭 · GM-22 pattern 复用)
# ---------------------------------------------------------------------------

_TRUTHY: FrozenSet[str] = frozenset({"1", "true", "yes", "on"})
_ENV_FLAG = "AUDIT_SERVICE_WRITE_ENABLED"


def is_audit_write_enabled() -> bool:
    """读取 `AUDIT_SERVICE_WRITE_ENABLED` env flag(默认 false)。"""
    raw = os.environ.get(_ENV_FLAG, "").strip().lower()
    return raw in _TRUTHY


# ---------------------------------------------------------------------------
# AuditService
# ---------------------------------------------------------------------------

DEFAULT_AUDIT_LOG_PATH = Path("data/identity/audit_logs.jsonl")


class AuditService:
    """结构化审计日志追加写服务。

    - JSONL 格式:一行一个 JSON 对象 · 尾附加 · 单机不需锁(POSIX append
      atomic within page size · Windows 需 `_lock` 兜底)。
    - 线程安全:进程内 `threading.Lock` 保证 append 原子。
    - 跨进程:JSONL append 语义 · 不使用文件锁(治理期单机场景)。
    - 默认关闭:`AUDIT_SERVICE_WRITE_ENABLED=false` 时 `append()` 只在
      内存缓存事件供测试查询 · 不落盘。
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        *,
        buffered_only: bool = False,
    ) -> None:
        """初始化 AuditService。

        - `log_path`:JSONL 文件路径 · 默认 `data/identity/audit_logs.jsonl`。
        - `buffered_only`:强制只在内存缓存 · 忽略 env flag(测试场景使用)。
        """
        self._log_path: Path = log_path if log_path is not None else DEFAULT_AUDIT_LOG_PATH
        self._buffered_only: bool = buffered_only
        self._buffer: List[AuditEvent] = []
        self._lock: threading.Lock = threading.Lock()

    # ---- 主 API ----------------------------------------------------------

    def append(self, event: AuditEvent) -> None:
        """追加 audit event(必要时写盘 · 无论 flag 恒缓存到 self._buffer)。

        - flag off 或 buffered_only=True → 只缓存内存
        - flag on 且非 buffered_only → 缓存内存 + JSONL 追加写盘
        - 写盘失败 → raise IOError(不静默 · caller 决策后续)
        """
        with self._lock:
            self._buffer.append(event)
            if not self._buffered_only and is_audit_write_enabled():
                self._write_to_file(event)

    def _write_to_file(self, event: AuditEvent) -> None:
        """JSONL 追加写(内部方法 · 不加锁 · caller 已持锁)。"""
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = event.to_dict()
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._log_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
            fh.write("\n")

    # ---- 查询 API(测试 / 未来 audit query 消费) -----------------------

    def buffered_events(self) -> List[AuditEvent]:
        """返回缓存事件的**副本** · 顺序 = append 顺序。"""
        with self._lock:
            return list(self._buffer)

    def clear_buffer(self) -> None:
        """清空缓存 · 常用于测试隔离。"""
        with self._lock:
            self._buffer.clear()


# ---------------------------------------------------------------------------
# 工厂 helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """UTC ISO-8601 时间戳(with tz)· 稳定格式供 audit / observability 共用。"""
    return datetime.now(timezone.utc).isoformat()


def new_event_id() -> str:
    """生成新 event_id(uuid4 hex · 32 字符)。"""
    return uuid.uuid4().hex


def make_event(
    action: AuditAction,
    outcome: AuditOutcome,
    *,
    event_id: Optional[str] = None,
    timestamp: Optional[str] = None,
    context: Optional[Mapping[str, Any]] = None,
) -> AuditEvent:
    """构造 AuditEvent 便利函数 · 未传 event_id / timestamp 自动生成。"""
    return AuditEvent(
        event_id=event_id if event_id is not None else new_event_id(),
        timestamp=timestamp if timestamp is not None else now_iso(),
        action=action,
        outcome=outcome,
        context=dict(context) if context is not None else {},
    )


__all__.extend(["now_iso", "new_event_id", "make_event", "AuditOutcome"])
