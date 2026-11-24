"""单元一 · 把这个零件放进一个 Agent：一次任务调几次模型、花多少 token、多少钱、多少秒？

用后面单元三会从零写出的最小 Agent（examples/mini_agent.py），让它排查 4 台出了问题的库，各跑 2 遍：
  干净：每个工具返回几行到几十行
  日志刷屏：错误日志一次返回全部，每台前面多 300 行无关告警（生产里很常见）
记下：调模型次数、单次调用最大输入、累计输入和输出、输入占比、命中缓存的 token、花费（按 2026-11 qwen-plus 公开价）、耗时。

    python examples/u01_agent_cost.py            # 真调模型（约 10 次，刷屏那组输入上万 token）
    python examples/u01_agent_cost.py --replay
"""
import copy

from _llm import replay_or_run
from mini_agent import run_agent
from mini_world import SCENARIOS, SYSTEM, TOOLS, execute

Q = "今天这 4 台库都有用户报问题：" + "、".join(s["instance"] for s in SCENARIOS.values()) + "。逐台查一下各自的根因。"
NOISY_TOOLS = copy.deepcopy(TOOLS)
NOISY_TOOLS[2]["function"]["description"] = "查询一个 MySQL 实例最近的错误日志（返回全部）"
NOISY_TOOLS[2]["function"]["parameters"]["properties"].pop("limit")
NOISE = [f"2026-11-24 09:{i // 60 % 60:02d}:{i % 60:02d} [Warning] Aborted connection {50000 + i} to db: 'app' user: 'app' "
         f"host: '10.9.{i % 5}.{i % 200}' (Got an error reading communication packets)" for i in range(300)]
PRICE_IN, PRICE_OUT = 0.8, 2.0          # 元/百万 token；隐式缓存命中按输入价的 20%


def noisy(name, args):
    if name == "query_error_log":
        out = execute(name, {**args, "limit": 10 ** 6})
        return out if out.startswith('{"error"') else "\n".join(NOISE + [out])
    return execute(name, args)


def one(world, seed):
    tools, ex = (TOOLS, execute) if world == "clean" else (NOISY_TOOLS, noisy)
    a = run_agent(Q, SYSTEM.replace("回答最后一行写：根因: <ID>", "最后每台一行，格式：实例名: 根因ID"), tools, ex, max_turns=15, seed=seed)
    t = a["trace"]
    inp, out, cached = (sum(x[k] for x in t) for k in ("prompt_tokens", "completion_tokens", "cached_tokens"))
    cost = ((inp - cached) * PRICE_IN + cached * PRICE_IN * 0.2 + out * PRICE_OUT) / 1e6
    return {"calls": len(t), "peak": max(x["prompt_tokens"] for x in t), "input": inp, "output": out, "cached": cached,
            "cost": round(cost, 5), "seconds": a["seconds"], "llm_seconds": round(sum(x["seconds"] for x in t), 1)}


def run():
    return {w: [one(w, s) for s in range(2)] for w in ("clean", "noisy")}


r = replay_or_run("u01_agent_cost", run)
for w, label in (("clean", "干净"), ("noisy", "日志刷屏")):
    for i, x in enumerate(r[w], 1):
        print(f"{label} 第 {i} 遍：调模型 {x['calls']} 次，单次最大输入 {x['peak']:,}，累计输入 {x['input']:,} / 输出 {x['output']:,}"
              f"（输入占 {x['input'] / (x['input'] + x['output']):.0%}），命中缓存 {x['cached']:,}，花费 ¥{x['cost']:.4f}，"
              f"耗时 {x['seconds']} 秒（其中等模型 {x['llm_seconds']} 秒）")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
