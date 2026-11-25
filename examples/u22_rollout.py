"""单元二十二 · 灰度和回滚：线上指针一改，新会话就换版本；已经在跑的任务不换。

三段流量，每段都从迷你评测集里随机抽问题，用 examples/skeleton/ 的骨架跑（4 个 worker）：
  A 段  8 个会话，全部走稳定版本 v1（单元十三的 Agent）
  B 段  16 个会话，开 50% 灰度：按会话 ID 的哈希，一半走 v2（v1 加一句“最多查两个数据源就下结论”）
        灰度版本做完 6 个会话后，比较两个版本：每次调工具的次数、答错的次数；v2 明显变差就回滚
  回滚  线上指针指回 v1；排队中还没开始的 v2 任务改回 v1；已经在跑的 v2 任务跑完
  C 段  8 个会话，全部走 v1

    python examples/u22_rollout.py            # 真调模型（约 32 个任务）
    python examples/u22_rollout.py --replay
"""
import copy
import os
import random
import statistics as st
import tempfile
import threading
import time

from _llm import replay_or_run
from mini_eval import CASES, make_execute
from skeleton.config import behavior_config, config_id
from skeleton.gateway import Gateway
from skeleton.rollout import repin_queued, route
from skeleton.store import Store
from skeleton.worker import run_pool

BY_ID = {c["id"]: c for c in CASES}
FAST = "。为了尽快给出结论，最多查两个数据源就下结论"


def run():
    rng = random.Random(22)
    store = Store(os.path.join(tempfile.mkdtemp(), "rollout.db"))
    v1 = behavior_config()
    v2 = copy.deepcopy(v1)
    v2["system_prompt"] += FAST
    c1, c2 = config_id(v1), config_id(v2)
    store.save_config(c1, v1)
    store.save_config(c2, v2)
    store.deploy("oncall", c1, "上线 v1")
    t0, phase, n = time.time(), {}, [0]
    accepting = threading.Event()
    accepting.set()

    def submit(k, canary=None, pct=0, tag=""):
        for _ in range(k):
            n[0] += 1
            case = rng.choice(CASES)
            sid = f"s{n[0]:03d}"
            cid = route(sid, store.active("oncall"), canary, pct)
            jid = store.submit(case["question"], sid, cid, case_id=case["id"])
            phase[jid] = tag

    pool = threading.Thread(target=run_pool, args=(store, v1, c1, Gateway(concurrency=4), lambda job: make_execute(BY_ID[job["case_id"]]), 4, 120),
                            kwargs={"keep_alive": accepting.is_set})
    submit(8, tag="A")
    pool.start()
    while sum(j["status"] == "done" for j in store.jobs()) < 4:
        time.sleep(0.5)
    store.deploy("oncall:canary", c2, "灰度 v2，50%")
    submit(16, canary=c2, pct=50, tag="B")

    def finished(cid):
        return [j for j in store.jobs() if j["config_id"] == cid and j["status"] == "done" and phase[j["job_id"]] == "B"]

    while len(finished(c2)) < 6:
        time.sleep(0.5)
    check = {}
    for name, cid in (("v1", c1), ("v2", c2)):
        js = finished(cid)
        check[name] = {"n": len(js), "calls": st.mean(sum(e["type"] == "tool" for e in store.events(j["job_id"])) for j in js) if js else None,
                       "wrong": sum(__import__("json").loads(j["result"])["pred"] != BY_ID[j["case_id"]]["cause"] for j in js)}
    snapshot = {s: sum(j["config_id"] == c2 and j["status"] == s for j in store.jobs()) for s in ("queued", "running", "done")}
    store.deploy("oncall:canary", "", "回滚：灰度关掉")
    repinned = repin_queued(store, c2, c1)
    rollback_t = time.time() - t0
    submit(8, tag="C")
    while store.pending():
        time.sleep(0.5)
    accepting.clear()
    pool.join()
    jobs = store.jobs()
    with store.db() as db:
        log = [dict(r) for r in db.execute("SELECT * FROM deploy_log ORDER BY ts").fetchall()]
    rows = []
    for j in jobs:
        res = __import__("json").loads(j["result"]) if j["result"] else {}
        rows.append({"phase": phase[j["job_id"]], "version": "v1" if j["config_id"] == c1 else "v2", "case": j["case_id"],
                     "started": round(j["started"] - t0, 1), "finished": round(j["finished"] - t0, 1),
                     "correct": res.get("pred") == BY_ID[j["case_id"]]["cause"],
                     "calls": sum(e["type"] == "tool" for e in store.events(j["job_id"]))})
    return {"v1": c1, "v2": c2, "check_at_rollback": check, "v2_at_rollback": snapshot, "repinned": repinned,
            "rollback_t": round(rollback_t, 1), "deploy_log": [{"t": round(max(0.0, x["ts"] - t0), 1), "name": x["name"], "config_id": x["config_id"], "note": x["note"]} for x in log],
            "jobs": rows}


if __name__ == "__main__":
    r = replay_or_run("u22_rollout", run)
    print(f"v1 = {r['v1']}，v2 = {r['v2']}（v1 加一句“最多查两个数据源就下结论”）\n")
    print("=== 发布记录")
    for x in r["deploy_log"]:
        print(f"  {x['t']:>6.1f} 秒  {x['name']:<14} → {x['config_id'] or '（关闭）':<14} {x['note']}")
    print("\n=== 回滚前的灰度检查（B 段已完成的会话）")
    for v, c in r["check_at_rollback"].items():
        print(f"  {v}：{c['n']} 个会话，平均调工具 {c['calls']:.1f} 次，答错 {c['wrong']} 个")
    s = r["v2_at_rollback"]
    print(f"  回滚那一刻 v2 的任务：已完成 {s['done']}，正在跑 {s['running']}，排队中 {s['queued']}；排队的 {r['repinned']} 个改回 v1")
    print("\n=== 各段走了哪个版本（完成数 / 答对数 / 平均调工具次数）")
    for ph in ("A", "B", "C"):
        for v in ("v1", "v2"):
            xs = [j for j in r["jobs"] if j["phase"] == ph and j["version"] == v]
            if xs:
                print(f"  {ph} 段 {v}：{len(xs)} 个，答对 {sum(j['correct'] for j in xs)}，调工具 {st.mean(j['calls'] for j in xs):.1f} 次")
    late = [j for j in r["jobs"] if j["version"] == "v2" and j["finished"] > r["rollback_t"]]
    print(f"  回滚以后才跑完的 v2 任务：{len(late)} 个（回滚前已经开始，按自己的版本跑完）")
    print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")
