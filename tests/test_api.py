from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


class FakeGraph:
    def invoke(self, state: dict) -> dict:
        return {
            "status": "approved",
            "final_report": "# 测试报告\n\n内容正确 [数据：d1]",
            "usage": [
                {"total_tokens": 100, "prompt_tokens": 80, "completion_tokens": 20}
            ],
            "review_round": 1,
            "queries": [],
            "review_history": [],
        }


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_serves_console_page():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "事件流" in response.text
    assert "/report/stream" in response.text


def test_question_is_required():
    response = client.post("/report", json={})

    assert response.status_code == 422


def test_report_returns_approved(monkeypatch):
    monkeypatch.setattr("api.report_graph", FakeGraph())

    response = client.post(
        "/report",
        json={
            "question": "测试问题：2026年8月销售额是多少",
            "auto_approve": True,
        },
    )

    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "approved"
    assert data["report"].startswith("# 测试报告")
    assert data["total_tokens"] == 100
    assert data["review_round"] == 1
    assert data["request_id"]