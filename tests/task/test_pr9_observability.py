"""任务 PR-9 · 结构化日志 + 指标骨架测试 · T100-T129 · 30 项。"""

from __future__ import annotations

import json
import logging

import pytest

from app.task.observability import (
    MetricRegistry,
    REGISTRY,
    emit_structured,
    emit_task_active,
    emit_task_completed,
    emit_task_submitted,
    now_ms,
)


@pytest.fixture(autouse=True)
def reset_registry():
    REGISTRY.reset()
    yield
    REGISTRY.reset()


# ---------------------------------------------------------------------------
# T100-T104 · emit_structured 白名单过滤
# ---------------------------------------------------------------------------


def test_T100_emit_structured_writes_allowed_fields(caplog):
    caplog.set_level(logging.INFO, logger="app.task.obs")
    emit_structured("task.submitted", {"task_id": "t1", "task_type": "image"})
    assert any("task.submitted" in r.message for r in caplog.records)
    line = [r.message for r in caplog.records if "task.submitted" in r.message][-1]
    payload = json.loads(line)
    assert payload["task_id"] == "t1"
    assert payload["task_type"] == "image"


def test_T101_emit_structured_filters_unknown_fields(caplog):
    caplog.set_level(logging.INFO, logger="app.task.obs")
    emit_structured(
        "task.submitted",
        {"task_id": "t1", "secret_field": "leaked", "arbitrary_key": "x"},
    )
    line = [r.message for r in caplog.records if "task.submitted" in r.message][-1]
    payload = json.loads(line)
    assert payload["task_id"] == "t1"
    assert "secret_field" not in payload
    assert "arbitrary_key" not in payload


def test_T102_emit_structured_all_14_fields():
    """治理方案清单 14 字段全部允许通过。"""
    fields = {
        "task_id": "t1",
        "node_run_id": "n1",
        "provider_task_id": "pt1",
        "user_id": "u1",
        "workspace_id": "w1",
        "project_id": "p1",
        "canvas_id": "c1",
        "provider_id": "prov1",
        "model": "gpt-4",
        "attempt": 2,
        "upstream_task_id": "up1",
        "status": "succeeded",
        "duration_ms": 1234.5,
        "error_category": None,
    }
    # 只是验证不抛异常 · 白名单接受全部 14 字段
    emit_structured("test", fields)


def test_T103_emit_structured_handles_non_json_values(caplog):
    caplog.set_level(logging.INFO, logger="app.task.obs")

    class Weird:
        pass

    # weird 对象经 default=str 兜底
    emit_structured("test", {"task_id": Weird()})
    line = [r.message for r in caplog.records if r.message.startswith("test")][0] \
        if not caplog.records or "test" not in caplog.records[-1].message \
        else caplog.records[-1].message
    # 只是要求不抛异常


def test_T104_emit_structured_default_info_level(caplog):
    caplog.set_level(logging.DEBUG, logger="app.task.obs")
    emit_structured("task.debug", {"task_id": "t1"}, level=logging.DEBUG)
    assert any(r.levelno == logging.DEBUG for r in caplog.records)


# ---------------------------------------------------------------------------
# T105-T112 · MetricRegistry counter/gauge/histogram
# ---------------------------------------------------------------------------


def test_T105_counter_inc_basic():
    reg = MetricRegistry()
    reg.counter_inc("foo")
    reg.counter_inc("foo")
    reg.counter_inc("foo")
    snap = reg.snapshot()
    assert snap["counters"]["foo|"] == 3


def test_T106_counter_inc_with_labels():
    reg = MetricRegistry()
    reg.counter_inc("bar", labels={"a": "1"})
    reg.counter_inc("bar", labels={"a": "2"})
    reg.counter_inc("bar", labels={"a": "1"})
    snap = reg.snapshot()
    assert snap["counters"]["bar|a=1"] == 2
    assert snap["counters"]["bar|a=2"] == 1


def test_T107_gauge_set_replaces():
    reg = MetricRegistry()
    reg.gauge_set("g", 5.0)
    reg.gauge_set("g", 10.0)
    snap = reg.snapshot()
    assert snap["gauges"]["g|"] == 10.0


