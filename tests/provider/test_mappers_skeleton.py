"""Provider PR-02 mappers 骨架契约测试(T500-T539)。"""
from __future__ import annotations

import pytest

from app.adapters.provider.mappers import (
    canvas_task_payload_to_view,
    comfyui_payload_to_view,
    generic_image_payload_to_view,
    jimeng_payload_to_view,
    runninghub_payload_to_view,
    video_payload_to_view,
)


class TestGenericImageMapper:
    def test_T500_success_status(self):
        payload = {"status": "succeeded", "task_id": "t1"}
        view = generic_image_payload_to_view(payload)
        assert view.status == "succeeded"
        assert view.upstream_task_id == "t1"

    def test_T501_running_status(self):
        payload = {"status": "in_progress", "task_id": "t2"}
        view = generic_image_payload_to_view(payload)
        assert view.status == "running"

    def test_T502_failed_status(self):
        payload = {"status": "failed", "task_id": "t3"}
        view = generic_image_payload_to_view(payload)
        assert view.status == "failed"

    def test_T503_progress_percent_normalized(self):
        payload = {"status": "in_progress", "task_id": "t4", "progress": 50}
        view = generic_image_payload_to_view(payload)
        assert view.progress == 0.5

    def test_T504_outputs_from_images(self):
        payload = {
            "status": "succeeded",
            "task_id": "t5",
            "images": [{"url": "https://cdn/a.png"}, {"url": "https://cdn/b.png"}],
        }
        view = generic_image_payload_to_view(payload)
        assert len(view.outputs) == 2
        assert view.outputs[0].source_url_or_bytes == "https://cdn/a.png"

    def test_T505_provider_id_from_payload(self):
        payload = {"status": "succeeded", "task_id": "t6", "provider_id": "custom-provider"}
        view = generic_image_payload_to_view(payload)
        assert view.provider_id == "custom-provider"


class TestRunninghubMapper:
    def test_T506_success(self):
        payload = {"taskStatus": "success", "taskId": "rh-1"}
        view = runninghub_payload_to_view(payload)
        assert view.status == "succeeded"
        assert view.upstream_task_id == "rh-1"
        assert view.provider_id == "runninghub"

    def test_T507_failed(self):
        payload = {"taskStatus": "failed", "taskId": "rh-2"}
        view = runninghub_payload_to_view(payload)
        assert view.status == "failed"

    def test_T508_running(self):
        payload = {"taskStatus": "running", "taskId": "rh-3"}
        view = runninghub_payload_to_view(payload)
        assert view.status == "running"


class TestVideoMapper:
    def test_T509_video_success(self):
        payload = {"status": "succeeded", "task_id": "v1", "video_url": "https://cdn/vid.mp4"}
        view = video_payload_to_view(payload)
        assert view.status == "succeeded"
        assert len(view.outputs) == 1

    def test_T510_video_processing(self):
        payload = {"status": "processing", "task_id": "v2"}
        view = video_payload_to_view(payload)
        assert view.status == "running"


class TestJimengMapper:
    def test_T511_jimeng_pending_maps_to_waiting_upstream(self):
        payload = {"gen_status": "jimeng_pending", "task_id": "j1"}
        view = jimeng_payload_to_view(payload)
        assert view.status == "waiting_upstream"

    def test_T512_jimeng_success(self):
        payload = {"gen_status": "succeeded", "task_id": "j2"}
        view = jimeng_payload_to_view(payload)
        assert view.status == "succeeded"
        assert view.provider_id == "jimeng"

    def test_T513_jimeng_rate_limit_maps_to_failed(self):
        payload = {"gen_status": "rate_limit", "task_id": "j3"}
        view = jimeng_payload_to_view(payload)
        assert view.status == "failed"


class TestComfyuiMapper:
    def test_T514_comfyui_success_via_outputs(self):
        """无 status_str · 有 outputs → success"""
        payload = {"prompt_id": "c1", "outputs": [{"url": "https://cdn/c.png"}]}
        view = comfyui_payload_to_view(payload)
        assert view.status == "succeeded"
        assert view.provider_id == "comfyui"

    def test_T515_comfyui_failed_via_error(self):
        payload = {"prompt_id": "c2", "error": "some error"}
        view = comfyui_payload_to_view(payload)
        assert view.status == "failed"

    def test_T516_comfyui_running_no_output_no_error(self):
        payload = {"prompt_id": "c3"}
        view = comfyui_payload_to_view(payload)
        assert view.status == "running"


class TestCanvasTaskMapper:
    def test_T517_canvas_success(self):
        payload = {"status": "succeeded", "task_id": "ct1", "provider_id": "canvas-local"}
        view = canvas_task_payload_to_view(payload)
        assert view.status == "succeeded"

    def test_T518_canvas_waiting(self):
        payload = {"status": "waiting", "task_id": "ct2"}
        view = canvas_task_payload_to_view(payload)
        assert view.status == "waiting_upstream"


class TestRawExcerptSanitization:
    """raw_excerpt 严禁密钥泄漏(P0 密钥零泄漏防线)"""

    @pytest.mark.parametrize(
        "mapper,payload",
        [
            (
                generic_image_payload_to_view,
                {"status": "succeeded", "task_id": "t", "api_key": "sk-secret"},
            ),
            (
                runninghub_payload_to_view,
                {"taskStatus": "success", "taskId": "r", "wallet_api_key": "secret"},
            ),
            (
                video_payload_to_view,
                {"status": "succeeded", "task_id": "v", "password": "hunter2"},
            ),
            (
                jimeng_payload_to_view,
                {"gen_status": "succeeded", "task_id": "j", "token": "abc"},
            ),
        ],
        ids=["generic", "runninghub", "video", "jimeng"],
    )
    def test_T519_raw_excerpt_excludes_secrets(self, mapper, payload):
        view = mapper(payload)
        for forbidden in ("api_key", "wallet_api_key", "password", "token", "secret"):
            assert forbidden not in view.raw_excerpt, (
                f"raw_excerpt leaked {forbidden}: {view.raw_excerpt}"
            )


class TestUnknownStatusFallback:
    def test_T520_unknown_status_falls_to_running(self):
        payload = {"status": "unknown_state_xyz", "task_id": "u1"}
        view = generic_image_payload_to_view(payload)
        # 未识别 → default 'running'
        assert view.status == "running"


class TestContractExports:
    def test_T521_all_exports(self):
        from app.adapters.provider import mappers as m

        for sym in (
            "generic_image_payload_to_view",
            "runninghub_payload_to_view",
            "video_payload_to_view",
            "jimeng_payload_to_view",
            "comfyui_payload_to_view",
            "canvas_task_payload_to_view",
        ):
            assert sym in m.__all__

    def test_T522_view_is_frozen(self):
        """ProviderTaskView 是 Pydantic frozen · 不可变"""
        payload = {"status": "succeeded", "task_id": "t"}
        view = generic_image_payload_to_view(payload)
        with pytest.raises(Exception):
            view.status = "failed"  # type: ignore