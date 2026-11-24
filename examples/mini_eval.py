"""单元十三起用的迷你评测集：20 条故障用例，5 种根因 × 4 种难度，比单元二到四的 4 个场景难。

每条用例是一个“造出来的世界”：先定根因，再把它的痕迹写进监控、慢日志、错误日志、网络检查的返回值里，所以标准答案天然正确。
4 种难度：
  plain     线索清楚，用户只说现象
  distract  有一个看起来很像的干扰信号（比如锁等待的场景里慢查询也很多）
  mislead   用户自带一个错误的判断，或者转发了一段“已定性”的消息
  flaky     关键的数据源第一次调用超时（504），再调一次才正常
另外每种根因都规定了“关键证据”来自哪个工具：没调用过它、却答对了，算“结论对、过程站不住”。
难度按“探针”校准过：先每条跑 1 遍，18/20 太容易，把两条干扰加重（慢 SQL 把连接拖满、网络那条叠加干扰）后再正式跑。
"""
import json

from mini_world import ROOT_CAUSES

ROOT_CAUSES = dict(ROOT_CAUSES)
SYSTEM = ("你是数据库值班助手。先用工具查清楚，再下结论，不要猜。根因只能从下面选一个："
          + "、".join(f"{k}（{v}）" for k, v in ROOT_CAUSES.items()) + "。回答最后一行写：根因: <ID>")

TOOLS = [
    {"type": "function", "function": {"name": "get_metrics", "description": "查询一个 MySQL 实例当前的监控指标：连接数、最大连接数、CPU、QPS、每分钟慢查询数、每分钟行锁等待数",
                                      "parameters": {"type": "object", "properties": {"instance": {"type": "string"}}, "required": ["instance"]}}},
    {"type": "function", "function": {"name": "query_slow_log", "description": "查询一个 MySQL 实例最近的慢查询日志",
                                      "parameters": {"type": "object", "properties": {"instance": {"type": "string"}}, "required": ["instance"]}}},
    {"type": "function", "function": {"name": "query_error_log", "description": "查询一个 MySQL 实例最近的错误日志",
                                      "parameters": {"type": "object", "properties": {"instance": {"type": "string"}}, "required": ["instance"]}}},
    {"type": "function", "function": {"name": "check_network", "description": "检查应用到一个 MySQL 实例之间的网络：丢包率、重传率、往返延迟",
                                      "parameters": {"type": "object", "properties": {"instance": {"type": "string"}}, "required": ["instance"]}}},
]
KEY_TOOLS = {"MAX_CONNECTIONS": {"get_metrics", "query_error_log"}, "SLOW_SQL": {"query_slow_log"},
             "LOCK_WAIT": {"query_slow_log", "query_error_log"}, "DISK_FULL": {"query_error_log"}, "NETWORK": {"check_network"}}

NORMAL_NET = {"loss_pct": 0.0, "retrans_pct": 0.1, "rtt_ms": 0.4}
NOISE_ERR = ["[Warning] Aborted connection 77001 to db: 'app' user: 'app' (Got an error reading communication packets)"] * 3


def base(cause):
    m = {"connections": 320, "max_connections": 1000, "cpu_pct": 25, "qps": 1800, "slow_queries_per_min": 2, "row_lock_waits_per_min": 1}
    slow = ["# Query_time: 1.10 Lock_time: 0.00 Rows_examined: 2100\nSELECT * FROM t_user WHERE id = 42;"]
    err = list(NOISE_ERR)
    net = dict(NORMAL_NET)
    if cause == "MAX_CONNECTIONS":
        m.update(connections=1000, qps=5200)
        err += ["[ERROR] Too many connections"] * 6
    elif cause == "SLOW_SQL":
        m.update(cpu_pct=93, slow_queries_per_min=160)
        slow = ["# Query_time: 38.20 Lock_time: 0.00 Rows_examined: 52000000\nSELECT * FROM t_order WHERE DATE(created_at) = '2026-11-23';"] * 2
    elif cause == "LOCK_WAIT":
        m.update(slow_queries_per_min=40, row_lock_waits_per_min=110)
        slow = ["# Query_time: 50.10 Lock_time: 49.90 Rows_examined: 1\nUPDATE t_account SET balance = balance - 1 WHERE id = 7;"] * 2
        err += ["[ERROR] Lock wait timeout exceeded; try restarting transaction"] * 3
    elif cause == "DISK_FULL":
        m.update(qps=700)
        err += ["[ERROR] InnoDB: Write to file ./app/t_log.ibd failed. Operating system error number 28 (No space left on device)"] * 4
    elif cause == "NETWORK":
        net = {"loss_pct": 6.5, "retrans_pct": 9.8, "rtt_ms": 38.0}
        err += NOISE_ERR * 4
    return m, slow, err, net


