"""单元十三 · 把迷你评测集（examples/mini_eval.py，20 条用例）用单元三的 Agent 原样跑 3 遍，录下每一次运行。

每次运行记下：结论、对不对、调了哪些工具（成功还是报错）、有没有拿到“关键证据”、轮数、token、耗时。
单元十三的分析脚本（u13_repeats.py、u13_single_run.py）都读这里录下的结果，不再调模型。

    python examples/u13_run.py            # 真调模型（60 次运行，约 250 次调用）
    python examples/u13_run.py --replay   # 只看汇总
"""
from _llm import replay_or_run
from mini_agent import run_agent
from mini_eval import CASES, KEY_TOOLS, SYSTEM, TOOLS, make_execute
from mini_world import verdict

RUNS = 3


def one(case, k):
    log = []
    ex = make_execute(case)

    def recorded(name, args):
        out = ex(name, args)
        log.append({"name": name, "ok": not out.startswith('{"error"')})
        return out

    a = run_agent(case["question"], SYSTEM, TOOLS, recorded, max_turns=10, seed=k)
    pred = verdict(a["answer"])
    return {"pred": pred, "correct": pred == case["cause"], "calls": log, "turns": len(a["trace"]),
            "key_evidence": any(c["ok"] and c["name"] in KEY_TOOLS[case["cause"]] for c in log),
            "tokens": sum(t["prompt_tokens"] + t["completion_tokens"] for t in a["trace"]), "seconds": a["seconds"],
            "answer": (a["answer"] or "")[-240:]}


def run():
    return {"cases": [{"id": c["id"], "cause": c["cause"], "level": c["level"], "question": c["question"],
                       "runs": [one(c, k) for k in range(RUNS)]} for c in CASES]}


r = replay_or_run("u13_run", run)
for k in range(RUNS):
    acc = sum(c["runs"][k]["correct"] for c in r["cases"]) / len(r["cases"])
    print(f"第 {k + 1} 遍：答对 {acc:.0%}")
print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
