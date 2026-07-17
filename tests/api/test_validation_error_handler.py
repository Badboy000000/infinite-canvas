"""PR-BE-12 短期兜底契约测试（承接 CB-02）。

覆盖 `app.api.errors.validation_error_handler` 的关键行为契约：

1. **CB-02 触发场景**（`PUT /api/providers` 错误 shape 含密钥）：
   - HTTP 422。
   - 响应 body 不含 `sk-TEST-DO-NOT-LOG` 字面量（`errors[].input` 已剔除）。
   - 响应 body 顶层含 `request_id`。
   - 响应 header 含 `X-Request-Id` 且值与 body 内 `request_id` 一致。
2. **其它 Pydantic 校验失败路由**（`POST /api/canvases` 缺字段 / 类型错误等）
   同样应用剔除策略；`errors[].input` 不出现在响应 body。
3. **正确 shape 请求**：不触发 handler，走原路径正常返回；证明 handler 不干扰
   非验证错误。
4. **参数化**：`errors[].input` 有 dict / list / bare value / None 四种源
   payload 场景，都不落敏感字面量到响应 body。

`RequestValidationError` handler 在 `main.py` 顶部通过
`app.add_exception_handler(RequestValidationError, validation_error_handler)`
注册；测试通过 `TestClient(main.app)` 消费真实 FastAPI 应用。
"""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient


_SENSITIVE_LITERAL = "sk-TEST-DO-NOT-LOG-e2e"


@pytest.fixture(scope="module")
def client() -> TestClient:
    # 懒 import main.app，避免 tests 顶部 import 触发全模块 side-effect。
    import main as _main  # type: ignore[import-untyped]

    return TestClient(_main.app)


# --- 1) CB-02 触发场景：PUT /api/providers 错误 shape 含密钥 ------------------


def test_put_providers_wrong_shape_strips_input_and_does_not_leak_key(
    client: TestClient,
) -> None:
    """CB-02 主场景：`{"providers":[...]}` 而非 bare list，body 含 api_key。

    旧行为：`errors[].input` 明文回显整个 `{"providers":[{...api_key...}]}` payload。
    新行为：`errors[].input` 剔除，响应 body 完全不含 `sk-TEST-DO-NOT-LOG-e2e`。
    """
    payload = {
        "providers": [
            {
                "id": "__smoke_be20_ct__",
                "name": "smoke",
                "protocol": "openai",
                "api_key": _SENSITIVE_LITERAL,
            }
        ]
    }
    resp = client.put("/api/providers", json=payload)
    assert resp.status_code == 422

    body_text = resp.text
    # 硬门槛：字面 grep 命中数必须为 0。
    assert _SENSITIVE_LITERAL not in body_text, (
        f"密钥字面量意外出现在 422 响应 body：\n{body_text}"
    )

    body = resp.json()
    # detail 中文文案保留。
    assert isinstance(body.get("detail"), str) and body["detail"], body
    # errors 数组存在且每条都不含 `input` 字段。
    assert isinstance(body.get("errors"), list) and body["errors"]
    for err in body["errors"]:
        assert isinstance(err, dict)
        assert "input" not in err, f"`errors[].input` 未剔除：{err}"
        # loc / msg / type 保留（这些不含 payload）。
        assert "type" in err
        assert "loc" in err
        assert "msg" in err
    # request_id 回填。
    rid = body.get("request_id")
    assert isinstance(rid, str) and rid, body
    # header 与 body 内 request_id 一致。
    assert resp.headers.get("X-Request-Id") == rid


def test_put_providers_wrong_shape_client_provided_request_id_is_echoed(
    client: TestClient,
) -> None:
    """CB-02 场景 + 客户端提供 X-Request-Id：body 与 header 都回显同值。"""
    fixed = "smoke-test-fixed-request-id-be20"
    payload = {
        "providers": [
            {
                "id": "__smoke_be20_rid__",
                "name": "smoke",
                "protocol": "openai",
                "api_key": _SENSITIVE_LITERAL,
            }
        ]
    }
    resp = client.put(
        "/api/providers",
        json=payload,
        headers={"X-Request-Id": fixed},
    )
    assert resp.status_code == 422
    assert _SENSITIVE_LITERAL not in resp.text
    body = resp.json()
    assert body.get("request_id") == fixed
    assert resp.headers.get("X-Request-Id") == fixed


