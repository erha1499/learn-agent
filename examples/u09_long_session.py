"""单元九 · 长会话：上下文快满了，丢掉什么、留下什么？

一段排查对话：用户在前几轮陆续交代了 6 个关键事实（实例、开始时间、“主库不能重启”、已排除网络、刚做的扩容、结论同步到哪），
中间夹着 8 段很长的工具输出（日志、进程列表……）。最后用户说：“我要下班了，写一段交接给下一班。”
  预算：最后一轮的输入里，系统提示词、用户的话、工具输出各占多少 token（用 max_tokens=1 单独量每一部分）。
  四种上下文策略，各跑 3 遍（每次换 seed），检查交接里写对了几个事实（打印时按录下的原文重新判定，改了规则 --replay 即可）：
    A. 完整历史：什么都不删
    B. 截断：只留最近 6 条消息
    C. 朴素摘要：最近 6 条之前的部分，让模型“总结一下以上对话”，用摘要代替原文
    D. 结构化摘要：同样压缩，但指定要保留的字段（事实、约束、已排除、变更、待办），不保留原始日志

    python examples/u09_long_session.py            # 真调模型（约 25 次，A 组每次输入两万多 token）
    python examples/u09_long_session.py --replay
"""
import re

from _llm import chat, replay_or_run

SYSTEM = "你是数据库值班助手，和用户一起排查故障。回答简洁。"


def noise(kind, n):
    if kind == "error":
        return "\n".join(f"2026-11-24 14:{5 + i // 60:02d}:{i % 60:02d} [Warning] Aborted connection {80000 + i} to db: 'order' "
                         f"user: 'app' host: '10.3.{i % 9}.{i % 200}' (Got timeout reading communication packets)" for i in range(n))
    if kind == "processlist":
        return "\n".join(f"| {9000 + i} | app | 10.3.{i % 9}.{i % 200}:{40000 + i} | order | Query | {i % 7} | "
                         f"Sending data | SELECT * FROM orders WHERE user_id = {100000 + i} |" for i in range(n))
    if kind == "pods":
        return "\n".join(f"order-service-7d9f{i:04x}  1/1  Running  0  {i % 50 + 1}m  10.8.{i % 4}.{i}" for i in range(n))
    return "\n".join(f"{kind}_{i} = {i * 7 % 1000}" for i in range(n))


FACTS = {  # 名字: (检查用的正则, 说明)
    "实例": (r"order-mysql-01", "order-mysql-01"),
    "开始时间": (r"14[:：]05", "14:05"),
    "约束": (r"(严禁|禁止|不能|不要|不可|不得|勿|不)[^。\n]{0,6}重启|重启[^。\n]{0,6}(禁止|不允许)", "主库不能重启"),
    "已排除": (r"网络[^。\n]{0,12}(排除|正常)|(排除|正常)[^。\n]{0,12}网络", "已排除网络"),
    "变更": (r"扩容|40 ?个", "14:00 扩容到 40 个实例"),
    "同步": (r"db-oncall", "同步到 #db-oncall"),
}

HISTORY = [
    ("user", "order-mysql-01 从 14:05 开始下单报错，影响全部下单，帮忙看看"),
    ("assistant", "收到，先看监控。监控结果：\n" + "connections=1000 max_connections=1000 cpu=38% qps=5200\n" + noise("metric", 120)),
    ("user", "注意：这是主库，任何情况下都不能重启"),
    ("assistant", "明白，不会重启主库。错误日志（最近 400 行）：\n" + noise("error", 400)),
    ("user", "网络组刚确认链路正常，可以排除网络"),
    ("assistant", "好的，排除网络。当前会话列表：\n" + noise("processlist", 250)),
    ("user", "补充：14:00 应用刚扩容到 40 个实例"),
    ("assistant", "收到。应用 pod 列表：\n" + noise("pods", 300)),
    ("user", "结论出来后同步到 #db-oncall 群"),
    ("assistant", "好。实例配置：\n" + noise("variable", 400)),
    ("assistant", "连接来源统计：\n" + noise("processlist", 250)),
    ("assistant", "错误日志（续）：\n" + noise("error", 300)),
    ("assistant", "应用侧连接池配置：每个实例最大 30 个连接。\n" + noise("pool_setting", 200)),
]
FINAL = "我要下班了，写一段交接给下一班：实例、开始时间、约束、已排除的原因、相关变更、结论同步到哪，以及目前判断的根因。"
KEEP = 6


