"""单元三 · 把工具调用放进一个循环：最小 Agent 跑 4 个故障场景，看每一轮发生了什么。

循环本身在 examples/mini_agent.py 的 run_agent（十几行）。每个场景跑一遍（seed=1），打印每一轮：
发了多少输入 token、模型要调哪些工具、为什么停。

    python examples/u03_agent_loop.py            # 真调模型（约 12 次）
    python examples/u03_agent_loop.py --replay
"""
from _llm import replay_or_run
from mini_agent import run_agent
from mini_world import SCENARIOS, SYSTEM, TOOLS, execute, verdict


def run():
    out = {}
    for sid, s in SCENARIOS.items():
        a = run_agent(s["question"], SYSTEM, TOOLS, execute, seed=1)
        out[sid] = {"question": s["question"], "gold": s["gold"], "pred": verdict(a["answer"]), "stop": a["stop"],
                    "seconds": a["seconds"], "trace": a["trace"], "answer": a["answer"]}
    return out


r = replay_or_run("u03_agent_loop", run)
meta = r.pop("_meta")
for sid, x in r.items():
    ok = "✓" if x["pred"] == x["gold"] else "✗"
    print(f"\n=== {sid} {x['question']}")
    for t in x["trace"]:
        calls = "，".join(f"{c['name']}({c['args'].get('instance', '')})" for c in t["calls"]) or "不调工具 → 结束"
        print(f"  第 {t['turn']} 轮  输入 {t['prompt_tokens']:>5}  输出 {t['completion_tokens']:>4}  {calls}")
    total_in = sum(t["prompt_tokens"] for t in x["trace"])
    print(f"  结论 {x['pred']} {ok}（标准答案 {x['gold']}）  {len(x['trace'])} 轮，累计输入 {total_in} token，{x['seconds']} 秒")
print(f"\n模型 {meta['model']}，{meta['date']} 实测")
