import operator
from typing import Annotated, TypedDict


class ReportState(TypedDict, total=False):
    user_request: str
    status: str

    # Planner 输出的报告方案
    plan: dict

    # Data Agent 执行的每条 SQL 及结果
    queries: Annotated[list, operator.add]

    # Writer 的报告草稿
    draft: str

    # Reviewer 检查了几轮、给出了什么意见
    review_round: int
    review_history: Annotated[list, operator.add]

    # 最终报告
    final_report: str

    # 每次模型调用的 token 消耗
    usage: Annotated[list, operator.add]

    # 是否跳过终端人工确认
    auto_approve: bool