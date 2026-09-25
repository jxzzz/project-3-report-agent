"""SSE 流式端点测试：FakeStreamGraph 离线验证帧序列与错误路径。"""

import json

from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


class FakeStreamGraph:
    """按预制 (mode, chunk) 序列产出，模拟 graph.stream 行为。"""

    def stream(self, state: dict, stream_mode=None):
        yield ("custom", {
            "type": "node_start", "node": "planner", "ts": 0.0, "data": {},
        })
        yield ("values", {"status": "planned"})
        yield ("custom", {
            "type": "node_end", "node": "planner", "ts": 0.0,
            "data": {"feasible": True},
        })
        yield ("values", {
            "status": "approved",
            "final_report": "# 测试",
            "review_round": 1,
            "usage": [{"total_tokens": 100}],
        })


class RaisingStreamGraph:
    def stream(self, state: dict, stream_mode=None):
        yield ("custom", {
            "type": "node_start", "node": "planner", "ts": 0.0, "data": {},
        })
        raise RuntimeError("boom")


def parse_sse(body: str) -> list:
    frames = []
    for chunk in body.split("\n\n"):
        if not chunk.strip():
            continue
        lines = chunk.split("\n")
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        event_type = lines[0].removeprefix("event: ").strip()
        data = json.loads(lines[1].removeprefix("data: "))
        frames.append((event_type, data))
    return frames


def test_stream_returns_sse_frames(monkeypatch):
    monkeypatch.setattr("api.report_graph", FakeStreamGraph())

    response = client.post(
        "/report/stream",
        json={"question": "测试问题：2026年8月销售额", "auto_approve": True},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"

    frames = parse_sse(response.text)
    types = [event_type for event_type, _ in frames]

    assert types[0] == "run_start"
    assert types[-1] == "report_complete"
    assert ("node_start", "planner") in [
        (t, d.get("node")) for t, d in frames
    ]

    # 每一帧都带 request_id，且同一次运行内一致
    request_ids = {d["request_id"] for _, d in frames}
    assert len(request_ids) == 1

    complete_data = frames[-1][1]["data"]
    assert complete_data["status"] == "approved"
    assert complete_data["report"] == "# 测试"
    assert complete_data["total_tokens"] == 100
    assert complete_data["review_round"] == 1


def test_stream_rejects_manual_approval(monkeypatch):
    monkeypatch.setattr("api.report_graph", FakeStreamGraph())

    response = client.post(
        "/report/stream",
        json={"question": "测试问题：2026年8月销售额", "auto_approve": False},
    )

    assert response.status_code == 422
    assert "auto_approve" in response.json()["detail"]


def test_stream_graph_error_emits_error_frame(monkeypatch):
    monkeypatch.setattr("api.report_graph", RaisingStreamGraph())

    response = client.post(
        "/report/stream",
        json={"question": "测试问题：2026年8月销售额", "auto_approve": True},
    )

    # 流已开始，状态码无法再改，错误以事件帧收尾
    assert response.status_code == 200

    frames = parse_sse(response.text)
    assert frames[-1][0] == "error"
    assert "boom" in frames[-1][1]["data"]["message"]


def test_stream_incremental_read(monkeypatch):
    monkeypatch.setattr("api.report_graph", FakeStreamGraph())

    with client.stream(
        "POST",
        "/report/stream",
        json={"question": "测试问题：2026年8月销售额", "auto_approve": True},
    ) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line]

    assert any(line.startswith("event: run_start") for line in lines)
    assert any(line.startswith("event: report_complete") for line in lines)
