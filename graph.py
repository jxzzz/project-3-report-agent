from langgraph.graph import END, START, StateGraph

from agent_nodes import (
    blocked_node,
    data_agent_node,
    human_approval_node,
    planner_node,
    reviewer_node,
    writer_node,
)
from state import ReportState


def route_after_planner(state: ReportState) -> str:
    if state.get("plan", {}).get("feasible"):
        return "data_agent"
    return "blocked"


def route_after_data(state: ReportState) -> str:
    if state.get("status") == "data_ready":
        return "writer"
    return "blocked"


def route_after_reviewer(state: ReportState) -> str:
    history = state.get("review_history", [])
    last = history[-1] if history else {}

    if last.get("decision") == "pass":
        return "human_gate"

    if state.get("review_round", 0) >= 2:
        return "blocked"

    return "writer"


def build_graph():
    graph = StateGraph(ReportState)

    graph.add_node("planner", planner_node)
    graph.add_node("data_agent", data_agent_node)
    graph.add_node("writer", writer_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("human_gate", human_approval_node)
    graph.add_node("blocked", blocked_node)

    graph.add_edge(START, "planner")

    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {"data_agent": "data_agent", "blocked": "blocked"},
    )

    graph.add_conditional_edges(
        "data_agent",
        route_after_data,
        {"writer": "writer", "blocked": "blocked"},
    )

    graph.add_edge("writer", "reviewer")

    graph.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        {
            "writer": "writer",
            "human_gate": "human_gate",
            "blocked": "blocked",
        },
    )

    graph.add_edge("human_gate", END)
    graph.add_edge("blocked", END)

    return graph.compile()