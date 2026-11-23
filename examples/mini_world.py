"""单元二到四共用的迷你值班现场：4 台出了问题的 MySQL 实例，3 个查询工具。

和 oncall-agent-mvp 是同一类问题，但小得多：每个场景一句用户提问、一组监控指标、慢日志和错误日志、一个标准答案。
工具定义用 OpenAI 兼容接口的格式（JSON Schema），execute() 是"你的代码"：模型只负责说要调什么，真正去查的是这里。
"""
import json
import re

ROOT_CAUSES = {
    "MAX_CONNECTIONS": "连接数打满",
    "SLOW_SQL": "慢 SQL",
    "LOCK_WAIT": "锁等待",
    "DISK_FULL": "磁盘写满",
    "NETWORK": "网络问题",
}

SYSTEM = ("你是数据库值班助手。先用工具查清楚，再下结论，不要猜。根因只能从下面选一个："
          + "、".join(f"{k}（{v}）" for k, v in ROOT_CAUSES.items())
          + "。回答最后一行写：根因: <ID>")

SCENARIOS = {
    "S1": {
        "question": "order-mysql-01 下单接口从 14:00 开始大量报错，帮忙看看",
        "instance": "order-mysql-01", "gold": "MAX_CONNECTIONS",
        "metrics": {"connections": 1000, "max_connections": 1000, "cpu_pct": 38, "qps": 5200,
                    "slow_queries_per_min": 3, "row_lock_waits_per_min": 0},
        "slow_log": ["# Query_time: 1.21 Lock_time: 0.00 Rows_examined: 3200\nSELECT * FROM orders WHERE user_id = 88231;"],
        "error_log": ["2026-11-24 14:00:0%d [Warning] Too many connections" % (i % 10) for i in range(40)]
                     + ["2026-11-24 14:02:11 [Note] Aborted connection 88123 to db: 'order' (Got timeout reading communication packets)"],
    },
    "S2": {
        "question": "报表页面打开要一分钟，report-mysql-02 是不是有问题",
        "instance": "report-mysql-02", "gold": "SLOW_SQL",
        "metrics": {"connections": 180, "max_connections": 1000, "cpu_pct": 94, "qps": 310,
                    "slow_queries_per_min": 160, "row_lock_waits_per_min": 0},
        "slow_log": ["# Query_time: 38.20 Lock_time: 0.00 Rows_examined: 52000000\n"
                     "SELECT * FROM orders WHERE DATE(created_at) = '2026-11-23';"] * 3,
        "error_log": ["2026-11-24 09:00:00 [Note] Event Scheduler: Loaded 0 events"],
    },
    "S3": {
        "question": "支付回调一直超时，pay-mysql-03 帮忙查一下",
        "instance": "pay-mysql-03", "gold": "LOCK_WAIT",
        "metrics": {"connections": 450, "max_connections": 1000, "cpu_pct": 22, "qps": 1900,
                    "slow_queries_per_min": 35, "row_lock_waits_per_min": 120},
        "slow_log": ["# Query_time: 50.10 Lock_time: 49.90 Rows_examined: 1\n"
                     "UPDATE account SET balance = balance - 100 WHERE id = 7;"] * 3,
        "error_log": ["2026-11-24 10:1%d:00 [ERROR] Lock wait timeout exceeded; try restarting transaction" % i for i in range(5)],
    },
    "S4": {
        "question": "user-mysql-04 写入全部失败，读好像还正常",
        "instance": "user-mysql-04", "gold": "DISK_FULL",
        "metrics": {"connections": 300, "max_connections": 1000, "cpu_pct": 12, "qps": 800,
                    "slow_queries_per_min": 6, "row_lock_waits_per_min": 2},
        "slow_log": ["# Query_time: 30.00 Lock_time: 0.00 Rows_examined: 0\n"
                     "INSERT INTO user_login_log (user_id, ip) VALUES (1201, '10.2.3.4');"] * 2,
        "error_log": ["2026-11-24 11:2%d:00 [ERROR] InnoDB: Write to file ./user/user_login_log.ibd failed at offset 0. "
                      "Operating system error number 28 (No space left on device)" % i for i in range(5)],
    },
}

