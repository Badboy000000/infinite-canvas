"""构建 42 个 fixture 样本 + 42 个 expected_normalized（PR-5）。

**这个脚本只在开发时手工跑一次**，产物直接 checkin；测试运行时**不**再调用
这个脚本，而是直接读取磁盘上的 JSON。

跑法（本地一次性）::

    python tests/task/view/fixtures/build_fixtures.py

运行后，`tests/task/view/fixtures/provider_samples/{provider}/{status}.json`
+ `expected_normalized.json` 会被覆盖写。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Mapping

ROOT = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(ROOT, "..", "..", "..", "..")))

from app.task.view.provider_view import (
    map_apimart_task,
    map_chat_task,
    map_comfy_task,
    map_generic_image_task,
    map_jimeng_task,
    map_runninghub_task,
    map_video_task,
)


STATUSES = ("success", "fail", "timeout", "cancel", "partial", "rate_limit")


# ---------------------------------------------------------------------------
# fixture 定义（每 provider × 6 status）
# ---------------------------------------------------------------------------


def _rh_samples() -> dict[str, dict]:
    return {
        "success": {
            "code": 0,
            "msg": "ok",
            "data": {
                "taskId": "rh-abc-001",
                "status": "SUCCESS",
                "progress": 100,
                "results": [
                    {"url": "https://rh.example.com/out/rh-abc-001.png"},
                    {"url": "https://rh.example.com/out/rh-abc-001-2.png"},
                ],
            },
            "requestId": "req-rh-001",
        },
        "fail": {
            "code": 502,
            "data": {
                "taskId": "rh-abc-002",
                "status": "FAILED",
                "task_status": "FAILED",
            },
            "message": "workflow execution failed",
            "error": {"code": "RH_WORKFLOW_ERROR", "message": "workflow execution failed"},
            "requestId": "req-rh-002",
            # SENTINEL: 该字段模拟上游误回带凭据，view 应剔除
            "api_key": "sk-should-be-redacted",
        },
        "timeout": {
            "code": 504,
            "data": {"taskId": "rh-abc-003", "status": "TIMEOUT"},
            "error": {"code": "TIMEOUT", "message": "task exceeded 600s"},
            "requestId": "req-rh-003",
        },
        "cancel": {
            "code": 0,
            "data": {"taskId": "rh-abc-004", "status": "CANCELLED"},
            "requestId": "req-rh-004",
        },
        "partial": {
            "code": 0,
            "data": {
                "taskId": "rh-abc-005",
                "status": "SUCCESS",
                # 声称成功但零 results —— 触发 partial_success 兜底
                "results": [],
            },
            "requestId": "req-rh-005",
        },
        "rate_limit": {
            "code": 429,
            "data": {"taskId": "rh-abc-006", "status": "rate_limited"},
            "error": {"code": "rate_limit", "message": "Too many requests"},
            "requestId": "req-rh-006",
            # SENTINEL: header 字段
            "Authorization": "Bearer LEAK-BE-REDACTED",
        },
    }


def _apimart_samples() -> dict[str, dict]:
    return {
        "success": {
            "code": 200,
            "data": {
                "task_id": "am-1001",
                "status": "SUCCEEDED",
                "results": [{"url": "https://am.example.com/img/am-1001.png"}],
            },
        },
        "fail": {
            "code": 500,
            "data": {"task_id": "am-1002", "status": "FAILED", "fail_reason": "内容审查失败"},
            "error": {"code": "APIMART_CONTENT_REJECTED", "message": "内容审查失败"},
            "access_token": "should-be-redacted-token",
        },
        "timeout": {
            "code": 504,
            "data": {"task_id": "am-1003", "status": "expired"},
            "error": {"code": "timeout", "message": "APIMart 任务超时"},
        },
        "cancel": {
            "code": 200,
            "data": {"task_id": "am-1004", "status": "cancelled"},
        },
        "partial": {
            "code": 200,
            "data": {"task_id": "am-1005", "status": "SUCCEEDED", "results": []},
        },
        "rate_limit": {
            "code": 429,
            "data": {"task_id": "am-1006", "status": "queued"},
            "error": {"code": "rate_limit_exceeded", "message": "APIMart 触发限流"},
        },
    }


def _generic_image_samples() -> dict[str, dict]:
    return {
        "success": {
            "task_id": "img-2001",
            "status": "completed",
            "progress": 100,
            "outputs": [
                {"url": "https://img.example.com/2001.png"},
                {"url": "https://img.example.com/2001-alt.png"},
            ],
        },
        "fail": {
            "task_id": "img-2002",
            "status": "failed",
            "fail_reason": "参数非法",
            "error": {"code": "invalid_param", "message": "参数非法"},
        },
        "timeout": {
            "task_id": "img-2003",
            "status": "timeout",
            "error": {"code": "timeout", "message": "生图任务超时"},
        },
        "cancel": {"task_id": "img-2004", "status": "cancelled"},
        "partial": {"task_id": "img-2005", "status": "done", "outputs": []},
        "rate_limit": {
            "task_id": "img-2006",
            "status": "queued",
            "error": {"code": "rate_limited", "message": "限流触发"},
        },
    }


def _video_samples() -> dict[str, dict]:
    return {
        "success": {
            "task_id": "vid-3001",
            "status": "completed",
            "progress_percent": 100,
            "videos": [{"url": "https://vid.example.com/3001.mp4"}],
        },
        "fail": {
            "task_id": "vid-3002",
            "status": "failed",
            "error": {"code": "generation_error", "message": "视频生成失败"},
        },
        "timeout": {
            "task_id": "vid-3003",
            "status": "expired",
            "error": {"code": "timeout", "message": "视频任务超时"},
        },
        "cancel": {"task_id": "vid-3004", "status": "cancelled"},
        "partial": {"task_id": "vid-3005", "status": "SUCCEED", "videos": []},
        "rate_limit": {
            "task_id": "vid-3006",
            "status": "queued",
            "error": {"code": "rate_limit", "message": "上游限流"},
        },
    }


def _jimeng_samples() -> dict[str, dict]:
    return {
        "success": {
            "submit_id": "jm-4001",
            "gen_status": "success",
            "images": [
                "https://jimeng.example.com/img/jm-4001-1.jpg",
                "https://jimeng.example.com/img/jm-4001-2.jpg",
            ],
        },
        "fail": {
            "submit_id": "jm-4002",
            "gen_status": "fail",
            "fail_reason": "prompt invalid",
        },
        "timeout": {
            "submit_id": "jm-4003",
            "gen_status": "fail",
            "fail_reason": "cli timeout after 300s",
        },
        "cancel": {"submit_id": "jm-4004", "gen_status": "cancelled"},
        "partial": {"submit_id": "jm-4005", "gen_status": "success", "images": []},
        "rate_limit": {
            "submit_id": "jm-4006",
            "gen_status": "jimeng_pending",
            "jimeng_pending": True,
            "queue_info": {"queue_idx": 12, "queue_length": 50},
        },
    }


def _comfyui_samples() -> dict[str, dict]:
    return {
        "success": {
            "prompt-5001": {
                "status": {
                    "status_str": "success",
                    "completed": True,
                    "messages": [
                        ["execution_start", {"prompt_id": "prompt-5001"}],
                        ["execution_success", {"prompt_id": "prompt-5001"}],
                    ],
                },
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "ComfyUI_00001_.png", "subfolder": "output", "type": "output"},
                        ]
                    }
                },
            }
        },
        "fail": {
            "prompt-5002": {
                "status": {
                    "status_str": "error",
                    "completed": True,
                    "messages": [
                        ["execution_error", {"exception_message": "KSampler failed: OOM"}],
                    ],
                },
                "outputs": {},
            }
        },
        "timeout": {
            "prompt-5003": {
                "status": {
                    "status_str": "error",
                    "completed": True,
                    "messages": [["execution_error", {"exception_message": "workflow timeout"}]],
                },
                "outputs": {},
            }
        },
        "cancel": {
            "prompt-5004": {
                "status": {
                    "status_str": "cancelled",
                    "completed": True,
                    "messages": [["execution_interrupted", {"reason": "user cancel"}]],
                },
                "outputs": {},
            }
        },
        "partial": {
            "prompt-5005": {
                "status": {"status_str": "success", "completed": True, "messages": []},
                "outputs": {},
            }
        },
        # ComfyUI 自身不返回 rate_limit，本 slot 用「空 history 表示排队中」
        "rate_limit": {},
    }


def _chat_samples() -> dict[str, dict]:
    return {
        "success": {
            "id": "chatcmpl-6001",
            "object": "chat.completion",
            "status": "completed",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello world."},
                    "finish_reason": "stop",
                }
            ],
        },
        "fail": {
            "id": "chatcmpl-6002",
            "status": "failed",
            "error": {"code": "invalid_request_error", "message": "unsupported model"},
        },
        "timeout": {
            "id": "chatcmpl-6003",
            "status": "failed",
            "error": {"code": "timeout", "message": "chat completion timeout"},
        },
        "cancel": {"id": "chatcmpl-6004", "status": "cancelled"},
        "partial": {
            "id": "chatcmpl-6005",
            "status": "completed",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "truncated..."},
                    "finish_reason": "length",
                }
            ],
        },
        "rate_limit": {
            "id": "chatcmpl-6006",
            "status": "failed",
            "error": {
                "code": "rate_limit_exceeded",
                "message": "You are being rate limited. Please retry.",
            },
            # SENTINEL: 上游误传的凭据字段
            "authorization": "Bearer LEAKED_TOKEN",
            "request_id": "req-6006",
        },
    }


PROVIDER_TO_SAMPLES = {
    "runninghub": _rh_samples,
    "apimart": _apimart_samples,
    "generic_image": _generic_image_samples,
    "video": _video_samples,
    "jimeng": _jimeng_samples,
    "comfyui": _comfyui_samples,
    "chat": _chat_samples,
}


PROVIDER_TO_MAPPER = {
    "runninghub": map_runninghub_task,
    "apimart": map_apimart_task,
    "generic_image": map_generic_image_task,
    "video": map_video_task,
    "jimeng": map_jimeng_task,
    "comfyui": map_comfy_task,
    "chat": map_chat_task,
}


def _write_json(path: str, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")


def build() -> None:
    base = os.path.join(ROOT, "provider_samples")
    for provider, samples_fn in PROVIDER_TO_SAMPLES.items():
        samples = samples_fn()
        mapper = PROVIDER_TO_MAPPER[provider]
        expected: dict[str, dict] = {}
        for status in STATUSES:
            sample = samples[status]
            _write_json(os.path.join(base, provider, f"{status}.json"), sample)
            view = mapper(sample)
            expected[status] = view.to_dict()
        _write_json(os.path.join(base, provider, "expected_normalized.json"), expected)


if __name__ == "__main__":
    build()
    print("built 42 samples + 7 expected_normalized aggregates")
