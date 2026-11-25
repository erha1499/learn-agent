"""单元二十二 · 发布门禁：改提示词、改运维参数、换模型，都走同一道门。

线上版本是单元十三的 Agent（模型写的是别名 qwen-plus）。六个候选改动，都用 examples/skeleton/ 的骨架跑：
  运维：worker 4 → 8                 只改运维参数，指纹不变，不用跑
  提示词：证据不足说不知道            单元二十的 U 版本
  提示词：最多查两个数据源            “为了更快”加的一句
  模型：钉到 qwen-plus-2025-12-01     别名 qwen-plus 现在指向的快照（实测同一请求两者 token 数完全相同）
  模型：qwen-plus-2025-01-25          同一系列早一年的快照
  模型：qwen3.7-plus                  新一代，默认开着思考
线上版本和每个候选，都在迷你评测集的 20 条用例上各跑 3 遍。门禁的规则在 skeleton/gate.py。
最后用线上版本和“最多查两个数据源”的数据，估算灰度时要多少个会话才看得出变差。

    python examples/u22_gate.py            # 真调模型（360 次 Agent 运行）
    python examples/u22_gate.py --replay
"""
import copy
import math
import os
import statistics as st
import tempfile

from _llm import replay_or_run
from mini_eval import CASES, make_execute
from skeleton.config import behavior_config, config_id, ops_config
from skeleton.gate import gate, summarize
from skeleton.gateway import Gateway
from skeleton.store import Store
from skeleton.worker import run_pool

RUNS = 3
BY_ID = {c["id"]: c for c in CASES}
ABSTAIN = "。如果关键的数据源查不到（超时、报错，重试后仍然失败），或者现有数据不足以确定根因，不要猜：最后一行写“根因: UNKNOWN”，并说明还缺哪些数据"
FAST = "。为了尽快给出结论，最多查两个数据源就下结论"


def candidates():
    base = behavior_config()
    out = {}
    for name, kind, value in (("提示词：证据不足说不知道", "prompt", ABSTAIN), ("提示词：最多查两个数据源", "prompt", FAST),
                              ("模型：钉到 qwen-plus-2025-12-01", "model", "qwen-plus-2025-12-01"),
                              ("模型：qwen-plus-2025-01-25", "model", "qwen-plus-2025-01-25"),
                              ("模型：qwen3.7-plus", "model", "qwen3.7-plus")):
        c = copy.deepcopy(base)
        if kind == "prompt":
            c["system_prompt"] += value
        else:
            c["model"] = value
        out[name] = c
    return base, out


def evaluate(cfg):
    store = Store(os.path.join(tempfile.mkdtemp(), "gate.db"))
    cid = config_id(cfg)
    store.save_config(cid, cfg)
    for k in range(RUNS):
        for c in CASES:
            store.submit(c["question"], f"s-{c['id']}-{k}", cid, case_id=c["id"])
    run_pool(store, cfg, cid, Gateway(concurrency=8, max_retries=6), lambda job: make_execute(BY_ID[job["case_id"]]), 8, 120)
    runs = []
    for j in store.jobs():
        ev = store.events(j["job_id"])
        fin = next((e["payload"] for e in ev if e["type"] == "final"), {})
        pred = fin.get("pred")
        outcome = "unknown" if pred in (None, "UNKNOWN") else ("right" if pred == BY_ID[j["case_id"]]["cause"] else "wrong")
        runs.append({"case": j["case_id"], "status": j["status"], "error": j["error"], "pred": pred, "outcome": outcome,
                     "tokens": fin.get("tokens") or sum(e["payload"]["usage"].get("prompt_tokens", 0) + e["payload"]["usage"].get("completion_tokens", 0)
                                                        for e in ev if e["type"] == "model"),
                     "seconds": round((j["finished"] or j["started"]) - j["started"], 2),
                     "calls": sum(e["type"] == "tool" for e in ev)})
    return {"config_id": cid, "model": cfg["model"], "runs": runs}


def run():
    base, cands = candidates()
    out = {"baseline": evaluate(base)}
    for name, c in cands.items():
        out[name] = evaluate(c)
    return out


def n_two_props(p0, p1, za=1.96, zb=0.84):
    pb = (p0 + p1) / 2
    return math.ceil((za * math.sqrt(2 * pb * (1 - pb)) + zb * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) ** 2 / (p1 - p0) ** 2)


if __name__ == "__main__":
    r = replay_or_run("u22_gate", run)
    base = r["baseline"]
    b = summarize(base["runs"])
    print(f"线上版本：指纹 {base['config_id']}，模型 {base['model']}；答对 {b['right']:.0%}，答错 {b['wrong']:.0%}，不知道 {b['unknown']:.0%}，"
          f"每次 {b['tokens']:,.0f} token，耗时 p90 {b['p90_seconds']:.1f} 秒，调工具 {b['calls']:.1f} 次\n")
    cfg0 = behavior_config()
    ops_same = config_id(cfg0) == base["config_id"]
    print(f"=== 运维：worker {ops_config()['workers']} → 8：指纹 {config_id(cfg0)}，{'和线上相同' if ops_same else '变了'} → {gate([], [], same_fingerprint=ops_same)['decision']}，不用跑\n")
    for name, c in r.items():
        if name in ("baseline", "_meta"):
            continue
        g = gate(base["runs"], c["runs"])
        g0 = gate(base["runs"], c["runs"], strict_targets=True)
        s = g["summary"]
        print(f"=== {name}：指纹 {c['config_id']} → {g['decision']}（第一版规则：{g0['decision']}）")
        bad = [x for x in c["runs"] if x["status"] != "done"]
        print(f"    答对 {s['right']:.0%}  答错 {s['wrong']:.0%}  不知道 {s['unknown']:.0%}  每次 {s['tokens']:,.0f} token  "
              f"耗时 p90 {s['p90_seconds']:.1f} 秒  调工具 {s['calls']:.1f} 次  没跑完的任务 {len(bad)}" +
              (f"（{', '.join(sorted({x['case'] for x in bad}))}）" if bad else ""))
        for reason in g["reasons"]:
            print(f"    - {reason}")
    print("\n=== 灰度要多少个会话才看得出变差（每组，80% 把握，双侧 5%）")
    p0 = b["wrong"]
    for d in (0.05, 0.10, 0.20):
        print(f"  答错率从 {p0:.0%} 变成 {p0 + d:.0%}：每组约 {n_two_props(p0, p0 + d)} 个会话")
    fast = r["提示词：最多查两个数据源"]["runs"]
    a, f = [x["calls"] for x in base["runs"]], [x["calls"] for x in fast]
    sd = math.sqrt((st.variance(a) + st.variance(f)) / 2)
    delta = st.mean(a) - st.mean(f)
    print(f"  调工具次数从 {st.mean(a):.1f} 降到 {st.mean(f):.1f}（标准差约 {sd:.2f}）：每组约 {math.ceil(2 * (1.96 + 0.84) ** 2 * sd ** 2 / delta ** 2)} 个会话")
    print(f"\n{r['_meta']['date']} 实测")
