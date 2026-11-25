"""单元二十三 · 上线以后转一圈：一周的线上流量 → 分诊 → 入库 → 修 → 过门禁 → 第二周。

全部用 examples/skeleton/ 的骨架跑。
  线上流量  每周 100 个会话，问题从 30 道里随机抽：迷你评测集的 20 条，加单元二十“换说法”的 10 条；
            30% 的会话碰上错误日志服务抖动，第一次调用超时（504）
  第一周    v1：单元十三的 Agent
  分诊      不用标准答案的代码信号（单元十九）标出可疑会话，再随机抽 25 个；两批合起来人工核对（这里用真实标签模拟）。
            答错的按机制分类：一次工具没调就下结论 / 某个数据源报错后没再成功过 / 其他
  入库      评测集从 20 条扩成 40 条：原来的 20 条，换说法的 10 条，再加 10 条“错误日志第一次超时”的版本
  修        v2 = v1 打开两条 harness 规则：工具超时自动重试一次；交卷时检查结论的关键证据，没拿到就转人工
  门禁      v1 和 v2 在新评测集上各跑 3 遍，用 skeleton/gate.py 判（单元二十二）
  第二周    v2，换一批随机会话

    python examples/u23_loop.py            # 真调模型（约 440 次 Agent 运行）
    python examples/u23_loop.py --replay
"""
import copy
import json
import math
import os
import random
import statistics as st
import tempfile

from _llm import replay_or_run
from mini_eval import CASES, KEY_TOOLS, make_execute
from skeleton.config import behavior_config, config_id
from skeleton.gate import gate, summarize
from skeleton.gateway import Gateway
from skeleton.store import Store
from skeleton.worker import run_pool
from u20_baselines import VARIANTS

POOL = CASES + VARIANTS
BY_ID = {c["id"]: c for c in POOL}
SESSIONS, FLAKY, SAMPLE, RUNS = 100, 0.3, 25, 3
TIMEOUT = json.dumps({"error": "下游服务超时（504），请稍后重试"}, ensure_ascii=False)


def env(case, flaky):
    base, n = make_execute(case), {"err": 0}

    def ex(name, args):
        if flaky and name == "query_error_log" and args.get("instance") == case["instance"]:
            n["err"] += 1
            if n["err"] == 1:
                return TIMEOUT
        return base(name, args)
    return ex


def configs():
    v1 = behavior_config()
    v2 = copy.deepcopy(v1)
    v2["harness"] = {"tool_retry": True, "key_evidence": {k: sorted(v) for k, v in KEY_TOOLS.items()}}
    return v1, v2


def run_batch(cfg, items, tag):
    """items: [(session_id, case_id, flaky)]，每个是一个任务。返回每个任务的记录。"""
    store = Store(os.path.join(tempfile.mkdtemp(), f"{tag}.db"))
    cid = config_id(cfg)
    store.save_config(cid, cfg)
    cond = {}
    for sid, case_id, flaky in items:
        store.submit(BY_ID[case_id]["question"], sid, cid, case_id=case_id)
        cond[sid] = flaky
    run_pool(store, cfg, cid, Gateway(concurrency=8, max_retries=6),
             lambda job: env(BY_ID[job["case_id"]], cond[job["session_id"]]), 8, 120)
    rows = []
    for j in store.jobs():
        ev = store.events(j["job_id"])
        fin = next((e["payload"] for e in ev if e["type"] == "final"), {})
        pred = fin.get("pred")
        rows.append({"session": j["session_id"], "case": j["case_id"], "flaky": cond[j["session_id"]], "status": j["status"],
                     "pred": pred, "model_pred": fin.get("model_pred"),
                     "outcome": "unknown" if pred in (None, "UNKNOWN") else ("right" if pred == BY_ID[j["case_id"]]["cause"] else "wrong"),
                     "calls": [{"name": e["payload"]["name"], "ok": e["payload"]["ok"], "retried": e["payload"].get("retried", False)}
                               for e in ev if e["type"] == "tool"],
                     "tokens": fin.get("tokens", 0), "seconds": round((j["finished"] or j["started"]) - j["started"], 2)})
    return {"config_id": cid, "rows": rows}


def traffic(seed, tag):
    rng = random.Random(seed)
    return [(f"{tag}-{i:03d}", rng.choice(POOL)["id"], rng.random() < FLAKY) for i in range(SESSIONS)]


