"""单元二十一 · 把骨架跑一遍：20 个排障任务进队列，4 个 worker 并发执行，中途让一个 worker 死掉。

骨架在 examples/skeleton/ 里。这里做五件事：
  1. 算配置指纹；看改一个字的工具描述、改一个运维参数，指纹各变不变
  2. 迷你评测集的 20 条问题作为 20 个任务提交；C01 和 C02、C11 和 C12 属于同一个会话（同一个用户连问两次）
  3. 4 个 worker 执行；C05 第一次执行到第二个工具结果写进日志后，worker“崩溃”，任务停在 running，等租约过期
  4. 看结果：每个任务的状态和尝试次数、同一会话是否串行、崩溃的任务有没有重复查数据、网关的用量
  5. 从事件日志生成崩溃那个任务的轨迹，并把跑完的任务导出成评测题候选
SQLite 文件放在临时目录，跑完把汇总写进 examples/output/u21_skeleton.json。

    python examples/u21_skeleton.py            # 真调模型（约 80 次调用）
    python examples/u21_skeleton.py --replay
"""
import copy
import os
import statistics as st
import sys
import tempfile
import time

from _llm import replay_or_run
from mini_eval import CASES, make_execute
from skeleton.config import behavior_config, config_id, ops_config
from skeleton.export import to_case
from skeleton.gateway import Gateway
from skeleton.runner import Crash
from skeleton.store import Store
from skeleton.trace import render, spans
from skeleton.worker import run_pool

BY_ID = {c["id"]: c for c in CASES}
SAME_SESSION = {"C02": "C01", "C12": "C11"}
CRASH_CASE, CRASH_AFTER_TOOLS = "C05", 2


def fault(job, events):
    if job["case_id"] == CRASH_CASE and job["attempts"] == 1 and sum(e["type"] == "tool" for e in events) >= CRASH_AFTER_TOOLS:
        raise Crash()


def run(backend=None):
    cfg, ops = behavior_config(), ops_config()
    cid = config_id(cfg)
    tweak_tool = copy.deepcopy(cfg)
    tweak_tool["tools"][0]["function"]["description"] += "。"
    tweak_ops = dict(ops, workers=8)
    store = Store(os.path.join(tempfile.mkdtemp(), "oncall.db"))
    store.save_config(cid, cfg)
    for c in CASES:
        store.submit(c["question"], f"s-{SAME_SESSION.get(c['id'], c['id'])}", cid, case_id=c["id"])
    gw = Gateway(concurrency=ops["gateway_concurrency"], max_retries=ops["max_retries"], **({"backend": backend} if backend else {}))
    t0 = time.time()
    crashes = run_pool(store, cfg, cid, gw, lambda job: make_execute(BY_ID[job["case_id"]]), ops["workers"], ops["lease_s"], fault)
    wall = time.time() - t0
    jobs = store.jobs()
    out = []
    for j in jobs:
        ev = store.events(j["job_id"])
        res = __import__("json").loads(j["result"]) if j["result"] else {}
        out.append({"case": j["case_id"], "session": j["session_id"], "status": j["status"], "attempts": j["attempts"],
                    "worker": j["worker"], "started": round(j["started"] - t0, 2), "finished": round((j["finished"] or t0) - t0, 2),
                    "events": [{"seq": e["seq"], "type": e["type"], "t": round(e["ts"] - t0, 2),
                                "name": e["payload"].get("name"), "ok": e["payload"].get("ok"),
                                "worker": e["payload"].get("worker")} for e in ev],
                    "pred": res.get("pred"), "correct": res.get("pred") == BY_ID[j["case_id"]]["cause"],
                    "tokens": res.get("tokens")})
    crash_job = next(j for j in jobs if j["case_id"] == CRASH_CASE)
    crash_events = store.events(crash_job["job_id"])
    return {"config_id": cid, "config_id_tool_tweak": config_id(tweak_tool), "config_id_after_ops_change": config_id(cfg),
            "ops": ops, "ops_changed_to": tweak_ops, "wall_seconds": round(wall, 1), "gateway": gw.stats,
            "crashes": [{"worker": c["worker"], "t": round(c["at"] - t0, 2)} for c in crashes], "jobs": out,
            "trace": render(spans(crash_job, crash_events, cfg["model"])),
            "exported": [to_case(j, store.events(j["job_id"])) for j in jobs if j["status"] == "done"]}


