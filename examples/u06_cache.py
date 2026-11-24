"""单元六 · 提示词缓存：前缀不变能省多少？每轮在开头插入“当前状态”会怎样？

模拟一个 Agent 跑 6 轮：系统提示词约三千 token（规则 + 5 份排查手册），每轮在末尾追加一段工具结果，再调一次模型。
三种写法，各跑 2 次（中间隔开，避免互相命中），记下每次调用的 cached_tokens：
  A. 前缀不变：当前状态放在最后一条消息里（隐式缓存，系统自动识别公共前缀）
  B. 每轮在系统提示词开头插入当前时间和系统状态（隐式缓存）——oncall-agent-mvp 改造后的写法
  C. 前缀不变 + 显式缓存：在系统提示词上标 cache_control
再按百炼的计费规则（2026-11 文档）算钱：隐式缓存命中按输入单价的 20%；显式缓存创建按 125%、命中按 10%。

    python examples/u06_cache.py            # 真调模型（36 次，每次只输出几个字）
    python examples/u06_cache.py --replay
"""
import os
import time
import uuid

from _llm import chat, replay_or_run

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mini_skills")
MANUALS = "\n\n".join(open(os.path.join(DIR, n, "SKILL.md"), encoding="utf-8").read() for n in sorted(os.listdir(DIR)))
BASE = ("你是数据库值班助手。先用工具查清楚，再下结论，不要猜。结论必须引用证据编号。\n\n排查手册：\n\n" + MANUALS) * 2
STEPS = ["[证据 E1] 监控：连接数 1000/1000，CPU 38%，每分钟慢查询 3 条",
         "[证据 E2] 慢日志：Query_time 1.21，Rows_examined 3200",
         "[证据 E3] 错误日志：Too many connections ×40",
         "[证据 E4] 变更记录：14:00 应用扩容到 40 个实例",
         "[证据 E5] 连接池配置：每个应用实例最大 30 个连接",
         "[证据 E6] 告警：14:01 连接数超过 95%"]
PRICE = 0.8  # qwen-plus 输入单价，元/百万 token（2026-11 公开价目，以控制台为准）


def conversation(mode, run_id):
    salt = f"（会话 {run_id}）"                     # 每次运行一个新前缀，不吃上一次运行留下的缓存
    records, history = [], []
    for turn, step in enumerate(STEPS, 1):
        history += [{"role": "assistant", "content": f"第 {turn} 步，继续查。"}, {"role": "user", "content": step}]
        state = f"当前时间 14:{10 + turn:02d}，已查 {turn} 项，剩余预算 {20 - turn} 次调用。"
        if mode == "B":
            system = {"role": "system", "content": state + "\n" + salt + BASE}
            tail = []
        else:
            system = {"role": "system", "content": salt + BASE}
            tail = [{"role": "user", "content": state + "下一步查什么？一句话。"}]
        if mode == "C":
            system = {"role": "system", "content": [{"type": "text", "text": system["content"], "cache_control": {"type": "ephemeral"}}]}
        first = [{"role": "user", "content": "order-mysql-01 下单接口大量报错，帮忙看看"}]
        msgs = [system] + first + history + (tail or [{"role": "user", "content": "下一步查什么？一句话。"}])
        u = chat(msgs, max_tokens=20)["usage"]
        d = u.get("prompt_tokens_details") or {}
        records.append({"prompt": u["prompt_tokens"], "cached": d.get("cached_tokens", 0) or 0,
                        "created": d.get("cache_creation_input_tokens", 0) or 0})
    return records


def cost(mode, recs):
    total = 0.0
    for x in recs:
        if mode == "C":
            total += (x["prompt"] - x["cached"] - x["created"]) * 1.0 + x["created"] * 1.25 + x["cached"] * 0.10
        else:
            total += (x["prompt"] - x["cached"]) * 1.0 + x["cached"] * 0.20
    return total * PRICE / 1e6


def run():
    out = {m: [] for m in "ABC"}
    for rep in range(2):
        for m in "ABC":
            out[m].append(conversation(m, uuid.uuid4().hex[:8]))
            time.sleep(1)
    return out


r = replay_or_run("u06_cache", run)
labels = {"A": "A. 前缀不变（隐式缓存）", "B": "B. 开头插入当前状态（隐式缓存）", "C": "C. 前缀不变 + 显式缓存"}
for m in "ABC":
    print(f"\n{labels[m]}")
    for i, recs in enumerate(r[m], 1):
        prompt = sum(x["prompt"] for x in recs)
        cached = sum(x["cached"] for x in recs)
        per = "  ".join(f"{x['cached']}/{x['prompt']}" for x in recs)
        nocache = prompt * PRICE / 1e6
        print(f"  第 {i} 次：每轮命中/输入 {per}")
        print(f"          命中率 {cached / prompt:.0%}，输入花费 ¥{cost(m, recs):.5f}（不缓存要 ¥{nocache:.5f}）")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
