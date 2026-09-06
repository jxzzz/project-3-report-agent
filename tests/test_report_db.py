from utils.report_db import execute_select, schema_text


def test_schema_contains_core_tables():
    schema = schema_text()

    assert "CREATE TABLE orders" in schema
    assert "CREATE TABLE customers" in schema
    assert "CREATE TABLE refund_requests" in schema


def test_select_returns_rows():
    result = execute_select("SELECT COUNT(*) AS total FROM orders")

    assert "error" not in result
    assert result["row_count"] == 1
    assert result["rows"][0]["total"] > 0


def test_update_is_rejected():
    result = execute_select(
        "UPDATE orders SET status = '已支付' WHERE id = '1001'"
    )

    assert "error" in result


def test_multiple_statements_are_rejected():
    result = execute_select(
        "SELECT * FROM orders; DROP TABLE orders"
    )

    assert "error" in result


def test_bad_sql_returns_error():
    result = execute_select("SELECT * FROM table_not_exists")

    assert "error" in result