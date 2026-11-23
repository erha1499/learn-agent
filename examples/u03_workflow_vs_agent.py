"""单元三 · 同样 4 个场景，固定流程（Workflow）和 Agent 各跑 5 遍，比准确率、调用次数、token、耗时。

  Workflow：代码写死"查指标 → 查慢日志 → 让模型下结论"，模型只调 1 次、不碰工具。
  Agent：  模型自己决定查什么、查几次（mini_agent.run_agent）。

    python examples/u03_workflow_vs_agent.py            # 真调模型（约 100 次）
    python examples/u03_workflow_vs_agent.py --replay
"""
import time

from _llm import chat, replay_or_run
from mini_agent import run_agent
from mini_world import SCENARIOS, SYSTEM, TOOLS, execute, verdict

SEEDS = range(5)


def workflow(s, seed):
    t0 = time.time()
    metrics = execute("get_metrics", {"instance": s["instance"]})          # 步骤是代码定的
    slow = execute("query_slow_log", {"instance": s["instance"]})
    prompt = f"{s['question']}\n\n监控指标：{metrics}\n\n慢查询日志：\n{slow}"
    r = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], seed=seed)
    return {"pred": verdict(r["text"]), "llm_calls": 1, "tool_calls": 2,
            "tokens": r["usage"]["prompt_tokens"] + r["usage"]["completion_tokens"], "seconds": round(time.time() - t0, 1)}


def agent(s, seed):
    a = run_agent(s["question"], SYSTEM, TOOLS, execute, seed=seed)
    return {"pred": verdict(a["answer"]), "llm_calls": len(a["trace"]),
            "tool_calls": sum(len(t["calls"]) for t in a["trace"]),
            "tokens": sum(t["prompt_tokens"] + t["completion_tokens"] for t in a["trace"]),
            "seconds": a["seconds"], "tools_used": sorted({c["name"] for t in a["trace"] for c in t["calls"]})}


def run():
    return {mode: {sid: [fn(s, seed) for seed in SEEDS] for sid, s in SCENARIOS.items()}
            for mode, fn in (("workflow", workflow), ("agent", agent))}


r = replay_or_run("u03_workflow_vs_agent", run)
meta = r.pop("_meta")
avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
print(f"{'':<10}{'场景':<6}{'答对':>6}{'调模型':>8}{'调工具':>8}{'token':>8}{'秒':>7}   答错时选了")
for mode in ("workflow", "agent"):
    for sid, runs in r[mode].items():
        gold = SCENARIOS[sid]["gold"]
        right = sum(x["pred"] == gold for x in runs)
        wrong = [x["pred"] for x in runs if x["pred"] != gold]
        print(f"{mode:<10}{sid:<6}{right:>4}/5{avg([x['llm_calls'] for x in runs]):>8.1f}{avg([x['tool_calls'] for x in runs]):>8.1f}"
              f"{avg([x['tokens'] for x in runs]):>8.0f}{avg([x['seconds'] for x in runs]):>7.1f}   {', '.join(map(str, wrong))}")
    allruns = [x for runs in r[mode].values() for x in runs]
    right = sum(x["pred"] == SCENARIOS[sid]["gold"] for sid, runs in r[mode].items() for x in runs)
    print(f"{mode:<10}{'合计':<6}{right:>3}/20{avg([x['llm_calls'] for x in allruns]):>8.1f}{avg([x['tool_calls'] for x in allruns]):>8.1f}"
          f"{avg([x['tokens'] for x in allruns]):>8.0f}{avg([x['seconds'] for x in allruns]):>7.1f}\n")
used = [x["tools_used"] for x in r["agent"]["S4"]]
print("Agent 在 S4 上用到的工具：", used)
print(f"\n模型 {meta['model']}，{meta['date']} 实测")