def eval_items(k):
    items = []
    for c in CASES:
        items.append((f"e{k}-{c['id']}", c["id"], False))
    for v in VARIANTS:
        items.append((f"e{k}-{v['id']}", v["id"], False))
    for c in CASES:
        if c["level"] in ("plain", "distract"):
            items.append((f"e{k}-T{c['id']}", c["id"], True))
    return items


def run():
    v1, v2 = configs()
    week1 = run_batch(v1, traffic(1, "w1"), "week1")
    evals = [it for k in range(RUNS) for it in eval_items(k)]
    gate_v1, gate_v2 = run_batch(v1, evals, "gate-v1"), run_batch(v2, evals, "gate-v2")
    week2 = run_batch(v2, traffic(2, "w2"), "week2")
    return {"v1": config_id(v1), "v2": config_id(v2), "week1": week1, "gate_v1": gate_v1, "gate_v2": gate_v2, "week2": week2}


# ---------- 分析（不调模型） ----------

def signals(r):
    ok = {c["name"] for c in r["calls"] if c["ok"]}
    p = r["model_pred"] if r["model_pred"] is not None else r["pred"]
    unrecovered = any(not c["ok"] and not any(d["ok"] and d["name"] == c["name"] for d in r["calls"][i + 1:])
                      for i, c in enumerate(r["calls"]))
    return {"没给结论": p is None, "工具调得太少": len(r["calls"]) < 2,
            "结论缺关键证据": p not in (None, "UNKNOWN") and not (KEY_TOOLS.get(p, set()) & ok),
            "报错没重试成功": unrecovered}


def cluster(r):
    if not r["calls"]:
        return "一次工具没调就下结论"
    if any(not c["ok"] and not any(d["ok"] and d["name"] == c["name"] for d in r["calls"][i + 1:]) for i, c in enumerate(r["calls"])):
        return "某个数据源报错后没再成功过"
    return "其他（推理出错）"


def wilson(k, n, z=1.96):
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return c - h, c + h


def week_report(name, w, rng):
    rows = w["rows"]
    n = len(rows)
    o = {k: sum(r["outcome"] == k for r in rows) for k in ("right", "wrong", "unknown")}
    print(f"  {name}（指纹 {w['config_id']}）：{n} 个会话，真实情况 答对 {o['right']}、答错 {o['wrong']}、转人工 {o['unknown']}"
          f"（线上看不到）；碰上超时的 {sum(r['flaky'] for r in rows)} 个")
    flagged = [r for r in rows if any(signals(r).values())]
    sample = rng.sample(rows, SAMPLE)
    sk = sum(r["outcome"] == "wrong" for r in sample)
    lo, hi = wilson(sk, SAMPLE)
    print(f"    代码信号标记 {len(flagged)} 个，其中真错 {sum(r['outcome'] == 'wrong' for r in flagged)} 个；"
          f"随机抽 {SAMPLE} 个核对，错了 {sk} 个，答错率估计 {sk / SAMPLE:.0%}（Wilson 95% 区间 {lo:.0%} ～ {hi:.0%}）")
    calls = [c for r in rows for c in r["calls"]]
    print(f"    平均调工具 {st.mean(len(r['calls']) for r in rows):.1f} 次，工具报错率 {sum(not c['ok'] for c in calls) / len(calls):.0%}，"
          f"程序自动重试 {sum(c['retried'] for c in calls)} 次，每个会话 {st.mean(r['tokens'] for r in rows):,.0f} token")
    return flagged, sample


