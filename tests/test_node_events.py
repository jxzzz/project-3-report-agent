"""真 graph + 假 LLM，验证节点 emit 接线与事件序列（完全离线）。"""

import time

import pytest

import agent_nodes
from graph import build_graph
from stream_events import iter_stream_events

PLAN_JSON = {
    "feasible": True,
    "report_title": "测试报告",
    "summary": "摘要",
    "sections": [{"title": "章节1", "focus": "总销售额"}],
    "data_requirements": [
        {"id": "d1", "description": "总销售额", "related_sections": ["章节1"]},
        {"id": "d2", "description": "订单数", "related_sections": ["章节1"]},
    ],
}

SQL_JSON = {
    "queries": [
        {"requirement_id": "d1", "sql": "SELECT 1"},
        {"requirement_id": "d2", "sql": "SELECT 2"},
    ],
}

REVIEW_PASS_JSON = {"decision": "pass", "issues": [], "summary": "ok"}

WRITER_CONTENT = "# 测试报告\n\n总销售额 100 元 [数据：d1]。订单数 5 笔 [数据：d2]。"

FAKE_USAGE = {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10}


def make_fake_chat_json():
    def fake_chat_json(system_prompt, user_content, temperature=0.2, max_retries=3):
        # 用各 system prompt 独有的角色声明分派，避免关键字重叠误判
        if "规划 Agent" in system_prompt:
            parsed = dict(PLAN_JSON)
        elif "SQL 查询 Agent" in system_prompt:
            parsed = dict(SQL_JSON)
        elif "审查 Agent" in system_prompt:
            parsed = dict(REVIEW_PASS_JSON)
        else:
            raise AssertionError(f"未知 system_prompt: {system_prompt[:50]}")
        parsed["_usage"] = dict(FAKE_USAGE)
        return parsed

    return fake_chat_json


def fake_chat(messages, temperature=0.2, json_mode=False):
    return {"content": WRITER_CONTENT, "usage": dict(FAKE_USAGE)}


def fake_execute_select_ok(sql, params=()):
    return {"sql": sql, "columns": ["total"], "rows": [[1]], "row_count": 1}


@pytest.fixture
def mock_llm(monkeypatch):
    monkeypatch.setattr(agent_nodes, "chat_json", make_fake_chat_json())
    monkeypatch.setattr(agent_nodes, "chat", fake_chat)
    monkeypatch.setattr(agent_nodes, "execute_select", fake_execute_select_ok)


INITIAL_STATE = {
    "user_request": "2026年8月总销售额是多少？",
    "auto_approve": True,
    "status": "start",
}


def collect_events(graph):
    events = []
    final_state = None
    for event, state in iter_stream_events(graph, dict(INITIAL_STATE), time.perf_counter()):
        events.append(event)
        if state is not None:
            final_state = state
    return events, final_state


def test_full_event_sequence(mock_llm):
    events, final_state = collect_events(build_graph())

    sequence = [
        (event.get("type"), event.get("node"))
        for event in events
    ]

    assert sequence == [
        ("node_start", "planner"),
        ("node_end", "planner"),
        ("node_start", "data_agent"),
        ("sql_round_start", "data_agent"),
        ("sql_attempt", "data_agent"),
        ("sql_attempt", "data_agent"),
        ("node_end", "data_agent"),
        ("node_start", "writer"),
        ("node_end", "writer"),
        ("node_start", "reviewer"),
        ("node_end", "reviewer"),
        ("node_start", "human_gate"),
        ("node_end", "human_gate"),
        ("report_complete", None),
    ]

    # 每个 node_start 都有配对的 node_end
    starts = [e for e in events if e["type"] == "node_start"]
    ends = [e for e in events if e["type"] == "node_end"]
    assert [e["node"] for e in starts] == [e["node"] for e in ends]

    planner_end = next(
        e for e in events if e["type"] == "node_end" and e["node"] == "planner"
    )
    assert planner_end["data"]["feasible"] is True
    assert planner_end["data"]["sections"] == ["章节1"]
    assert planner_end["data"]["data_requirement_count"] == 2

    reviewer_end = next(
        e for e in events if e["type"] == "node_end" and e["node"] == "reviewer"
    )
    assert reviewer_end["data"]["decision"] == "pass"
    assert reviewer_end["data"]["hard_rule"] is False

    complete = events[-1]
    assert complete["type"] == "report_complete"
    assert complete["data"]["status"] == "approved"
    assert complete["data"]["report"] == WRITER_CONTENT
    assert complete["data"]["total_tokens"] > 0

    assert final_state is not None
    assert final_state["status"] == "approved"


def test_sql_retry_events(mock_llm, monkeypatch):
    calls = {"SELECT 1": 0}

    def flaky_execute_select(sql, params=()):
        if sql == "SELECT 1":
            calls[sql] += 1
            if calls[sql] == 1:
                return {"error": "no such column: x"}
        return {"sql": sql, "columns": ["total"], "rows": [[1]], "row_count": 1}

    monkeypatch.setattr(agent_nodes, "execute_select", flaky_execute_select)

    events, _ = collect_events(build_graph())

    attempts = [
        e["data"] for e in events
        if e["type"] == "sql_attempt" and e["data"]["requirement_id"] == "d1"
    ]

    assert len(attempts) == 2
    assert attempts[0]["ok"] is False
    assert attempts[0]["attempt"] == 1
    assert "no such column" in attempts[0]["error"]
    assert attempts[1]["ok"] is True
    assert attempts[1]["attempt"] == 2

    rounds = [
        e["data"] for e in events if e["type"] == "sql_round_start"
    ]
    assert [r["attempt"] for r in rounds] == [1, 2]
    assert rounds[1]["pending_ids"] == ["d1"]


def test_invoke_unaffected_by_emit(mock_llm):
    # 同一套 mock 下 invoke 行为不变（emit 在非流式下为 no-op）
    result = build_graph().invoke(dict(INITIAL_STATE))

    assert result["status"] == "approved"
    assert result["final_report"] == WRITER_CONTENT
    assert len(result["queries"]) == 2