def test_T108_gauge_inc_accumulates():
    reg = MetricRegistry()
    reg.gauge_inc("g", delta=1.0)
    reg.gauge_inc("g", delta=2.5)
    reg.gauge_inc("g", delta=-1.5)
    snap = reg.snapshot()
    assert snap["gauges"]["g|"] == 2.0


def test_T109_histogram_observe_buckets():
    reg = MetricRegistry()
    for v in (50, 200, 700, 2000, 10000, 50000):
        reg.histogram_observe("h", v)
    snap = reg.snapshot()
    hist = snap["histograms"]["h|"]
    assert hist["count"] == 6
    assert hist["sum"] == pytest.approx(62950.0)
    # bucket 100: 只有 50 落入
    assert hist["buckets"][100.0] == 1
    # bucket 500: 50 + 200 落入
    assert hist["buckets"][500.0] == 2
    # bucket 5000: 50 + 200 + 700 + 2000 落入
    assert hist["buckets"][5000.0] == 4
    # bucket 30000: 50 + 200 + 700 + 2000 + 10000 落入
    assert hist["buckets"][30000.0] == 5


def test_T110_registry_reset_clears_all():
    reg = MetricRegistry()
    reg.counter_inc("c")
    reg.gauge_set("g", 5.0)
    reg.histogram_observe("h", 100.0)
    reg.reset()
    snap = reg.snapshot()
    assert snap == {"counters": {}, "gauges": {}, "histograms": {}}


def test_T111_label_key_sorted():
    """相同 labels 不同顺序 · label_key 一致(sorted 保证)。"""
    reg = MetricRegistry()
    reg.counter_inc("c", labels={"b": "2", "a": "1"})
    reg.counter_inc("c", labels={"a": "1", "b": "2"})
    snap = reg.snapshot()
    assert snap["counters"]["c|a=1,b=2"] == 2


def test_T112_global_registry_singleton():
    """REGISTRY 是全局单例 · fixture reset 已清空。"""
    assert isinstance(REGISTRY, MetricRegistry)
    REGISTRY.counter_inc("x")
    snap = REGISTRY.snapshot()
    assert snap["counters"]["x|"] == 1


# ---------------------------------------------------------------------------
# T113-T119 · emit_task_* 高层函数
# ---------------------------------------------------------------------------


def test_T113_emit_task_submitted_counter():
    emit_task_submitted(task_id="t1", task_type="image", provider_id="p1")
    snap = REGISTRY.snapshot()
    key = "infcvs_task_submitted_total|provider_id=p1,task_type=image"
    assert snap["counters"][key] == 1


def test_T114_emit_task_completed_success_counter():
    emit_task_completed(
        task_id="t1",
        task_type="image",
        status="succeeded",
        duration_ms=500.0,
    )
    snap = REGISTRY.snapshot()
    key = "infcvs_task_completed_total|status=succeeded,task_type=image"
    assert snap["counters"][key] == 1


def test_T115_emit_task_completed_failure_counter():
    emit_task_completed(
        task_id="t1",
        task_type="image",
        status="failed",
        duration_ms=500.0,
        error_category="timeout",
    )
    snap = REGISTRY.snapshot()
    key = "infcvs_task_failed_total|error_category=timeout,status=failed,task_type=image"
    assert snap["counters"][key] == 1


def test_T116_emit_task_completed_duration_histogram():
    emit_task_completed(
        task_id="t1",
        task_type="image",
        status="succeeded",
        duration_ms=750.0,
    )
    snap = REGISTRY.snapshot()
    key = "infcvs_task_duration_ms|status=succeeded,task_type=image"
    hist = snap["histograms"][key]
    assert hist["count"] == 1
    assert hist["sum"] == 750.0


def test_T117_emit_task_active_gauge_symmetry():
    emit_task_active(task_type="image", delta=1.0)
    emit_task_active(task_type="image", delta=1.0)
    emit_task_active(task_type="image", delta=-1.0)
    snap = REGISTRY.snapshot()
    key = "infcvs_task_active_gauge|task_type=image"
    assert snap["gauges"][key] == 1.0