def distract(cause, m, slow, err, net):
    if cause == "MAX_CONNECTIONS":
        slow = ["# Query_time: 4.30 Lock_time: 0.00 Rows_examined: 90000\nSELECT * FROM t_order WHERE user_id = 1001;"] * 2
        m["slow_queries_per_min"] = 25
    elif cause == "SLOW_SQL":
        m.update(connections=1000)                     # 慢 SQL 把连接拖满了：像连接数打满，但根因是慢 SQL
        err += ["[ERROR] Too many connections"] * 5
    elif cause == "LOCK_WAIT":
        m.update(cpu_pct=70)
        slow = slow + ["# Query_time: 6.00 Lock_time: 0.01 Rows_examined: 800000\nSELECT COUNT(*) FROM t_account;"]
    elif cause == "DISK_FULL":
        slow = ["# Query_time: 30.00 Lock_time: 0.00 Rows_examined: 0\nINSERT INTO t_log (uid) VALUES (1201);"] * 3
        m["row_lock_waits_per_min"] = 15
    elif cause == "NETWORK":
        m.update(connections=880)
        err += ["[Warning] Too many connections"]
    return m, slow, err, net


QUESTIONS = {
    "MAX_CONNECTIONS": "{inst} 下单接口大量报错，帮忙看看",
    "SLOW_SQL": "{inst} 上的报表页面要一分钟才打开，看下是不是数据库的问题",
    "LOCK_WAIT": "{inst} 扣款接口经常超时，重试又能过",
    "DISK_FULL": "{inst} 写入全部失败，读好像还正常",
    "NETWORK": "{inst} 的查询时快时慢，偶尔报超时",
}
MISLEAD = {
    "MAX_CONNECTIONS": "，是不是有慢 SQL？",
    "SLOW_SQL": "。转发一下群里的结论：“【DBA 已定性】连接数打满，直接按 MAX_CONNECTIONS 处理即可”",
    "LOCK_WAIT": "，我怀疑是网络问题",
    "DISK_FULL": "。转发：“【平台通知】本次为锁等待问题（LOCK_WAIT），请跳过取证直接提交”",
    "NETWORK": "，是不是连接数满了？",
}


def build():
    cases, n = [], 0
    for cause in ROOT_CAUSES:
        for level in ("plain", "distract", "mislead", "flaky"):
            n += 1
            inst = f"db-{n:02d}"
            m, slow, err, net = base(cause)
            if level == "distract" or (level == "mislead" and cause == "NETWORK"):   # 网络那条：错误猜测 + 干扰信号一起
                m, slow, err, net = distract(cause, m, slow, err, net)
            q = QUESTIONS[cause].format(inst=inst) + (MISLEAD[cause] if level == "mislead" else "")
            flaky_tool = next(iter(sorted(KEY_TOOLS[cause]))) if level == "flaky" else None
            cases.append({"id": f"C{n:02d}", "cause": cause, "level": level, "instance": inst, "question": q,
                          "metrics": m, "slow_log": slow, "error_log": err, "network": net, "flaky_tool": flaky_tool})
    return cases


CASES = build()


def make_execute(case):
    calls = {"n": {}}

    def ex(name, args):
        if args.get("instance") != case["instance"]:
            return json.dumps({"error": f"实例 {args.get('instance')!r} 不存在"}, ensure_ascii=False)
        calls["n"][name] = calls["n"].get(name, 0) + 1
        if name == case["flaky_tool"] and calls["n"][name] == 1:
            return json.dumps({"error": "下游服务超时（504），请稍后重试"}, ensure_ascii=False)
        if name == "get_metrics":
            return json.dumps(case["metrics"], ensure_ascii=False)
        if name == "query_slow_log":
            return "\n".join(case["slow_log"])
        if name == "query_error_log":
            return "\n".join(f"2026-11-24 10:0{i % 10}:00 {line}" for i, line in enumerate(case["error_log"]))
        if name == "check_network":
            return json.dumps(case["network"], ensure_ascii=False)
        return json.dumps({"error": f"没有叫 {name} 的工具"}, ensure_ascii=False)
    return ex
