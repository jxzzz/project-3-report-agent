import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from graph import build_graph
from stream_events import (
    EVT_RUN_START,
    iter_stream_events,
    sse_format,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("report-agent")

app = FastAPI(title="多 Agent 数据分析报告服务", version="0.1.0")
report_graph = build_graph()

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


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


@app.post("/report/stream")
def stream_report(req: ReportRequest):
    if not req.auto_approve:
        raise HTTPException(
            status_code=422,
            detail="流式端点仅支持 auto_approve=true，请使用 POST /report",
        )

    request_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()

    logger.info(
        "report stream start request_id=%s question=%s",
        request_id,
        req.question,
    )

    def with_request_id(event: dict) -> dict:
        return {**event, "request_id": request_id}

    def sse_gen():
        yield sse_format(with_request_id({
            "type": EVT_RUN_START,
            "ts": time.time(),
            "data": {"question": req.question},
        }))

        # 注意：读模块级 report_graph，保持 monkeypatch 可替换
        for event, _state in iter_stream_events(
            report_graph,
            {
                "user_request": req.question,
                "auto_approve": True,
                "status": "start",
            },
            started,
        ):
            yield sse_format(with_request_id(event))

        logger.info(
            "report stream done request_id=%s elapsed_ms=%s",
            request_id,
            round((time.perf_counter() - started) * 1000, 1),
        )

    return StreamingResponse(
        sse_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )