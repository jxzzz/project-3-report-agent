import random
import sqlite3
import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "support.db"

customers = [
    ("C001", "张三", "普通客户"),
    ("C002", "李四", "会员"),
    ("C003", "王五", "普通客户"),
    ("C004", "赵六", "VIP"),
    ("C005", "钱七", "会员"),
    ("C006", "孙八", "普通客户"),
]

products = [
    ("P001", "无线鼠标", 79),
    ("P002", "机械键盘", 299),
    ("P003", "显示器", 1299),
    ("P004", "USB-C 数据线", 39),
    ("P005", "笔记本支架", 129),
    ("P006", "降噪耳机", 899),
    ("P007", "便携充电宝", 149),
    ("P008", "高清摄像头", 399),
    ("P009", "桌面音箱", 459),
    ("P010", "电脑背包", 219),
]


def create_db() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    conn.executescript(
        """
        CREATE TABLE customers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            level TEXT NOT NULL
        );

        CREATE TABLE products (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL NOT NULL
        );

        CREATE TABLE orders (
            id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL REFERENCES customers(id),
            product TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE refund_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL REFERENCES orders(id),
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        );
        """
    )

    random.seed(7)

    orders = []
    for i in range(1, 241):
        customer_id, _, _ = random.choice(customers)
        _, product_name, price = random.choice(products)

        month = random.randint(6, 8)
        day = random.randint(1, 28)
        created_date = datetime.date(2026, month, day)

        status = random.choices(
            ["已支付", "已发货", "已签收"],
            weights=[3, 3, 4],
        )[0]

        orders.append((
            str(1000 + i),
            customer_id,
            product_name,
            price,
            status,
            f"{created_date.isoformat()} 10:00",
        ))

    signed_orders = [
        order for order in orders if order[4] == "已签收"
    ]

    refunds = []
    for order in random.sample(signed_orders, 18):
        reason = random.choice([
            "商品收到时有划痕",
            "线材接触不良",
            "商品与描述不符",
            "尺寸不合适",
            "质量问题",
        ])
        status = random.choices(
            ["pending", "approved", "rejected"],
            weights=[6, 3, 1],
        )[0]
        refunds.append((
            order[0],
            reason,
            status,
            order[5][:10],
        ))

    conn.executemany(
        "INSERT INTO customers (id, name, level) VALUES (?, ?, ?)",
        customers,
    )
    conn.executemany(
        "INSERT INTO products (id, name, price) VALUES (?, ?, ?)",
        products,
    )
    conn.executemany(
        """
        INSERT INTO orders (id, customer_id, product, amount, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        orders,
    )
    conn.executemany(
        """
        INSERT INTO refund_requests (order_id, reason, status, created_at)
        VALUES (?, ?, ?, ?)
        """,
        refunds,
    )

    conn.commit()
    conn.close()

    print("数据库创建完成")
    print("客户数：", len(customers))
    print("商品数：", len(products))
    print("订单数：", len(orders))
    print("退款申请数：", len(refunds))


if __name__ == "__main__":
    create_db()