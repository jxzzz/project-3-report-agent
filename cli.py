import argparse
import datetime
import json
import time
from pathlib import Path

from graph import build_graph

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"
RUN_DIR = PROJECT_ROOT / "runs"


def summarize_tokens(usage_records: list) -> dict:
    prompt = sum(item.get("prompt_tokens", 0) for item in usage_records)
    completion = sum(item.get("completion_tokens", 0) for item in usage_records)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "llm_calls": len(usage_records),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="多 Agent 数据分析报告生成器")
    parser.add_argument("--question", required=True, help="用户问题")
    parser.add_argument("--approve", action="store_true", help="跳过人工确认")
    args = parser.parse_args()

    started = time.perf_counter()

    app = build_graph()
    result = app.invoke({
        "user_request": args.question,
        "auto_approve": args.approve,
        "status": "start",
    })

    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    usage_records = result.get("usage", [])
    token_summary = summarize_tokens(usage_records)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    report_text = result.get("final_report", "")
    status = result.get("status", "unknown")

    print("\n===== 最终报告 =====")
    print(report_text)
    print("\n===== 运行摘要 =====")
    print("status:", status)
    print("llm_calls:", token_summary["llm_calls"])
    print("total_tokens:", token_summary["total_tokens"])
    print("latency_ms:", latency_ms)
    print("review_round:", result.get("review_round"))

    OUTPUT_DIR.mkdir(exist_ok=True)
    RUN_DIR.mkdir(exist_ok=True)

    report_path = OUTPUT_DIR / f"report_{timestamp}.md"
    run_path = RUN_DIR / f"run_{timestamp}.json"

    report_path.write_text(report_text, encoding="utf-8")

    metrics = {
        "timestamp": timestamp,
        "question": args.question,
        "status": status,
        "latency_ms": latency_ms,
        "review_round": result.get("review_round"),
        "review_history": result.get("review_history"),
        "token_summary": token_summary,
        "usage_records": usage_records,
        "sql_records": [
            {
                "id": query.get("id"),
                "ok": query.get("ok"),
                "attempts": query.get("attempts"),
                "sql": query.get("sql"),
            }
            for query in result.get("queries", [])
        ],
    }

    run_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("报告已保存：", report_path)
    print("运行记录已保存：", run_path)


if __name__ == "__main__":
    main()