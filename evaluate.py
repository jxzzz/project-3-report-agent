import argparse
import datetime
import json
import time
from pathlib import Path

from cli import summarize_tokens
from graph import build_graph

PROJECT_ROOT = Path(__file__).resolve().parent
EVAL_FILE = PROJECT_ROOT / "tests" / "eval_questions.jsonl"
EVAL_OUTPUT_DIR = PROJECT_ROOT / "evaluations"


def check_case(item: dict, state: dict) -> tuple:
    report = state.get("final_report", "")
    status = state.get("status", "unknown")
    failures = []

    if item.get("should_refuse"):
        if status == "approved":
            failures.append("无答案问题不应输出正式报告")
    else:
        if status != "approved":
            failures.append(f"应生成报告，实际状态：{status}")

        for phrase in item.get("must_contain", []):
            if phrase not in report:
                failures.append(f"报告中缺少关键内容：{phrase}")

        for phrase in item.get("must_not_contain", []):
            if phrase in report:
                failures.append(f"报告中不应出现：{phrase}")

    return not failures, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 题")
    args = parser.parse_args()

    app = build_graph()
    lines = [
        json.loads(line)
        for line in EVAL_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    if args.limit:
        lines = lines[: args.limit]

    cases = []

    for item in lines:
        started = time.perf_counter()

        state = app.invoke({
            "user_request": item["question"],
            "auto_approve": True,
            "status": "start",
        })

        latency_ms = round((time.perf_counter() - started) * 1000, 1)

        usage = state.get("usage", [])
        token_summary = summarize_tokens(usage)

        passed, failures = check_case(item, state)

        cases.append({
            "question": item["question"],
            "passed": passed,
            "status": state.get("status"),
            "failures": failures,
            "latency_ms": latency_ms,
            "llm_calls": token_summary["llm_calls"],
            "total_tokens": token_summary["total_tokens"],
        })

        print(f"[{'PASS' if passed else 'FAIL'}] {item['question']}")
        for failure in failures:
            print("  -", failure)

    passed_count = sum(1 for case in cases if case["passed"])

    summary = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "total": len(cases),
        "passed": passed_count,
        "pass_rate": round(passed_count / len(cases) * 100, 1),
        "cases": cases,
    }

    EVAL_OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = EVAL_OUTPUT_DIR / f"eval_{timestamp}.json"
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n===== 汇总 =====")
    print("总题数：", summary["total"])
    print("通过：", summary["passed"])
    print("通过率：", summary["pass_rate"], "%")
    print("结果已保存：", output_path)


if __name__ == "__main__":
    main()