TOOLS = [
    {"type": "function", "function": {
        "name": "get_metrics",
        "description": "查询一个 MySQL 实例当前的监控指标：连接数、最大连接数、CPU、QPS、每分钟慢查询数、每分钟行锁等待数",
        "parameters": {"type": "object", "properties": {"instance": {"type": "string", "description": "实例名，例如 order-mysql-01"}},
                       "required": ["instance"]}}},
    {"type": "function", "function": {
        "name": "query_slow_log",
        "description": "查询一个 MySQL 实例最近的慢查询日志",
        "parameters": {"type": "object", "properties": {"instance": {"type": "string"},
                                                        "limit": {"type": "integer", "description": "最多返回几条，默认 5"}},
                       "required": ["instance"]}}},
    {"type": "function", "function": {
        "name": "query_error_log",
        "description": "查询一个 MySQL 实例最近的错误日志",
        "parameters": {"type": "object", "properties": {"instance": {"type": "string"},
                                                        "limit": {"type": "integer", "description": "最多返回几行，默认 20"}},
                       "required": ["instance"]}}},
]

# 单元四的“日志刷屏”场景：错误日志 400 行，390 行是无关的断连告警，只有 10 行是真正的线索。不放进 SCENARIOS，单元三的实验不受影响。
FLOOD = {
    "question": "inventory-mysql-05 错误日志一直在刷屏，扣库存时不时失败，帮忙看下",
    "instance": "inventory-mysql-05", "gold": "LOCK_WAIT",
    "metrics": {"connections": 520, "max_connections": 1000, "cpu_pct": 31, "qps": 2400,
                "slow_queries_per_min": 14, "row_lock_waits_per_min": 95},
    "slow_log": ["# Query_time: 3.10 Lock_time: 0.02 Rows_examined: 880000\n"
                 "SELECT sku_id, SUM(stock) FROM inventory GROUP BY sku_id;"],
    "error_log": [("2026-11-24 15:%02d:%02d [ERROR] Lock wait timeout exceeded; try restarting transaction" % (i // 60 % 60, i % 60))
                  if i % 40 == 17 else
                  ("2026-11-24 15:%02d:%02d [Warning] Aborted connection %d to db: 'inventory' user: 'app' host: '10.8.%d.%d' "
                   "(Got an error reading communication packets)" % (i // 60 % 60, i % 60, 70000 + i, i % 7, i % 250))
                  for i in range(400)],
}

BY_INSTANCE = {s["instance"]: s for s in list(SCENARIOS.values()) + [FLOOD]}


def execute(name, args):
    """执行一次工具调用，返回给模型看的字符串。这就是"你的代码"：模型从来不碰数据，只看到这里返回的文字。"""
    s = BY_INSTANCE.get(args.get("instance", ""))
    if s is None:
        return json.dumps({"error": f"实例 {args.get('instance')!r} 不存在"}, ensure_ascii=False)
    if name == "get_metrics":
        return json.dumps(s["metrics"], ensure_ascii=False)
    if name == "query_slow_log":
        return "\n".join(s["slow_log"][: int(args.get("limit") or 5)]) or "(无慢查询)"
    if name == "query_error_log":
        return "\n".join(s["error_log"][-int(args.get("limit") or 20):]) or "(无错误日志)"
    return json.dumps({"error": f"没有叫 {name} 的工具"}, ensure_ascii=False)


def verdict(text):
    """从回答里取出最后一个"根因: XXX"，取不到返回 None。"""
    found = re.findall(r"根因\s*[:：]\s*\**\s*([A-Z_]+)", text or "")
    return found[-1] if found else None
