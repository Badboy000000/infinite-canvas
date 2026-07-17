"""全局 API 错误 handler（PR-BE-12 短期兜底承接 CB-02）。

本模块承接 [[70 开发过程跟踪/缺陷追踪/CB-02 - PUT providers 422 error 回显
request body 含密钥]] 的**短期兜底部分**：FastAPI 默认
`RequestValidationError` handler 会把整个 request body 塞进
`errors[].input`，当 payload 含密钥字段（`api_key` / `wallet_api_key` /
`secret_access_key` / …）时，422 响应体明文回显密钥。

短期兜底策略：**完全剔除 `errors[].input`**。保留 `type` / `loc` / `msg` /
`ctx` 四字段（loc 是字段路径不含值；ctx 是 Pydantic 上下文，如 limit_value/
max_length 等标量约束值，不含 payload 数据）。响应体顶层追加 `request_id`
字段（消费 `RequestContext.request_id`；middleware 未装配的兜底路径退化到
`request.headers.get('X-Request-Id')`）；响应 header 也回写 `X-Request-Id`。

选择"剔除"而非"递归 mask"的理由：
1. `errors[].input` 可为任意嵌套结构（dict / list / bare value / None），
   不可能穷举密钥字段名白名单；一次漏配即导致同类事故复发。
2. CB-02 触发原文明确"或整体不回显 body"，剔除是最保守的兜底。
3. 长期根治（Provider PR-05 密钥子资源）与紧急日志脱敏（部署 PR-10）
   由 Lead 后续开工，本 handler 不承担长期职责。

保留 `detail` 中文文案（`"请求参数格式不正确：..."`）——本 handler 通过
懒 import `main.friendly_validation_error` 复用既有 FIELD_LABELS + msg
格式化逻辑；避免与旧行为形成第二份 truth。

**PR 边界**：本 handler 只覆盖 `RequestValidationError`；不引入错误 code 表
（PR-BE-12 §2）、DTO 迁移分层（§3）、启动兼容检查（§4）、下线判据登记（§5）
——这些等 PR-BE-06~11 落地后再另起增量 PR 承接。不修改日志脱敏配置——
那是部署 PR-10 的范畴。

参考：
- [[40 实施计划/后端模块化治理实施计划与PR清单]] PR-BE-12
- [[60 讨论记录/2026-07-17 第二批开工/2026-07-17 第二批 PR 开工协调纲要]]
  §"CB-02 承接边界说明"、§"保活烟测 BE-20"
- [[70 开发过程跟踪/缺陷追踪/CB-02 - PUT providers 422 error 回显 request
  body 含密钥]]
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from app.api.context import get_request_context

__all__ = ["validation_error_handler"]

_REQUEST_ID_HEADER = "X-Request-Id"


def _resolve_request_id(request: Request) -> str:
    """优先取 middleware 装配的 `RequestContext.request_id`；失败退化到 header。"""
    try:
        ctx = get_request_context()
        rid = getattr(ctx, "request_id", None)
        if isinstance(rid, str) and rid:
            return rid
    except Exception:
        # 任何 ctx 提取失败均退化，不允许 handler 抛错遮蔽原始 422。
        pass
    header_rid = request.headers.get(_REQUEST_ID_HEADER)
    if isinstance(header_rid, str) and header_rid.strip():
        return header_rid.strip()
    return "unknown"


def _sanitize_errors(raw_errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """剔除每条 error 里的 `input` 字段；保留其余键名。

    Pydantic v2 的 `errors()` 返回条目字段：`type` / `loc` / `msg` / `input` /
    `ctx` / `url`。本函数**只删除 `input`**，其他键原样透传（`loc` 只含字段
    路径，无 payload 值；`ctx` 是 Pydantic 校验器上下文，标量约束值如
    max_length，不含用户输入）。
    """
    sanitized: List[Dict[str, Any]] = []
    for err in raw_errors or []:
        if not isinstance(err, dict):
            # 罕见路径：非 dict 条目，直接透传（避免二次异常）。
            sanitized.append(err)  # type: ignore[arg-type]
            continue
        clean = {k: v for k, v in err.items() if k != "input"}
        sanitized.append(clean)
    return sanitized


def _friendly_detail(exc: RequestValidationError) -> str:
    """复用 `main.friendly_validation_error` 生成中文 `detail` 文案。

    懒 import 规避 `main` <-> `app.api` 循环依赖。若 main 侧函数缺失（例如
    未来重构解耦），退化到默认 fallback 文案。
    """
    try:
        import main as _main  # type: ignore[import-untyped]

        formatter = getattr(_main, "friendly_validation_error", None)
        if callable(formatter):
            return str(formatter(exc.errors()))
    except Exception:
        pass
    return "请求参数格式不正确。"


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """全局 `RequestValidationError` handler（CB-02 短期兜底）。

    行为契约：
    - HTTP 422（与 FastAPI / 旧 `main.py` 默认状态码一致）。
    - 响应体 shape：`{"detail": <中文文案>, "errors": [...清理过的...], "request_id": <str>}`。
      `detail` / `errors` 字段名与旧 handler 保持一致，前端解析路径无需改动；
      `errors[].input` 已被剔除（本 PR 核心变更），`errors[].type / loc / msg / ctx` 保留；
      顶层新增 `request_id`（本 PR 新增字段）。
    - 响应 header 含 `X-Request-Id`（`RequestContextMiddleware` 在 response
      阶段本就会写；本 handler 显式再写一次，覆盖 middleware 之前抛出的
      早期异常路径——保证 header 与 body 内 `request_id` 一致）。

    OpenAPI schema 影响：FastAPI 默认不把 422 响应 body 描述为 schema
    组件（只在 `responses.422.content` 挂 `HTTPValidationError` refer）；
    本 handler 修改 body 结构不进 OpenAPI spec，`openapi_diff.py --baseline`
    应保持 exit=0。
    """
    request_id = _resolve_request_id(request)
    body: Dict[str, Any] = {
        "detail": _friendly_detail(exc),
        "errors": _sanitize_errors(exc.errors()),
        "request_id": request_id,
    }
    response = JSONResponse(status_code=422, content=body)
    response.headers[_REQUEST_ID_HEADER] = request_id
    return response
