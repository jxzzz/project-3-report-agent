import logging
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from graph import build_graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("report-agent")

app = FastAPI(title="多 Agent 数据分析报告服务", version="0.1.0")
report_graph = build_graph()


class ReportRequest(BaseModel):
    question: str = Field(min_length=5, max_length=2000)
    auto_approve: bool = True


class ReportResponse(BaseModel):
    request_id: str
    status: str
    report: str
    latency_ms: float
    llm_calls: int
    total_tokens: int
    review_round: int | None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/report", response_model=ReportResponse)
def create_report(req: ReportRequest):
    request_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()

    logger.info(
        "report start request_id=%s question=%s",
        request_id,
        req.question,
    )

    try:
        state = report_graph.invoke({
            "user_request": req.question,
            "auto_approve": req.auto_approve,
            "status": "start",
        })
    except Exception as exc:
        logger.exception(
            "report failed request_id=%s error=%s",
            request_id,
            exc,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    usage = state.get("usage", [])
    total_tokens = sum(
        item.get("total_tokens", 0) for item in usage
    )

    logger.info(
        "report done request_id=%s status=%s latency_ms=%s tokens=%s",
        request_id,
        state.get("status"),
        latency_ms,
        total_tokens,
    )

    return ReportResponse(
        request_id=request_id,
        status=state.get("status", "unknown"),
        report=state.get("final_report", ""),
        latency_ms=latency_ms,
        llm_calls=len(usage),
        total_tokens=total_tokens,
        review_round=state.get("review_round"),
    )