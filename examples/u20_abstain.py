"""单元二十 · 答错和不答，哪个更贵？立项时要先写下来，因为它决定了该做哪个版本。

两个版本：
  A  单元十三的 Agent，原样：总要给出一个根因
  U  再加一句：关键数据查不到、或者证据不足以确定根因时，不要猜，最后一行写“根因: UNKNOWN”，并说明缺哪些数据
两种情况：
  正常      和评测集一样
  错误日志宕机  query_error_log 每次都返回 504。磁盘写满的唯一硬证据在错误日志里，这时它其实查不出来
每个组合在 20 条用例上各跑 5 遍，共 400 次运行。
另外在录下的运行上加一道程序的“门”（不重跑）：结论对应的关键数据源一次都没成功返回过，就把结论改成 UNKNOWN、转人工
（单元十九的“结论缺关键证据”，当成单元四的提交门来用）。

    python examples/u20_abstain.py            # 真调模型（400 次 Agent 运行）
    python examples/u20_abstain.py --replay
"""
import json
import statistics as st
from concurrent.futures import ThreadPoolExecutor

from _llm import replay_or_run
from mini_agent import run_agent
from mini_eval import CASES, KEY_TOOLS, SYSTEM, TOOLS, make_execute
from mini_world import verdict

RUNS = 5
ABSTAIN = "。如果关键的数据源查不到（超时、报错，重试后仍然失败），或者现有数据不足以确定根因，不要猜：最后一行写“根因: UNKNOWN”，并说明还缺哪些数据"
VERSIONS = {"A": SYSTEM, "U": SYSTEM + ABSTAIN}
DOWN = json.dumps({"error": "下游服务超时（504），请稍后重试"}, ensure_ascii=False)


def one(version, cond, case, seed):
    base, log = make_execute(case), []

    def ex(name, args):
        out = DOWN if cond == "outage" and name == "query_error_log" else base(name, args)
        log.append({"name": name, "ok": not out.startswith('{"error"')})
        return out

    a = run_agent(case["question"], VERSIONS[version], TOOLS, ex, max_turns=10, seed=seed)
    return {"version": version, "cond": cond, "case": case["id"], "cause": case["cause"], "k": seed,
            "pred": verdict(a["answer"]), "calls": log, "answer": (a["answer"] or "")[-300:],
            "tokens": sum(t["prompt_tokens"] + t["completion_tokens"] for t in a["trace"])}


def run():
    jobs = [(v, cond, c, k) for v in VERSIONS for cond in ("normal", "outage") for c in CASES for k in range(RUNS)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        return {"systems": VERSIONS, "runs": list(pool.map(lambda j: one(*j), jobs))}


def gated(x):
    """门：结论对应的关键数据源一次都没成功返回过，就改成 UNKNOWN。"""
    ok = {c["name"] for c in x["calls"] if c["ok"]}
    if x["pred"] in (None, "UNKNOWN") or not (KEY_TOOLS.get(x["pred"], set()) & ok):
        return "UNKNOWN"
    return x["pred"]


def outcome(x, gate=False):
    p = gated(x) if gate else x["pred"]
    if p in (None, "UNKNOWN"):
        return "unknown"
    return "right" if p == x["cause"] else "wrong"


if __name__ == "__main__":
    r = replay_or_run("u20_abstain", run)
    R = r["runs"]
    names = {"normal": "正常", "outage": "错误日志宕机"}
    print("=== 每 100 次里：答对 / 答错 / 说不知道（转人工）")
    table, labels = {}, ("A", "U", "A+门", "U+门")
    for cond in names:
        for lab in labels:
            v, gate = lab[0], lab.endswith("门")
            xs = [x for x in R if x["version"] == v and x["cond"] == cond]
            o = [outcome(x, gate) for x in xs]
            right, wrong, unk = (o.count(k) / len(o) for k in ("right", "wrong", "unknown"))
            table[(cond, lab)] = (right, wrong, unk)
            print(f"  {names[cond]:<8} {lab:<4}  答对 {right:.0%}  答错 {wrong:.0%}  不知道 {unk:.0%}  "
                  f"答了的里面答对 {right / (right + wrong):.0%}")
    for cond in names:
        for key, name in (("right", "答对"), ("wrong", "答错")):
            d = []
            for c in CASES:
                a = [outcome(x) == key for x in R if x["version"] == "A" and x["cond"] == cond and x["case"] == c["id"]]
                u = [outcome(x) == key for x in R if x["version"] == "U" and x["cond"] == cond and x["case"] == c["id"]]
                d.append(st.mean(u) - st.mean(a))
            print(f"  {names[cond]}：U 减 A 的{name}率，按用例配对 {st.mean(d) * 100:+.1f} ± {1.96 * st.stdev(d) / len(d) ** .5 * 100:.1f} 个点")
    print("\n=== 按根因看（错误日志宕机时）：答对 / 答错 / 不知道")
    for cause in sorted({c["cause"] for c in CASES}):
        cells = []
        for v in VERSIONS:
            o = [outcome(x) for x in R if x["version"] == v and x["cond"] == "outage" and x["cause"] == cause]
            cells.append(f"{v} {o.count('right')}/{o.count('wrong')}/{o.count('unknown')}")
        print(f"  {cause:<16} " + "   ".join(cells))
    print("\n=== 宕机时磁盘写满那几条，各版本答成了什么")
    for v in VERSIONS:
        preds = [x["pred"] for x in R if x["version"] == v and x["cond"] == "outage" and x["cause"] == "DISK_FULL"]
        print(f"  {v}：" + "，".join(f"{p}×{preds.count(p)}" for p in sorted(set(preds), key=lambda p: -preds.count(p))))
    print("\n=== 正常情况下 U 说不知道的，都是哪些用例")
    print("  ", {c["id"]: sum(outcome(x) == "unknown" for x in R if x["version"] == "U" and x["cond"] == "normal" and x["case"] == c["id"])
                 for c in CASES if any(outcome(x) == "unknown" for x in R if x["version"] == "U" and x["cond"] == "normal" and x["case"] == c["id"])})
    print("\n=== 每个会话的平均代价：答对记 0，转人工记 1，答错记 r（答错比转人工贵几倍）")
    for r_ in (1, 3, 10):
        for cond in names:
            cost = {lab: table[(cond, lab)][1] * r_ + table[(cond, lab)][2] for lab in labels}
            best = min(cost, key=cost.get)
            print(f"  r = {r_:>2}  {names[cond]:<8}  " + "  ".join(f"{lab} {c:.2f}" for lab, c in cost.items()) + f"  → {best} 最划算")
    print(f"\n每次运行平均 token：" + "  ".join(f"{v}/{names[c]} {st.mean(x['tokens'] for x in R if x['version'] == v and x['cond'] == c):,.0f}"
                                      for v in VERSIONS for c in names))
    print(f"模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
