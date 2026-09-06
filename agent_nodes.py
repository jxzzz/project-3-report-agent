from llm_client import chat_json
from state import ReportState
from utils.report_db import schema_text
from llm_client import chat, chat_json
import json
import re

DATA_VOCABULARY = """
orders.status 的实际取值只有：已支付、已发货、已签收。
refund_requests.status 的实际取值只有：pending、approved、rejected。
SQL 中禁止使用 valid、completed、cancelled、refunded 等 schema 中不存在的状态。
除非用户问题明确要求按状态分析，否则不要自行添加状态过滤条件。
"""

PLANNER_SYSTEM_PROMPT = """
你是销售报告规划 Agent。
你的任务：把用户问题拆成可执行的数据查询需求和报告章节。

规则：
1. 不查询数据库，不写任何具体数字。
2. 不生成最终结论，只做计划。
3. 必须严格输出 JSON，不要输出 Markdown。
4. 如果问题涉及的数据不在表结构内，输出 feasible=false。
5. data_requirements 每项只能描述“需要查什么”，不能包含 SQL 结果。
6. data_requirements 必须是能直接放进报告的数据指标，不要写成“查询全部明细”。
   应写“查询 2026 年 8 月订单总数和总销售额”，而不是“查询 2026 年 8 月所有订单”。

可用表：customers, products, orders, refund_requests。

输出格式：
{
  "feasible": true,
  "report_title": "报告标题",
  "summary": "报告摘要",
  "sections": [
    {"title": "章节标题", "focus": "这一章要回答什么问题"}
  ],
  "data_requirements": [
    {
      "id": "d1",
      "description": "需要查询的数据内容",
      "related_sections": ["对应章节标题"]
    }
  ]
}
"""


def planner_node(state: ReportState) -> dict:
    user_request = state["user_request"]

    user_content = f"""
数据库表结构：
{schema_text()}

数据取值约束：
{DATA_VOCABULARY}

用户问题：
{user_request}

请输出 JSON 规划。
"""

    parsed = chat_json(
        PLANNER_SYSTEM_PROMPT,
        user_content,
        temperature=0.2,
    )

    usage = parsed.pop("_usage", {})

    return {
        "plan": parsed,
        "usage": [{"node": "planner", **usage}],
        "status": "planned",
    }

from utils.report_db import execute_select

MAX_SQL_ATTEMPTS = 3

DATA_AGENT_SYSTEM_PROMPT = """
你是只读 SQL 查询 Agent。
根据 data_requirements 生成 SQL，并保证 SQL 能查出需求描述的数据。

规则：
1. 只能使用 SELECT。
2. 每条 data_requirement 必须生成一条 SQL。
3. SQL 不允许包含分号，不允许修改数据库。
4. 不要编造列名，以给出的表结构为准。
5. created_at 是文本日期，格式 YYYY-MM-DD HH:MM。
6. 过滤月份时使用 strftime('%Y-%m', created_at) = '2026-08'。
7. 如果查询涉及客户，必须 JOIN customers 并返回 c.name AS customer_name。
     最终结果应包含姓名，而不是只返回客户 ID。

输出 JSON，格式：
{
  "queries": [
    {
      "requirement_id": "d1",
      "sql": "SELECT ..."
    }
  ]
}
"""


def data_agent_node(state: ReportState) -> dict:
    plan = state["plan"]

    if not plan.get("feasible"):
        return {
            "status": "blocked",
            "final_report": f"无法生成报告：{plan.get('reason', '数据库中没有足够数据')}",
        }

    requirements = plan["data_requirements"]

    records = []
    for requirement in requirements:
        records.append({
            "id": requirement["id"],
            "description": requirement.get("description", ""),
            "related_sections": requirement.get("related_sections", []),
            "ok": False,
            "attempts": 0,
            "sql": None,
            "error": None,
            "attempt_log": [],
        })

    usage_records = []

    for attempt in range(1, MAX_SQL_ATTEMPTS + 1):
        failed = [record for record in records if not record["ok"]]

        if not failed:
            break

        failed_text = "\n".join(
            f"- id={record['id']} description={record['description']} "
            f"last_error={record['error'] or '尚未生成 SQL'}"
            for record in failed
        )

        user_content = f"""
数据库表结构：
{schema_text()}

数据取值约束：
{DATA_VOCABULARY}

需要生成 SQL 的需求：
{failed_text}

请输出 JSON。
"""

        parsed = chat_json(
            DATA_AGENT_SYSTEM_PROMPT,
            user_content,
            temperature=0.0,
        )

        usage_records.append({
            "node": "data_agent",
            "attempt": attempt,
            **parsed.pop("_usage", {}),
        })

        generated = {
            item["requirement_id"]: item["sql"]
            for item in parsed.get("queries", [])
        }

        for record in failed:
            sql = generated.get(record["id"])

            if not sql:
                error = "模型没有为这条需求生成 SQL"
                record["attempt_log"].append({
                    "attempt": attempt,
                    "sql": None,
                    "error": error,
                })
                record["attempts"] = attempt
                record["error"] = error
                continue

            result = execute_select(sql)

            if "error" in result:
                error = result["error"]
                record["attempt_log"].append({
                    "attempt": attempt,
                    "sql": sql,
                    "error": error,
                })
                record["attempts"] = attempt
                record["error"] = error
                continue

            record["attempts"] = attempt
            record["ok"] = True
            record["sql"] = sql
            record["result"] = result
            record["error"] = None
            record["attempt_log"].append({
                "attempt": attempt,
                "sql": sql,
                "error": None,
            })

    failed_again = [record for record in records if not record["ok"]]

    if failed_again:
        return {
            "queries": records,
            "usage": usage_records,
            "status": "data_error",
            "data_error": "部分数据查询在多次修正后仍然失败，请人工检查 SQL",
        }

    return {
        "queries": records,
        "usage": usage_records,
        "status": "data_ready",
    }

