"""单元二十 · 立项时先量最简单的方案：规则、一次调用、Agent，在同一套评测集上各能做到多少？

三种方案：
  规则      不调模型。程序把四个数据源都查一遍（超时就重试一次），按固定阈值判根因。
  一次调用  程序把四个数据源都查一遍（超时重试一次），把用户的问题和全部结果一次交给模型下结论。
  Agent    单元十三的 Agent。
两套题：
  原题      迷你评测集的 20 条用例。规则是作者写的，作者知道这套用例是怎么造的，所以规则在这里的成绩是乐观的上限；
            Agent 直接用单元十七录下的 200 次运行（每条 10 遍），一次调用每条跑 5 遍。
  换说法    规则写定以后，再造 10 条：根因不变，证据换成规则没预料到的写法和数值（比如“Disk full; waiting for someone
            to free some space”而不是 errno 28、重传率很高但丢包率不高、扫了 5200 万行但只跑了 9.8 秒的查询）。
            它们是冲着规则的盲区造的，对规则不公平，正好说明规则怕什么。一次调用和 Agent 每条各跑 5 遍。

    python examples/u20_baselines.py            # 真调模型（150 次一次调用 + 50 次 Agent 运行）
    python examples/u20_baselines.py --replay
"""
import json
import os
import re
import statistics as st
from concurrent.futures import ThreadPoolExecutor

import copy

from _llm import chat, replay_or_run
from mini_agent import run_agent
from mini_eval import CASES, SYSTEM, TOOLS, make_execute
from mini_world import verdict

SOURCES = ("get_metrics", "query_slow_log", "query_error_log", "check_network")
RUNS = 5


def fetch_all(case):
    """程序按固定顺序把四个数据源都查一遍；返回 504 就再查一次。"""
    ex, out = make_execute(case), {}
    for name in SOURCES:
        r = ex(name, {"instance": case["instance"]})
        if r.startswith('{"error"'):
            r = ex(name, {"instance": case["instance"]})
        out[name] = r
    return out


def rules(data):
    """按 DBA 的常识写的固定规则：先看能直接定案的硬证据，再看指标。"""
    err, slow = data["query_error_log"], data["query_slow_log"]
    try:
        m, net = json.loads(data["get_metrics"]), json.loads(data["check_network"])
    except json.JSONDecodeError:
        return "UNKNOWN"
    if "error" in m or "error" in net:
        return "UNKNOWN"
    times = [float(x) for x in re.findall(r"Query_time: ([\d.]+)", slow)]
    locks = [float(x) for x in re.findall(r"Lock_time: ([\d.]+)", slow)]
    if net.get("loss_pct", 0) >= 1 or net.get("rtt_ms", 0) >= 10:
        return "NETWORK"
    if "No space left" in err or "error number 28" in err:
        return "DISK_FULL"
    if "Lock wait timeout" in err or m["row_lock_waits_per_min"] >= 50 or any(l >= 10 for l in locks):
        return "LOCK_WAIT"
    if m["slow_queries_per_min"] >= 50 or any(t >= 10 for t in times):     # 慢 SQL 会把连接拖满，所以先于连接数判断
        return "SLOW_SQL"
    if m["connections"] >= 0.95 * m["max_connections"]:
        return "MAX_CONNECTIONS"
    return "UNKNOWN"


def one_call(case, data, seed):
    body = "\n\n".join(f"【{k}】\n{v}" for k, v in data.items())
    r = chat([{"role": "system", "content": SYSTEM},
              {"role": "user", "content": f"{case['question']}\n\n下面是已经查到的数据：\n\n{body}"}], seed=seed)
    return {"pred": verdict(r["text"]), "tokens": r["usage"].get("prompt_tokens", 0) + r["usage"].get("completion_tokens", 0),
            "seconds": r["latency"]}


def reword(c, n):
    """根因不变，证据换一种规则没预料到的写法。"""
    v = copy.deepcopy(c)
    v.update(id=f"V{n:02d}", level="reworded", instance=f"db-{40 + n}", flaky_tool=None)
    v["question"] = c["question"].replace(c["instance"], v["instance"])
    cause = c["cause"]
    if cause == "MAX_CONNECTIONS":       # 监控是某一刻的快照，刚好回落到 93%；错误日志一直在报连接满
        v["metrics"]["connections"] = 930
        v["error_log"] = [x.replace("[ERROR] Too many connections", "[ERROR] [MY-010273] Connection refused: max_connections (1000) reached for user 'app'")
                          for x in v["error_log"]]
    elif cause == "SLOW_SQL":            # 刚好压在规则的阈值下面
        v["metrics"]["slow_queries_per_min"] = 45
        v["slow_log"] = [x.replace("Query_time: 38.20", "Query_time: 9.80") for x in v["slow_log"]]
    elif cause == "LOCK_WAIT":           # 报错换了措辞，锁等待次数和加锁时间都不高，但查询都在等锁
        v["metrics"]["row_lock_waits_per_min"] = 35
        v["slow_log"] = [x.replace("Lock_time: 49.90", "Lock_time: 8.00") for x in v["slow_log"]]
        v["error_log"] = [x.replace("[ERROR] Lock wait timeout exceeded; try restarting transaction",
                                    "[ERROR] InnoDB: Transaction 4218 rolled back after waiting 50 s for a row lock held by transaction 4190")
                          for x in v["error_log"]]
    elif cause == "DISK_FULL":           # MySQL 自己的另一种写法，没有 errno 28
        v["error_log"] = [re.sub(r"\[ERROR\] InnoDB: Write to file .*", "[ERROR] mysqld: Disk full (./app/t_log.ibd); waiting for someone to free some space...", x)
                          for x in v["error_log"]]
    elif cause == "NETWORK":             # 丢包不高、延迟不高，但重传率很高
        v["network"] = {"loss_pct": 0.6, "retrans_pct": 14.0, "rtt_ms": 7.5}
    return v


