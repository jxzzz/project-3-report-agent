from agent_nodes import _hard_rule_check


def test_unknown_citation_is_rejected():
    draft = "退款率最高的是笔记本支架 [数据：d9]"

    queries = [
        {
            "id": "d3",
            "ok": True,
            "result": {"columns": ["product", "order_count"], "rows": []},
        }
    ]

    issues = _hard_rule_check(draft, queries)

    assert any("引用不存在" in issue for issue in issues)


def test_refund_claim_without_refund_query_is_rejected():
    draft = "退款率最高的是笔记本支架 [数据：d3]"

    queries = [
        {
            "id": "d3",
            "ok": True,
            "result": {"columns": ["product", "order_count"], "rows": []},
        }
    ]

    issues = _hard_rule_check(draft, queries)

    assert any("未引用退款查询" in issue for issue in issues)


def test_refund_claim_with_refund_query_passes():
    draft = "退款率最高的是笔记本支架 [数据：d3 / 数据：d4]"

    queries = [
        {
            "id": "d3",
            "ok": True,
            "result": {"columns": ["product", "order_count"], "rows": []},
        },
        {
            "id": "d4",
            "ok": True,
            "result": {"columns": ["product", "refund_count"], "rows": []},
        },
    ]

    issues = _hard_rule_check(draft, queries)

    assert issues == []