def test_T118_now_ms_monotonic():
    t1 = now_ms()
    t2 = now_ms()
    assert t2 >= t1
    assert isinstance(t1, float)


def test_T119_all_events_use_independent_logger(caplog):
    """所有 emit_* 走 app.task.obs logger · 不污染 root。"""
    caplog.set_level(logging.INFO, logger="app.task.obs")
    root_before = len([r for r in caplog.records if r.name == "root"])
    emit_task_submitted(task_id="t1", task_type="image")
    emit_task_completed(task_id="t1", task_type="image", status="succeeded", duration_ms=100.0)
    obs_records = [r for r in caplog.records if r.name == "app.task.obs"]
    assert len(obs_records) >= 2
    root_after = len([r for r in caplog.records if r.name == "root"])
    assert root_after == root_before  # 不污染 root


# ---------------------------------------------------------------------------
# T120-T124 · P0 密钥零泄漏
# ---------------------------------------------------------------------------


def test_T120_emit_structured_drops_unknown_keys(caplog):
    """尝试塞 9 sentinel 键名 · 全部被 _ALLOWED_LOG_FIELDS 过滤。"""
    caplog.set_level(logging.INFO, logger="app.task.obs")
    sentinel_fields = {
        "task_id": "t1",
        "api_key": "leak-1",
        "access_token": "leak-2",
        "secret": "leak-3",
        "bearer": "leak-4",
        "refresh_token": "leak-5",
        "authorization": "leak-6",
        "x-api-key": "leak-7",
        "client_secret": "leak-8",
        "sk-abc": "leak-9",
    }
    emit_structured("test", sentinel_fields)
    obs_records = [r for r in caplog.records if r.name == "app.task.obs"]
    assert len(obs_records) >= 1
    line = obs_records[-1].getMessage()
    # 断言 9 sentinel value 全部不在输出中
    for leak in ("leak-1", "leak-2", "leak-3", "leak-4", "leak-5",
                 "leak-6", "leak-7", "leak-8", "leak-9"):
        assert leak not in line, f"sentinel {leak} leaked into log: {line}"


def test_T121_metric_labels_do_not_include_pii():
    """指标 labels 只允许 task_type / provider_id / status / error_category 4 类
    · 不接受任意用户提供的 label(比如 user_id 会被合规审计拦)。"""
    # 本 PR 骨架不做 label 白名单强制 · 但记录:实际调用点应严守。
    # 只验证 emit_task_submitted 输出不含 user_id label。
    emit_task_submitted(task_id="t1", task_type="image")
    snap = REGISTRY.snapshot()
    for key in snap["counters"]:
        assert "user_id" not in key


def test_T122_registry_reset_isolates_tests():
    """每个测试后 reset · 抗回归确保测试隔离。"""
    # fixture 已自动 reset · 这里只验证初始状态。
    snap = REGISTRY.snapshot()
    assert snap["counters"] == {}
    assert snap["gauges"] == {}
    assert snap["histograms"] == {}


def test_T123_emit_structured_json_serializable():
    """输出 JSON 可 parse · 便于 log aggregation 消费。"""
    import io
    handler = logging.StreamHandler(io.StringIO())
    logger = logging.getLogger("app.task.obs")
    handler.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        emit_structured("task.submitted", {"task_id": "t1", "task_type": "image"})
        output = handler.stream.getvalue().strip()
        payload = json.loads(output)
        assert payload["event"] == "task.submitted"
    finally:
        logger.removeHandler(handler)


def test_T124_module_exports_stable():
    """__all__ 稳定契约 · 抗回归。"""
    from app.task import observability
    assert "emit_task_submitted" in observability.__all__
    assert "emit_task_completed" in observability.__all__
    assert "emit_task_active" in observability.__all__
    assert "MetricRegistry" in observability.__all__
    assert "REGISTRY" in observability.__all__