WRITER_SYSTEM_PROMPT = """
你是销售报告写作 Agent。
你将收到：用户问题、报告计划、查询结果。

规则：
1. 只能使用查询结果中的数字，禁止凭常识编造数据。
2. 每条关键业务结论后面必须引用来源，例如 [数据：d1]。
3. 如果一个指标需要由两个查询计算，例如退款率 = 退款数 / 订单数，
   必须同时引用两个来源，例如 [数据：d3 / 数据：d4]。
4. 不要输出“系统统计”“我的分析”这类无意义文字。
5. 如果数据不足，明确写“当前数据无法支撑该结论”。
6. 使用 Markdown 输出。
7. 禁止描述查询没有执行过的过滤语义。除非 SQL 中有对应的 WHERE 条件，
   不要写“排除退款”“取消状态”“有效订单”等词。
8. 附录表格的“来源”列必须写成 [数据：dX] 格式，不能只写裸的 dX。
9. 摘要中的每一条退款结论必须与它引用的查询在同一行或同一段落，
   且该引用确实来自包含退款字段的查询。
10. 写“最高、第二、第三、排名”时，必须先按数据值从大到小排序；
     数值不同就不能写成并列。
11. 章节只能来自 planner 的 sections，禁止新增 planner 没规划、查询结果也不支持的子章节。
12. 重写时只修改 Reviewer 指出的问题，不要为了“补内容”而新增没有数据支撑的章节或表格。

报告结构：
- 标题
- 摘要（3-5 条关键结论）
- 章节（按计划 sections 展开）
- 附录：数据引用说明
"""


