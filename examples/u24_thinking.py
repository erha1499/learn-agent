"""单元二十四 · 推理模型：打开“思考”，Agent 会更准吗？代价是多少？

qwen-plus 可以用 enable_thinking 打开思考模式：回答之前先写一段推理（reasoning_content），这段推理也按输出 token 计费。
  A. 简单题：“9.11 和 9.9 哪个大？”开关思考各问 3 遍，看思考了多少 token、多花多少时间。
  B. 诊断题：数据都给全了，但要分清“症状”和“根因”。3 道题，开关思考各 5 遍（每次换 seed），比答对几次、思考 token、耗时。
     D1 连接数快满，但慢查询很多、单条扫描三千万行：连接是被慢 SQL 拖住的，根因是 SLOW_SQL
     D2 慢查询很多，但每条的 Lock_time 几乎等于 Query_time、只扫 1 行：时间花在等锁上，根因是 LOCK_WAIT
     D3 只有刷屏的 Aborted connection 告警，没有任何网络侧证据：数据不足，应答 UNKNOWN

    python examples/u24_thinking.py            # 真调模型（36 次，思考模式每次一两千 token）
    python examples/u24_thinking.py --replay
"""
from _llm import chat, replay_or_run
from mini_world import verdict

SYSTEM = ("你是数据库值班助手。根据给出的数据判断根因，只能从下面选一个：MAX_CONNECTIONS（连接数打满）、SLOW_SQL（慢 SQL）、"
          "LOCK_WAIT（锁等待）、DISK_FULL（磁盘写满）、NETWORK（网络问题）；数据不足以下结论时写 UNKNOWN。回答最后一行写：根因: <ID>")

CASES = {
    "D1": ("SLOW_SQL", "订单库 order-mysql-07 报错变多。\n监控：连接数 985/1000，CPU 91%，每分钟慢查询 170 条，每分钟行锁等待 2 次。\n"
                       "慢日志（节选）：# Query_time: 46.30 Lock_time: 0.01 Rows_examined: 31000000\n"
                       "SELECT * FROM orders WHERE DATE(created_at) = '2026-11-23';\n"
                       "错误日志：Too many connections（最近 10 分钟 126 次）"),
    "D2": ("LOCK_WAIT", "账户库 acct-mysql-02 扣款接口很慢。\n监控：连接数 430/1000，CPU 18%，每分钟慢查询 60 条，每分钟行锁等待 9 次。\n"
                        "慢日志（节选，60 条都类似）：# Query_time: 41.80 Lock_time: 41.70 Rows_examined: 1\n"
                        "UPDATE account SET balance = balance - 30 WHERE id = 10001;\n错误日志：无异常"),
    "D3": ("UNKNOWN", "用户说 crm-mysql-03 偶尔报错，说不清是什么错。\n监控：连接数 260/1000，CPU 15%，每分钟慢查询 1 条，每分钟行锁等待 0 次。\n"
                      "慢日志：无\n错误日志：Aborted connection ... (Got an error reading communication packets)（最近一小时 310 次，其他无）\n"
                      "网络监控：没有接入"),
}


def ask(content, thinking, seed=None):
    r = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}],
             enable_thinking=thinking, seed=seed)
    u = r["usage"]
    return {"answer": r["text"][-200:], "pred": verdict(r["text"]), "latency": r["latency"],
            "completion_tokens": u.get("completion_tokens", 0),
            "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)}


def run():
    simple = "9.11 和 9.9 哪个大？只回答数字"
    out = {"simple": {}, "diag": {}}
    for thinking in (False, True):
        key = "on" if thinking else "off"
        out["simple"][key] = []
        for _ in range(3):
            r = chat([{"role": "user", "content": simple}], enable_thinking=thinking)
            u = r["usage"]
            out["simple"][key].append({"answer": r["text"].strip(), "latency": r["latency"],
                                       "completion_tokens": u.get("completion_tokens", 0),
                                       "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)})
        out["diag"][key] = {cid: [ask(text, thinking, seed) for seed in range(5)] for cid, (_, text) in CASES.items()}
    return out


r = replay_or_run("u24_thinking", run)
avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
print("=== A. 简单题：9.11 和 9.9 哪个大？")
for key, label in (("off", "不思考"), ("on", "思考")):
    xs = r["simple"][key]
    print(f"{label}：回答 {[x['answer'] for x in xs]}，输出 {avg([x['completion_tokens'] for x in xs]):,.0f} token"
          f"（其中思考 {avg([x['reasoning_tokens'] for x in xs]):,.0f}），耗时 {avg([x['latency'] for x in xs]):.1f} 秒")
print("\n=== B. 诊断题（各 5 遍）")
for cid, (gold, _) in CASES.items():
    for key, label in (("off", "不思考"), ("on", "思考")):
        xs = r["diag"][key][cid]
        right = sum(x["pred"] == gold for x in xs)
        print(f"{cid}（{gold}）{label}：答对 {right}/5，给出 {[x['pred'] for x in xs]}，"
              f"输出 {avg([x['completion_tokens'] for x in xs]):,.0f} token（思考 {avg([x['reasoning_tokens'] for x in xs]):,.0f}），"
              f"耗时 {avg([x['latency'] for x in xs]):.1f} 秒")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
