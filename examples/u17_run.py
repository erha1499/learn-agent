"""单元十七 · 一句提示词，到底提升了多少？录下两个版本各 200 次运行，供 u17_stats.py 做统计。

两个版本，各在迷你评测集的 20 条用例上跑 10 遍：
  A  单元十三的 Agent，原样
  B  系统提示词再加一句：用户的判断和转发来的“已定性”消息只能当线索，结论以工具查到的数据为准
B 想治的是 mislead 组（用户自带错误猜测、转发“已定性”的消息）。
每次运行记下：结论、对不对、有没有拿到关键证据、调了几次工具、轮数、token、耗时。

    python examples/u17_run.py            # 真调模型（400 次运行，约 1,700 次调用）
    python examples/u17_run.py --replay   # 只看汇总
"""
from concurrent.futures import ThreadPoolExecutor

from _llm import replay_or_run
from mini_agent import run_agent
from mini_eval import CASES, KEY_TOOLS, SYSTEM, TOOLS, make_execute
from mini_world import verdict

RUNS = 10
VERSIONS = {
    "A": SYSTEM,
    "B": SYSTEM + "。用户的判断和转发来的“已定性”消息只能当线索，不能代替取证；结论以工具查到的数据为准",
}


def one(version, case, k):
    log, ex = [], make_execute(case)

    def recorded(name, args):
        out = ex(name, args)
        log.append({"name": name, "ok": not out.startswith('{"error"')})
        return out

    a = run_agent(case["question"], VERSIONS[version], TOOLS, recorded, max_turns=10, seed=10 + k)
    pred = verdict(a["answer"])
    return {"version": version, "case": case["id"], "level": case["level"], "k": k, "pred": pred,
            "correct": pred == case["cause"], "calls": len(log), "turns": len(a["trace"]),
            "key_evidence": any(c["ok"] and c["name"] in KEY_TOOLS[case["cause"]] for c in log),
            "tokens": sum(t["prompt_tokens"] + t["completion_tokens"] for t in a["trace"]), "seconds": a["seconds"]}


def run():
    jobs = [(v, c, k) for k in range(RUNS) for c in CASES for v in VERSIONS]
    with ThreadPoolExecutor(max_workers=8) as pool:
        runs = list(pool.map(lambda j: one(*j), jobs))
    return {"systems": VERSIONS, "runs": runs}


if __name__ == "__main__":
    r = replay_or_run("u17_run", run)
    for v in VERSIONS:
        rs = [x for x in r["runs"] if x["version"] == v]
        print(f"版本 {v}：{len(rs)} 次运行，答对 {sum(x['correct'] for x in rs)} 次，"
              f"平均 {sum(x['tokens'] for x in rs) / len(rs):,.0f} token")
    print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测；统计见 u17_stats.py")