if __name__ == "__main__":
    r = replay_or_run("u23_loop", run)
    rng = random.Random(0)
    print(f"v1 = {r['v1']}；v2 = {r['v2']}（打开工具超时重试、交卷检查关键证据）\n")
    print("=== 一、第一周（v1）")
    flagged, sample = week_report("第一周", r["week1"], rng)
    review = {x["session"]: x for x in flagged + sample}
    wrong = [x for x in review.values() if x["outcome"] == "wrong"]
    all_wrong = [x for x in r["week1"]["rows"] if x["outcome"] == "wrong"]
    print(f"  人工核对 {len(review)} 个会话（标记的加随机抽的），找到答错 {len(wrong)} 个，占这一周全部答错（{len(all_wrong)} 个）的 {len(wrong) / len(all_wrong):.0%}")
    print("  按机制分类（核对出来的答错）：")
    for k in ("一次工具没调就下结论", "某个数据源报错后没再成功过", "其他（推理出错）"):
        xs = [x for x in wrong if cluster(x) == k]
        labels = sorted({x["case"] + ("（超时）" if x["flaky"] else "") + "→" + str(x["pred"]) for x in xs})
        print(f"    {k}：{len(xs)} 个  " + "，".join(labels))
    print("\n=== 二、门禁：v1 和 v2 在扩充后的 40 条评测集上各跑 3 遍")
    flat = {tag: [dict(x, calls=len(x["calls"]), case=x["case"] + ("-T" if x["flaky"] else "")) for x in r[tag]["rows"]]
            for tag in ("gate_v1", "gate_v2")}
    for tag in ("gate_v1", "gate_v2"):
        s = summarize(flat[tag])
        print(f"  {'v1' if tag == 'gate_v1' else 'v2'}：答对 {s['right']:.0%}  答错 {s['wrong']:.0%}  转人工 {s['unknown']:.0%}  "
              f"每次 {s['tokens']:,.0f} token  耗时 p90 {s['p90_seconds']:.1f} 秒")
    for part, pick in (("原来的 20 条", lambda x: x["case"].startswith("C") and not x["flaky"]),
                       ("换说法的 10 条", lambda x: x["case"].startswith("V")), ("超时版本的 10 条", lambda x: x["flaky"])):
        cells = []
        for tag in ("gate_v1", "gate_v2"):
            xs = [x for x in r[tag]["rows"] if pick(x)]
            cells.append(f"{'v1' if tag == 'gate_v1' else 'v2'} 对/错/转 {sum(x['outcome'] == 'right' for x in xs)}/{sum(x['outcome'] == 'wrong' for x in xs)}/{sum(x['outcome'] == 'unknown' for x in xs)}")
        print(f"    {part}：" + "   ".join(cells))
    g = gate(flat["gate_v1"], flat["gate_v2"])
    print(f"  门禁结论：{g['decision']}")
    for reason in g["reasons"]:
        print(f"    - {reason}")
    print("\n=== 三、第二周（v2）")
    week_report("第二周", r["week2"], rng)
    print("\n=== 四、两周对比（真实情况，线上看不到；每 100 个会话）")
    for w in ("week1", "week2"):
        rows = r[w]["rows"]
        by = {}
        for x in rows:
            if x["outcome"] == "wrong":
                k = cluster(x)
                by[k] = by.get(k, 0) + 1
        print(f"  {'第一周 v1' if w == 'week1' else '第二周 v2'}：答错 {sum(x['outcome'] == 'wrong' for x in rows)}，转人工 {sum(x['outcome'] == 'unknown' for x in rows)}；"
              f"答错按机制：{by}")
    w1, w2 = r["week1"]["rows"], r["week2"]["rows"]
    flagged2 = [x for x in w2 if any(signals(x).values())]
    print(f"  第二周被代码信号标记的 {len(flagged2)} 个：" + "，".join(f"{x['case']}（{ {'right': '答对', 'wrong': '答错', 'unknown': '转人工'}[x['outcome']] }）" for x in flagged2) +
          f"；第二周的 {sum(x['outcome'] == 'wrong' for x in w2)} 个答错，代码信号一个都没标出来")
    hard = [c for c in BY_ID if any(x["case"] == c and cluster(x) == "其他（推理出错）" and x["outcome"] == "wrong" for x in w1 + w2)]
    print(f"  流量组成：出过“推理出错”的那几道题（{', '.join(sorted(hard))}），第一周抽到 {sum(x['case'] in hard for x in w1)} 次，第二周 {sum(x['case'] in hard for x in w2)} 次")
    both = sorted({x["case"] for x in w1} & {x["case"] for x in w2})
    d = [st.mean(x["outcome"] == "wrong" for x in w2 if x["case"] == c) - st.mean(x["outcome"] == "wrong" for x in w1 if x["case"] == c) for c in both]
    print(f"  按题配对（两周都出现过的 {len(both)} 道）：第二周减第一周的答错率 {st.mean(d) * 100:+.1f} ± {1.96 * st.stdev(d) / math.sqrt(len(d)) * 100:.1f} 个点")
    print("\n=== 五、质量 SLO 要抽多少个会话核对（答错率目标 ≤ 10%，用 Wilson 区间的上限判断）")
    for p_true in (0.05, 0.08):
        n = next(n for n in range(10, 2000) if wilson(round(p_true * n), n)[1] <= 0.10)
        print(f"  如果真实答错率是 {p_true:.0%}：每周至少随机核对约 {n} 个会话，区间上限才压得到 10% 以下")
    for n in (25, 100):
        lo, hi = wilson(round(0.1 * n), n)
        print(f"  抽 {n} 个、错了 {round(0.1 * n)} 个：区间 {lo:.0%} ～ {hi:.0%}")
    print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