def report(r):
    print(f"=== 1. 配置指纹：{r['config_id']}")
    print(f"  get_metrics 的描述末尾加一个句号 → {r['config_id_tool_tweak']}（变了）")
    print(f"  worker 从 {r['ops']['workers']} 个改成 {r['ops_changed_to']['workers']} 个（运维参数，不进指纹）→ {r['config_id_after_ops_change']}（没变）")
    J = r["jobs"]
    print(f"\n=== 2. 20 个任务，4 个 worker，墙钟 {r['wall_seconds']} 秒")
    print(f"  完成 {sum(j['status'] == 'done' for j in J)}，失败 {sum(j['status'] == 'failed' for j in J)}；"
          f"答对 {sum(j['correct'] for j in J)}/{len(J)}；每个 worker 做了：" +
          "，".join(f"{w} {sum(j['worker'] == w for j in J)}" for w in sorted({j['worker'] for j in J})))
    for a, b in (("C01", "C02"), ("C11", "C12")):
        ja, jb = next(j for j in J if j["case"] == a), next(j for j in J if j["case"] == b)
        print(f"  同一会话 {ja['session']}：{a} 在 {ja['started']}～{ja['finished']} 秒，{b} 在 {jb['started']}～{jb['finished']} 秒"
              f"（{'串行' if jb['started'] >= ja['finished'] else '重叠了'}）")
    print(f"\n=== 3. 崩溃和恢复：{r['crashes']}")
    cj = next(j for j in J if j["case"] == CRASH_CASE)
    print(f"  {CRASH_CASE}：状态 {cj['status']}，领取 {cj['attempts']} 次，结论 {cj['pred']}")
    for e in cj["events"]:
        print(f"    seq {e['seq']:>2}  {e['t']:>6.1f}s  {e['type']:<7} {e['name'] or ''} {'' if e['ok'] is None else ('成功' if e['ok'] else '报错')} {e['worker'] or ''}")
    tools = [e["name"] for e in cj["events"] if e["type"] == "tool"]
    print(f"  工具调用顺序：{tools}；有没有重复查同一个数据源：{len(tools) != len(set(tools))}")
    g = r["gateway"]
    print(f"\n=== 4. 网关：成功调用 {g['calls']}，尝试 {g['attempts']}，限流 {g['rate_limited']}，出错 {g['errors']}；"
          f"输入 {g['input_tokens']:,} token，输出 {g['output_tokens']:,} token")
    print(f"  每个任务的 token：中位数 {st.median(j['tokens'] for j in J if j['tokens']):,.0f}")
    print(f"\n=== 5. {CRASH_CASE} 的轨迹（从事件日志生成，不带正文）\n{r['trace']}")
    ex = r["exported"]
    print(f"\n=== 6. 导出成评测题候选：{len(ex)} 条；举一条（已脱敏）：")
    sample = next((x for x in ex if any('<ID>' in s for v in x['recorded_tools'].values() for s in v)), ex[0])
    print("  ", {k: (v if k != "recorded_tools" else {n: [s[:110] for s in xs] for n, xs in v.items()}) for k, v in sample.items()})
    print(f"\n模型 {r['_meta']['model']}，{r['_meta']['date']} 实测")


if __name__ == "__main__":
    if "--mock" in sys.argv:                              # 不调模型，检查骨架本身
        from mini_world import ROOT_CAUSES

        def mock(messages, model, tools=None, **kw):
            time.sleep(0.05)
            n_tool = sum(m["role"] == "tool" for m in messages)
            inst = messages[1]["content"].split(" ")[0]
            if n_tool < 3:
                name = ["get_metrics", "query_slow_log", "query_error_log"][n_tool]
                call = {"id": f"c{n_tool}", "type": "function", "function": {"name": name, "arguments": f'{{"instance": "{inst}"}}'}}
                msg = {"role": "assistant", "content": "", "tool_calls": [call]}
                return {"text": "", "message": msg, "tool_calls": [call], "usage": {"prompt_tokens": 100, "completion_tokens": 10}, "latency": 0.05}
            msg = {"role": "assistant", "content": "根因: SLOW_SQL"}
            return {"text": "根因: SLOW_SQL", "message": msg, "tool_calls": [], "usage": {"prompt_tokens": 200, "completion_tokens": 20}, "latency": 0.05}
        r = run(mock)
        r["_meta"] = {"model": "mock", "date": "-"}
        report(r)
    else:
        report(replay_or_run("u21_skeleton", run))