# --- 2) 其它 Pydantic 校验失败路由同样应用剔除策略 ----------------------------


def test_post_canvas_image_tasks_missing_fields_strips_input(
    client: TestClient,
) -> None:
    """POST /api/canvas-image-tasks 缺 required 字段：errors[].input 剔除。"""
    # 故意传入 dict payload with 敏感值——即使不是 credentials 路由，
    # errors[].input 也不许回显。
    payload = {"foo": _SENSITIVE_LITERAL}
    resp = client.post("/api/canvas-image-tasks", json=payload)
    # 422（Pydantic 校验失败）或 4xx（业务校验）都可接受；关键是 handler
    # 触发时 errors[].input 剔除。
    if resp.status_code == 422:
        body = resp.json()
        assert _SENSITIVE_LITERAL not in resp.text, resp.text
        for err in body.get("errors", []) or []:
            assert "input" not in err
        assert isinstance(body.get("request_id"), str) and body["request_id"]


def test_post_canvases_wrong_body_type_strips_input(client: TestClient) -> None:
    """POST /api/canvases 传入非法 shape：errors[].input 剔除。"""
    # 传入 list 而非 dict，触发顶层 shape 校验错误。
    payload = [{"api_key": _SENSITIVE_LITERAL}]
    resp = client.post("/api/canvases", json=payload)
    if resp.status_code == 422:
        assert _SENSITIVE_LITERAL not in resp.text
        body = resp.json()
        assert isinstance(body.get("request_id"), str)
        for err in body.get("errors", []) or []:
            assert "input" not in err


# --- 3) 正确 shape 请求：不触发 handler，走原路径 -----------------------------


def test_correct_shape_request_bypasses_handler(client: TestClient) -> None:
    """正确 shape 的 GET /api/providers 走原路径，不触发 422 handler。"""
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    body = resp.json()
    # 原路径响应 shape 应含 `providers` 字段；不应含 `errors` / `request_id`
    # 顶层字段（那是 422 handler 才追加的）。
    assert "providers" in body
    assert "errors" not in body
    # 顶层 `request_id` 是 handler 专属；正常路径响应不追加。
    assert "request_id" not in body
    # 但 middleware 仍然在 header 层回写 X-Request-Id。
    assert resp.headers.get("X-Request-Id")


# --- 4) 参数化：input 有 dict / list / bare value / None 四种源 payload ------


@pytest.mark.parametrize(
    "payload_case",
    [
        # dict payload
        {"providers": [{"id": "x", "name": "x", "protocol": "openai", "api_key": _SENSITIVE_LITERAL}]},
        # list payload with dict items (仍然 422，因为 provider 缺字段 / 类型 或 shape 不匹配)
        [{"api_key": _SENSITIVE_LITERAL, "malformed": True}],
        # bare string payload（顶层 body 类型错误）
        _SENSITIVE_LITERAL,
        # None payload (empty body 场景对多数路由等价于缺 required 字段)
        None,
    ],
    ids=["dict", "list", "bare_str", "none"],
)
def test_various_payload_shapes_never_leak_sensitive_literal(
    client: TestClient, payload_case
) -> None:
    """参数化：各种 input 源 payload 都不落敏感字面量到 422 响应 body。"""
    # 用 requests 底层允许传 None body；FastAPI 会视为空 body → 缺字段 422。
    if payload_case is None:
        resp = client.put("/api/providers")
    else:
        resp = client.put("/api/providers", content=json.dumps(payload_case), headers={"Content-Type": "application/json"})

    # 只在 422 路径断言（其它 4xx / 5xx 不是本 handler 覆盖场景）。
    if resp.status_code == 422:
        assert _SENSITIVE_LITERAL not in resp.text, (
            f"payload_case={payload_case!r} 泄漏密钥字面量：\n{resp.text}"
        )
        body = resp.json()
        assert isinstance(body.get("request_id"), str) and body["request_id"]
        for err in body.get("errors", []) or []:
            assert "input" not in err, f"未剔除 input：{err}"