VARIANTS = [reword(c, i + 1) for i, c in enumerate(c for c in CASES if c["level"] in ("plain", "distract"))]


def agent_once(case, seed):
    log = []
    ex = make_execute(case)

    def recorded(name, args):
        out = ex(name, args)
        log.append(name)
        return out

    a = run_agent(case["question"], SYSTEM, TOOLS, recorded, max_turns=10, seed=seed)
    return {"pred": verdict(a["answer"]), "calls": len(log), "seconds": a["seconds"],
            "tokens": sum(t["prompt_tokens"] + t["completion_tokens"] for t in a["trace"])}


def run():
    allc = CASES + VARIANTS
    data = {c["id"]: fetch_all(c) for c in allc}
    jobs = [(c, k) for c in allc for k in range(RUNS)]
    ajobs = [(c, k) for c in VARIANTS for k in range(RUNS)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        outs = list(pool.map(lambda j: one_call(j[0], data[j[0]["id"]], j[1]), jobs))
        aouts = list(pool.map(lambda j: agent_once(*j), ajobs))
    return {"one_call": [{"case": c["id"], "k": k, **o} for (c, k), o in zip(jobs, outs)],
            "agent_variants": [{"case": c["id"], "k": k, **o} for (c, k), o in zip(ajobs, aouts)]}


if __name__ == "__main__":
    r = replay_or_run("u20_baselines", run)
    agent = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "u17_run.json"),
                           encoding="utf-8"))["runs"]
    agent = [x for x in agent if x["version"] == "A"]
    allc = CASES + VARIANTS
    cause = {c["id"]: c["cause"] for c in allc}
    level = {c["id"]: c["level"] for c in allc}
    rule_pred = {c["id"]: rules(fetch_all(c)) for c in allc}
    oc, av = r["one_call"], r["agent_variants"]
    rows = {
        "规则": {c: [rule_pred[c] == cause[c]] for c in cause},
        "一次调用": {c: [x["pred"] == cause[c] for x in oc if x["case"] == c] for c in cause},
        "Agent": {**{c: [x["correct"] for x in agent if x["case"] == c] for c in cause if c.startswith("C")},
                  **{c: [x["pred"] == cause[c] for x in av if x["case"] == c] for c in cause if c.startswith("V")}},
    }
    print("=== 答对率（先按用例平均，再对用例平均）")
    for name, d in rows.items():
        orig = [st.mean(v) for c, v in d.items() if c.startswith("C")]
        var = [st.mean(v) for c, v in d.items() if c.startswith("V")]
        by_lv = {lv: st.mean(st.mean(d[c]) for c in d if level[c] == lv) for lv in ("plain", "distract", "mislead", "flaky")}
        print(f"  {name:<6} 原题 {st.mean(orig):.1%}（" + "  ".join(f"{lv} {v:.0%}" for lv, v in by_lv.items()) +
              f"）  换说法 {st.mean(var):.1%}")
    d = [st.mean(rows["一次调用"][c]) - st.mean(rows["Agent"][c]) for c in cause if c.startswith("C")]
    print(f"  原题上一次调用减 Agent，按用例配对：{st.mean(d) * 100:+.1f} ± {1.96 * st.stdev(d) / len(d) ** .5 * 100:.1f} 个点；差别来自 " +
          "，".join(f"{c} {x * 100:+.0f}" for c, x in zip([c for c in cause if c.startswith('C')], d) if x))
    print("  规则判错的用例：", {c: rule_pred[c] for c in cause if rule_pred[c] != cause[c]})
    for name, d in rows.items():
        bad = {c: f"{len(v) - sum(v)}/{len(v)}" for c, v in d.items() if not all(v)}
        print(f"  {name} 有答错的用例：{bad}")
    print("  一次调用答错时答成：", {c: [x["pred"] for x in oc if x["case"] == c and x["pred"] != cause[c]]
                            for c in cause if any(x["case"] == c and x["pred"] != cause[c] for x in oc)})
    print("  Agent（换说法）答错时答成：", {c: [x["pred"] for x in av if x["case"] == c and x["pred"] != cause[c]]
                                   for c in cause if any(x["case"] == c and x["pred"] != cause[c] for x in av)})
    print("\n=== 每次的花费")
    print(f"  规则      0 token，几毫秒")
    print(f"  一次调用  平均 {st.mean(x['tokens'] for x in oc):,.0f} token，中位耗时 {st.median(x['seconds'] for x in oc):.1f} 秒（不含查数据）")
    print(f"  Agent    平均 {st.mean(x['tokens'] for x in agent):,.0f} token，中位耗时 {st.median(x['seconds'] for x in agent):.1f} 秒（原题，单元十七）")
    print(f"\n一次调用：模型 {r['_meta']['model']}，{r['_meta']['date']} 实测；Agent 数据来自 u17_run.json")
