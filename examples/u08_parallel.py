"""单元八 · 并行：4 台库各派一个子 Agent，挨个跑和同时跑，差多少？

编排是代码定的（单元三的“并行”Workflow）：程序把 4 台实例分给 4 个子 Agent（mini_agent.run_agent），
再把 4 个结论拼起来。只比两种跑法，各 3 遍：
  A. 顺序：一个跑完再跑下一个
  B. 并行：4 个同时跑（线程池）
比：墙钟时间、所有调用加起来的 token、答对几台。

    python examples/u08_parallel.py            # 真调模型（约 80 次）
    python examples/u08_parallel.py --replay
"""
import time
from concurrent.futures import ThreadPoolExecutor

from _llm import replay_or_run
from mini_agent import run_agent
from mini_world import SCENARIOS, SYSTEM, TOOLS, execute, verdict


def child(s, seed):
    t0 = time.time()
    a = run_agent(s["question"], SYSTEM, TOOLS, execute, seed=seed)
    return {"instance": s["instance"], "right": verdict(a["answer"]) == s["gold"], "seconds": round(time.time() - t0, 1),
            "tokens": sum(t["prompt_tokens"] + t["completion_tokens"] for t in a["trace"]), "calls": len(a["trace"])}


def fan_out(parallel, seed):
    t0 = time.time()
    scenarios = list(SCENARIOS.values())
    if parallel:
        with ThreadPoolExecutor(max_workers=len(scenarios)) as pool:
            results = list(pool.map(lambda s: child(s, seed), scenarios))
    else:
        results = [child(s, seed) for s in scenarios]
    return {"wall": round(time.time() - t0, 1), "children": results}


def run():
    return {"sequential": [fan_out(False, seed) for seed in range(3)],
            "parallel": [fan_out(True, seed) for seed in range(3)]}


r = replay_or_run("u08_parallel", run)
avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
for mode, label in (("sequential", "A. 顺序"), ("parallel", "B. 并行")):
    runs = r[mode]
    right = [sum(c["right"] for c in x["children"]) for x in runs]
    print(f"{label}：墙钟时间 {[x['wall'] for x in runs]} 秒（平均 {avg([x['wall'] for x in runs]):.1f}），"
          f"每遍 token {avg([sum(c['tokens'] for c in x['children']) for x in runs]):,.0f}，"
          f"调模型 {avg([sum(c['calls'] for c in x['children']) for x in runs]):.1f} 次，答对 {right}")
    slowest = [max(c["seconds"] for c in x["children"]) for x in runs]
    print(f"    每遍里最慢的那个子 Agent：{slowest} 秒")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
