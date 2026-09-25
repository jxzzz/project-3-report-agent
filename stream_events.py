"""节点级进度事件：定义、发射、序列化与共享流消费循环。

API（SSE）与 CLI（--stream）共用本模块，节点侧只需调用 emit()。
emit 在任何非流式环境（invoke、单测直调节点函数）下安全 no-op，永不抛异常。
"""

import json
import time
from typing import Any, Iterator

EVT_RUN_START = "run_start"
EVT_NODE_START = "node_start"
EVT_NODE_END = "node_end"
EVT_SQL_ROUND_START = "sql_round_start"
EVT_SQL_ATTEMPT = "sql_attempt"
EVT_REPORT_COMPLETE = "report_complete"
EVT_ERROR = "error"


def emit(event_type: str, node: str | None = None, **data: Any) -> None:
    """节点侧唯一事件入口。

    - graph.stream(stream_mode 含 "custom") 时：事件实时推给消费端
    - graph.invoke / 单测直调 / 任何 runnable 上下文之外：静默丢弃
    """
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:
        return

    event: dict = {"type": event_type, "ts": time.time(), "data": data}
    if node is not None:
        event["node"] = node

    try:
        writer(event)
    except Exception:
        pass


def sse_format(event: dict) -> str:
    """事件 dict -> 单帧 SSE 文本。"""
    payload = json.dumps(event, ensure_ascii=False)
    return f"event: {event.get('type', 'message')}\ndata: {payload}\n\n"


def _brief(data: dict) -> str:
    """node_end 的 data 摘要，用于 CLI 单行展示。"""
    keys = (
        "feasible", "status", "decision", "round", "draft_chars",
        "ok_count", "failed_count", "reason",
    )
    parts = [f"{k}={data[k]}" for k in keys if k in data]
    return " ".join(parts)


def format_console_line(event: dict) -> str | None:
    """事件 -> CLI 人类可读单行；不需要打印的事件返回 None。"""
    event_type = event.get("type")
    node = event.get("node")
    data = event.get("data", {})

    if event_type == EVT_NODE_START:
        return f"→ [{node}] 开始…"

    if event_type == EVT_SQL_ROUND_START:
        ids = ", ".join(data.get("pending_ids", []))
        return f"  [{node}] 第 {data.get('attempt')} 轮 SQL 生成（待查：{ids}）"

    if event_type == EVT_SQL_ATTEMPT:
        mark = "✓" if data.get("ok") else "✗"
        line = f"  [{node}] {mark} {data.get('requirement_id')} 第 {data.get('attempt')} 次尝试"
        if data.get("error"):
            line += f"：{data['error']}"
        return line

    if event_type == EVT_NODE_END:
        brief = _brief(data)
        return f"← [{node}] 完成{('  ' + brief) if brief else ''}"

    if event_type == EVT_REPORT_COMPLETE:
        return (
            f"■ 结束 status={data.get('status')} "
            f"tokens={data.get('total_tokens')} "
            f"latency_ms={data.get('latency_ms')}"
        )

    if event_type == EVT_ERROR:
        return f"!! 错误: {data.get('message')}"

    return None


def build_complete_event(final_state: dict, started: float) -> dict:
    """从最终状态汇总 report_complete 事件（API 与 CLI 共用）。"""
    usage = final_state.get("usage", [])
    return {
        "type": EVT_REPORT_COMPLETE,
        "ts": time.time(),
        "data": {
            "status": final_state.get("status", "unknown"),
            "report": final_state.get("final_report", ""),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "llm_calls": len(usage),
            "total_tokens": sum(item.get("total_tokens", 0) for item in usage),
            "review_round": final_state.get("review_round"),
        },
    }


def iter_stream_events(
    graph,
    initial_state: dict,
    started: float,
) -> Iterator[tuple[dict, dict | None]]:
    """API 与 CLI 共用的流消费循环。

    yield (event, final_state)；final_state 仅在最后一条 report_complete 时非 None。
    graph 内部异常转成 error 事件，不向调用方抛出。
    """
    final_state: dict = {}

    try:
        for mode, chunk in graph.stream(
            initial_state,
            stream_mode=["custom", "values"],
        ):
            if mode == "custom":
                yield chunk, None
            elif mode == "values":
                final_state = chunk
    except Exception as exc:
        yield {
            "type": EVT_ERROR,
            "ts": time.time(),
            "data": {"message": str(exc)},
        }, None
        return

    yield build_complete_event(final_state, started), final_state
