# 多 Agent 数据分析报告系统

基于 LangGraph + DeepSeek + SQLite 的多 Agent 工作流。
输入一个自然语言数据问题，系统自动完成：任务规划 -> SQL 查询 -> 报告写作 -> 事实审查 -> 人工确认，最终输出带数据引用的 Markdown 报告。

## 核心能力

- 4 个 Agent 角色：Planner、Data Agent、Writer、Reviewer
- LangGraph 条件路由与最多 2 轮审查重写
- SQLite 只读保护：`PRAGMA query_only`、禁止分号、禁止非 SELECT
- 报告硬校验：每个数据结论必须引用真实存在的查询
- 每次运行记录 token、耗时、SQL 尝试次数
- CLI 人工确认（y/n）与 HTTP API 两种入口
- 4 条评估集，支持真实模型效果评估

## 架构

```text
START -> planner -> data_agent -> writer -> reviewer -> human_gate -> END
                              |             |
                              |             +-- fix，未超过 2 轮 --> writer
                              +-- data_error --> blocked
```

State 在节点之间传递以下关键字段：

- `plan`：报告章节和数据需求
- `queries`：每条 SQL、结果、错误、尝试次数
- `draft`：Writer 草稿
- `review_history`：Reviewer 每轮结论
- `usage`：每次模型调用 token
- `final_report`：最终输出

## 目录结构

```text
project-3-report-agent/
  api.py                 # FastAPI HTTP 服务
  cli.py                 # 命令行入口
  evaluate.py            # 真实模型评估
  graph.py               # LangGraph 组装
  agent_nodes.py         # 四个 Agent 节点与路由
  state.py               # State 定义
  llm_client.py          # DeepSeek 调用、JSON 重试、token 统计
  support.db             # 生成的演示数据库，不入库
  utils/
    report_db.py         # 只读 SQLite 安全访问层
    create_report_db.py  # 演示数据生成脚本
  tests/
    eval_questions.jsonl # 评估题目
    test_api.py
    test_agent_rules.py
    test_report_db.py
  output/                # 生成的报告
  runs/                  # 每次运行指标
  evaluations/           # 评估结果
```

## 运行

```bash
cd ~/agent-lab/project-3-report-agent

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY

python3 utils/create_report_db.py
```

生成演示报告：

```bash
python3 cli.py \
  --question "分析 2026 年 8 月的销售情况：总销售额、订单量、消费 Top 3 客户、退款率最高的商品" \
  --approve
```

不传 `--approve` 时会在输出前要求人工确认。

启动 HTTP 服务：

```bash
python3 -m uvicorn api:app --host 127.0.0.1 --port 8010
```

请求示例：

```bash
curl -X POST http://127.0.0.1:8010/report \
  -H "Content-Type: application/json" \
  -d '{"question": "2026年8月总销售额是多少？", "auto_approve": true}'
```

## 测试与评估

离线测试，不调用真实模型：

```bash
python3 -m pytest tests -q
```

真实效果评估：

```bash
python3 evaluate.py
```

示例结果：

```text
总题数： 4
通过： 4
通过率： 100.0 %
```

## 防幻觉设计

错误数据不会直接变成最终报告，防线按顺序执行：

1. `report_db.py`：只读 SQLite，SQL Agent 无法写数据
2. `DATA_VOCABULARY`：告诉模型真实状态枚举，禁止编造 `valid/completed` 等字段
3. 数据层：SQL 失败自动带错误重试，最多 3 次
4. Writer 规则：每个结论必须引用 `[数据：dX]`
5. 代码级硬校验：未知引用、退款结论没有退款查询引用时直接拒绝
6. Reviewer：检查数字与 SQL 结果是否一致、排名是否乱写
7. Human Gate：最终报告输出前人工确认

典型失败场景：Writer 想新增“退款原因分析”章节，但查询中没有任何退款原因数据，硬校验发现该段落没有数据引用后拦截，最终不输出编造报告。

## 可观测结果

每次运行在 `runs/` 保存一个 JSON：

```json
{
  "question": "...",
  "status": "approved",
  "latency_ms": 9396.2,
  "llm_calls": 4,
  "total_tokens": 6789,
  "review_round": 1,
  "review_history": [],
  "sql_records": []
}
```

通过 `review_history` 可以复盘 Reviewer 要求重写的轮次；通过 `sql_records` 可以看到每条 SQL 成功或修正过程。