def writer_node(state: ReportState) -> dict:
    plan = state["plan"]
    queries = state["queries"]
    user_request = state["user_request"]

    query_text = []
    for query in queries:
        if not query.get("ok"):
            query_text.append(
                f"[查询 {query['id']}] {query['description']}\n执行失败：{query.get('error')}"
            )
            continue

        query_text.append(
            f"[查询 {query['id']}] {query['description']}\n"
            f"SQL: {query['sql']}\n"
            f"结果: {query['result']}"
        )

    review_history = state.get("review_history", [])
    review_feedback = ""

    if review_history and review_history[-1].get("decision") == "fix":
        review_feedback = (
            "\n\n上一轮 Reviewer 未通过，请按以下意见重写：\n"
            + json.dumps(
                review_history[-1].get("issues", []),
                ensure_ascii=False,
                indent=2,
            )
        )

    user_content = f"""
用户问题：
{user_request}

报告计划：
{plan}

查询结果：
{chr(10).join(query_text)}

{review_feedback}

请输出完整 Markdown 报告。
"""

    result = chat(
        [
            {"role": "system", "content": WRITER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )

    usage = result["usage"]

    return {
        "draft": result["content"],
        "usage": [{"node": "writer", **usage}],
        "status": "drafted",
    }

# 
REFUND_KEYWORDS = ["退款率", "退款数", "退款", "refund"]
REFUND_COLUMNS = {"refund_count", "approved_refund_count", "refund_requests", "退款数"}


def _query_ids(text: str) -> set:
    ids = set()
    for chunk in re.findall(r"数据：([^\]\n]+)", text):
        for token in re.split(r"[/、,，\s]+", chunk):
            token = token.strip().split("：")[-1].strip()
            if token:
                ids.add(token)
    return ids


def _split_blocks(text: str) -> list:
    return re.split(r"\n(?=#{1,6}\s)", text)


def _hard_rule_check(draft: str, queries: list) -> list:
    issues = []
    query_by_id = {q["id"]: q for q in queries}

    refund_query_ids = {
        q["id"]
        for q in queries
        if any(
            "refund" in str(column).lower() or "退款" in str(column)
            for column in q.get("result", {}).get("columns", [])
        )
    }

    for block in _split_blocks(draft):
        lines = [
            line
            for line in block.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        body = "\n".join(lines)

        if not body.strip():
            continue

        cited_ids = _query_ids(block)

        for query_id in cited_ids:
            if query_id not in query_by_id:
                issues.append(f"引用不存在的查询：{query_id}")

        if any(keyword in block for keyword in REFUND_KEYWORDS):
            if not cited_ids.intersection(refund_query_ids):
                issues.append(
                    "含退款结论的段落未引用退款查询；"
                    f"可用退款查询：{refund_query_ids or '无'}；"
                    f"段落开头：{block.strip()[:60]!r}"
                )

    return issues


#  -
REVIEWER_SYSTEM_PROMPT = """
你是报告审查 Agent。
你收到：报告计划、Writer 草稿、全部查询记录（包含 SQL 和 rows）。

检查规则：
1. 草稿中每一个数字都必须能在查询结果中直接找到，或能由查询结果明确计算出来。
2. 草稿的引用必须正确：引用 d3，d3 里就必须真的有这个字段。
3. 如果查询只返回了少数商品，草稿不得把“没有记录”当成任意值或编造。
4. 如果草稿解释 SQL 语义，例如“排除退款状态”，必须和 SQL 一致。
5. 不要把无法验证的判断写成事实。
6. 如果草稿出现“最高、第二、第三、排名”，必须按查询数值从大到小重新核对；
     数值不同却写成并列或顺序错误，属于 issue。

输出 JSON：
{
  "decision": "pass 或 fix",
  "issues": [
    "问题1：...",
    "问题2：..."
  ],
  "summary": "一句话总结审查结论"
}
"""



def reviewer_node(state: ReportState) -> dict:
    plan = state["plan"]
    queries = state["queries"]
    draft = state["draft"]
    current_round = state.get("review_round", 0) + 1

    hard_issues = _hard_rule_check(draft, queries)

    if hard_issues:
        return {
            "review_round": current_round,
            "review_history": [
                {
                    "round": current_round,
                    "decision": "fix",
                    "issues": hard_issues,
                    "summary": "代码级硬校验未通过，不进入 LLM 审查",
                }
            ],
            "usage": [],
            "status": "needs_fix",
        }

    query_digest = json.dumps(
        [
            {
                "id": q["id"],
                "description": q["description"],
                "sql": q.get("sql"),
                "columns": q.get("result", {}).get("columns", []),
                "rows": q.get("result", {}).get("rows", []),
            }
            for q in queries
        ],
        ensure_ascii=False,
        indent=2,
    )

    user_content = f"""
报告计划：
{json.dumps(plan, ensure_ascii=False, indent=2)}

查询记录：
{query_digest}

Writer 草稿：
{draft}

请按规则审查，输出 JSON。
"""

    parsed = chat_json(
        REVIEWER_SYSTEM_PROMPT,
        user_content,
        temperature=0.0,
    )

    usage = parsed.pop("_usage", {})

    decision = parsed.get("decision", "fix")

    return {
        "review_round": current_round,
        "review_history": [
            {
                "round": current_round,
                "decision": decision,
                "issues": parsed.get("issues", []),
                "summary": parsed.get("summary", ""),
            }
        ],
        "usage": [
            {
                "node": "reviewer",
                "round": current_round,
                **usage,
            }
        ],
        "status": "reviewed" if decision == "pass" else "needs_fix",
    }

MAX_REVIEW_ROUNDS = 2


def blocked_node(state: ReportState) -> dict:
    plan = state.get("plan", {})

    if not plan.get("feasible"):
        return {
            "status": "blocked",
            "final_report": f"无法生成报告：{plan.get('reason', '数据库没有足够数据')}",
        }

    if state.get("status") == "data_error":
        return {
            "status": "blocked",
            "final_report": "部分数据查询在多次修正后仍然失败，报告已停止生成。",
        }

    history = state.get("review_history", [])

    if history and history[-1].get("decision") == "fix":
        issues = "\n".join(
            f"- {issue}" for issue in history[-1].get("issues", [])
        )
        return {
            "status": "blocked",
            "final_report": f"报告多次审查未通过，不输出最终报告：\n{issues}",
        }

    return {
        "status": "blocked",
        "final_report": "流程未能生成报告，需要人工介入。",
    }


def human_approval_node(state: ReportState) -> dict:
    if state.get("auto_approve"):
        return {
            "status": "approved",
            "final_report": state["draft"],
        }

    print("\n===== 等待人工确认 =====")
    print(state["draft"])
    answer = input("是否确认并输出这份报告？(y/n) ").strip().lower()

    if answer in {"y", "yes"}:
        return {
            "status": "approved",
            "final_report": state["draft"],
        }

    return {
        "status": "rejected",
        "final_report": "报告未获得人工确认，已取消。",
    }