def msgs(pairs):
    return [{"role": r, "content": c} for r, c in pairs]


def summarize(pairs, structured, seed):
    text = "\n\n".join(f"[{r}] {c}" for r, c in pairs)
    ask = ("把下面这段值班对话压缩成一份状态摘要，供后续接着排查。必须逐项保留：用户给出的事实（实例、时间、影响）、"
           "约束和禁止事项、已排除的原因、相关变更、待办和要通知的人。原始日志不要保留，只保留从日志里得出的结论。"
           if structured else "总结一下以上对话。")
    r = chat([{"role": "user", "content": text + "\n\n" + ask}], seed=seed)
    return r["text"], r["usage"]["prompt_tokens"] + r["usage"]["completion_tokens"]


def final(context, seed):
    r = chat([{"role": "system", "content": SYSTEM}] + context + [{"role": "user", "content": FINAL}], seed=seed)
    return r["text"], r["usage"]["prompt_tokens"]


def recall(text):
    return {k: bool(re.search(p, text)) for k, (p, _) in FACTS.items()}


def budget():
    base = chat([{"role": "user", "content": ""}], max_tokens=1)["usage"]["prompt_tokens"]
    size = lambda s: chat([{"role": "user", "content": s}], max_tokens=1)["usage"]["prompt_tokens"] - base  # noqa: E731
    user = "\n".join(c for r, c in HISTORY if r == "user") + FINAL
    tool = "\n".join(c for r, c in HISTORY if r == "assistant")
    return {"system": size(SYSTEM), "user": size(user), "assistant_and_tools": size(tool)}


def run():
    out = {"budget": budget(), "A": [], "B": [], "C": [], "D": []}
    old, recent = HISTORY[:-KEEP], HISTORY[-KEEP:]
    for seed in range(3):
        t, n = final(msgs(HISTORY), seed)
        out["A"].append({"answer": t, "final_prompt": n, "extra": 0, "recall": recall(t)})
        t, n = final(msgs(recent), seed)
        out["B"].append({"answer": t, "final_prompt": n, "extra": 0, "recall": recall(t)})
        for key, structured in (("C", False), ("D", True)):
            summary, cost = summarize(old, structured, seed)
            ctx = [{"role": "user", "content": "（之前的对话已压缩成摘要）\n" + summary},
                   {"role": "assistant", "content": "好的，我按摘要继续。"}] + msgs(recent)
            t, n = final(ctx, seed)
            out[key].append({"answer": t, "final_prompt": n, "extra": cost, "summary": summary,
                             "summary_recall": recall(summary), "recall": recall(t)})
    return out


r = replay_or_run("u09_long_session", run)
b = r["budget"]
total = sum(b.values())
print(f"=== 最后一轮输入的构成（共约 {total:,} token）")
for k, label in (("system", "系统提示词"), ("user", "用户说的话（含最后的要求）"), ("assistant_and_tools", "助手回复和工具输出")):
    print(f"  {label:<16}{b[k]:>7,} token  {b[k] / total:.0%}")
print("\n=== 交接里写对的事实（共 6 个：" + "、".join(FACTS) + "）")
labels = {"A": "A. 完整历史", "B": "B. 只留最近 6 条", "C": "C. 朴素摘要", "D": "D. 结构化摘要"}
avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
for k in "ABCD":
    runs = r[k]
    got = [sum(recall(x["answer"]).values()) for x in runs]
    missing = sorted({f for x in runs for f, ok in recall(x["answer"]).items() if not ok})
    print(f"{labels[k]:<14}每遍写对 {got}，最后一次调用输入 {avg([x['final_prompt'] for x in runs]):,.0f} token，"
          f"压缩多花 {avg([x['extra'] for x in runs]):,.0f} token，漏掉过 {missing}")
    if k in "CD":
        print(f"    摘要本身保住的事实：{[sum(recall(x['summary']).values()) for x in runs]}，"
              f"摘要漏掉过 {sorted({f for x in runs for f, ok in recall(x['summary']).items() if not ok})}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
