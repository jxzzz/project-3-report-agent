import json

from stream_events import (
    EVT_ERROR,
    EVT_NODE_END,
    EVT_NODE_START,
    EVT_REPORT_COMPLETE,
    EVT_SQL_ATTEMPT,
    EVT_SQL_ROUND_START,
    build_complete_event,
    emit,
    format_console_line,
    sse_format,
)


def test_emit_outside_runnable_context_is_noop():
    # 单测直调（无 graph 运行上下文）不应抛异常
    emit(EVT_NODE_START, "planner", foo=1)
    emit(EVT_NODE_END, "writer")


def test_sse_format_is_single_frame():
    event = {
        "type": EVT_NODE_START,
        "node": "planner",
        "ts": 123.0,
        "data": {"title": "销售报告"},
    }

    frame = sse_format(event)

    assert frame.startswith("event: node_start\n")
    assert frame.endswith("\n\n")

    lines = frame.strip().split("\n")
    assert len(lines) == 2

    payload = json.loads(lines[1].removeprefix("data: "))
    assert payload["node"] == "planner"
    # 中文不应被转义
    assert "销售报告" in lines[1]


def test_format_console_line_mapping():
    cases = [
        ({"type": EVT_NODE_START, "node": "planner", "data": {}}, "[planner]"),
        (
            {
                "type": EVT_SQL_ROUND_START,
                "node": "data_agent",
                "data": {"attempt": 2, "pending_ids": ["d1"]},
            },
            "第 2 轮",
        ),
        (
            {
                "type": EVT_SQL_ATTEMPT,
                "node": "data_agent",
                "data": {
                    "requirement_id": "d1",
                    "attempt": 1,
                    "ok": False,
                    "error": "no such column",
                },
            },
            "✗ d1",
        ),
        (
            {
                "type": EVT_NODE_END,
                "node": "reviewer",
                "data": {"decision": "pass", "round": 1},
            },
            "[reviewer]",
        ),
        (
            {
                "type": EVT_REPORT_COMPLETE,
                "data": {
                    "status": "approved",
                    "total_tokens": 100,
                    "latency_ms": 1.0,
                },
            },
            "approved",
        ),
        (
            {"type": EVT_ERROR, "data": {"message": "boom"}},
            "boom",
        ),
    ]

    for event, expected_fragment in cases:
        line = format_console_line(event)
        assert line is not None
        assert expected_fragment in line


def test_format_console_line_unknown_event_returns_none():
    assert format_console_line({"type": "run_start", "data": {}}) is None


def test_build_complete_event_summarizes_usage():
    import time

    final_state = {
        "status": "approved",
        "final_report": "# 报告",
        "review_round": 1,
        "usage": [
            {"total_tokens": 100},
            {"total_tokens": 50},
        ],
    }

    event = build_complete_event(final_state, time.perf_counter())

    assert event["type"] == EVT_REPORT_COMPLETE
    data = event["data"]
    assert data["status"] == "approved"
    assert data["report"] == "# 报告"
    assert data["llm_calls"] == 2
    assert data["total_tokens"] == 150
    assert data["review_round"] == 1
    assert data["latency_ms"] >= 0
